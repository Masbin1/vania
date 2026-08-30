"""Standalone replay of the engine logic against the client's own Business Use
Case numbers. No Odoo required -- this only validates the ARITHMETIC and the
sequencing, so a mismatch here means the spec was misread."""

TIERS = [  # (level, min, max, allocation)
    (0, 0.00, 0.75, 0.00),
    (1, 0.75, 0.85, 0.40),
    (2, 0.85, 0.90, 0.80),
    (3, 0.90, 1.00, 0.90),
    (4, 1.00, 1.10, 1.00),
    (5, 1.10, None, 1.05),
]
BASE_RATE = 0.0075
BONUS_RATE = 0.01


def get_tier(ach, is_mixed=False, cap=4):
    matched = TIERS[0]
    for t in TIERS:
        lo, hi = t[1], t[2]
        if ach >= lo and (hi is None or ach < hi):
            matched = t
    if is_mixed and matched[0] > cap:
        matched = [t for t in TIERS if t[0] == cap][0]
    return matched


def rate(tier):
    return round(tier[3] * BASE_RATE, 8)


def buckets(eligible_base, t_inc, t_bon):
    """(elig_inc, elig_bon) -- mirrors _run. The bonus bucket is UNCAPPED:
    everything past the incentive target is paid at the flat bonus rate."""
    if not t_bon:
        return eligible_base, 0.0
    return min(eligible_base, t_inc), max(eligible_base - t_inc, 0.0)


def split_lines(line_amounts, elig_inc, elig_bon):
    """Greedy split of eligible lines into (incentive, bonus) -- mirrors _run.

    A line straddling the boundary must SPLIT, not fall through to excluded.
    ``line_amounts`` is taken in CHRONOLOGICAL order and consumed in that
    order: a later invoice must never displace an earlier one's allocation.
    """
    rem_inc, rem_bon = elig_inc, elig_bon
    out = []
    for amt in line_amounts:
        inc = min(amt, rem_inc)
        rem_inc -= inc
        bon = min(amt - inc, rem_bon)
        rem_bon -= bon
        out.append((inc, bon))
    return out


def run(name, t_inc, t_bon, net, eligible_inc, paid_cur, paid_prior,
        prior_rate, eligible_bon=0.0, paid_bon=0.0):
    is_mixed = bool(t_bon)
    ach = net / t_inc if t_inc else 0.0
    tier = get_tier(ach, is_mixed)
    r = rate(tier)
    payout_cur = paid_cur * r
    payout_prior = paid_prior * prior_rate
    payout_bon = paid_bon * BONUS_RATE
    return {
        'name': name, 'ach': ach, 'tier': tier[0], 'rate': r,
        'payout_cur': payout_cur, 'payout_prior': payout_prior,
        'payout_bon': payout_bon,
        'total': payout_cur + payout_prior + payout_bon,
    }


M = 1_000_000
CASES = [
    # name, t_inc, t_bon, net, elig_inc, paid_cur, paid_prior, prior_rate,
    #   elig_bon, paid_bon, EXPECT tier, EXPECT payout_cur, EXPECT payout_prior,
    #   EXPECT bonus, EXPECT total
    ("A May   (TC01 Tier 0)", 100*M, 0, 70*M, 65*M, 45*M, 0, 0.0, 0, 0,
     0, 0, 0, 0, 0),
    ("B May   (TC02 Tier 2)", 100*M, 0, 86*M, 70*M, 60*M, 0, 0.0, 0, 0,
     2, 360_000, 0, 0, 360_000),
    ("B June  (Tier 2 +prior)", 100*M, 0, 89*M, 85*M, 70*M, 10*M, 0.006, 0, 0,
     2, 420_000, 60_000, 0, 480_000),
    ("C May   (TC05 Tier 4)", 100*M, 0, 100*M, 60*M, 60*M, 0, 0.0, 0, 0,
     4, 450_000, 0, 0, 450_000),
    ("C June  (TC04 Tier 3)", 100*M, 0, 93*M, 80*M, 70*M, 0, 0.0, 0, 0,
     3, 472_500, 0, 0, 472_500),
    ("C July  (prior @Jun rate)", 100*M, 50*M, 100*M, 90*M, 70*M, 10*M, 0.00675, 0, 0,
     4, 525_000, 67_500, 0, 592_500),
    ("D June  (TC06 Tier 1)", 100*M, 0, 82*M, 70*M, 70*M, 5*M, 0.006, 0, 0,
     1, 210_000, 30_000, 0, 240_000),
    ("D July  (TC03 Tier 5)", 100*M, 0, 110*M, 105*M, 105*M, 0, 0.0, 0, 0,
     5, 826_875, 0, 0, 826_875),
    ("B July  (MIXED cap T5->T4)", 100*M, 50*M, 145*M, 100*M, 100*M, 5*M, 0.006, 45*M, 45*M,
     4, 750_000, 30_000, 450_000, 1_230_000),
    ("B Aug   (MIXED, bonus miss)", 100*M, 30*M, 95*M, 90*M, 65*M, 0, 0.0, 0, 0,
     3, 438_750, 0, 0, 438_750),
    ("C Aug   (MIXED, bonus hit)", 100*M, 30*M, 105*M, 100*M, 100*M, 0, 0.0, 5*M, 5*M,
     4, 750_000, 0, 50_000, 800_000),
    ("E Aug   (new hire 14/31)", 40*M, 0, 30*M, 30*M, 20*M, 0, 0.0, 0, 0,
     1, 60_000, 0, 0, 60_000),
]

print(f"{'CASE':<30}{'ACH':>8}{'TIER':>5}{'EXP':>5}{'TOTAL':>14}{'EXPECTED':>14}  OK")
print('-'*94)
fails = 0
for c in CASES:
    (name, ti, tb, net, ei, pc, pp, pr, eb, pb,
     x_tier, x_cur, x_prior, x_bon, x_total) = c
    r = run(name, ti, tb, net, ei, pc, pp, pr, eb, pb)
    ok = (r['tier'] == x_tier
          and round(r['payout_cur']) == x_cur
          and round(r['payout_prior']) == x_prior
          and round(r['payout_bon']) == x_bon
          and round(r['total']) == x_total)
    if not ok:
        fails += 1
    print(f"{name:<30}{r['ach']*100:>7.1f}%{r['tier']:>5}{x_tier:>5}"
          f"{round(r['total']):>14,}{x_total:>14,}  {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"    got cur={round(r['payout_cur']):,} prior={round(r['payout_prior']):,} "
              f"bonus={round(r['payout_bon']):,}")

print('-'*94)
print(f"{len(CASES)-fails}/{len(CASES)} passed")

# Split sanity -- a line crossing the boundary must split, not be excluded.
assert split_lines([100_000], 50_000, 50_000) == [(50_000, 50_000)], \
    "boundary line must split 50/50"
assert split_lines([100_000, 50_000], 100_000, 50_000) == [(100_000, 0), (0, 50_000)], \
    "whole lines fill inc then bonus"
assert split_lines([100_000], 0, 0) == [(0, 0)], \
    "nothing to allocate means nothing is paid"

# The bonus bucket is UNCAPPED -- excess past the bonus TARGET is still paid
# at the flat bonus rate, never forfeited.
assert buckets(700_000, 428_571.43, 171_428.57) == (428_571.43, 271_428.57), \
    "bonus bucket must absorb everything past the incentive target"
assert buckets(150_000, 100_000, 20_000) == (100_000, 50_000), \
    "overflow past the bonus target is still paid, not dropped"
assert buckets(90_000, 100_000, 30_000) == (90_000, 0.0), \
    "under the incentive target, nothing spills to bonus"
assert buckets(700_000, 428_571.43, 0) == (700_000, 0.0), \
    "non-mixed: no bonus bucket at all"

# Regression: allocation is chronological, so adding a LATER, larger invoice
# must not retroactively change what the earlier invoices already got.
# Nur Suci Oct-2025: incentive target 428,571.43 / bonus target 171,428.57.
_INC, _BON = buckets(600_000, 428_571.43, 171_428.57)
_before = split_lines([200_000, 200_000], _INC, _BON)
_INC3, _BON3 = buckets(700_000, 428_571.43, 171_428.57)
_after = split_lines([200_000, 200_000, 300_000], _INC3, _BON3)
assert _before == [(200_000, 0), (200_000, 0)], _before
assert _after[:2] == _before, \
    "a new invoice must not displace earlier invoices' allocation"
assert (round(_after[2][0], 2), round(_after[2][1], 2)) == (28_571.43, 271_428.57), _after[2]
# ...and every rupiah of the line is accounted for -- nothing forfeited.
assert round(sum(sum(p) for p in _after), 2) == 700_000.00, _after

# A salesperson WITH a bonus target must never earn less than the same sales
# figures without one. This is what the capped bonus bucket used to break.
_mixed = (_INC3 * rate(get_tier(700_000 / 428_571.43, True))
          + _BON3 * BONUS_RATE)
_plain = 700_000 * rate(get_tier(700_000 / 428_571.43, False))
assert _mixed >= _plain, (_mixed, _plain)
print("split checks: 9/9 passed")

# ---- Branch stream (0.75%) self-check -------------------------------
def branch_pool(branch_target, net, paid, weights):
    """Pool = paid x base_rate x tier_allocation; split by FTE weight."""
    ach = net / branch_target if branch_target else 0.0
    tier = get_tier(ach)          # branch never caps tier 5 (S18 is individual-only)
    pool = paid * rate(tier)
    total = sum(weights) or 0.0
    return pool, [pool * (w / total) if total else 0.0 for w in weights]

pool, shares = branch_pool(100*M, 100*M, 90*M, [1.5, 1.0, 0.25])
# Tier 4 (ach 100%) -> rate 0.0075; pool = 90M * 0.0075 = 675,000
assert round(pool) == 675_000, pool
assert round(sum(shares)) == round(pool)
assert round(shares[0]) == round(pool * 1.5 / 2.75)
assert round(shares[2]) == round(pool * 0.25 / 2.75)
print("branch stream checks: 4/4 passed")

# ---- Tier is INVOICED, payout is COLLECTED --------------------------
# The team invoiced its full July target but only collected half. Achievement
# is measured on what was INVOICED (SQ1), so the tier is 100%; the money is
# paid on what was COLLECTED (SQ3). Selecting transactions by payment date
# used to drop the unpaid invoice from SQ1 entirely, halving the tier.
_JULY = run("July: 2M invoiced, 1M collected", 2*M, 0,
            net=2*M,          # SQ1: every invoice of the month, paid or not
            eligible_inc=2*M,
            paid_cur=1*M,     # SQ3: only what was actually collected
            paid_prior=0, prior_rate=0.0)
assert _JULY['tier'] == 4, _JULY          # 2M/2M = 100% -> tier 4
assert round(_JULY['ach'] * 100) == 100, _JULY
assert round(_JULY['total']) == 7_500, _JULY   # 1M x 0.75%, not 2M

# The bug: tier taken from the collected 1M instead of the invoiced 2M.
_BUG = run("July (wrong: tier from collected)", 2*M, 0,
           net=1*M, eligible_inc=1*M, paid_cur=1*M, paid_prior=0, prior_rate=0.0)
assert _BUG['tier'] == 0 and _JULY['tier'] == 4, (_BUG['tier'], _JULY['tier'])
# 1M/2M = 50% lands in tier 0, whose allocation is 0.00 -- so the team that
# hit its target on paper was paid NOTHING at all, not merely less.
assert round(_BUG['total']) == 0, _BUG

# August: the remaining 1M is collected. It belongs to JULY's tier (4 ->
# 0.75%), not to whatever August achieves on its own. This is the prior-period
# rule -- dead code until source and payment periods could differ.
_AUG = run("Aug: July's remaining 1M collected", 2*M, 0,
           net=0, eligible_inc=0, paid_cur=0,
           paid_prior=1*M, prior_rate=_JULY['rate'])
assert round(_AUG['total']) == 7_500, _AUG
assert _AUG['tier'] == 0, "August invoiced nothing, so its OWN tier is 0"

# Across both months the full 2M is paid exactly once, at July's rate.
assert round(_JULY['total'] + _AUG['total']) == round(2*M * _JULY['rate']) == 15_000
print("tier-vs-payment checks: 7/7 passed")

# ---- Down payment exclusion -----------------------------------------
def incentive_lines(move_lines):
    """What the engine keeps: product lines that are NOT down payments.

    Mirrors the domain in _generate_for_period. ``move_lines`` is
    (display_type, is_downpayment, price_subtotal).
    """
    return [amt for dtype, is_dp, amt in move_lines
            if dtype == 'product' and not is_dp]

# 100M order, 30% down payment. Odoo builds three product lines across two
# invoices; only the real one may earn incentive.
DP_INVOICE = [('product', True, 30*M)]                  # month 10, paid
FINAL_INVOICE = [('product', False, 100*M),             # the actual goods
                 ('product', True, -30*M)]              # DP negation, qty -1

# Month 10: the DP invoice is fully paid but produces no incentive base.
assert incentive_lines(DP_INVOICE) == [], \
    "a paid down payment must not earn incentive on its own"

# Month 11: the final invoice is paid -- base is the FULL order value, once.
assert sum(incentive_lines(FINAL_INVOICE)) == 100*M, \
    "final invoice must be worth the full order value, not 70M and not 160M"

# The bug this replaces: abs() flipped the -30M negation back to +30M, so the
# same order was worth 160M and the down payment was counted twice.
assert sum(abs(amt) for _, _, amt in DP_INVOICE + FINAL_INVOICE) == 160*M, \
    "sanity: this is the WRONG number the old abs() produced"

# A credit note against the final invoice still nets off the real line only.
assert incentive_lines([('product', False, 20*M), ('product', True, -30*M)]) \
    == [20*M], "credit note nets the product line, never the DP negation"
print("down payment checks: 4/4 passed")

# ---- Rolling-forecast carry-forward (per employee) -------------------
def carry(shortfall, months_remaining):
    """Own shortfall spread evenly over the scheme's remaining months."""
    return shortfall / months_remaining if months_remaining else 0.0

# July 2023 Bandung b2b (rule ends Dec -> 5 remaining months):
#   Aditya shortfall 257,142.86 -> 51,428.57/month
#   Agus / Andri shortfall 271,428.57 each -> 54,285.71/month
aditya = round(carry(257_142.86, 5), 2)
agus = round(carry(271_428.57, 5), 2)
assert aditya == 51_428.57
assert agus == 54_285.71
# Total carry = 800k / 5 = 160k (sum of shortfalls, never FTE-mixed).
assert round(carry(257_142.86 + 271_428.57 + 271_428.57, 5), 2) == 160_000.00
# August branch target = base 2,000,000 + 160,000 = 2,160,000 (NOT 2,800,000).
assert round(2_000_000 + carry(800_000, 5), 2) == 2_160_000.00
# A salesperson who hit target carries nothing; carry is isolated per person.
assert carry(0, 5) == 0.0
# Accumulation: Aditya falls short again in Aug by 108,571.43 over 4 months.
sep_carry = round(aditya + carry(108_571.43, 4), 2)
assert sep_carry == 78_571.43
print("rolling-forecast checks: passed")
