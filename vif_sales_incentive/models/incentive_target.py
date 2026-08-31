# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IncentiveTarget(models.Model):
    """One row per employee / period / bucket.

    S03: every salesperson has TWO buckets.
      * incentive  -- predefined, from the rolling forecast cascade
      * bonus      -- dynamic, inherited from vacant or resigned colleagues
    """
    _name = 'incentive.target'
    _description = 'Incentive Target'
    _order = 'period_id desc, employee_id, target_type'
    _inherit = ['mail.thread']

    period_id = fields.Many2one(
        'incentive.period', required=True, ondelete='restrict', tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', required=True, ondelete='restrict', tracking=True)
    branch_id = fields.Many2one(
        related='employee_id.incentive_branch_id', store=True, readonly=True)
    business_type = fields.Selection(
        related='employee_id.incentive_business_type', store=True, readonly=True)
    designation_id = fields.Many2one(
        related='employee_id.incentive_designation_id', store=True, readonly=True)

    target_type = fields.Selection([
        ('incentive', 'Incentive-Based'),
        ('bonus', 'Bonus-Based'),
    ], required=True, default='incentive', tracking=True)

    amount = fields.Monetary(required=True, tracking=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        related='period_id.company_id.currency_id', readonly=True)
    company_id = fields.Many2one(related='period_id.company_id', store=True, readonly=True)

    source = fields.Selection([
        ('manual', 'Manual Input'),
        ('rf_cascade', 'Rolling Forecast Cascade'),
        ('redistribution', 'Vacancy Redistribution'),
        ('proration', 'New Hire Proration'),
    ], default='manual', required=True, tracking=True)

    fte_used = fields.Float(string='FTE Used', digits=(16, 2), readonly=True)
    date_effective_start = fields.Date(
        help="S14: for a mid-month new hire this is the effective target start "
             "date. The amount above is already prorated.")
    date_effective_end = fields.Date()
    proration_ratio = fields.Float(
        string='Proration', digits=(16, 4), default=1.0,
        help="active_days / days_in_month, counting the joining day. "
             "14/31 = 0.4516 for the client's 18-August new-hire example.")

    shortfall_amount = fields.Monetary(
        string='Shortfall', currency_field='currency_id', readonly=True,
        help="Target minus net sales at lock, when positive. Zero if achieved.")
    carry_forward_amount = fields.Monetary(
        string='Carry-Forward / Month', currency_field='currency_id', readonly=True,
        help="This salesperson's own shortfall spread evenly over the scheme's "
             "remaining months. Added to their next-month target by the cascade.")
    months_remaining = fields.Integer(
        string='Months Remaining', readonly=True,
        help="Number of months after this period, up to the rule's end date.")

    movement_ids = fields.One2many(
        'incentive.target.movement', 'target_id', string='Movements')
    note = fields.Char()

    _sql_constraints = [
        ('unique_bucket', 'unique(period_id, employee_id, target_type)',
         'A salesperson can only have one target row per bucket per period.'),
    ]

    @api.constrains('period_id')
    def _check_period_state(self):
        for rec in self:
            if rec.period_id.state in ('approved', 'locked'):
                raise UserError(_(
                    'Period %s is %s -- targets can no longer be changed.'
                ) % (rec.period_id.name, rec.period_id.state))

    @api.model
    def _get_amount(self, employee, period, target_type):
        """Helper used by the payout engine. Returns a float, never a recordset."""
        rec = self.search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('target_type', '=', target_type),
        ], limit=1)
        return rec.amount if rec else 0.0

    def _compute_shortfall(self):
        """Snapshot each incentive target's shortfall at lock.

        shortfall = target - net sales (only when positive), then spread evenly
        over the scheme's remaining months. Only the incentive bucket rolls; the
        bonus bucket is a vacancy redistribution, not a personal commitment.
        """
        Payout = self.env['incentive.payout']
        for target in self.filtered(lambda t: t.target_type == 'incentive'):
            payout = Payout.search([
                ('period_id', '=', target.period_id.id),
                ('employee_id', '=', target.employee_id.id),
            ], limit=1)
            net = payout.net_sales if payout else 0.0
            shortfall = max(target.amount - net, 0.0)
            months = len(target.period_id._remaining_months())
            target.shortfall_amount = shortfall
            target.months_remaining = months
            target.carry_forward_amount = (shortfall / months) if months else 0.0
