# -*- coding: utf-8 -*-
"""The refund wizard is a regular model now (Odoo Studio cannot touch a
TransientModel), so its record survives the dialog and the button can be
pressed a second time. Once means once: the second press must refuse instead
of posting a second credit note for the same money.
"""
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRefundOnce(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Refund Sales',
            'incentive_business_type': 'b2b',
            'incentive_designation_id': cls.env.ref(
                'vif_sales_incentive.designation_team').id,
        })
        cls.employee.user_id = cls.env.user
        cls.period = cls.env['incentive.period'].create({
            'name': 'Refund Jun 2025',
            'date_start': fields.Date.to_date('2025-06-01'),
            'date_end': fields.Date.to_date('2025-06-30'),
            'company_id': cls.company.id,
        })
        product = cls.env['product.product'].create(
            {'name': 'Refund Widget', 'type': 'consu', 'list_price': 1000.0})
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.env['res.partner'].create(
                {'name': 'Refund Customer'}).id,
            'invoice_date': fields.Date.to_date('2025-06-10'),
            'invoice_user_id': cls.env.user.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'quantity': 10,
                'price_unit': 1000.0,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        cls.invoice.action_post()
        line = cls.invoice.invoice_line_ids[0]
        cls.tx = cls.env['incentive.transaction'].create({
            'move_line_id': line.id,
            'move_id': cls.invoice.id,
            'employee_id': cls.employee.id,
            'company_id': cls.company.id,
            'source_period_id': cls.period.id,
            'transaction_type': 'invoice',
            'base_amount': line.price_subtotal,
            'state': 'confirmed',
        })

    def _wizard(self, amount):
        return self.env['incentive.transaction.refund'].create({
            'transaction_id': self.tx.id,
            'refund_amount': amount,
        })

    def test_second_press_is_refused(self):
        wizard = self._wizard(2000.0)
        wizard.action_refund()
        self.assertTrue(wizard.refund_move_id, 'credit note not stamped')
        before = wizard.refund_move_id
        with self.assertRaises(ValidationError):
            wizard.action_refund()
        self.assertEqual(
            wizard.refund_move_id, before,
            'a second press must not replace the credit note')
        self.assertEqual(
            self.env['account.move'].search_count([
                ('move_type', '=', 'out_refund'),
                ('reversed_entry_id', '=', self.invoice.id),
            ]), 1, 'a second credit note was posted')

    def test_full_refund_still_closes_the_transaction(self):
        self._wizard(self.tx._refundable_amount()).action_refund()
        self.assertEqual(self.tx.state, 'reversed')
