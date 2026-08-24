# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class IncentivePeriod(models.Model):
    """Monthly incentive period -- the unit everything is tagged against.

    S21: every transaction stores incentive month, source invoice month and
    payment month separately.
    S22: once approved and locked, no recalculation may touch it.
    """
    _name = 'incentive.period'
    _description = 'Incentive Period'
    _order = 'date_start desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    rule_id = fields.Many2one(
        'incentive.rule', string='Rule Version', tracking=True,
        help="Tier table version frozen for this period. Changing the rule "
             "after approval is blocked.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('calculated', 'Calculated'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], default='draft', required=True, tracking=True)

    target_ids = fields.One2many('incentive.target', 'period_id', string='Targets')
    payout_ids = fields.One2many('incentive.payout', 'period_id', string='Payouts')
    branch_target_ids = fields.One2many(
        'incentive.branch.target', 'period_id', string='Branch Targets',
        help="Per-branch rolling forecast and sign-off. Each row calculates, "
             "approves and locks on its own schedule.")
    transaction_ids = fields.One2many(
        'incentive.transaction', 'source_period_id', string='Source Transactions')

    target_count = fields.Integer(compute='_compute_counts')
    payout_count = fields.Integer(compute='_compute_counts')
    transaction_count = fields.Integer(compute='_compute_counts')

    total_target = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    total_payout = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    _sql_constraints = [
        ('date_uniq', 'unique(date_start, date_end, company_id)',
         'An incentive period with these dates already exists.'),
    ]

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_('End date must be after start date.'))

    @api.depends('target_ids', 'payout_ids', 'transaction_ids')
    def _compute_counts(self):
        for rec in self:
            rec.target_count = len(rec.target_ids)
            rec.payout_count = len(rec.payout_ids)
            rec.transaction_count = len(rec.transaction_ids)

    @api.depends('target_ids.amount', 'payout_ids.total_payout')
    def _compute_totals(self):
        for rec in self:
            rec.total_target = sum(rec.target_ids.mapped('amount'))
            rec.total_payout = sum(rec.payout_ids.mapped('total_payout'))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_period_for_date(self, date_value, company=None):
        """Return the period containing ``date_value`` (or empty recordset)."""
        if not date_value:
            return self.browse()
        company = company or self.env.company
        return self.search([
            ('date_start', '<=', date_value),
            ('date_end', '>=', date_value),
            ('company_id', '=', company.id),
        ], limit=1)

    def _previous_period(self):
        self.ensure_one()
        return self.search([
            ('date_end', '<', self.date_start),
            ('company_id', '=', self.company_id.id),
        ], order='date_end desc', limit=1)

    def _check_not_locked(self):
        locked = self.filtered(lambda p: p.state == 'locked')
        if locked:
            raise UserError(_(
                'Period %s is locked. Approved payout figures must never change '
                'after the accounting period is closed. Create an adjustment in '
                'a later period instead.'
            ) % ', '.join(locked.mapped('name')))

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def action_open(self):
        for rec in self:
            if not rec.rule_id:
                raise UserError(_('Assign a Rule Version before opening period %s.') % rec.name)
        self.write({'state': 'open'})

    def action_calculate(self):
        """Generate transactions + payouts for this period."""
        self._check_not_locked()
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_('Open period %s before calculating.') % rec.name)
            # Same gate as the per-branch button: a period-wide calculate must
            # not slip past a stale cascade just because it went the other way in.
            rec.branch_target_ids.filtered(
                lambda b: not b._is_closed())._check_cascade_current()
            rec.transaction_ids  # noqa -- keep prefetch warm
            self.env['incentive.transaction']._generate_for_period(rec)
            self.env['incentive.payout']._compute_for_period(rec)
            rec.state = 'calculated'
        return True

    def action_approve(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Calculate period %s before approving.') % rec.name)
        self.write({'state': 'approved'})
        self.branch_target_ids.filtered(
            lambda b: b.state == 'calculated').write({'state': 'approved'})

    def action_lock(self):
        """Lock the whole period -- the umbrella over the per-branch locks.

        Branches sign off independently, but closing the accounting period
        freezes every one of them, including any still in draft.
        """
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only an approved period can be locked.'))
        self.write({'state': 'locked'})
        self.branch_target_ids.write({'state': 'locked'})
        self.payout_ids.write({'is_frozen': True})
        self.target_ids._compute_shortfall()

    def _remaining_months(self):
        """First-of-month dates after this period up to the rule's end date."""
        self.ensure_one()
        rule = self.rule_id
        if not rule or not rule.date_to:
            return []
        out = []
        month = (self.date_end + relativedelta(months=1)).replace(day=1)
        while month <= rule.date_to:
            out.append(month)
            month = month + relativedelta(months=1)
        return out

    def action_reset_to_open(self):
        self._check_not_locked()
        self.write({'state': 'open'})
        self.branch_target_ids.filtered(
            lambda b: b.state == 'approved').write({'state': 'calculated'})

    def action_generate_next(self):
        """Convenience: create the following month's period."""
        self.ensure_one()
        nxt = self.date_start + relativedelta(months=1)
        return self.create({
            'name': nxt.strftime('%b %Y'),
            'date_start': nxt,
            'date_end': nxt + relativedelta(months=1, days=-1),
            'rule_id': self.rule_id.id,
            'company_id': self.company_id.id,
        })

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def action_view_payouts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payouts -- %s') % self.name,
            'res_model': 'incentive.payout',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transactions -- %s') % self.name,
            'res_model': 'incentive.transaction',
            'view_mode': 'list,form',
            'domain': [('source_period_id', '=', self.id)],
        }

    def action_view_targets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Targets -- %s') % self.name,
            'res_model': 'incentive.target',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }
