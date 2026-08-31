# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IncentiveBranchTarget(models.Model):
    """Branch rolling-forecast net sales target per period -- and the unit of
    work the whole scheme is driven from.

    This is the denominator of the BRANCH incentive stream (0.75%). It is the
    same number the cascade wizard distributes to individual targets, but it is
    stored here separately because the branch pool tier is computed against the
    branch total, not the sum of individual targets (Support carries 0.25 branch
    FTE but no individual target).

    ``incentive.period`` stays a plain calendar month -- it is looked up by date
    (``_get_period_for_date``) and must resolve to exactly one row. So the
    per-branch state machine lives HERE, at the (period, branch, business type)
    grain: JKT-B2B can be calculated, approved and locked while SBY-B2C is still
    being revised. The period state remains the umbrella -- locking a period
    locks every branch under it.
    """
    _name = 'incentive.branch.target'
    _description = 'Incentive Branch Target'
    _order = 'period_id desc, branch_id, business_type'

    period_id = fields.Many2one(
        'incentive.period', required=True, ondelete='restrict', index=True)
    branch_id = fields.Many2one('incentive.branch', required=True, index=True)
    business_type = fields.Selection([
        ('b2b', 'B2B'),
        ('b2c', 'B2C'),
    ], required=True)

    amount = fields.Monetary(
        string='Branch Net Sales Target', required=True, currency_field='currency_id',
        help="Base rolling forecast for this branch / business type. Enter it "
             "here; the cascade reads it, it never overwrites it.")
    carry_forward_amount = fields.Monetary(
        string='Carry-Forward', currency_field='currency_id', readonly=True,
        help="Sum of each salesperson's carry-forward top-up, filled by the "
             "cascade. Kept apart from the base so re-running the cascade "
             "cannot compound it.")
    amount_total = fields.Monetary(
        string='Total Target', compute='_compute_amount_total', store=True,
        currency_field='currency_id',
        help="Base + carry-forward. This is what the branch tier is measured "
             "against.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], default='draft', required=True, index=True)

    payout_total = fields.Monetary(
        string='Branch Payout', compute='_compute_payout_total',
        currency_field='currency_id')

    needs_recascade = fields.Boolean(
        string='Population Changed', compute='_compute_needs_recascade',
        help="The team is no longer the one these targets were cascaded for -- "
             "somebody resigned, joined or moved since. Calculate is blocked "
             "until the cascade is re-run.")
    recascade_reason = fields.Char(compute='_compute_needs_recascade')

    currency_id = fields.Many2one(
        related='period_id.company_id.currency_id', readonly=True)
    company_id = fields.Many2one(
        related='period_id.company_id', store=True, readonly=True)

    _sql_constraints = [
        ('unique_branch_target', 'unique(period_id, branch_id, business_type)',
         'One branch target per period / branch / business type.'),
    ]

    @api.depends('amount', 'carry_forward_amount')
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = rec.amount + rec.carry_forward_amount

    def _compute_payout_total(self):
        for rec in self:
            rec.payout_total = sum(rec._payouts().mapped('total_payout'))

    def _compute_needs_recascade(self):
        """Have the people changed since these targets were cascaded?

        Nothing recalculates when HR types a resignation date -- targets are a
        commitment, they must not shift under a month-end that is already
        running. So the risk is the opposite one: the date is entered, nobody
        re-runs the cascade, and the month closes on figures for a team that no
        longer exists. This is the flag that makes that visible.

        No timestamp needed: the cascade already stamps ``proration_ratio`` on
        every target row, so comparing it against today's value of the same
        calculation says whether the population moved.
        """
        for rec in self:
            rec.needs_recascade = False
            rec.recascade_reason = False
            if rec.state == 'locked' or not rec.period_id:
                continue
            targets = rec._targets().filtered(
                lambda t: t.target_type == 'incentive')
            if not targets:
                continue

            stale = targets.filtered(lambda t: abs(
                t.proration_ratio
                - t.employee_id._incentive_proration(rec.period_id)) > 0.0001)
            if stale:
                rec.needs_recascade = True
                rec.recascade_reason = _(
                    'Working days changed for: %s') % ', '.join(
                        stale.mapped('employee_id.name'))
                continue

            # Somebody joined the team and has no target row at all.
            # ponytail: only checks people carrying an individual FTE, because
            # a target row cannot say which scope the cascade ran with -- a
            # Support hire under a branch-scope cascade is missed here.
            covered = targets.mapped('employee_id')
            joined = rec.branch_id._team_employees(rec.business_type).filtered(
                lambda e: e not in covered
                and not e.is_vacant_slot
                and e.incentive_designation_id.fte_individual
                and e._incentive_proration(rec.period_id))
            if joined:
                rec.needs_recascade = True
                rec.recascade_reason = _(
                    'No target yet for: %s') % ', '.join(joined.mapped('name'))

    # ------------------------------------------------------------------
    # Scoping helpers -- every branch-scoped query goes through these
    # ------------------------------------------------------------------
    @api.model
    def _for_employee(self, employee, period):
        """The branch target governing this employee in this period."""
        if not (employee.incentive_branch_id and employee.incentive_business_type):
            return self.browse()
        return self.search([
            ('period_id', '=', period.id),
            ('branch_id', '=', employee.incentive_branch_id.id),
            ('business_type', '=', employee.incentive_business_type),
        ], limit=1)

    def _scope_domain(self):
        """Domain selecting this branch x business type inside its period.

        ``branch_id`` / ``business_type`` are stored related fields on target,
        payout and transaction, so the same three clauses work on all of them.
        """
        self.ensure_one()
        return [
            ('period_id', '=', self.period_id.id),
            ('branch_id', '=', self.branch_id.id),
            ('business_type', '=', self.business_type),
        ]

    def _targets(self):
        self.ensure_one()
        return self.env['incentive.target'].search(self._scope_domain())

    def _payouts(self):
        self.ensure_one()
        return self.env['incentive.payout'].search(self._scope_domain())

    def _is_closed(self):
        """True when nothing under this branch target may change any more."""
        self.ensure_one()
        return (
            self.state in ('approved', 'locked')
            or self.period_id.state in ('approved', 'locked'))

    def _check_cascade_current(self):
        """Refuse to calculate a branch whose team has moved since the cascade.

        Payouts are weighted by each salesperson's target and working days, so
        calculating against last week's population pays real money to the wrong
        split. The banner warns; this is what stops it.
        """
        stale = self.filtered('needs_recascade')
        if stale:
            raise UserError(_(
                'These teams changed since their targets were cascaded:\n\n'
                '%(details)s\n\n'
                'Calculating now would pay against a team that no longer '
                'exists. Re-run the target cascade first.',
                details='\n'.join(
                    '- %s: %s' % (rec.display_name, rec.recascade_reason or '')
                    for rec in stale)))

    def _check_not_locked(self):
        blocked = self.filtered(
            lambda b: b.state == 'locked' or b.period_id.state == 'locked')
        if blocked:
            raise UserError(_(
                'Branch target %s is locked. Approved payout figures must never '
                'change after the accounting period is closed. Create an '
                'adjustment in a later period instead.'
            ) % ', '.join(blocked.mapped('display_name')))

    def _display_label(self):
        self.ensure_one()
        return '%s / %s -- %s' % (
            self.branch_id.name,
            dict(self._fields['business_type'].selection).get(self.business_type),
            self.period_id.name)

    @api.depends('branch_id', 'business_type', 'period_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec._display_label()

    # ------------------------------------------------------------------
    # State machine -- mirrors the period, scoped to one branch
    # ------------------------------------------------------------------
    def action_calculate(self):
        """Generate transactions + payouts for THIS branch only."""
        self._check_not_locked()
        for rec in self:
            if rec.period_id.state == 'draft':
                raise UserError(_(
                    'Open period %s before calculating a branch.') % rec.period_id.name)
            if rec.state == 'approved':
                raise UserError(_(
                    'Branch target %s is approved. Reset it to draft to '
                    'recalculate.') % rec.display_name)
            rec._check_cascade_current()
            self.env['incentive.transaction']._generate_for_period(rec.period_id)
            self.env['incentive.payout']._compute_for_period(
                rec.period_id, branch_target=rec)
            rec.state = 'calculated'
        return True

    def action_approve(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_(
                    'Calculate branch target %s before approving.') % rec.display_name)
        self.write({'state': 'approved'})

    def action_lock(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_(
                    'Only an approved branch target can be locked.'))
            rec.state = 'locked'
            rec._payouts().write({'is_frozen': True})
            rec._targets()._compute_shortfall()
        return True

    def action_reset_to_draft(self):
        self._check_not_locked()
        self.write({'state': 'draft'})
