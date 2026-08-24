# -*- coding: utf-8 -*-
"""Mid-month resignation: prorate the leaver, redistribute what they drop.

The client's scenario, verbatim: 4.5M over 1 Lead (1.5 FTE) + 3 Team (1.0
each). Full month that is Lead 1.5M and 1.0M each. One Team member resigns on
21 August, so 21/31 of their August target stands and the other 10/31 becomes
bonus for the three who worked the whole month.

Before the fix the leaver was classed as a vacant slot, which lost their
target row entirely and put the WHOLE 1.0M into the pool.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestResignationProration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        lead = cls.env.ref('vif_sales_incentive.designation_lead')
        team = cls.env.ref('vif_sales_incentive.designation_team')

        cls.branch = cls.env['incentive.branch'].create(
            {'name': 'Test Resign', 'code': 'TSTR', 'company_id': cls.company.id})

        cls.lead, cls.m1, cls.m2, cls.leaver = cls.env['hr.employee'].create([
            {'name': 'R Lead', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b', 'incentive_designation_id': lead.id},
            {'name': 'R Member 1', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b', 'incentive_designation_id': team.id},
            {'name': 'R Member 2', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b', 'incentive_designation_id': team.id},
            {'name': 'R Leaver', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b', 'incentive_designation_id': team.id,
             'incentive_date_end': fields.Date.to_date('2025-08-21')},
        ])

        rule = cls.env['incentive.rule'].create({
            'name': 'Resign Rule',
            'date_from': fields.Date.to_date('2025-01-01'),
            'date_to': fields.Date.to_date('2025-12-31'),
            'company_id': cls.company.id,
            'tier_ids': [(0, 0, {
                'name': 'Tier 1', 'level': 1, 'achievement_min': 0.0,
                'achievement_max': 1.0, 'allocation': 0.4,
            })],
        })
        # August: proration divides by the actual 31 calendar days.
        cls.period = cls.env['incentive.period'].create({
            'name': 'Test Aug 2025',
            'date_start': fields.Date.to_date('2025-08-01'),
            'date_end': fields.Date.to_date('2025-08-31'),
            'rule_id': rule.id,
            'company_id': cls.company.id,
        })
        cls.period.action_open()
        cls.env['incentive.branch.target'].create({
            'period_id': cls.period.id, 'branch_id': cls.branch.id,
            'business_type': 'b2b', 'amount': 4_500_000.0,
        })
        cls.env['incentive.target.cascade'].create({
            'period_id': cls.period.id,
            'branch_ids': [(6, 0, cls.branch.ids)],
            'business_type': 'b2b',
        }).action_apply()

    def _target(self, employee, target_type='incentive'):
        return self.env['incentive.target'].search([
            ('period_id', '=', self.period.id),
            ('employee_id', '=', employee.id),
            ('target_type', '=', target_type),
        ], limit=1)

    def test_leaver_keeps_a_prorated_target(self):
        """21/31 of 1.0M, and the row EXISTS -- August's sales need it."""
        target = self._target(self.leaver)
        self.assertTrue(target, "the leaver must still get a target row")
        self.assertAlmostEqual(target.amount, 1_000_000.0 * 21 / 31, 2)
        self.assertAlmostEqual(target.proration_ratio, 21 / 31, 4)

    def test_full_month_staff_are_untouched(self):
        """Nobody else's own commitment moves because a colleague left."""
        self.assertAlmostEqual(self._target(self.lead).amount, 1_500_000.0, 2)
        self.assertAlmostEqual(self._target(self.m1).amount, 1_000_000.0, 2)
        self.assertAlmostEqual(self._target(self.m2).amount, 1_000_000.0, 2)

    def test_dropped_slice_becomes_bonus_split_by_fte(self):
        """10/31 of 1.0M over Lead 1.5 + 2 x 1.0 = 3.5 FTE."""
        dropped = 1_000_000.0 * 10 / 31
        self.assertAlmostEqual(
            self._target(self.lead, 'bonus').amount, dropped * 1.5 / 3.5, 2)
        self.assertAlmostEqual(
            self._target(self.m1, 'bonus').amount, dropped / 3.5, 2)
        self.assertAlmostEqual(
            self._target(self.m2, 'bonus').amount, dropped / 3.5, 2)
        self.assertFalse(
            self._target(self.leaver, 'bonus'),
            "the leaver must not receive a share of the slice they dropped")

    def test_branch_figure_still_adds_up(self):
        """Proration moves money between buckets; it never destroys any.

        delta, not places: summing seven stored Monetary values leaves a
        sub-cent float residue. A real leak here is the 300k slice, so a
        one-rupiah tolerance still catches everything worth catching.
        """
        total = sum(self.env['incentive.target'].search(
            [('period_id', '=', self.period.id)]).mapped('amount'))
        self.assertAlmostEqual(total, 4_500_000.0, delta=1.0)

    def test_proration_uses_actual_days_in_the_period(self):
        """August uses 31 days, February uses 28 -- no fixed 30-day shortcut."""
        feb = self.env['incentive.period'].create({
            'name': 'Test Feb 2025',
            'date_start': fields.Date.to_date('2025-02-01'),
            'date_end': fields.Date.to_date('2025-02-28'),
            'rule_id': self.period.rule_id.id,
            'company_id': self.company.id,
        })
        self.m1.incentive_date_end = fields.Date.to_date('2025-02-14')
        self.assertAlmostEqual(self.m1._incentive_proration(feb), 14 / 28, 4)