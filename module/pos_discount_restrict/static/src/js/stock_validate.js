/** @odoo-module */
/**
 * POS Stock & Lot/Serial Validation — Odoo 19 Enterprise
 *
 * Two checks before order validation:
 *   1. Stock check: block if storable product qty_available < ordered qty
 *   2. Lot/Serial check: block if product requires lot/serial tracking
 *      but no lot/serial is assigned (overrides Odoo's default behavior
 *      which allows bypassing with "Ok")
 *
 * Odoo 19 POS API:
 *   - order.lines, line.product_id, line.qty
 *   - product.tracking: "none" | "lot" | "serial"
 *   - line.lot_name / line.lot_id: the assigned lot/serial
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// ── Helper: show blocking error popup ────────────────────────────
function showBlockingError(self, title, message) {
    console.warn(`[pos_restrict] BLOCKED: ${title}`, message);

    if (self.env?.services?.dialog) {
        self.env.services.dialog.add(AlertDialog, {
            title: _t(title),
            body: message,
        });
        return;
    }

    // Fallback
    alert(`${title}\n\n${message}`);
}

// ── Helper: get orderlines safely ────────────────────────────────
function getOrderlines(order) {
    if (Array.isArray(order.lines)) return order.lines;
    if (order.lines && typeof order.lines[Symbol.iterator] === "function") {
        return [...order.lines];
    }
    if (Array.isArray(order.orderlines)) return order.orderlines;
    if (order.orderlines && typeof order.orderlines[Symbol.iterator] === "function") {
        return [...order.orderlines];
    }
    if (typeof order.get_orderlines === "function") {
        return order.get_orderlines();
    }
    return [];
}

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder || this.pos?.get_order?.();

        if (!order) {
            return super.validateOrder(isForceValidate);
        }

        const orderlines = getOrderlines(order);
        console.log("[pos_restrict] orderlines count:", orderlines.length);

        if (!orderlines || orderlines.length === 0) {
            console.warn("[pos_restrict] No orderlines found, skipping checks");
            return super.validateOrder(isForceValidate);
        }

        const outOfStock = [];
        const missingLots = [];

        for (const line of orderlines) {
            const product = line.product_id || line.product;
            if (!product) continue;

            const name = product.display_name || product.name || "Unknown";
            const qtyOrdered = line.qty ?? line.quantity ?? 0;

            // ── CHECK 1: Lot/Serial required but missing ─────────
            // product.tracking: "lot", "serial", or "none"
            const tracking = product.tracking || "none";

            if (tracking !== "none") {
                // Check if lot/serial is assigned
                const hasLot = line.lot_name
                    || line.lot_id
                    || line.pack_lot_lines?.length > 0
                    || line.pack_lot_ids?.length > 0;

                if (!hasLot) {
                    const trackLabel = tracking === "serial"
                        ? "Serial Number"
                        : "Lot Number";
                    missingLots.push(`• ${name}: ${trackLabel} belum diisi`);
                }
            }

            // ── CHECK 2: Stock insufficient (storable only) ──────
            if (product.type === "product") {
                const qtyAvailable = product.qty_available ?? 0;

                console.log(
                    `[pos_restrict] ${name}: ` +
                    `ordered=${qtyOrdered}, available=${qtyAvailable}, ` +
                    `tracking=${tracking}, type=${product.type}`
                );

                if (qtyAvailable < qtyOrdered) {
                    outOfStock.push(
                        `• ${name}: tersedia ${qtyAvailable}, dipesan ${qtyOrdered}`
                    );
                }
            }
        }

        // ── BLOCK 1: Missing Lot/Serial ──────────────────────────
        if (missingLots.length > 0) {
            showBlockingError(
                this,
                "Lot/Serial Number Wajib Diisi",
                "Produk berikut memerlukan Lot/Serial Number:\n\n" +
                missingLots.join("\n") +
                "\n\nIsi Lot/Serial terlebih dahulu sebelum validasi."
            );
            return; // Hard block — no bypass
        }

        // ── BLOCK 2: Out of stock ────────────────────────────────
        if (outOfStock.length > 0) {
            showBlockingError(
                this,
                "Stok Tidak Cukup",
                "Produk berikut stoknya tidak cukup di warehouse:\n\n" +
                outOfStock.join("\n") +
                "\n\nPesanan tidak dapat divalidasi."
            );
            return; // Hard block
        }

        // ── All checks passed → proceed ──────────────────────────
        return super.validateOrder(isForceValidate);
    },
});
