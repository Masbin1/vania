# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class IncentiveTransaction(models.Model):
    """ONE ROW PER INVOICE LINE. This is the heart of the scheme.

    Three period stamps live on every row and must never be confused:

      source_period_id   -- the month the invoice was issued. Drives the TIER.
      payment_period_id  -- the month the invoice became fully paid. Drives
                            WHEN the payout is released.
      payout_period_id   -- the month the money is actually paid out
                            (= payment_period, kept separate for adjustments).

    The single most important rule, verified against the client's own numbers:

        A prior-period invoice paid in the current month is paid at the tier
        rate of its ORIGINAL source period, not the current month's tier.

        Proof from Business Use Case, Sales C, July:
            paid invoice previous month 10,000,000 -> payout 67,500
            67,500 / 10,000,000 = 0.675% = Tier 3 = the JUNE tier,
            even though July itself is Tier 4 (0.75%).

    That is why ``tier_payout_rate`` is snapshotted onto the row when the
    source period is calculated, and is never recomputed afterwards.
    """
    _name = 'incentive.transaction'
    _description = 'Incentive Transaction'
    _order = 'source_period_id desc, employee_id, id'
    _rec_name = 'display_ref'

    # -- links ---------------------------------------------------------
    move_line_id = fields.Many2one(
        'account.move.line', string='Invoice Line', ondelete='cascade', index=True)
    move_id = fields.Many2one(
        'account.move', string='Invoice', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    branch_id = fields.Many2one(
        related='employee_id.incentive_branch_id', store=True, readonly=True)
    business_type = fields.Selection(
        related='employee_id.incentive_business_type', store=True, readonly=True)
    partner_id = fields.Many2one(related='move_id.partner_id', store=True, readonly=True)
    product_id = fields.Many2one(related='move_line_id.product_id', store=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    display_ref = fields.Char(compute='_compute_display_ref', store=True)

    # -- period stamps -------------------------------------------------
    source_period_id = fields.Many2one(
        'incentive.period', string='Source Period', required=True, index=True,
        help="Month the invoice was ISSUED -- drives the tier. Not the month "
             "it was paid; that is Payment Period.")
    payment_period_id = fields.Many2one(
        'incentive.period', string='Payment Period', index=True,
        help="Month the invoice became FULLY paid. Empty while unpaid.")
    payout_period_id = fields.Many2one(
        'incentive.period', string='Payout Period', index=True)

    invoice_date = fields.Date(related='move_id.invoice_date', store=True, readonly=True)
    payment_date = fields.Date(string='Fully Paid On', index=True)

    is_prior_period = fields.Boolean(
        compute='_compute_is_prior_period', store=True,
        help="True when the invoice was issued before the period it is paid in "
             "-- the 'Paid invoice previous month' line of the client's sheet.")

    # -- amounts -------------------------------------------------------
    transaction_type = fields.Selection([
        ('invoice', 'Invoice'),
        ('refund', 'Credit Note / Refund'),
    ], required=True, default='invoice')

    base_amount = fields.Monetary(
        string='Line Amount', currency_field='currency_id',
        help="Signed. Negative for credit notes.")
    discount = fields.Float(string='Discount (%)', digits=(16, 2))

    # -- eligibility (SQ2) ---------------------------------------------
    is_discount_eligible = fields.Boolean(
        string='Discount Eligible', default=True,
        help="S07: line discount <= the rule's max. Evaluated per LINE, "
             "not per invoice.")
    is_payment_eligible = fields.Boolean(
        string='Fully Paid', default=False)
    eligibility_note = fields.Char()

    # -- bucket allocation (split, not whole-line) ---------------------
    bucket = fields.Selection([
        ('incentive', 'Incentive-Based'),
        ('bonus', 'Bonus-Based'),
        ('excluded', 'Excluded'),
    ], compute='_compute_bucket', store=True, string='Bucket',
        help="Dominant bucket for display/grouping only; the real split is "
             "incentive_alloc / bonus_alloc.")
    incentive_alloc = fields.Monetary(
        string='Incentive Allocation', currency_field='currency_id',
        help="Portion of this line's base amount allocated to the incentive "
             "bucket (capped by the incentive target).")
    bonus_alloc = fields.Monetary(
        string='Bonus Allocation', currency_field='currency_id',
        help="Portion allocated to the bonus bucket (overflow past the "
             "incentive target).")

    # -- snapshot (frozen at source-period calculation) -----------------
    tier_id = fields.Many2one('incentive.rule.tier', string='Tier (snapshot)')
    tier_payout_rate = fields.Float(
        string='Payout Rate (snapshot)', digits=(16, 6),
        help="Frozen from the SOURCE period's tier. Never recomputed.")
    payout_amount = fields.Monetary(currency_field='currency_id')

    # -- reversal linkage ----------------------------------------------
    reversal_of_id = fields.Many2one(
        'incentive.transaction', string='Reversal Of', ondelete='set null')
    reversal_ids = fields.One2many(
        'incentive.transaction', 'reversal_of_id', string='Reversals')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid_out', 'Paid Out'),
        ('reversed', 'Reversed'),
    ], default='draft', required=True)

    _sql_constraints = [
        ('move_line_uniq', 'unique(move_line_id, employee_id)',
         'An invoice line already has an incentive transaction for this salesperson.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('move_id.name', 'product_id.name')
    def _compute_display_ref(self):
        for rec in self:
            rec.display_ref = '%s / %s' % (
                rec.move_id.name or '-', rec.product_id.display_name or '-')

    @api.depends('source_period_id', 'payment_period_id')
    def _compute_is_prior_period(self):
        for rec in self:
            rec.is_prior_period = bool(
                rec.payment_period_id
                and rec.source_period_id
                and rec.payment_period_id.date_start > rec.source_period_id.date_start
            )

    @api.depends('incentive_alloc', 'bonus_alloc')
    def _compute_bucket(self):
        for rec in self:
            if rec.incentive_alloc >= rec.bonus_alloc and rec.incentive_alloc > 0:
                rec.bucket = 'incentive'
            elif rec.bonus_alloc > 0:
                rec.bucket = 'bonus'
            else:
                rec.bucket = 'excluded'

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @api.model
    def _generate_for_period(self, period):
        """Create/refresh transactions for every posted customer invoice line
        ISSUED inside ``period`` -- paid or not.

        The period is selected on ``invoice_date``, NOT on the payment date.
        SQ1 needs every invoice of the month to pick the tier, including the
        ones still outstanding: a team that invoices its full 2M target but has
        only collected 1M is at 100% achievement, and gets paid on the 1M.
        Selecting on the payment date instead used to drop unpaid invoices from
        the tier entirely, and stamped ``source_period_id`` with the month the
        money arrived -- which also meant source and payment were always the
        same period, so the prior-period rule below could never fire.

        Whether the money has actually arrived is carried separately by
        ``payment_period_id`` / ``is_payment_eligible`` (see
        ``_refresh_payment_stamp``), and that is what SQ3 pays on. This method
        also refreshes the payment stamp of OLDER, still-open transactions --
        the multi-iteration requirement of S09.
        """
        period.ensure_one()
        if period.state == 'locked':
            raise UserError(_('Period %s is locked.') % period.name)

        rule = period.rule_id
        max_discount = rule.max_discount if rule else 35.0

        lines = self.env['account.move.line'].search([
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', 'in', ('out_invoice', 'out_refund')),
            ('move_id.invoice_date', '>=', period.date_start),
            ('move_id.invoice_date', '<=', period.date_end),
            ('display_type', '=', 'product'),
            # Down payments never earn incentive on their own. Odoo puts TWO
            # is_downpayment product lines in play: the "Down payment of x%"
            # line on the DP invoice, and its negation (qty -1) on the final
            # invoice. Dropping both leaves only the real product line, so a
            # 100M order with a 30M DP is worth 100M -- counted once, in the
            # month the FINAL invoice is fully paid, never in the month the DP
            # was settled.
            ('is_downpayment', '=', False),
            ('company_id', '=', period.company_id.id),
        ])

        created = self.browse()
        for line in lines:
            employee = line.move_id._incentive_employee()
            if not employee:
                continue
            existing = self.search([
                ('move_line_id', '=', line.id),
                ('employee_id', '=', employee.id),
            ], limit=1)
            is_refund = line.move_id.move_type == 'out_refund'
            sign = -1 if is_refund else 1
            vals = {
                'move_line_id': line.id,
                'move_id': line.move_id.id,
                'employee_id': employee.id,
                'company_id': line.company_id.id,
                'source_period_id': period.id,
                'transaction_type': 'refund' if is_refund else 'invoice',
                'base_amount': sign * abs(line.price_subtotal),
                'discount': line.discount,
                'is_discount_eligible': line.discount <= max_discount,
                'eligibility_note': (
                    _('Line discount %.2f%% exceeds the %.2f%% cap.')
                    % (line.discount, max_discount)
                    if line.discount > max_discount else False),
                'state': 'confirmed',
            }
            if existing:
                if existing.state == 'paid_out':
                    continue
                existing.write(vals)
                created |= existing
            else:
                created |= self.create(vals)

        # Drop down-payment rows an earlier run created before they were
        # excluded. _generate_for_period only creates and updates, so without
        # this a stale +DP row keeps inflating the base forever. Rows already
        # paid out are left alone -- history is never rewritten.
        stale_dp = self.search([
            ('company_id', '=', period.company_id.id),
            ('source_period_id', '=', period.id),
            ('move_line_id.is_downpayment', '=', True),
            ('state', '!=', 'paid_out'),
        ])
        if stale_dp:
            _logger.info('Incentive: removing %s stale down-payment rows in %s',
                         len(stale_dp), period.name)
            stale_dp.unlink()

        # Refresh payment stamps for THIS period's rows and for every older
        # row that is still waiting for payment (S08 / S09 multi-iteration).
        pending = self.search([
            ('company_id', '=', period.company_id.id),
            ('source_period_id.date_start', '<=', period.date_start),
            ('state', '!=', 'paid_out'),
        ])
        (created | pending)._refresh_payment_stamp()

        # Second pass: link refunds to the transaction of the invoice they
        # reverse (S10 / partial credit note net-off). Done after the loop so it
        # is independent of line iteration order.
        unlinked_refunds = self.search([
            ('transaction_type', '=', 'refund'),
            ('source_period_id', '=', period.id),
            ('reversal_of_id', '=', False),
        ])
        for refund in unlinked_refunds:
            src_move = refund.move_id.reversed_entry_id
            if not src_move:
                continue
            invoice_tx = self.search([
                ('move_id', '=', src_move.id),
                ('employee_id', '=', refund.employee_id.id),
                ('transaction_type', '=', 'invoice'),
            ], limit=1)
            if invoice_tx:
                refund.reversal_of_id = invoice_tx.id

        _logger.info('Incentive: %s transactions refreshed for period %s',
                     len(created | pending), period.name)
        return created

    def _refresh_payment_stamp(self):
        """Set payment_date / payment_period_id when the invoice is fully paid."""
        Period = self.env['incentive.period']
        for rec in self:
            move = rec.move_id
            if not move:
                continue
            paid_on = move._incentive_full_payment_date()
            if not paid_on:
                rec.write({
                    'is_payment_eligible': False,
                    'payment_date': False,
                    'payment_period_id': False,
                })
                continue
            pay_period = Period._get_period_for_date(paid_on, rec.company_id)
            rec.write({
                'is_payment_eligible': True,
                'payment_date': paid_on,
                'payment_period_id': pay_period.id or False,
                'payout_period_id': pay_period.id or False,
            })

    # ------------------------------------------------------------------
    # Tier snapshot
    # ------------------------------------------------------------------
    def _stamp_tier(self, tier):
        """Freeze the source period's tier onto these rows.

        Called once, from the payout engine, when the SOURCE period is
        calculated. Rows already paid out are skipped so history stays intact.
        """
        rate = tier.payout_rate if tier else 0.0
        self.filtered(lambda t: t.state != 'paid_out').write({
            'tier_id': tier.id if tier else False,
            'tier_payout_rate': rate,
        })

    def _net_base(self):
        """Effective base amount, net of linked reversals.

        A partial credit note (Option A net-off) is stored as a linked refund
        transaction with a negative ``base_amount``; subtracting it here means
        the invoice pays out on the collected amount, not the gross amount.
        Capped at zero so a refund can never produce a negative base.
        """
        self.ensure_one()
        refund = sum(
            r.base_amount for r in self.reversal_ids if r.state != 'reversed')
        return max(self.base_amount + refund, 0.0)

    def _net_alloc(self):
        """(incentive, bonus) portions of the net base, split by gross alloc."""
        self.ensure_one()
        base = self._net_base()
        if base <= 0 or not self.base_amount:
            return 0.0, 0.0
        inc_frac = self.incentive_alloc / self.base_amount
        bon_frac = self.bonus_alloc / self.base_amount
        return base * inc_frac, base * bon_frac

    def _compute_payout(self, bonus_rate):
        """Payout = incentive portion x frozen tier rate + bonus portion x bonus rate."""
        for rec in self:
            if not rec.is_discount_eligible or not rec.is_payment_eligible:
                rec.payout_amount = 0.0
                continue
            inc_net, bon_net = rec._net_alloc()
            rec.payout_amount = (
                inc_net * rec.tier_payout_rate + bon_net * bonus_rate
            )

    # ------------------------------------------------------------------
    # Refund reversal (S10)
    # ------------------------------------------------------------------
    def _refundable_amount(self):
        """Remaining base amount that can still be refunded via credit note."""
        self.ensure_one()
        refunded = sum(
            r.base_amount for r in self.reversal_ids if r.state != 'reversed')
        return max(self.base_amount + refunded, 0.0)

    def action_create_reversal(self):
        """Open the refund wizard: create a (partial) credit note for the
        invoice, then link a negative reversal transaction so the payout is
        reduced by the refunded amount. Amount is editable, capped at the
        line's remaining refundable amount."""
        self.ensure_one()
        if self.transaction_type != 'invoice':
            raise UserError(_('Only invoice transactions can be refunded.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refund Invoice'),
            'res_model': 'incentive.transaction.refund',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transaction_id': self.id,
                'default_refund_amount': self._refundable_amount(),
            },
        }
