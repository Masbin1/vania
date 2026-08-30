# -*- coding: utf-8 -*-
"""Seamless handover: a seat that changes hands mid-month is ONE seat.

The client's rule: when a member resigns on 20 Aug and a replacement joins on
21 Aug, the seat never stood empty -- the leaver covered 20/31 and the
replacement covers 11/31. So the seat's full target splits between the two of
them, and NOTHING becomes bonus for the full-month staff.

Before the fix the cascade counted leaver and replacement as two separate
FTE in the denominator (a 4-person team read as 5), and dumped BOTH of their
uncovered slices into the bonus pool -- paying the whole team a raise nobody
agreed to, while the leaver and replacement each got less than their share.

A genuine gap (leaver out 20 Aug, replacement in 25 Aug) is different: the
21st-24th really had nobody, so those days still go to the bonus pool.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSeatHandover(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        lead = cls.env.ref('vif_sales_incentive.designation_lead')
        team = cls.env.ref('vif_sales_incentive.designation_team')

        cls.branch = cls.env['incentive.branch'].create(
            {'name': 'Test Handover', 'code': 'TSHO',
             'company_id': cls.company.id, 'ideal_team_size': 4})

        # Ideal 4: 1 Lead (1.5 FTE) + 3 Team (1.0 each). Member 3 is the seat
        # that changes hands.
        cls.lead, cls.m1, cls.m2, cls.leaver = cls.env['hr.employee'].create([
            {'name': 'H Lead', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': lead.id},
            {'name': 'H Member 1', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': team.id},
            {'name': 'H Member 2', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': team.id},
            {'name': 'H Leaver', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': team.id,
             'incentive_date_end': fields.Date.to_date('2025-08-20')},
        ])
        cls.replacement = cls.env['hr.employee'].create({
            'name': 'H Replacement', 'incentive_branch_id': cls.branch.id,
            'incentive_business_type': 'b2b',
            'incentive_designation_id': team.id,
            'incentive_date_start': fields.Date.to_date('2025-08-21'),
        })

        rule = cls.env['incentive.rule'].create({
            'name': 'Handover Rule',
            'date_from': fields.Date.to_date('2025-01-01'),
            'date_to': fields.Date.to_date('2025-12-31'),
            'company_id': cls.company.id,
            'tier_ids': [(0, 0, {
                'name': 'Tier 1', 'level': 1, 'achievement_min': 0.0,
                'achievement_max': 1.0, 'allocation': 0.4,
            })],
        })
        cls.period = cls.env['incentive.period'].create({
            'name': 'Handover Aug 2025',
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

    # ------------------------------------------------------------------
    # Seamless handover (resign 20 Aug, replacement 21 Aug -- zero gap)
    # ------------------------------------------------------------------
    def test_seat_splits_between_leaver_and_replacement(self):
        """20/31 and 11/31 of the SAME 1.0M seat -- both as their own target."""
        self.assertAlmostEqual(
            self._target(self.leaver).amount, 1_000_000.0 * 20 / 31, 2)
        self.assertAlmostEqual(
            self._target(self.replacement).amount, 1_000_000.0 * 11 / 31, 2)

    def test_full_month_staff_are_untouched(self):
        """The denominator still reads 4.5 FTE, not 5.5 -- nobody's own
        commitment moves because a seat changed hands."""
        self.assertAlmostEqual(self._target(self.lead).amount, 1_500_000.0, 2)
        self.assertAlmostEqual(self._target(self.m1).amount, 1_000_000.0, 2)
        self.assertAlmostEqual(self._target(self.m2).amount, 1_000_000.0, 2)

    def test_seamless_handover_has_no_bonus(self):
        """Nothing is left uncovered, so the bonus pool stays empty -- the
        leaver's remainder went to the replacement, not to the team."""
        for emp in (self.lead, self.m1, self.m2, self.leaver, self.replacement):
            self.assertFalse(
                self._target(emp, 'bonus'),
                "%s must not receive bonus from a covered handover" % emp.name)

    def test_branch_figure_still_adds_up(self):
        total = sum(self.env['incentive.target'].search(
            [('period_id', '=', self.period.id)]).mapped('amount'))
        self.assertAlmostEqual(total, 4_500_000.0, delta=1.0)

    # ------------------------------------------------------------------
    # Gapped handover (resign 20 Aug, replacement 25 Aug -- 21st-24th empty)
    # ------------------------------------------------------------------
    def test_gap_days_still_go_to_the_bonus_pool(self):
        self.replacement.incentive_date_start = fields.Date.to_date('2025-08-25')
        self.env['incentive.target.cascade'].create({
            'period_id': self.period.id,
            'branch_ids': [(6, 0, self.branch.ids)],
            'business_type': 'b2b',
        }).action_apply()

        # Leaver 20/31, replacement covers 25th-31st = 7/31. The 21st-24th
        # (4/31) really had nobody -> bonus pool, split by FTE over 3.5.
        self.assertAlmostEqual(
            self._target(self.replacement).amount, 1_000_000.0 * 7 / 31, 2)
        gap = 1_000_000.0 * 4 / 31
        self.assertAlmostEqual(
            self._target(self.lead, 'bonus').amount, gap * 1.5 / 3.5, 2)
        self.assertAlmostEqual(
            self._target(self.m1, 'bonus').amount, gap / 3.5, 2)
        self.assertAlmostEqual(
            self._target(self.m2, 'bonus').amount, gap / 3.5, 2)
        self.assertFalse(self._target(self.leaver, 'bonus'))
        self.assertFalse(self._target(self.replacement, 'bonus'))

        total = sum(self.env['incentive.target'].search(
            [('period_id', '=', self.period.id)]).mapped('amount'))
        self.assertAlmostEqual(total, 4_500_000.0, delta=1.0)
