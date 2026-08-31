# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IncentiveTargetCascade(models.Model):
    """S02 -- cascade a branch rolling-forecast number to individual targets.

    Mirrors Step 5 + Step 6 of the client's '<BRANCH> 2H TARGET' sheets:

        individual target = branch net sales
                          x (own FTE / total effective FTE of the population)
                          x proration ratio (new hire / resignation)
                          + carry-forward

    Carry-forward is PER EMPLOYEE: only a salesperson who fell short of their own
    target in a prior locked month carries a top-up forward, and only into their
    own bucket. Their shortfall is spread over the scheme's remaining months; the
    branch target is bumped by the sum of those top-ups.

    Nothing is lost to proration. The slice a mid-month joiner or leaver does
    NOT cover -- base x (1 - proration) -- joins the vacant-slot pool and is
    redistributed by FTE to the people who worked the full month, into their
    BONUS bucket. The branch figure therefore still adds up to the rolling
    forecast even in a month with churn.
    """
    # ponytail: regular model, not TransientModel -- Odoo Studio (Online) only
    # works on regular models. The rows persist and double as a cascade run
    # history; nothing reads them back, so an abandoned preview is only
    # clutter. Add an ir.cron unlink of old rows if that clutter ever matters.
    _name = 'incentive.target.cascade'
    _description = 'Cascade Branch Target to Individuals'
    _order = 'create_date desc'
    _rec_name = 'period_id'

    # ondelete='cascade' on every required m2o below: the rows persist now, and
    # the default 'restrict' would make an old cascade run block deleting the
    # period/branch/employee it mentions.
    period_id = fields.Many2one(
        'incentive.period', required=True, ondelete='cascade',
        domain="[('state', 'in', ('draft', 'open', 'calculated'))]")
    branch_ids = fields.Many2many(
        'incentive.branch', string='Branches', required=True,
        help="Cascade every selected branch in one run. Each one uses its own "
             "Branch Target figure for this period.")
    business_type = fields.Selection([
        ('b2b', 'B2B'),
        ('b2c', 'B2C'),
    ], required=True, default='b2b')

    carry_forward_total = fields.Monetary(
        string='Carry-Forward Total', currency_field='currency_id', readonly=True,
        help="Sum of each salesperson's carry-forward top-up across the "
             "selected branches.")
    currency_id = fields.Many2one(
        related='period_id.company_id.currency_id', readonly=True)

    scope = fields.Selection([
        ('individual', 'Individual Target'),
        ('branch', 'Branch Pool'),
    ], default='individual', required=True,
        help="Individual uses the individual FTE column (Support = 0.00); "
             "Branch uses the branch FTE column (Support = 0.25).")

    redistribute_vacant = fields.Boolean(
        string='Redistribute Vacant Slots', default=True,
        help="S13: a vacant headcount's share -- plus the uncovered slice of "
             "anyone who joined or resigned mid-month -- is spread over the "
             "full-month population and lands in their BONUS bucket.")
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Targets', default=True)

    preview_line_ids = fields.One2many(
        'incentive.target.cascade.line', 'wizard_id', string='Preview')

    # ------------------------------------------------------------------
    def _branch_targets(self):
        """The branch target row of every selected branch, in order.

        The figures are NOT entered here any more -- each branch carries its own
        rolling forecast, so they live on ``incentive.branch.target`` (one row
        per branch x business type) and this wizard only reads them. A branch
        without a row is an error rather than a silent zero.
        """
        self.ensure_one()
        BranchTarget = self.env['incentive.branch.target']
        rows = BranchTarget.browse()
        missing = []
        for branch in self.branch_ids:
            bt = BranchTarget.search([
                ('period_id', '=', self.period_id.id),
                ('branch_id', '=', branch.id),
                ('business_type', '=', self.business_type),
            ], limit=1)
            if bt:
                rows |= bt
            else:
                missing.append(branch.name)
        if missing:
            raise UserError(_(
                'No Branch Target for %s in %s. Enter the rolling forecast '
                'under Branch Targets first.'
            ) % (', '.join(missing), self.period_id.name))
        return rows

    def _collect_population(self, branch):
        self.ensure_one()
        employees = self.env['hr.employee'].search([
            ('incentive_branch_id', '=', branch.id),
            ('incentive_business_type', '=', self.business_type),
        ])
        active, vacant = [], []
        for emp in employees:
            desig = emp.incentive_designation_id
            if not desig:
                continue
            fte = desig.fte_individual if self.scope == 'individual' else desig.fte_branch
            if not fte:
                continue
            # Active = worked ANY day of the period, not active on its LAST
            # day. Someone who resigns mid-month still earned a (prorated)
            # target for the days they worked; treating them as vacant used to
            # drop their target row entirely, so that month's sales had no
            # payout row to land on and the WHOLE slot went into the pool.
            if emp.is_vacant_slot or not emp._incentive_proration(self.period_id):
                vacant.append((emp, fte))
            else:
                active.append((emp, fte))
        return active, vacant

    def _seat_groups(self, active):
        """Chain ACTIVE employees into "seats": a resignation linked to the
        next same-designation hire that fills it, in date order.

        A seat that changes hands mid-month is still ONE position. It must
        count once in the FTE denominator -- not once per body that sat in
        it -- and only the days genuinely uncovered (before the first
        occupant, between two occupants, or after the last one) belong in
        the bonus pool. Without this, a same-day-adjacent resign+hire reads
        as the team growing by a whole FTE for that month, and BOTH halves
        of the handover leak into the bonus pool instead of covering each
        other.

        Returns a list of chains; each chain is a list of ``(employee, fte)``
        in chronological order. An employee with no chain partner is a
        chain of one -- the ordinary case.

        ponytail: pairs the nearest later hire by date, same designation
        only -- a Lead replaced by a Team member mid-month is left as two
        independent contributors (old behaviour). Add designation-spanning
        seats if that combination is ever needed.
        """
        by_id = {emp.id: (emp, fte) for emp, fte in active}
        leavers = sorted(
            (t for t in active if t[0].incentive_date_end),
            key=lambda t: t[0].incentive_date_end)
        joiners = sorted(
            (t for t in active if t[0].incentive_date_start),
            key=lambda t: t[0].incentive_date_start)

        succ, claimed = {}, set()
        for leaver, _lf in leavers:
            for joiner, _jf in joiners:
                if (joiner.id in claimed or joiner.id == leaver.id
                        or joiner.incentive_date_start <= leaver.incentive_date_end
                        or joiner.incentive_designation_id != leaver.incentive_designation_id):
                    continue
                succ[leaver.id] = joiner.id
                claimed.add(joiner.id)
                break

        seats = []
        for emp, fte in active:
            if emp.id in claimed:
                continue  # picked up as somebody's successor below
            chain = [(emp, fte)]
            cur_id = emp.id
            while cur_id in succ:
                cur_id = succ[cur_id]
                chain.append(by_id[cur_id])
            seats.append(chain)
        return seats

    def _carry_forward(self, employee):
        """Sum of this employee's own carry-forward from prior locked months.

        'Locked' is now decided by the employee's OWN branch target, not by the
        period: a shortfall only rolls forward once that branch has been signed
        off, even if a neighbouring branch in the same period is still open.
        """
        self.ensure_one()
        if not self.period_id.rule_id:
            return 0.0
        locked_periods = self.env['incentive.branch.target'].search([
            ('branch_id', '=', employee.incentive_branch_id.id),
            ('business_type', '=', employee.incentive_business_type),
            ('state', '=', 'locked'),
            ('period_id.date_end', '<', self.period_id.date_start),
            ('period_id.rule_id', '=', self.period_id.rule_id.id),
        ]).mapped('period_id')
        if not locked_periods:
            return 0.0
        prior = self.env['incentive.target'].search([
            ('employee_id', '=', employee.id),
            ('target_type', '=', 'incentive'),
            ('period_id', 'in', locked_periods.ids),
            ('carry_forward_amount', '>', 0.0),
        ])
        return sum(prior.mapped('carry_forward_amount'))

    def _preview_branch(self, branch_target):
        """Build the preview lines of ONE branch. Returns its carry-forward sum.

        Each branch is a self-contained population: its own FTE denominator, its
        own vacancy pool. Nothing crosses a branch boundary, which is why the
        multi-branch run is just this method in a loop.
        """
        self.ensure_one()
        branch = branch_target.branch_id
        active, vacant = self._collect_population(branch)
        if not active:
            raise UserError(_(
                'No eligible salesperson found for %s / %s.'
            ) % (branch.name, self.business_type.upper()))

        # A team short of its ideal size still divides by the ideal. Without
        # this, a branch running 4 of 5 seats hands the missing seat's slice to
        # the four who are there -- silently raising their individual targets
        # because a colleague left. Charging the gap keeps the denominator
        # stable, and the unclaimed slice lands in the bonus pool instead.
        # ponytail: an empty seat weighs 1.0 (a Team member). Model a missing
        # LEAD as a vacant-slot record with the Lead designation to get 1.5.
        gap_fte = float(branch._headcount_gap(self.business_type))
        seats = self._seat_groups(active)
        # One FTE contribution per SEAT, not per employee -- a mid-month
        # handover is still a single position (see _seat_groups).
        total_fte_all = (
            sum(seat[0][1] for seat in seats)
            + sum(f for _e, f in vacant) + gap_fte)
        if not total_fte_all:
            raise UserError(_('Total effective FTE is zero for %s.') % branch.name)

        Line = self.env['incentive.target.cascade.line']
        base_target = branch_target.amount
        vacant_pool = 0.0
        rows = []
        carry_total = 0.0

        for seat in seats:
            seat_fte = seat[0][1]
            seat_base = base_target * (seat_fte / total_fte_all)
            coverage = 0.0
            for emp, fte in seat:
                proration = emp._incentive_proration(self.period_id)
                coverage += proration
                carry = self._carry_forward(emp)
                carry_total += carry
                rows.append((emp, fte, proration, seat_base, seat_base * proration, carry))
            if self.redistribute_vacant:
                # Only the days nobody occupied this seat at all -- a
                # seamless handover covers 100% between its occupants and
                # leaves nothing behind.
                vacant_pool += seat_base * max(0.0, 1.0 - coverage)

        if self.redistribute_vacant:
            # Two more sources feed the same pool: whole slots nobody filled
            # at all, and the ideal-size gap.
            vacant_pool += sum(
                base_target * (f / total_fte_all) for _e, f in vacant)
            vacant_pool += base_target * (gap_fte / total_fte_all)

        # The pool is a full-month commitment, so only full-month people can
        # take it on. Falling back to everyone (weighted by their proration)
        # when nobody worked the whole month keeps the pool from silently
        # evaporating in a month where the entire team churned.
        receivers = [(e, f) for e, f, p, _b, _a, _c in rows if p >= 1.0]
        if not receivers:
            receivers = [(e, f * p) for e, f, p, _b, _a, _c in rows]
        total_fte_receiving = sum(f for _e, f in receivers)
        share_by_emp = {
            e.id: f / total_fte_receiving for e, f in receivers
        } if total_fte_receiving else {}

        for emp, fte, proration, _base, amount, carry in rows:
            bonus = vacant_pool * share_by_emp.get(emp.id, 0.0)
            Line.create({
                'wizard_id': self.id,
                'branch_target_id': branch_target.id,
                'employee_id': emp.id,
                'fte': fte,
                'proration': proration,
                'base_amount': amount,
                'carry_forward_amount': carry,
                'bonus_amount': bonus,
            })
        return carry_total

    def action_preview(self):
        self.ensure_one()
        self.preview_line_ids.unlink()
        self.carry_forward_total = sum(
            self._preview_branch(bt) for bt in self._branch_targets())
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        self.ensure_one()
        if not self.preview_line_ids:
            self.action_preview()
        if self.period_id.state in ('approved', 'locked'):
            raise UserError(_('Period %s is closed.') % self.period_id.name)

        branch_targets = self._branch_targets()
        closed = branch_targets.filtered(lambda b: b._is_closed())
        if closed:
            raise UserError(_(
                'Branch target %s is closed -- reset it to draft to cascade '
                'again.') % ', '.join(closed.mapped('display_name')))

        Target = self.env['incentive.target']
        Movement = self.env['incentive.target.movement']

        for line in self.preview_line_ids:
            for ttype, amount, source in (
                    ('incentive', line.incentive_amount, 'rf_cascade'),
                    ('bonus', line.bonus_amount, 'redistribution')):
                if not amount:
                    continue
                existing = Target.search([
                    ('period_id', '=', self.period_id.id),
                    ('employee_id', '=', line.employee_id.id),
                    ('target_type', '=', ttype),
                ], limit=1)
                vals = {
                    'amount': amount,
                    'source': source,
                    'fte_used': line.fte,
                    'proration_ratio': line.proration,
                }
                if existing:
                    if self.overwrite_existing:
                        existing.write(vals)
                else:
                    Target.create(dict(
                        vals,
                        period_id=self.period_id.id,
                        employee_id=line.employee_id.id,
                        target_type=ttype,
                    ))
                if ttype == 'bonus':
                    Movement.create({
                        'period_id': self.period_id.id,
                        'reason': 'resignation',
                        'to_employee_id': line.employee_id.id,
                        'amount': amount,
                        'target_type': 'bonus',
                        'fte_share': line.fte,
                        'date_effective': self.period_id.date_start,
                        'note': _('Vacancy redistribution from FTE cascade.'),
                    })

        # Stamp each branch's carry-forward so its pool tiers against the total
        # the team is now accountable for. Stored SEPARATELY from the base
        # figure: writing base+carry back into ``amount`` would compound the
        # carry every time the cascade is re-run.
        for bt in branch_targets:
            bt.carry_forward_amount = sum(
                self.preview_line_ids
                .filtered(lambda l: l.branch_target_id == bt)
                .mapped('carry_forward_amount'))
        return {'type': 'ir.actions.act_window_close'}


class IncentiveTargetCascadeLine(models.Model):
    _name = 'incentive.target.cascade.line'
    _description = 'Cascade Preview Line'

    wizard_id = fields.Many2one('incentive.target.cascade', ondelete='cascade')
    branch_target_id = fields.Many2one(
        'incentive.branch.target', required=True, ondelete='cascade')
    branch_id = fields.Many2one(
        related='branch_target_id.branch_id', readonly=True, string='Branch')
    employee_id = fields.Many2one(
        'hr.employee', required=True, ondelete='cascade')
    designation_id = fields.Many2one(
        related='employee_id.incentive_designation_id', readonly=True)
    fte = fields.Float(digits=(16, 2))
    proration = fields.Float(digits=(16, 4))
    base_amount = fields.Monetary(
        string='Base Incentive', currency_field='currency_id',
        help="Branch target x FTE share x proration. This month's own work, "
             "before anything carried over.")
    carry_forward_amount = fields.Monetary(
        string='Carry-Forward', currency_field='currency_id',
        help="Top-up rolled in from this person's shortfall in prior locked "
             "months. Shown apart so the base figure stays readable.")
    incentive_amount = fields.Monetary(
        string='Total Incentive', compute='_compute_incentive_amount',
        currency_field='currency_id',
        help="Base + carry-forward. This is what lands in the incentive target.")
    bonus_amount = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id', readonly=True)

    @api.depends('base_amount', 'carry_forward_amount')
    def _compute_incentive_amount(self):
        for line in self:
            line.incentive_amount = line.base_amount + line.carry_forward_amount
