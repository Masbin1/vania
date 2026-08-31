# -*- coding: utf-8 -*-
from odoo import fields, models


class IncentiveRefundPolicy(models.Model):
    """S10 / S11 / S12 -- refund matrix from the 'Kebijakan Refund' block."""
    _name = 'incentive.refund.policy'
    _description = 'Incentive Refund Policy'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)

    stock_type = fields.Selection([
        ('available', 'Available Stock'),
        ('indent', 'Indent'),
        ('service', 'Jasa / Service'),
        ('any', 'All Types'),
    ], required=True, default='any')

    is_wip = fields.Boolean(
        string='Work In Progress',
        help="Production already started.")

    payment_status = fields.Selection([
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
        ('any', 'Partial or Fully Paid'),
    ], required=True, default='any')

    initiator = fields.Selection([
        ('customer', 'Customer'),
        ('company', 'Company (VIF)'),
    ], required=True, default='customer')

    refund_pct = fields.Float(
        string='Refund %', digits=(16, 2), default=0.0,
        help="99.0 means 99% refunded to the customer. 0 = no refund.")
    by_agreement = fields.Boolean(
        string='By Agreement',
        help="Company-initiated refunds follow the negotiated exception; the "
             "percentage is entered manually on the credit note.")
    note = fields.Char()
    active = fields.Boolean(default=True)

    def _match(self, stock_type, is_wip, payment_status, initiator):
        """Return the first policy matching the situation."""
        domain = [
            ('stock_type', 'in', [stock_type, 'any']),
            ('is_wip', '=', is_wip),
            ('payment_status', 'in', [payment_status, 'any']),
            ('initiator', '=', initiator),
        ]
        return self.search(domain, order='sequence, id', limit=1)
