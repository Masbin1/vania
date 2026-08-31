# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_round


class IncentiveTransactionRefund(models.Model):
    """S10 -- create a (partial) credit note for the invoice behind a
    transaction, then link a negative reversal transaction so the payout is
    reduced by the refunded amount.

    The refund amount is editable but capped at the line's remaining
    refundable amount (invoice line amount minus what was already refunded).
    """
    # ponytail: regular model, not TransientModel -- Odoo Studio (Online) only
    # works on regular models. Rows are the refund log; keeping them is a
    # feature here (who refunded what, when) rather than clutter.
    _name = 'incentive.transaction.refund'
    _description = 'Refund Incentive Transaction'
    _order = 'create_date desc'
    _rec_name = 'transaction_id'

    transaction_id = fields.Many2one(
        'incentive.transaction', required=True, ondelete='cascade')
    move_id = fields.Many2one(related='transaction_id.move_id', readonly=True)
    move_line_id = fields.Many2one(
        related='transaction_id.move_line_id', readonly=True)
    employee_id = fields.Many2one(
        related='transaction_id.employee_id', readonly=True)
    base_amount = fields.Monetary(
        string='Invoice Line Amount', currency_field='currency_id',
        readonly=True, related='transaction_id.base_amount')
    refundable_amount = fields.Monetary(
        string='Refundable', currency_field='currency_id', readonly=True,
        compute='_compute_refundable_amount')
    refund_amount = fields.Monetary(
        string='Refund Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        related='transaction_id.currency_id', readonly=True)
    refund_move_id = fields.Many2one(
        'account.move', string='Credit Note', readonly=True, copy=False,
        help="Set once the credit note is posted. A record that already has "
             "one cannot be refunded again.")

    @api.depends('transaction_id')
    def _compute_refundable_amount(self):
        for wizard in self:
            wizard.refundable_amount = (
                wizard.transaction_id._refundable_amount()
                if wizard.transaction_id else 0.0)

    def _check_refund_amount(self):
        for wizard in self:
            if float_compare(
                    wizard.refund_amount, 0.0,
                    precision_rounding=wizard.currency_id.rounding) <= 0:
                raise ValidationError(_('Refund amount must be positive.'))
            if float_compare(
                    wizard.refund_amount, wizard.refundable_amount,
                    precision_rounding=wizard.currency_id.rounding) > 0:
                raise ValidationError(_(
                    'Refund amount %s exceeds the refundable amount %s.')
                    % (wizard.refund_amount, wizard.refundable_amount))

    @api.constrains('refund_amount')
    def _check_refund_amount_constraint(self):
        self._check_refund_amount()

    def action_refund(self):
        self.ensure_one()
        # The record persists now (regular model), so the button survives the
        # dialog and can be pressed twice. Without this, that is two credit
        # notes for one refund.
        if self.refund_move_id:
            raise ValidationError(_(
                'This refund was already processed as credit note %s.')
                % self.refund_move_id.display_name)
        self._check_refund_amount()
        # Posting the credit note triggers the incentive refund transaction
        # (see account.move._create_incentive_refund_transactions), so no
        # separate reversal is created here.
        self.refund_move_id = self._create_credit_note()
        # A full refund closes the original transaction.
        if float_compare(
                self.refund_amount, self.refundable_amount,
                precision_rounding=self.currency_id.rounding) >= 0:
            self.transaction_id.state = 'reversed'
        return {'type': 'ir.actions.act_window_close'}

    def _create_credit_note(self):
        """Create + post an ``out_refund`` scaled to ``refund_amount``."""
        self.ensure_one()
        tx = self.transaction_id
        move = tx.move_id
        line = tx.move_line_id

        subtotal = line.price_subtotal or 1.0
        factor = self.refund_amount / subtotal
        qty = float_round(line.quantity * factor, precision_digits=6)

        refund = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': move.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'journal_id': move.journal_id.id,
            'reversed_entry_id': move.id,
            'ref': _('Incentive refund of %s') % (move.name or move.id),
            'invoice_user_id': move.invoice_user_id.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom_id.id,
                'quantity': qty,
                'price_unit': line.price_unit,
                'discount': line.discount,
                'tax_ids': [(6, 0, line.tax_ids.ids)],
                'account_id': line.account_id.id,
                'name': line.name or line.product_id.display_name,
                'analytic_distribution': line.analytic_distribution,
            })],
        })
        refund.action_post()
        return refund
