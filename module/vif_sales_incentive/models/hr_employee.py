# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    incentive_branch_id = fields.Many2one('incentive.branch', string='Sales Branch')
    incentive_business_type = fields.Selection([
        ('b2b', 'B2B'),
        ('b2c', 'B2C'),
    ], string='Business Type')
    incentive_designation_id = fields.Many2one(
        'incentive.designation', string='FTE Designation')

    incentive_date_start = fields.Date(
        string='Effective Target Start',
        help="S14: for a mid-month new hire this is the date the target starts "
             "counting. Used to prorate the first month.")
    incentive_date_end = fields.Date(
        string='Resignation Date',
        help="S13: after this date the target is redistributed by FTE to the "
             "remaining active salespeople.")

    is_vacant_slot = fields.Boolean(
        string='Vacant Position',
        help="Placeholder record for a headcount slot that is not filled. "
             "Its target is redistributed until a replacement joins.")

    branch_incentive_eligible = fields.Boolean(
        compute='_compute_incentive_eligibility', store=True, readonly=False)
    individual_incentive_eligible = fields.Boolean(
        compute='_compute_incentive_eligibility', store=True, readonly=False)

    incentive_payout_ids = fields.One2many(
        'incentive.payout', 'employee_id', string='Incentive Payouts')

    @api.depends('incentive_designation_id')
    def _compute_incentive_eligibility(self):
        for emp in self:
            desig = emp.incentive_designation_id
            emp.branch_incentive_eligible = desig.branch_incentive_eligible if desig else False
            emp.individual_incentive_eligible = (
                desig.individual_incentive_eligible if desig else False)

    @api.constrains('incentive_branch_id', 'incentive_business_type',
                    'incentive_date_start', 'incentive_date_end')
    def _check_no_same_day_handover(self):
        """Nobody may join a team on the day a colleague leaves it.

        The scenario: someone resigns on 21 Aug and their replacement is
        entered as joining on 21 Aug. Both count as active that day, so the
        team carries one FTE too many and the two proration ratios add up to
        more than a full month -- 21/31 + 11/31. The replacement starts on
        the 22nd.

        Checked in both directions, because either date can be the one being
        edited: this record joining onto somebody's last day, or this record
        resigning onto somebody's first.
        """
        for emp in self:
            branch = emp.incentive_branch_id
            if not (branch and emp.incentive_business_type):
                continue
            others = branch._team_employees(emp.incentive_business_type) - emp
            # ponytail: dates only, no time of day -- a same-day handover is
            # precisely what is being rejected.
            if emp.incentive_date_start:
                clash = others.filtered(
                    lambda e: e.incentive_date_end == emp.incentive_date_start)
                if clash:
                    raise ValidationError(emp._same_day_handover_message(
                        clash, emp, emp.incentive_date_start))
            if emp.incentive_date_end:
                clash = others.filtered(
                    lambda e: e.incentive_date_start == emp.incentive_date_end)
                if clash:
                    raise ValidationError(emp._same_day_handover_message(
                        emp, clash, emp.incentive_date_end))

    def _same_day_handover_message(self, leaving, joining, date_clash):
        self.ensure_one()
        return _(
            '%(leaver)s resigns from %(branch)s / %(btype)s on %(date)s and '
            '%(joiner)s joins the same team on the same date.\n\n'
            'One seat cannot be held by two people on the same day -- the '
            'joining date must be at least the day AFTER the resignation.',
            leaver=', '.join(leaving.mapped('name')),
            joiner=', '.join(joining.mapped('name')),
            branch=self.incentive_branch_id.name,
            btype=(self.incentive_business_type or '').upper(),
            date=fields.Date.to_string(date_clash),
        )

    def _is_incentive_active_on(self, date_ref):
        """Active for incentive purposes on ``date_ref``."""
        self.ensure_one()
        if self.is_vacant_slot:
            return False
        if self.incentive_date_start and date_ref < self.incentive_date_start:
            return False
        if self.incentive_date_end and date_ref > self.incentive_date_end:
            return False
        return True

    def _incentive_proration(self, period):
        """active_days / days_in_period for the first or last month.

        Joining and resignation days both count: a resignation on 21 Aug ->
        21/31; the same resignation day in a 30-day month -> 21/30.
        """
        self.ensure_one()
        start = max(self.incentive_date_start or period.date_start, period.date_start)
        end = min(self.incentive_date_end or period.date_end, period.date_end)
        if end < start:
            return 0.0
        total_days = (period.date_end - period.date_start).days + 1
        active_days = (end - start).days + 1
        return (active_days / total_days) if total_days else 0.0
