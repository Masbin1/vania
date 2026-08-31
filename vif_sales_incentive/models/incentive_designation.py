# -*- coding: utf-8 -*-
from odoo import api, fields, models


class IncentiveDesignation(models.Model):
    """Effective FTE master (Lead / Team / Support).

    Two FTE columns because the client's workbook uses different weights for
    branch-level and individual-level allocation:

        Role      Branch FTE   Individual FTE
        Lead        1.50           1.50
        Team        1.00           1.00
        Support     0.25           0.00      <- support has no individual target
    """
    _name = 'incentive.designation'
    _description = 'Incentive FTE Designation'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)

    fte_branch = fields.Float(
        string='Branch FTE', digits=(16, 2), default=1.0,
        help="Weight used when cascading the BRANCH incentive pool.")
    fte_individual = fields.Float(
        string='Individual FTE', digits=(16, 2), default=1.0,
        help="Weight used when cascading the INDIVIDUAL target. "
             "Support roles are 0.00 -- they carry no individual target.")

    branch_incentive_eligible = fields.Boolean(default=True)
    individual_incentive_eligible = fields.Boolean(default=True)

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Designation code must be unique.'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s (%s)' % (rec.name, rec.code) if rec.code else rec.name
