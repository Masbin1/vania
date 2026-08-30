# -*- coding: utf-8 -*-
"""Multi-branch cascade + per-branch sign-off.

Two things must hold once targets are branch-scoped:
  1. one cascade run over N branches gives each branch its OWN figure, split by
     that branch's own FTE population -- no cross-branch bleed;
  2. locking one branch does not block its neighbours.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBranchCascade(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.lead = cls.env.ref('vif_sales_incentive.designation_lead')
        cls.team = cls.env.ref('vif_sales_incentive.designation_team')

        cls.branch_a, cls.branch_b = cls.env['incentive.branch'].create([
            {'name': 'Test Alpha', 'code': 'TSTA', 'company_id': cls.company.id},
            {'name': 'Test Beta', 'code': 'TSTB', 'company_id': cls.company.id},
        ])

        # Alpha: Lead(1.5) + Team(1.0) = 2.5 FTE.  Beta: Team(1.0) = 1.0 FTE.
        cls.emp_a1, cls.emp_a2, cls.emp_b1 = cls.env['hr.employee'].create([
            {'name': 'Alpha Lead', 'incentive_branch_id': cls.branch_a.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.lead.id},
            {'name': 'Alpha Team', 'incentive_branch_id': cls.branch_a.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.team.id},
            {'name': 'Beta Team', 'incentive_branch_id': cls.branch_b.id,
             'incentive_business_type': 'b2b',
             'incentive_designation_id': cls.team.id},
        ])

        cls.rule = cls.env['incentive.rule'].create({
            'name': 'Test Rule',
            'date_from': fields.Date.to_date('2025-01-01'),
            'date_to': fields.Date.to_date('2025-12-31'),
            'company_id': cls.company.id,
            'tier_ids': [(0, 0, {
                'name': 'Tier 1', 'level': 1, 'achievement_min': 0.0,
                'achievement_max': 1.0, 'allocation': 0.4,
            }), (0, 0, {
                'name': 'Tier 2', 'level': 2, 'achievement_min': 1.0,
                'allocation': 1.0, 'is_top_tier': True,
            })],
        })
        cls.period = cls.env['incentive.period'].create({
            'name': 'Test Mar 2025',
            'date_start': fields.Date.to_date('2025-03-01'),
            'date_end': fields.Date.to_date('2025-03-31'),
            'rule_id': cls.rule.id,
            'company_id': cls.company.id,
        })
        cls.period.action_open()

        # Different figures per branch -- the whole point of the change.
        cls.bt_a, cls.bt_b = cls.env['incentive.branch.target'].create([
            {'period_id': cls.period.id, 'branch_id': cls.branch_a.id,
             'business_type': 'b2b', 'amount': 250_000_000.0},
            {'period_id': cls.period.id, 'branch_id': cls.branch_b.id,
             'business_type': 'b2b', 'amount': 100_000_000.0},
        ])

    def _cascade(self, branches):
        return self.env['incentive.target.cascade'].create({
            'period_id': self.period.id,
            'branch_ids': [(6, 0, branches.ids)],
            'business_type': 'b2b',
        })

    def _target(self, employee):
        return self.env['incentive.target'].search([
            ('period_id', '=', self.period.id),
            ('employee_id', '=', employee.id),
            ('target_type', '=', 'incentive'),
        ], limit=1)

    def test_cascade_splits_each_branch_by_its_own_figure(self):
        """One run, two branches, each split against its own target and FTE."""
        self._cascade(self.branch_a | self.branch_b).action_apply()

        # Alpha: 250M over 2.5 FTE -> Lead 1.5/2.5 = 150M, Team 1.0/2.5 = 100M.
        self.assertAlmostEqual(self._target(self.emp_a1).amount, 150_000_000.0, 2)
        self.assertAlmostEqual(self._target(self.emp_a2).amount, 100_000_000.0, 2)
        # Beta: its own 100M, undiluted by Alpha's larger population.
        self.assertAlmostEqual(self._target(self.emp_b1).amount, 100_000_000.0, 2)

    def test_missing_branch_target_is_an_error(self):
        """A branch with no figure must fail loudly, not cascade a silent zero."""
        branch_c = self.env['incentive.branch'].create({
            'name': 'Test Gamma', 'code': 'TSTC', 'company_id': self.company.id})
        self.env['hr.employee'].create({
            'name': 'Gamma Team', 'incentive_branch_id': branch_c.id,
            'incentive_business_type': 'b2b',
            'incentive_designation_id': self.team.id})
        with self.assertRaises(UserError):
            self._cascade(self.branch_a | branch_c).action_preview()

    def test_lock_is_per_branch(self):
        """Locking Alpha freezes only Alpha; Beta stays workable."""
        self._cascade(self.branch_a | self.branch_b).action_apply()

        self.bt_a.action_calculate()
        self.bt_a.action_approve()
        self.bt_a.action_lock()

        self.assertEqual(self.bt_a.state, 'locked')
        self.assertEqual(self.bt_b.state, 'draft')
        self.assertTrue(self.bt_a._payouts().mapped('is_frozen'))

        # Beta still calculates while Alpha is locked.
        self.bt_b.action_calculate()
        self.assertEqual(self.bt_b.state, 'calculated')

        # Alpha refuses further work; re-cascading it is blocked too.
        with self.assertRaises(UserError):
            self.bt_a.action_calculate()
        with self.assertRaises(UserError):
            self._cascade(self.branch_a).action_apply()

    def test_carry_forward_is_stored_apart_from_the_base(self):
        """Re-running the cascade must not compound the carry into the base."""
        self._cascade(self.branch_a | self.branch_b).action_apply()
        self.assertAlmostEqual(self.bt_a.amount, 250_000_000.0, 2)

        self._cascade(self.branch_a | self.branch_b).action_apply()
        self.assertAlmostEqual(self.bt_a.amount, 250_000_000.0, 2)
        self.assertAlmostEqual(
            self.bt_a.amount_total,
            self.bt_a.amount + self.bt_a.carry_forward_amount, 2)
