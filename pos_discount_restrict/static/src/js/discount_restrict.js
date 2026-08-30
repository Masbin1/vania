/** @odoo-module */
/**
 * POS Discount Restriction — Odoo 19
 *
 * Disables the "%" (discount) numpad button unless the active cashier
 * belongs to point_of_sale.group_pos_manager.
 *
 * The numpad buttons are supplied by ProductScreen.getNumpadButtons()
 * (a method, called directly from product_screen.xml as
 * buttons="getNumpadButtons()") — there is no "numpadButtons" getter to
 * patch. The active cashier's role is exposed as pos.cashier._role
 * ("manager" | "cashier"), computed server-side in
 * point_of_sale/models/res_users.py.
 */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

function isPosManager(pos) {
    return pos.cashier?._role === "manager";
}

// When the cashier changes, drop any inherited numpad mode (e.g. a manager
// who left the numpad in "discount" mode). Otherwise the next cashier could
// keep entering discounts by just pressing numbers — the disabled button
// alone does not protect against that.
patch(PosStore.prototype, {
    setCashier(user) {
        super.setCashier(user);
        this.numpadMode = "quantity";
    },
});

// ── Orderlines helper ────────────────────────────────────────────
function getOrderlines(order) {
    if (!order) return [];
    if (Array.isArray(order.lines)) return order.lines;
    if (order.lines?.[Symbol.iterator]) return [...order.lines];
    if (Array.isArray(order.orderlines)) return order.orderlines;
    if (typeof order.get_orderlines === "function") return order.get_orderlines();
    return [];
}

patch(ProductScreen.prototype, {
    getNumpadButtons() {
        const buttons = super.getNumpadButtons();
        if (isPosManager(this.pos)) {
            return buttons;
        }
        return buttons.map((btn) =>
            btn.value === "discount" ? { ...btn, disabled: true } : btn
        );
    },

    async pay() {
        const pos = this.env?.services?.pos || this.pos;
        const order = pos?.get_order?.() || this.currentOrder;

        if (order) {
            const orderlines = getOrderlines(order);
            const missingLots = [];

            for (const line of orderlines) {
                const product = line.product_id || line.product;
                if (!product) continue;
                if ((product.tracking || "none") === "none") continue;

                const hasLot = line.lot_name || line.lot_id
                    || (line.pack_lot_lines?.length > 0)
                    || (line.pack_lot_ids?.length > 0);

                if (!hasLot) {
                    missingLots.push(product.display_name || product.name);
                }
            }

            if (missingLots.length > 0) {
                const msg = "Lot/Serial Number belum diisi untuk:\n" +
                    missingLots.map(n => "• " + n).join("\n") +
                    "\n\nIsi terlebih dahulu.";
                try {
                    const mod = await import("@web/core/confirmation_dialog/confirmation_dialog");
                    this.env.services.dialog.add(mod.AlertDialog || mod.default, {
                        title: "Lot/Serial Number Wajib Diisi", body: msg,
                    });
                } catch { alert(msg); }
                return;
            }
        }
        return super.pay(...arguments);
    },
});
