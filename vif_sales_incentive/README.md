# VIF Sales Incentive — Odoo 19

Custom module implementing the incentive scheme in `Odoo_Incentive_Setup_Scenario.xlsx`
and `Incentive_Scheme_-Masbin.xlsx`.

## Install

```bash
git subtree add --prefix=vif_sales_incentive <repo> main
# or just drop the folder into your Odoo.sh repo root
odoo -u vif_sales_incentive -d <db>
```

Depends on: `base`, `hr`, `sale_management`, `account`.

## The calculation, in one screen

Three sequences, each on a **different base**. This is the part most
implementations get wrong.

| | Base | Purpose |
|---|---|---|
| **SQ1** | Net Sales of **all** invoices in the source month — including unpaid, including lines with discount > 35% | selects the **tier only** |
| **SQ2** | only lines with discount ≤ 35% | the eligible base |
| **SQ3** | of SQ2, only what is **fully paid** | the amount actually multiplied |

```
payout = SQ3 × (base_rate 0.75% × tier allocation)
```

### The rule that drives the whole data model

> A prior-period invoice paid in the current month is paid at the tier rate of
> its **original source period**, not the current month's tier.

Verified against the client's own figures — Business Use Case, Sales C, July:
`10,000,000 → 67,500` = 0.675% = **June's** Tier 3, while July itself is Tier 4.

That is why `incentive.transaction.tier_payout_rate` is snapshotted when the
source period is calculated and never recomputed.

### Mixed scenario

When `target_bonus > 0`:
* incentive bucket capped at the incentive target; the remainder spills into
  the bonus bucket (capped at the bonus target)
* Tier 5 is unavailable to the incentive bucket → capped at Tier 4 (S18)
* bonus bucket paid at a flat 1.00%, no tiering

## Models

| Model | Role |
|---|---|
| `incentive.period` | month master + state machine + hard lock |
| `incentive.rule` / `.tier` | versioned tier table |
| `incentive.branch` | JKT / BDG / SBY / BLI / MDN |
| `incentive.designation` | FTE weights, branch vs individual column |
| `incentive.target` | dual bucket per employee per period |
| `incentive.target.movement` | resignation / new hire / RF revision audit trail |
| `incentive.transaction` | **one row per invoice line**, three period stamps |
| `incentive.payout` | per employee per period snapshot |
| `incentive.refund.policy` | refund matrix |
| `incentive.target.cascade` (wizard) | branch RF → individual targets by FTE |

## Scenario coverage

| Scenario | Status |
|---|---|
| S01–S03 target structure, dual bucket | done |
| S04–S05 tier + base rate | done |
| S06 eligible/not-eligible month tag | done (`is_eligible`) |
| S07 35% discount gate, per line | done |
| S08–S09 payment-based, multi-iteration | done |
| S10–S12 refund reversal + policy matrix | policy matrix + manual reversal + automatic credit-note **net-off** done; full auto-reversal hook **pending** (3 UAT cases still say "NEED UPDATE") |
| S13–S15 resignation / vacancy / proration | done |
| S16–S18 scenario 1 vs 2, tier 5 cap | done |
| S19–S20 visibility | done (record rules) |
| S21–S22 period tagging, freeze | done |
| **Branch incentive stream (0.75%)** | **not implemented — scope question, see below** |

## Verification

`test_engine.py` (in the repo root, not part of the module) replays the
arithmetic against all 12 numeric cases from the client's Business Use Case.
Current status: **12/12 pass**.

## Open items before go-live

1. **Branch incentive stream.** The scheme sheet defines 0.75% branch +
   0.75% individual = 1.5%, and Team Listing carries separate eligibility
   flags. But the Business Use Case and every UAT case only exercise the
   individual stream. Confirm scope; the module is structured so the branch
   stream slots in as a second `incentive.payout` row type.
2. **Tier 0/1 boundary.** The table says Tier 0 = `≤75%` and Tier 1 =
   `75%–84.9%`. Implemented as `min ≤ ach < max` so 75.0% → Tier 1, matching
   the client's new-hire case.
3. **Net Sales in the use case does not tie out.** Sales B May:
   90M − 11M = 79M but the sheet shows 86M. Sales B Aug: 80M − 0 = 80M but the
   sheet shows 95M. Does not change the engine, but the UAT baseline needs
   correcting.
4. **Bonus rate** shown as "tbd" in one table, 1.00% in the simulation.
   Configured as 1.00%.
5. **"Fully paid" + partial credit note — net-off implemented.** After the
   `payment_state` fix, "fully paid" = `payment_state == 'paid'` only (partial /
   in-process / reversed are excluded). A credit note (`out_refund`) is now
   linked to the transaction of the invoice it reverses (via
   `account.move.reversed_entry_id`) and subtracted from that invoice's paid
   base through `_net_base()`, so payout is on the collected amount. Remaining
   limitation: a credit note issued *after* the source period is already locked
   still only reduces the current period's tier (it cannot retroactively net an
   already-locked payout) — use the manual reversal there. Manual credit notes
   (not created via "Add Credit Note") have no `reversed_entry_id`, so they
   reduce tier only.
6. **Sales Support** gets branch incentive but has no individual target —
   what achievement drives its tier?

## Odoo 19 migration (done)

* `<tree>` → `<list>` in every view, and `view_mode="tree,form"` → `"list,form"`
* `<div class="oe_chatter">` → `<chatter/>`
* the `account.move` inheritance xpath now targets `.../list/field[@name='discount']`
* Python is version-neutral — no API changes were required.
