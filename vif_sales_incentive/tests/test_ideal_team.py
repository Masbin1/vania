# -*- coding: utf-8 -*-
"""Ideal team size: a short-staffed team keeps a stable denominator, and a
seat cannot be handed over on the same day.

The client's rule, verbatim: a Bandung B2B team is meant to hold 5 people. If
someone resigns and their replacement is entered as starting on the SAME date,
both are active that day -- one seat, two people -- so the save is rejected.
And while the seat sits empty, its slice must go to the bonus pool rather than
inflate the targets of everyone who stayed.
"""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIdealTeamSize(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.lead_desig = cls.env.ref('vif_sales_incentive.designation_lead')
        cls.team_desig = cls.env.ref('vif_sales_incentive.designation_team')

        # Ideal 5, but only 4 records exist: 1 Lead (1.5) + 3 Team (1.0 each).
        cls.branch = cls.env['incentive.branch'].create({
            'name': 'Test Ideal', 'code': 'TSTI',
            'company_id': cls.company.id, 'ideal_team_size': 5,
        })
        cls.lead, cls.m1, cls.m2, cls.m3 = cls.env['hr.employee'].create([
            {'name': 'I Lead', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.lead_desig.id},
            {'name': 'I Member 1', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.team_desig.id},
            {'name': 'I Member 2', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.team_desig.id},
            {'name': 'I Member 3', 'incentive_branch_id': cls.branch.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.team_desig.id},
        ])

        rule = cls.env['incentive.rule'].create({
            'name': 'Ideal Rule',
            'date_from': fields.Date.to_date('2025-01-01'),
            'date_to': fields.Date.to_date('2025-12-31'),
            'company_id': cls.company.id,
            'tier_ids': [(0, 0, {
                'name': 'Tier 1', 'level': 1, 'achievement_min': 0.0,
                'achievement_max': 1.0, 'allocation': 0.4,
            })],
        })
        cls.period = cls.env['incentive.period'].create({
            'name': 'Ideal Aug 2025',
            'date_start': fields.Date.to_date('2025-08-01'),
            'date_end': fields.Date.to_date('2025-08-31'),
            'rule_id': rule.id,
            'company_id': cls.company.id,
        })
        cls.period.action_open()

    def _cascade(self, amount=5_500_000.0):
        self.env['incentive.branch.target'].create({
            'period_id': self.period.id, 'branch_id': self.branch.id,
            'business_type': 'b2b', 'amount': amount,
        })
        self.env['incentive.target.cascade'].create({
            'period_id': self.period.id,
            'branch_ids': [(6, 0, self.branch.ids)],
            'business_type': 'b2b',
        }).action_apply()

    def _target(self, employee, target_type='incentive'):
        return self.env['incentive.target'].search([
            ('period_id', '=', self.period.id),
            ('employee_id', '=', employee.id),
            ('target_type', '=', target_type),
        ], limit=1)

    # ------------------------------------------------------------------
    # Denominator
    # ------------------------------------------------------------------
    def test_empty_seat_holds_its_weight_in_the_denominator(self):
        """4.5 FTE present + 1.0 for the unfilled seat = 5.5, not 4.5.

        5.5M over 5.5 FTE makes a Team member's target exactly 1.0M. Divided
        by 4.5 it would have been 1.22M -- a raise nobody asked for.
        """
        self._cascade()
        self.assertAlmostEqual(self._target(self.m1).amount, 1_000_000.0, 2)
        self.assertAlmostEqual(self._target(self.lead).amount, 1_500_000.0, 2)

    def test_empty_seat_slice_becomes_bonus(self):
        """The missing seat's 1.0M is split by FTE over the four who are here."""
        self._cascade()
        self.assertAlmostEqual(
            self._target(self.lead, 'bonus').amount, 1_000_000.0 * 1.5 / 4.5, 2)
        self.assertAlmostEqual(
            self._target(self.m1, 'bonus').amount, 1_000_000.0 / 4.5, 2)

    def test_branch_figure_still_adds_up(self):
        """The gap moves money between buckets; it never destroys any."""
        self._cascade()
        total = sum(self.env['incentive.target'].search(
            [('period_id', '=', self.period.id)]).mapped('amount'))
        self.assertAlmostEqual(total, 5_500_000.0, delta=1.0)

    def test_zero_ideal_keeps_the_old_denominator(self):
        """An unset ideal must not change a single existing figure."""
        self.branch.ideal_team_size = 0
        self._cascade(4_500_000.0)
        self.assertAlmostEqual(self._target(self.m1).amount, 1_000_000.0, 2)
        self.assertFalse(self._target(self.m1, 'bonus'))

    def test_vacant_slot_record_is_not_double_counted(self):
        """Creating the 5th seat as a vacant record closes the gap.

        Otherwise the same empty chair would be charged twice -- once as the
        record, once as a gap -- and the denominator would read 6.5.
        """
        self.env['hr.employee'].create({
            'name': 'I Vacant', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2b', 'is_vacant_slot': True,
            'incentive_designation_id': self.team_desig.id,
        })
        self.assertEqual(self.branch._headcount_gap('b2b'), 0)
        self._cascade()
        self.assertAlmostEqual(self._target(self.m1).amount, 1_000_000.0, 2)

    def test_effective_fte_reads_the_live_population(self):
        """The form's actual-vs-ideal figure, computed not typed."""
        self.assertAlmostEqual(self.branch.effective_fte, 4.5, 2)
        self.env['hr.employee'].create({
            'name': 'I B2C FTE', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2c',
            'incentive_designation_id': self.team_desig.id,
        })
        self.branch.invalidate_recordset(['effective_fte'])
        self.assertAlmostEqual(self.branch.effective_fte, 5.5, 2)

    # ------------------------------------------------------------------
    # Stale-cascade flag
    # ------------------------------------------------------------------
    def test_a_fresh_cascade_is_not_flagged(self):
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.assertFalse(bt.needs_recascade)

    def test_a_resignation_after_the_cascade_raises_the_flag(self):
        """The whole point: HR types a date, nothing recalculates, and the
        month must not close quietly on the old figures."""
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-20')
        bt.invalidate_recordset(['needs_recascade', 'recascade_reason'])
        self.assertTrue(bt.needs_recascade)
        self.assertIn('I Member 3', bt.recascade_reason)

    def test_re_running_the_cascade_clears_the_flag(self):
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-20')
        self.env['incentive.target.cascade'].create({
            'period_id': self.period.id,
            'branch_ids': [(6, 0, self.branch.ids)],
            'business_type': 'b2b',
        }).action_apply()
        bt.invalidate_recordset(['needs_recascade', 'recascade_reason'])
        self.assertFalse(bt.needs_recascade)
        # And the resignation actually landed: 20/31 of a full-month 1.0M.
        self.assertAlmostEqual(
            self._target(self.m3).amount, 1_000_000.0 * 20 / 31, 2)

    def test_calculate_is_blocked_while_the_flag_is_up(self):
        """The banner warns; this is what actually stops the wrong payout."""
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-20')
        bt.invalidate_recordset(['needs_recascade', 'recascade_reason'])
        with self.assertRaises(UserError):
            bt.action_calculate()
        # The period-wide button must not be a way around it.
        with self.assertRaises(UserError):
            self.period.action_calculate()

    def test_calculate_works_once_the_cascade_is_re_run(self):
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-20')
        self.env['incentive.target.cascade'].create({
            'period_id': self.period.id,
            'branch_ids': [(6, 0, self.branch.ids)],
            'business_type': 'b2b',
        }).action_apply()
        bt.invalidate_recordset(['needs_recascade', 'recascade_reason'])
        bt.action_calculate()
        self.assertEqual(bt.state, 'calculated')

    def test_a_new_hire_without_a_target_raises_the_flag(self):
        self._cascade()
        bt = self.env['incentive.branch.target'].search([
            ('period_id', '=', self.period.id),
            ('branch_id', '=', self.branch.id)], limit=1)
        self.env['hr.employee'].create({
            'name': 'I Late Hire', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2b',
            'incentive_designation_id': self.team_desig.id,
            'incentive_date_start': fields.Date.to_date('2025-08-18'),
        })
        bt.invalidate_recordset(['needs_recascade', 'recascade_reason'])
        self.assertTrue(bt.needs_recascade)
        self.assertIn('I Late Hire', bt.recascade_reason)

    # ------------------------------------------------------------------
    # Same-day handover
    # ------------------------------------------------------------------
    def test_join_on_the_resignation_date_is_rejected(self):
        """21 Aug out, 21 Aug in -- both active on the 21st. One seat, two people."""
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-21')
        with self.assertRaises(ValidationError):
            self.env['hr.employee'].create({
                'name': 'I Replacement', 'incentive_branch_id': self.branch.id,
                'incentive_business_type': 'b2b',
                'incentive_designation_id': self.team_desig.id,
                'incentive_date_start': fields.Date.to_date('2025-08-21'),
            })

    def test_resigning_onto_a_colleagues_start_date_is_rejected(self):
        """The same clash, entered from the other side: the leaver is edited
        after the joiner already exists."""
        joiner = self.env['hr.employee'].create({
            'name': 'I Joiner', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2b',
            'incentive_designation_id': self.team_desig.id,
            'incentive_date_start': fields.Date.to_date('2025-08-21'),
        })
        self.assertTrue(joiner.id)
        with self.assertRaises(ValidationError):
            self.m3.incentive_date_end = fields.Date.to_date('2025-08-21')

    def test_join_the_day_after_is_allowed(self):
        """The fix the error message asks for must actually work."""
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-21')
        replacement = self.env['hr.employee'].create({
            'name': 'I Replacement OK', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2b',
            'incentive_designation_id': self.team_desig.id,
            'incentive_date_start': fields.Date.to_date('2025-08-22'),
        })
        self.assertTrue(replacement.id)

    def test_the_other_business_type_is_a_different_team(self):
        """One branch, two populations: a B2C hire on the day a B2B colleague
        leaves is a different seat, so it stands."""
        self.m3.incentive_date_end = fields.Date.to_date('2025-08-21')
        b2c = self.env['hr.employee'].create({
            'name': 'I B2C', 'incentive_branch_id': self.branch.id,
            'incentive_business_type': 'b2c',
            'incentive_designation_id': self.team_desig.id,
            'incentive_date_start': fields.Date.to_date('2025-08-21'),
        })
        self.assertTrue(b2c.id)
