/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable";

patch(PosStore.prototype, {
    // ── Feature 1: FEFO lot warning ──────────────────────────────────
    async editLots(product, packLotLinesToEdit) {
        const result = await super.editLots(product, packLotLinesToEdit);
        if (!result) {
            return result;
        }

        const selectedLotNames = [
            ...Object.values(result.modifiedPackLotLines || {}),
            ...(result.newPackLotLines || []).map((l) => l.lot_name),
        ];

        if (!selectedLotNames.length) {
            return result;
        }

        // Fetch all lots with expiration_date for this product via ORM
        let lots = [];
        try {
            lots = await this.data.call(
                "stock.lot",
                "search_read",
                [[
                    ["product_id", "=", product.id],
                    ["expiration_date", "!=", false],
                ]],
                { fields: ["name", "expiration_date"], limit: 0 }
            );
        } catch {
            return result;
        }

        if (!lots.length) {
            return result;
        }

        const earliestLot = lots.reduce((earliest, lot) =>
            lot.expiration_date < earliest.expiration_date ? lot : earliest
        );

        const selectedWithLaterExpiry = selectedLotNames.filter((name) => {
            const selected = lots.find((l) => l.name === name);
            return selected && selected.expiration_date > earliestLot.expiration_date;
        });

        if (selectedWithLaterExpiry.length) {
            const earlyDate = new Date(earliestLot.expiration_date).toLocaleDateString();
            const confirmed = await makeAwaitable(this.dialog, ConfirmationDialog, {
                title: _t("FEFO Warning"),
                body: _t(
                    'You selected lot "%(selected)s" which expires later than lot "%(earliest_lot)s" (expires %(earliest_date)s). ' +
                        "According to FEFO (First Expired, First Out), you should pick the lot that expires soonest. " +
                        "Do you want to continue anyway?",
                    {
                        selected: selectedWithLaterExpiry.join(", "),
                        earliest_lot: earliestLot.name,
                        earliest_date: earlyDate,
                    }
                ),
                confirmLabel: _t("Continue Anyway"),
                cancelLabel: _t("Cancel"),
            });

            if (!confirmed) {
                return null;
            }
        }

        return result;
    },

    // ── Feature 2: Block discount for non-manager ────────────────────
    async setDiscountFromUI(line, val) {
        if (this.cashier._role !== "manager") {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Discount Restricted"),
                body: _t(
                    "Only POS Managers are allowed to apply discounts. " +
                        "Please ask your manager for assistance."
                ),
            });
            return;
        }
        return super.setDiscountFromUI(line, val);
    },
});
