/** @odoo-module */
/**
 * Route the built-in "Print Full Receipt" button to the A4 PDF report
 * instead of the thermal receipt renderer.
 *
 * The PDF is generated server-side, so the order must already be synced —
 * an order created while the POS was offline has no server id yet.
 */

import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { patch } from "@web/core/utils/patch";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const REPORT_XML_ID = "pos_discount_restrict.action_report_pos_order_a4";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        this.report = useService("report");
        this.doFullPrint = useTrackedAsync(() => this._printA4(this.currentOrder));
    },

    async _printA4(order) {
        if (!order?.isSynced) {
            this.dialog.add(AlertDialog, {
                title: _t("Order Not Synced"),
                body: _t(
                    "This order has not reached the server yet, so the A4 PDF cannot be " +
                        "generated. Check your connection and try again once the order is synced."
                ),
            });
            return;
        }
        return this.report.doAction(REPORT_XML_ID, [order.id]);
    },
});
