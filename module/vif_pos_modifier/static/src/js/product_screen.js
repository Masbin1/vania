/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(ProductScreen.prototype, {
    getNumpadButtons() {
        const buttons = super.getNumpadButtons();
        if (this.pos.cashier._role !== "manager") {
            return buttons.map((button) => {
                if (button.value === "discount") {
                    return { ...button, disabled: true };
                }
                return button;
            });
        }
        return buttons;
    },
});
