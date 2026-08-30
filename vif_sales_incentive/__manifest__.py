# -*- coding: utf-8 -*-
{
    'name': 'VIF Sales Incentive',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Tier-based sales incentive engine with FTE target cascade, '
               'payment-based payout and multi-period iteration',
    'description': """
VIF Sales Incentive
===================

Implements the incentive scheme defined in the client's Scenario Matrix:

* Incentive Period master with state machine and hard lock (S21, S22)
* Tier / rule versioning -- base rate x allocation (S04, S05)
* Dual target bucket: Incentive-Based and Bonus-Based (S03, S16-S18)
* FTE-driven target cascade from branch rolling forecast to individual (S02)
* Target movement log for resignation, vacancy and new-hire proration
  (S13, S14, S15)
* Invoice-LINE level incentive transactions with 35% discount eligibility
  gate (S07)
* Payment-based payout: prior-period invoices paid in the current period keep
  the tier of their ORIGINAL source period (S08, S09)
* Refund / credit note handling through linked reversal transactions,
  never by editing history (S10, S11, S12)
* Record-rule based visibility: salesperson sees own data, manager sees
  subordinates, C-level sees all (S19, S20)
""",
    'author': 'Linked ERP',
    'website': 'https://www.linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'sale_management',
        'account',
    ],
    'data': [
        'security/incentive_groups.xml',
        'security/ir.model.access.csv',
        'security/incentive_security.xml',

        'data/incentive_sequence.xml',
        'data/incentive_designation_data.xml',
        'data/incentive_rule_data.xml',
        'data/incentive_period_data.xml',
        'data/incentive_refund_policy_data.xml',

        'views/incentive_branch_views.xml',
        'views/incentive_branch_target_views.xml',
        'views/incentive_designation_views.xml',
        'views/incentive_period_views.xml',
        'views/incentive_rule_views.xml',
        'views/incentive_target_views.xml',
        'views/incentive_target_movement_views.xml',
        'views/incentive_transaction_views.xml',
        'views/incentive_payout_views.xml',
        'views/incentive_refund_policy_views.xml',
        'views/hr_employee_views.xml',
        'views/account_move_views.xml',
        'wizards/incentive_target_cascade_views.xml',
        'wizards/incentive_transaction_refund_views.xml',
        'views/incentive_menus.xml',
    ],
    'demo': [
        'data/incentive_demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
