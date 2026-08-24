# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IncentiveTargetMovement(models.Model):
    """S13 / S14 / S15 -- audit trail for every target transfer.

    Never edit a historical target silently. Each redistribution, proration or
    rolling-forecast revision creates a movement row so Finance can explain the
    delta between the original cascade and the paid figure.
    """
    _name = 'incentive.target.movement'
    _description = 'Incentive Target Movement'
    _order = 'date_effective desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, default=lambda s: _('New'), copy=False)
    period_id = fields.Many2one('incentive.period', required=True, ondelete='restrict')
    target_id = fields.Many2one('incentive.target', ondelete='set null',
                                string='Resulting Target')

    reason = fields.Selection([
        ('resignation', 'Resignation / Vacant'),
        ('new_hire', 'New Hire Proration'),
        ('rf_revision', 'Rolling Forecast Revision'),
        ('replacement', 'Replacement Joined'),
        ('manual', 'Manual Adjustment'),
    ], required=True, default='manual', tracking=True)

    from_employee_id = fields.Many2one(
        'hr.employee', string='From', tracking=True,
        help="Leave empty for a pure rolling-forecast revision.")
    to_employee_id = fields.Many2one('hr.employee', string='To', tracking=True)

    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(related='period_id.company_id.currency_id', readonly=True)

    target_type = fields.Selection([
        ('incentive', 'Incentive-Based'),
        ('bonus', 'Bonus-Based'),
    ], required=True, default='bonus',
        help="Redistributed target lands in the BONUS bucket of the receiving "
             "salesperson -- it is not part of their original commitment.")

    fte_share = fields.Float(string='FTE Share', digits=(16, 4))
    date_effective = fields.Date(required=True, default=fields.Date.context_today)
    note = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'incentive.target.movement') or _('New')
        return super().create(vals_list)

    def action_apply(self):
        """Materialise the movement into an incentive.target row."""
        Target = self.env['incentive.target']
        for mv in self:
            if mv.period_id.state in ('approved', 'locked'):
                raise UserError(_('Period %s is closed.') % mv.period_id.name)
            if not mv.to_employee_id:
                raise UserError(_('Set the receiving salesperson first.'))
            target = Target.search([
                ('period_id', '=', mv.period_id.id),
                ('employee_id', '=', mv.to_employee_id.id),
                ('target_type', '=', mv.target_type),
            ], limit=1)
            if target:
                target.amount += mv.amount
            else:
                target = Target.create({
                    'period_id': mv.period_id.id,
                    'employee_id': mv.to_employee_id.id,
                    'target_type': mv.target_type,
                    'amount': mv.amount,
                    'source': 'redistribution' if mv.reason == 'resignation' else 'manual',
                    'fte_used': mv.fte_share,
                })
            mv.target_id = target.id
        return True
