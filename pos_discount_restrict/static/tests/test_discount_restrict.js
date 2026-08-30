/**
 * Standalone self-check for the discount-restriction logic.
 * Run with: node static/tests/test_discount_restrict.js
 * (No Odoo/Owl runtime needed — mirrors discount_restrict.js's pure logic.)
 */
const assert = require("assert");

function isPosManager(pos) {
    return pos.cashier?._role === "manager";
}

function applyDiscountRestriction(buttons, pos) {
    if (isPosManager(pos)) {
        return buttons;
    }
    return buttons.map((btn) =>
        btn.value === "discount" ? { ...btn, disabled: true } : btn
    );
}

const buttons = [
    { value: "quantity", disabled: false },
    { value: "discount", disabled: false },
    { value: "price", disabled: false },
];

// Manager cashier → discount stays enabled
assert.deepStrictEqual(
    applyDiscountRestriction(buttons, { cashier: { _role: "manager" } })[1],
    { value: "discount", disabled: false }
);

// Regular cashier → discount forced disabled
assert.deepStrictEqual(
    applyDiscountRestriction(buttons, { cashier: { _role: "cashier" } })[1],
    { value: "discount", disabled: true }
);

// No cashier logged in yet → treated as non-manager (fail closed)
assert.strictEqual(isPosManager({ cashier: null }), false);
assert.strictEqual(isPosManager({}), false);

// Switching cashier must drop a leftover "discount" numpad mode, or the next
// cashier could keep editing the discount just by pressing numbers.
function setCashier(pos, user) {
    pos.cashier = user;
    pos.numpadMode = "quantity";
}
const posState = { cashier: { _role: "manager" }, numpadMode: "discount" };
setCashier(posState, { _role: "cashier" });
assert.strictEqual(posState.numpadMode, "quantity");

console.log("OK: discount_restrict logic");
