{
    "name": "POS Discount & Stock Restriction",
    "version": "19.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Restrict POS discount to group_pos_manager, block validation when out of stock, print A4 receipt",
    "depends": ["point_of_sale"],
    "data": [
        "views/report_pos_order.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_discount_restrict/static/src/js/discount_restrict.js",
            "pos_discount_restrict/static/src/js/stock_validate.js",
            "pos_discount_restrict/static/src/js/print_a4.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
