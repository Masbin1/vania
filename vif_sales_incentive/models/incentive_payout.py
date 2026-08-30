# -*- coding: utf-8 -*-
import logging
from datetime import date as _date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class IncentivePayout(models.Model):
    """One row per salesperson per period -- the calculation snapshot.

    THE THREE SEQUENCES (each uses a DIFFERENT base -- this is the part that
    is most often implemented wrong):

      SQ1  Tier          = Net Sales of ALL invoices in the source period
                           (including unpaid AND including lines with a
                           discount above 35%) / incentive target.
                           This ONLY selects the tier.

      SQ2  Eligible base = only the lines with discount <= 35%.

      SQ3  Payout base   = of SQ2, only what is FULLY PAID, split into
                           "paid in current month" and "prior-period invoice
                           paid this month".

      Payout = SQ3 x (base_rate x tier allocation)

    Mixed scenario (bonus target > 0):
      * the incentive bucket is capped at the incentive target, the remainder
        spills into the bonus bucket (capped at the bonus target)
      * tier 5 is not available to the incentive bucket (S18)
      * the bonus bucket is paid at a flat 1.00%, no tiering
    """
    _name = 'incentive.payout'
    _description = 'Incentive Payout'
    _order = 'period_id desc, employee_id'
    _inherit = ['mail.thread']

    period_id = fields.Many2one(
        'incentive.period', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    user_id = fields.Many2one(
        related='employee_id.user_id', store=True, readonly=True, string='User')
    manager_id = fields.Many2one(
        related='employee_id.parent_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='employee_id.incentive_branch_id', store=True, readonly=True)
    business_type = fields.Selection(
        related='employee_id.incentive_business_type', store=True, readonly=True)
    company_id = fields.Many2one(related='period_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    # -- targets -------------------------------------------------------
    target_incentive = fields.Monetary(currency_field='currency_id')
    target_bonus = fields.Monetary(currency_field='currency_id')
    target_total = fields.Monetary(
        compute='_compute_target_total', store=True, currency_field='currency_id')
    is_mixed = fields.Boolean(
        string='Mixed Scenario', compute='_compute_target_total', store=True)

    # -- SQ1 -----------------------------------------------------------
    gross_sales = fields.Monetary(currency_field='currency_id')
    sales_return = fields.Monetary(
        currency_field='currency_id',
        help="S10: credit notes reduce the CURRENT period achievement even "
             "when they relate to a prior-period invoice.")
    net_sales = fields.Monetary(currency_field='currency_id')
    achievement_pct = fields.Float(string='Achievement', digits=(16, 4))
    tier_id = fields.Many2one('incentive.rule.tier', string='Tier')
    tier_level = fields.Integer(related='tier_id.level', store=True, readonly=True)
    payout_rate = fields.Float(digits=(16, 6))

    # -- SQ2 -----------------------------------------------------------
    eligible_incentive = fields.Monetary(
        string='Eligible Achievement Incentive', currency_field='currency_id')
    eligible_bonus = fields.Monetary(
        string='Eligible Achievement Bonus', currency_field='currency_id')
    excluded_discount = fields.Monetary(
        string='Excluded (Discount > cap)', currency_field='currency_id')

    # -- SQ3 -----------------------------------------------------------
    paid_current_month = fields.Monetary(currency_field='currency_id')
    paid_prior_month = fields.Monetary(currency_field='currency_id')
    paid_bonus = fields.Monetary(currency_field='currency_id')

    payout_current = fields.Monetary(
        string='Incentive Payout Current Month', currency_field='currency_id')
    payout_prior = fields.Monetary(
        string='Incentive Payout Previous Month', currency_field='currency_id')
    payout_bonus = fields.Monetary(string='Bonus Payout', currency_field='currency_id')

    # -- Branch stream (0.75%) -----------------------------------------
    branch_target = fields.Monetary(
        string='Branch Target', currency_field='currency_id',
        help="Branch net-sales target for this employee's branch x business "
             "type (denominator of the branch tier).")
    branch_net_sales = fields.Monetary(currency_field='currency_id')
    branch_achievement_pct = fields.Float(
        string='Branch Achievement', digits=(16, 4))
    branch_tier_id = fields.Many2one('incentive.rule.tier', string='Branch Tier')
    branch_tier_level = fields.Integer(
        related='branch_tier_id.level', store=True, readonly=True)
    branch_payout_rate = fields.Float(digits=(16, 6))
    branch_eligible = fields.Monetary(
        string='Branch Eligible Base', currency_field='currency_id')
    branch_paid = fields.Monetary(
        string='Branch Paid Base', currency_field='currency_id')
    branch_pool = fields.Monetary(
        string='Branch Pool', currency_field='currency_id',
        help="Total branch pool = branch paid x branch rate. Split across the "
             "branch's eligible team by FTE weight.")
    branch_fte = fields.Float(
        string='Branch FTE Weight', digits=(16, 4),
        help="This employee's fte_branch x proration.")
    branch_fte_share = fields.Float(
        string='Branch FTE Share', digits=(16, 4),
        help="weight / sum(weight) for the branch x business type.")
    branch_payout = fields.Monetary(
        string='Branch Payout', currency_field='currency_id')

    total_payout = fields.Monetary(
        compute='_compute_total_payout', store=True, currency_field='currency_id')

    is_eligible = fields.Boolean(
        string='Eligible Month', compute='_compute_total_payout', store=True,
        help="S06 tagging: the month qualifies (tier 1 or above).")
    is_frozen = fields.Boolean(
        readonly=True, copy=False,
        help="Set when the period is locked. Blocks any recalculation.")

    computation_log = fields.Text(readonly=True)

    _sql_constraints = [
        ('period_employee_uniq', 'unique(period_id, employee_id)',
         'One payout row per salesperson per period.'),
    ]

    @api.depends('target_incentive', 'target_bonus')
    def _compute_target_total(self):
        for rec in self:
            rec.target_total = rec.target_incentive + rec.target_bonus
            rec.is_mixed = bool(rec.target_bonus)

    @api.depends('payout_current', 'payout_prior', 'payout_bonus', 'branch_payout',
                 'tier_id', 'branch_tier_id')
    def _compute_total_payout(self):
        for rec in self:
            rec.total_payout = (
                rec.payout_current + rec.payout_prior
                + rec.payout_bonus + rec.branch_payout)
            rec.is_eligible = bool(
                (rec.tier_id and rec.tier_id.level > 0)
                or (rec.branch_tier_id and rec.branch_tier_id.level > 0))

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------
    @api.model
    def _compute_for_period(self, period, branch_target=None):
        """Recalculate ``period``, optionally narrowed to one branch target.

        ``branch_target`` set  -- only that branch x business type is touched.
        ``branch_target`` unset -- the whole period, skipping any branch whose
        own target row is already approved or locked. That is what lets one
        branch be signed off while its neighbours are still being revised.
        """
        period.ensure_one()
        if period.state == 'locked':
            raise UserError(_('Period %s is locked.') % period.name)
        rule = period.rule_id
        if not rule:
            raise UserError(_('Period %s has no rule version.') % period.name)

        Transaction = self.env['incentive.transaction']
        BranchTarget = self.env['incentive.branch.target']
        target_domain = [('period_id', '=', period.id)]
        if branch_target:
            branch_target.ensure_one()
            target_domain += branch_target._scope_domain()[1:]
        employees = self.env['incentive.target'].search(
            target_domain).mapped('employee_id')

        results = self.browse()
        for employee in employees:
            bt = branch_target or BranchTarget._for_employee(employee, period)
            if bt and bt._is_closed() and not branch_target:
                continue
            payout = self.search([
                ('period_id', '=', period.id),
                ('employee_id', '=', employee.id),
            ], limit=1)
            if payout.is_frozen:
                results |= payout
                continue
            if not payout:
                payout = self.create({
                    'period_id': period.id,
                    'employee_id': employee.id,
                })
            payout._run(rule, Transaction)
            results |= payout

        # Branch stream: also fills payout rows for support staff who carry
        # branch FTE but no individual target.
        results |= self._compute_branch_for_period(period, branch_target=branch_target)
        return results

    @api.model
    def _compute_branch_for_period(self, period, branch_target=None):
        """BRANCH incentive stream (0.75%).

        For each branch x business type with a target this period: pool =
        (fully-paid, discount-eligible net base) x (base_rate x branch tier
        allocation). The pool is split across the branch's eligible team by
        ``fte_branch x proration``. Each employee's share lands on their payout
        row as ``branch_payout``.
        """
        period.ensure_one()
        if period.state == 'locked':
            return self.browse()
        rule = period.rule_id
        if not rule:
            return self.browse()

        Transaction = self.env['incentive.transaction']
        results = self.browse()
        branch_targets = branch_target or self.env['incentive.branch.target'].search(
            [('period_id', '=', period.id)])
        for bt in branch_targets:
            if bt._is_closed() and not branch_target:
                continue
            branch = bt.branch_id
            employees = branch.employee_ids.filtered(
                lambda e: e.incentive_business_type == bt.business_type
                and e.branch_incentive_eligible
                and e._is_incentive_active_on(period.date_start))
            if not employees:
                continue

            tx = Transaction.search([
                ('branch_id', '=', branch.id),
                ('business_type', '=', bt.business_type),
                ('source_period_id', '=', period.id),
                ('state', '!=', 'reversed'),
            ])
            gross = sum(t.base_amount for t in tx if t.transaction_type == 'invoice')
            returns = abs(sum(
                t.base_amount for t in tx if t.transaction_type == 'refund'))
            net = gross - returns

            achievement = (net / bt.amount_total) if bt.amount_total else 0.0
            # S18 caps only the INDIVIDUAL incentive bucket; the branch tier is
            # always taken from the plain table.
            tier = rule._get_tier(achievement)

            eligible_base = sum(
                t.base_amount for t in tx
                if t.is_discount_eligible and t.transaction_type == 'invoice')
            paid = sum(
                t._net_base() for t in tx
                if t.is_discount_eligible and t.is_payment_eligible
                and t.transaction_type == 'invoice')

            rate = tier.payout_rate if tier else 0.0
            pool = paid * rate

            weights = [
                (emp, (emp.incentive_designation_id.fte_branch
                       if emp.incentive_designation_id else 0.0)
                 * emp._incentive_proration(period))
                for emp in employees
            ]
            total_weight = sum(w for _, w in weights) or 0.0

            for emp, weight in weights:
                share = (weight / total_weight) if total_weight else 0.0
                payout = self.search([
                    ('period_id', '=', period.id),
                    ('employee_id', '=', emp.id),
                ], limit=1)
                if payout.is_frozen:
                    results |= payout
                    continue
                if not payout:
                    payout = self.create({
                        'period_id': period.id,
                        'employee_id': emp.id,
                    })
                payout.write({
                    'branch_target': bt.amount_total,
                    'branch_net_sales': net,
                    'branch_achievement_pct': achievement,
                    'branch_tier_id': tier.id if tier else False,
                    'branch_payout_rate': rate,
                    'branch_eligible': eligible_base,
                    'branch_paid': paid,
                    'branch_pool': pool,
                    'branch_fte': weight,
                    'branch_fte_share': share,
                    'branch_payout': pool * share,
                })
                results |= payout
        return results

    def _run(self, rule, Transaction):
        self.ensure_one()
        period = self.period_id
        employee = self.employee_id
        log = []

        # ---------- targets ----------
        Target = self.env['incentive.target']
        t_inc = Target._get_amount(employee, period, 'incentive')
        t_bon = Target._get_amount(employee, period, 'bonus')
        self.target_incentive = t_inc
        self.target_bonus = t_bon
        is_mixed = bool(t_bon)
        log.append('Target incentive=%s bonus=%s mixed=%s' % (t_inc, t_bon, is_mixed))

        # ---------- SQ1: tier from UNRESTRICTED net sales ----------
        source_tx = Transaction.search([
            ('employee_id', '=', employee.id),
            ('source_period_id', '=', period.id),
            ('state', '!=', 'reversed'),
        ])
        gross = sum(t.base_amount for t in source_tx if t.transaction_type == 'invoice')

        # Credit notes booked in this period, whatever the source invoice month.
        returns_tx = Transaction.search([
            ('employee_id', '=', employee.id),
            ('transaction_type', '=', 'refund'),
            ('source_period_id', '=', period.id),
        ])
        returns = abs(sum(returns_tx.mapped('base_amount')))

        net = gross - returns
        self.gross_sales = gross
        self.sales_return = returns
        self.net_sales = net

        achievement = (net / t_inc) if t_inc else 0.0
        self.achievement_pct = achievement
        tier = rule._get_tier(achievement, is_mixed=is_mixed)
        self.tier_id = tier.id if tier else False
        self.payout_rate = tier.payout_rate if tier else 0.0
        log.append('SQ1 net=%s / target=%s => %.4f => %s (rate %.6f)' % (
            net, t_inc, achievement, tier.name if tier else 'none',
            tier.payout_rate if tier else 0.0))

        # Freeze the tier onto this period's rows -- prior-period invoices paid
        # later will read it back instead of the future month's tier.
        source_tx._stamp_tier(tier)

        # ---------- SQ2: discount-eligible base + bucket split ----------
        eligible_tx = source_tx.filtered(
            lambda t: t.is_discount_eligible and t.transaction_type == 'invoice')
        excluded = sum(
            t.base_amount for t in source_tx
            if not t.is_discount_eligible and t.transaction_type == 'invoice')
        self.excluded_discount = excluded

        eligible_base = sum(eligible_tx.mapped('base_amount'))
        if is_mixed:
            # The bonus bucket is UNCAPPED: everything above the incentive
            # target is paid at the flat bonus rate. ``t_bon`` only flags that
            # this employee is in the mixed scenario -- it is a target to hit,
            # not a ceiling on what gets paid. Capping it here used to forfeit
            # the excess, which made a salesperson WITH a bonus target earn
            # less than the same sales figures without one.
            elig_inc = min(eligible_base, t_inc)
            elig_bon = max(eligible_base - t_inc, 0.0)
        else:
            elig_inc = eligible_base
            elig_bon = 0.0
        self.eligible_incentive = elig_inc
        self.eligible_bonus = elig_bon
        log.append('SQ2 eligible=%s excluded=%s -> incentive=%s bonus=%s' % (
            eligible_base, excluded, elig_inc, elig_bon))

        # Fill the incentive bucket first, then bonus -- allowing a single line
        # to SPLIT across the boundary. Order is CHRONOLOGICAL (invoice date,
        # then id): an invoice booked later must never displace the allocation
        # of one booked earlier. Sorting by amount instead would let a new,
        # larger invoice grab the incentive bucket and retroactively push an
        # already-calculated earlier invoice into the bonus bucket.
        remaining_inc = elig_inc
        remaining_bon = elig_bon
        for tx in eligible_tx.sorted(lambda t: (t.invoice_date or _date.max, t.id)):
            inc = min(tx.base_amount, remaining_inc)
            tx.incentive_alloc = inc
            remaining_inc -= inc
            bon = min(tx.base_amount - inc, remaining_bon)
            tx.bonus_alloc = bon
            remaining_bon -= bon
        source_tx.filtered(lambda t: not t.is_discount_eligible).write({
            'incentive_alloc': 0.0, 'bonus_alloc': 0.0})

        # ---------- SQ3: only what is FULLY PAID ----------
        # (a) invoices of THIS period paid in THIS period -- incentive and bonus
        #     portions both come from the same fully-paid rows, now split.
        paid_current_tx = eligible_tx.filtered(
            lambda t: t.is_payment_eligible and t.payment_period_id == period)
        paid_current = sum(t._net_alloc()[0] for t in paid_current_tx)
        paid_bonus = sum(t._net_alloc()[1] for t in paid_current_tx)

        # (b) invoices of a PRIOR period that became fully paid in this period
        prior_tx = Transaction.search([
            ('employee_id', '=', employee.id),
            ('payment_period_id', '=', period.id),
            ('source_period_id', '!=', period.id),
            ('is_discount_eligible', '=', True),
            ('is_payment_eligible', '=', True),
            ('transaction_type', '=', 'invoice'),
            ('state', '!=', 'reversed'),
            ('incentive_alloc', '>', 0.0),
        ])
        paid_prior = sum(t._net_alloc()[0] for t in prior_tx)

        self.paid_current_month = paid_current
        self.paid_prior_month = paid_prior
        self.paid_bonus = paid_bonus

        # ---------- payout ----------
        rate = tier.payout_rate if tier else 0.0
        self.payout_current = paid_current * rate

        # KEY RULE: each prior-period row is paid at ITS OWN frozen rate,
        # net of any partial credit note (incentive portion only).
        self.payout_prior = sum(
            t._net_alloc()[0] * t.tier_payout_rate for t in prior_tx)

        self.payout_bonus = paid_bonus * rule.bonus_rate

        log.append('SQ3 paid_current=%s x %.6f = %s' % (
            paid_current, rate, self.payout_current))
        log.append('SQ3 paid_prior=%s (own frozen rates) = %s' % (
            paid_prior, self.payout_prior))
        log.append('Bonus %s x %.6f = %s' % (
            paid_bonus, rule.bonus_rate, self.payout_bonus))

        (paid_current_tx | prior_tx)._compute_payout(rule.bonus_rate)
        self.computation_log = '\n'.join(log)
        return True

    def action_recompute(self):
        BranchTarget = self.env['incentive.branch.target']
        for rec in self:
            if rec.is_frozen:
                raise UserError(_(
                    'Payout for %s in %s is frozen -- the accounting period is '
                    'closed.') % (rec.employee_id.name, rec.period_id.name))
            bt = BranchTarget._for_employee(rec.employee_id, rec.period_id)
            if bt and bt._is_closed():
                raise UserError(_(
                    'Branch target %s is %s -- reset it to draft before '
                    'recomputing.') % (bt.display_name, bt.state))
            rec._run(rec.period_id.rule_id, self.env['incentive.transaction'])
        return True

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transactions -- %s') % self.employee_id.name,
            'res_model': 'incentive.transaction',
            'view_mode': 'list,form',
            'domain': [
                ('employee_id', '=', self.employee_id.id),
                '|',
                ('source_period_id', '=', self.period_id.id),
                ('payment_period_id', '=', self.period_id.id),
            ],
        }
