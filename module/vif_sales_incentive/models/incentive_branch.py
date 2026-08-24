# -*- coding: utf-8 -*-
from odoo import api, fields, models


class IncentiveBranch(models.Model):
    """Sales branch (JKT / BDG / SBY / BLI / MDN).

    Kept as a dedicated master instead of reusing crm.team because one branch
    carries BOTH a B2B and a B2C population, while crm.team is a flat list.
    Effective FTE is computed per branch x business type.
    """
    _name = 'incentive.branch'
    _description = 'Incentive Sales Branch'
    _order = 'sequence, code'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Short code, e.g. JKT, BDG, SBY, BLI, MDN.")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    manager_id = fields.Many2one('hr.employee', string='Branch Manager')
    active = fields.Boolean(default=True)

    employee_ids = fields.One2many('hr.employee', 'incentive_branch_id', string='Sales Team')
    employee_count = fields.Integer(compute='_compute_employee_count')

    ideal_team_size = fields.Integer(
        string='Ideal Team Size',
        help="Headcount one team of this branch is meant to have, lead "
             "included. Applied to the B2B and the B2C team separately -- each "
             "population is still counted on its own.\n"
             "A seat short of this number keeps weighing on the cascade "
             "denominator, so its slice goes to the bonus pool instead of "
             "inflating the target of everyone who stayed. 0 disables that.")

    effective_fte = fields.Float(
        string='Effective FTE', digits=(16, 2),
        compute='_compute_effective_fte_display',
        help="Today's actual weighted headcount of the whole branch, B2B and "
             "B2C together. Read against Ideal Team Size, which is per team.")

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)',
         'Branch code must be unique per company.'),
        ('ideal_team_size_positive', 'CHECK(ideal_team_size >= 0)',
         'Ideal team size cannot be negative.'),
    ]

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for branch in self:
            branch.employee_count = len(branch.employee_ids)

    @api.depends('employee_ids.incentive_business_type',
                 'employee_ids.incentive_designation_id',
                 'employee_ids.incentive_date_start',
                 'employee_ids.incentive_date_end',
                 'employee_ids.is_vacant_slot')
    def _compute_effective_fte_display(self):
        """Today's actual FTE, for the form only -- nothing computes off it.

        The cascade never reads this: it builds its own population per branch x
        business type (``_collect_population``) for the period being cascaded,
        not for today.
        """
        for branch in self:
            branch.effective_fte = sum(
                branch._compute_effective_fte(bt) for bt in ('b2b', 'b2c'))

    # ------------------------------------------------------------------
    # Team population -- one definition, used by the cascade and by the
    # headcount constraint on hr.employee.
    # ------------------------------------------------------------------
    def _team_employees(self, business_type):
        """Every record filling a seat of this branch x business type.

        Vacant slots count: they are seats that were explicitly created, so
        counting them again as a gap would charge the same empty chair twice.
        """
        self.ensure_one()
        return self.employee_ids.filtered(
            lambda e: e.incentive_business_type == business_type)

    def _headcount_gap(self, business_type):
        """Seats the ideal calls for that no record fills at all."""
        self.ensure_one()
        if not self.ideal_team_size:
            return 0
        return max(0, self.ideal_team_size - len(self._team_employees(business_type)))

    def _compute_effective_fte(self, business_type, scope='branch', date_ref=None):
        """Sum of effective FTE for the active population of this branch.

        :param business_type: 'b2b' or 'b2c'
        :param scope: 'branch' -> support counts 0.25
                      'individual' -> support counts 0.00
        :return: float
        """
        self.ensure_one()
        date_ref = date_ref or fields.Date.context_today(self)
        total = 0.0
        for emp in self.employee_ids:
            if emp.incentive_business_type != business_type:
                continue
            if not emp._is_incentive_active_on(date_ref):
                continue
            desig = emp.incentive_designation_id
            if not desig:
                continue
            total += desig.fte_branch if scope == 'branch' else desig.fte_individual
        return total
