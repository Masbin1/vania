{
    'name': 'VIF POS Modifier',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'FEFO lot warning and discount restriction in POS',
    'description': """
VIF POS Modifier
================

Two modifications to the Point of Sale:

1. **FEFO Lot Warning**: When a user selects a lot whose expiration date
   is later than another available lot, a warning popup is shown reminding
   the cashier to pick the lot that expires soonest (First Expired, First Out).

2. **Discount Restriction**: Only users with the POS Manager role can apply
   manual discounts. Non-manager cashiers see the discount button disabled.
""",
    'author': 'Linked ERP',
    'website': 'https://www.linkederp.com',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'product_expiry',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'vif_pos_modifier/static/src/js/pos_store.js',
            'vif_pos_modifier/static/src/js/product_screen.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
