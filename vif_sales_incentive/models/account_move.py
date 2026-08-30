# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    incentive_employee_id = fields.Many2one(
        'hr.employee', string='Incentive Salesperson',
        compute='_compute_incentive_employee', store=True, readonly=False,
        help="Defaults to the employee behind the invoice salesperson. "
             "Override when the commission belongs to somebody else.")
    incentive_full_payment_date = fields.Date(
        string='Fully Paid On', compute='_compute_full_payment_date', store=True)
    incentive_transaction_ids = fields.One2many(
        'incentive.transaction', 'move_id', string='Incentive Transactions')

    @api.depends('invoice_user_id')
    def _compute_incentive_employee(self):
        Employee = self.env['hr.employee']
        for move in self:
            emp = Employee.browse()
            if move.invoice_user_id:
                emp = Employee.search(
                    [('user_id', '=', move.invoice_user_id.id)], limit=1)
            move.incentive_employee_id = emp.id or False

    def _incentive_employee(self):
        self.ensure_one()
        return self.incentive_employee_id

    @api.depends('payment_state', 'line_ids.matched_debit_ids',
                 'line_ids.matched_credit_ids')
    def _compute_full_payment_date(self):
        for move in self:
            move.incentive_full_payment_date = move._incentive_full_payment_date()

    def _incentive_full_payment_date(self):
        """Date on which the invoice became FULLY paid.

        S09 only counts a fully paid invoice, so anything else returns False:
          * 'partial'      -- residual > 0, genuinely partially paid
          * 'in_payment'   -- residual is zero but the payment is still in
                              process / not fully matched (transitional)
          * 'not_paid' / 'reversed' / 'blocked' -- not collected money
        The date is the LAST reconciliation date, because that is the moment
        the balance reached zero.
        """
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        if self.payment_state not in  ('paid', 'in_payment'):
            return False

        dates = []
        for line in self.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable'):
            for partial in line.matched_credit_ids:
                dates.append(partial.max_date)
            for partial in line.matched_debit_ids:
                dates.append(partial.max_date)
        return max(dates) if dates else self.invoice_date

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted.filtered(
            lambda m: m.move_type == 'out_refund' and m.reversed_entry_id
        )._create_incentive_refund_transactions()
        return posted

    def _create_incentive_refund_transactions(self):
        """S10 -- a credit note posted against an incentivized invoice nets off
        the payout by creating a linked refund transaction, whether the credit
        note came from the refund wizard or natively from the invoice.

        Idempotent: skips lines that already have a transaction (the wizard
        posts first, then this same hook would otherwise duplicate it).
        """
        Tx = self.env['incentive.transaction']
        Period = self.env['incentive.period']
        for cn in self:
            src = cn.reversed_entry_id
            employee = src.incentive_employee_id or cn.incentive_employee_id
            if not employee:
                continue
            invoice_tx = Tx.search([
                ('move_id', '=', src.id),
                ('employee_id', '=', employee.id),
                ('transaction_type', '=', 'invoice'),
            ], limit=1)
            if not invoice_tx:
                continue
            period = Period._get_period_for_date(
                cn.invoice_date or fields.Date.context_today(cn),
                cn.company_id)
            for line in cn.invoice_line_ids.filtered(
                    lambda l: l.display_type == 'product'
                    and not l.is_downpayment):
                if Tx.search_count([
                    ('move_line_id', '=', line.id),
                    ('employee_id', '=', employee.id),
                ]):
                    continue
                Tx.create({
                    'move_line_id': line.id,
                    'move_id': cn.id,
                    'employee_id': employee.id,
                    'company_id': cn.company_id.id,
                    'source_period_id': period.id,
                    'transaction_type': 'refund',
                    'base_amount': -abs(line.price_subtotal),
                    'discount': line.discount,
                    'is_discount_eligible': invoice_tx.is_discount_eligible,
                    'reversal_of_id': invoice_tx.id,
                    'state': 'confirmed',
                })


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # ponytail: not stored -- it is a display-only column on the invoice line
    # list, so computing on read costs nothing and no stored row can go stale
    # when the rule's cap changes or the depends grow. Store it again only if
    # it ever needs to be filtered or grouped.
    incentive_eligible = fields.Boolean(
        string='Incentive Eligible', compute='_compute_incentive_eligible',
        help="S07: True when the line discount is within the configured cap. "
             "Evaluated per line, so one bad line does not disqualify the "
             "whole invoice. Down-payment lines are never eligible.")

    @api.depends('discount', 'move_id.invoice_date', 'is_downpayment')
    def _compute_incentive_eligible(self):
        Rule = self.env['incentive.rule']
        for line in self:
            if (line.display_type != 'product'
                    or line.is_downpayment
                    or line.move_id.move_type not in (
                        'out_invoice', 'out_refund')):
                line.incentive_eligible = False
                continue
            date_ref = line.move_id.invoice_date or fields.Date.context_today(line)
            rule = Rule.search([
                ('date_from', '<=', date_ref),
                '|', ('date_to', '=', False), ('date_to', '>=', date_ref),
                ('company_id', '=', line.company_id.id),
            ], limit=1)
            cap = rule.max_discount if rule else 35.0
            line.incentive_eligible = line.discount <= cap
