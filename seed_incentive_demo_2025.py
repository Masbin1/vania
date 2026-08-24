# -*- coding: utf-8 -*-
"""Seed a full VIF Sales Incentive demo for 2H 2025 (Jul-Dec) and CALCULATE it.

Run AFTER installing the module (its data files load the rule, tiers, branches,
designations and 2025 periods):

    <venv>/python /home/masbintang/linkederp/base/odoo/odoo-bin shell \
        -c /home/masbintang/linkederp/vania/odoo.conf -d <DB> \
        --no-http < /home/masbintang/linkederp/vania/seed_incentive_demo_2025.py

What it does (idempotent -- safe to re-run):
  1. Ensures a res.user per salesperson and links it to hr.employee.
  2. Ensures Jul-Dec 2025 targets (incl. prorated Rina/Siti, Dina's bonus).
  3. Creates demo products + customers.
  4. Creates one posted out_invoice per active salesperson per month, with a
     spread of achievement tiers, then registers payments so invoices are
     FULLY PAID (via account.payment.register). Edge cases:
       - budi  : a 40%-discount line (excluded from eligible base, S07)
       - gilang: July invoice paid in August (prior-period-paid, S08/S09)
       - joko  : September invoice left UNPAID (tier only, no payout)
       - dina  : mixed scenario (150M incentive + 10M bonus, S16-S18)
       - rina  : resigned 15 Jul (prorated July target only)
       - siti  : joined 18 Aug (prorated Aug target, then full)
  5. Opens + calculates each period chronologically so payouts are populated.

Assumes a chart of accounts is installed (a bank/cash journal and an income
account exist). Prints a payout summary table at the end.
"""
from datetime import date, timedelta

S = env  # noqa: F821 -- `env` (superuser) is provided by `odoo-bin shell`
COMPANY = S.company

# ---------------------------------------------------------------- roster
# key: (name, branch_ref, business_type, designation_ref,
#       full_monthly_incentive_target, factor, bonus_target)
# factor = net sales / incentive target  -> picks the tier.
ROSTER = [
    ('arief', 'Arief Setiawan', 'branch_jkt', 'b2b', 'designation_lead', 200_000_000, 1.15, 0),
    ('budi',  'Budi Santoso',   'branch_jkt', 'b2b', 'designation_team', 100_000_000, 0.88, 0),
    ('citra', 'Citra Lestari',  'branch_jkt', 'b2b', 'designation_team', 100_000_000, 0.60, 0),
    ('dina',  'Dina Marlina',   'branch_jkt', 'b2c', 'designation_lead', 150_000_000, 1.07, 50_000_000),
    ('eko',   'Eko Prasetyo',   'branch_jkt', 'b2c', 'designation_team',  80_000_000, 0.95, 0),
    ('gilang','Gilang Ramadhan','branch_bdg', 'b2b', 'designation_team', 120_000_000, 1.00, 0),
    ('hana',  'Hana Nurjanah',  'branch_bdg', 'b2b', 'designation_team', 120_000_000, 0.78, 0),
    ('indra', 'Indra Wijaya',   'branch_sby', 'b2b', 'designation_lead', 180_000_000, 1.12, 0),
    ('joko',  'Joko Susilo',    'branch_sby', 'b2b', 'designation_team',  90_000_000, 0.70, 0),
    ('kadek', 'Kadek Ariawan',  'branch_bli', 'b2c', 'designation_team',  70_000_000, 1.15, 0),
    ('lukman','Lukman Hakim',   'branch_mdn', 'b2b', 'designation_team',  85_000_000, 0.92, 0),
    ('rina',  'Rina Kartika',   'branch_jkt', 'b2b', 'designation_team', 100_000_000, 0.80, 0),  # Jul only
    ('siti',  'Siti Rahma',     'branch_jkt', 'b2b', 'designation_team', 100_000_000, 0.75, 0),  # Aug+
]
# (employee key, join month) / (key, resign month) -- prorated first month.
JOINS = {'siti': 8}
RESIGNS = {'rina': 7}  # resigns 15 July
MONTHS = range(7, 13)

FTE = {'designation_lead': 1.5, 'designation_team': 1.0, 'designation_support': 0.25}


def roundM(x):
    return int(round(x / 1_000_000)) * 1_000_000


def prorated_target(full, month, days_in_month, start_day=None, end_day=None):
    """Spreadsheet convention: remaining days / 30. Returns the prorated target."""
    if start_day:   # mid-month join: remaining days = days_in_month - start_day + 1
        ratio = round((days_in_month - start_day + 1) / 30.0, 4)
    elif end_day:   # mid-month resign: days 1..end_day
        ratio = round(end_day / 30.0, 4)
    else:
        ratio = 1.0
    return roundM(full * ratio), ratio


def target_inc_for(emp, month):
    """(incentive_amount, proration_ratio, effective_start, effective_end) or None."""
    key, name, br, bt, desig, full, factor, bonus = emp
    days = 31 if month in (7, 8, 10, 12) else 30
    if key in RESIGNS and month > RESIGNS[key]:
        return None
    if month < JOINS.get(key, 0):
        return None
    if key in RESIGNS and month == RESIGNS[key]:
        amt, ratio = prorated_target(full, month, days, end_day=15)
        return amt, ratio, date(2025, month, 1), date(2025, month, 15)
    if key in JOINS and month == JOINS[key]:
        amt, ratio = prorated_target(full, month, days, start_day=18)
        return amt, ratio, date(2025, month, 18), date(2025, month, days)
    return full, 1.0, False, False


def main():
    # 1. master data references (loaded by the module on install)
    def get(xid):
        if '.' not in xid:
            xid = 'vif_sales_incentive.' + xid
        return S.ref(xid)

    # 2. products + customers + accounts/journals
    income = S['account.account'].search(
        [('account_type', '=', 'income'), ('company_ids', 'in', COMPANY.ids)], limit=1)
    receivable = S['account.account'].search(
        [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', COMPANY.ids)], limit=1)
    if not income or not receivable:
        raise RuntimeError('No income/receivable account -- install a chart of accounts first.')

    product = S['product.product'].search(
        [('name', '=', 'Incentive Demo Product')], limit=1)
    if not product:
        product = S['product.product'].create({
            'name': 'Incentive Demo Product',
            'type': 'service',
            'list_price': 1_000_000,
        })

    customers = []
    for i, cname in enumerate(['PT Pelanggan JKT', 'PT Pelanggan BDG', 'PT Pelanggan Timur']):
        c = S['res.partner'].search([('name', '=', cname)], limit=1)
        if not c:
            c = S['res.partner'].create({'name': cname, 'is_company': True})
        if receivable:
            c.write({'property_account_receivable_id': receivable.id})
        customers.append(c)

    sales_journal = S['account.journal'].search(
        [('type', '=', 'sale'), ('company_id', '=', COMPANY.id)], limit=1)
    bank_journal = S['account.journal'].search(
        [('type', '=', 'bank'), ('company_id', '=', COMPANY.id)], limit=1) or \
        S['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', COMPANY.id)], limit=1)
    if not sales_journal or not bank_journal:
        raise RuntimeError('No sale/bank journal -- install a chart of accounts first.')

    # 3. users + employees + targets
    employees = {}
    for i, (key, name, br, bt, desig, full, factor, bonus) in enumerate(ROSTER):
        login = 'demo.%s@vif.local' % key
        user = S['res.users'].search([('login', '=', login)], limit=1)
        if not user:
            user = S['res.users'].create({'name': name, 'login': login, 'email': login})
        emp = S['hr.employee'].search([('name', '=', name)], limit=1)
        vals = {
            'name': name,
            'incentive_branch_id': get(br).id,
            'incentive_business_type': bt,
            'incentive_designation_id': get(desig).id,
            'user_id': user.id,
        }
        if key in RESIGNS:
            vals['incentive_date_end'] = date(2025, RESIGNS[key], 15)
        if key in JOINS:
            vals['incentive_date_start'] = date(2025, JOINS[key], 18)
        if emp:
            emp.write(vals)
        else:
            emp = S['hr.employee'].create(vals)
        employees[key] = emp

    periods = {m: get('period_2025_%02d' % m) for m in MONTHS}
    for m in MONTHS:
        for key, name, br, bt, desig, full, factor, bonus in ROSTER:
            t = target_inc_for((key, name, br, bt, desig, full, factor, bonus), m)
            if t is None:
                continue
            inc_amt, ratio, eff_start, eff_end = t
            # incentive bucket
            rec = S['incentive.target'].search([
                ('period_id', '=', periods[m].id),
                ('employee_id', '=', employees[key].id),
                ('target_type', '=', 'incentive')], limit=1)
            vals = {
                'period_id': periods[m].id,
                'employee_id': employees[key].id,
                'target_type': 'incentive',
                'amount': inc_amt,
                'source': 'manual',
                'fte_used': FTE[desig],
            }
            if ratio != 1.0:
                vals.update(proration_ratio=ratio,
                            date_effective_start=eff_start,
                            date_effective_end=eff_end)
            if rec:
                rec.write(vals)
            else:
                S['incentive.target'].create(vals)
            # bonus bucket (mixed scenario)
            if bonus:
                brec = S['incentive.target'].search([
                    ('period_id', '=', periods[m].id),
                    ('employee_id', '=', employees[key].id),
                    ('target_type', '=', 'bonus')], limit=1)
                bvals = {'period_id': periods[m].id, 'employee_id': employees[key].id,
                         'target_type': 'bonus', 'amount': bonus, 'source': 'redistribution',
                         'fte_used': FTE[desig]}
                if brec:
                    brec.write(bvals)
                else:
                    S['incentive.target'].create(bvals)

    # 4. invoices + payments
    def line_specs(key, net):
        if key == 'dina':                    # mixed: 150M incentive + 10M bonus spill
            return [(150_000_000, 0.0), (10_000_000, 0.0)]
        if key == 'budi':                    # 40%-discount line (S07)
            return [(net - 6_000_000, 0.0), (10_000_000, 40.0)]
        return [(net, 0.0)]

    created = paid = unpaid = 0
    for m in MONTHS:
        for key, name, br, bt, desig, full, factor, bonus in ROSTER:
            t = target_inc_for((key, name, br, bt, desig, full, factor, bonus), m)
            if t is None:
                continue
            inc_amt = t[0]
            net = roundM(factor * inc_amt)
            inv_date = date(2025, m, 5)
            inv = S['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': customers[(m - 7) % len(customers)].id,
                'invoice_date': inv_date,
                'invoice_user_id': employees[key].user_id.id,
                'journal_id': sales_journal.id,
                'invoice_line_ids': [
                    (0, 0, {'product_id': product.id, 'name': product.name,
                            'quantity': 1.0, 'price_unit': pu, 'discount': d,
                            'account_id': income.id, 'tax_ids': []})
                    for pu, d in line_specs(key, net)
                ],
            })
            inv.action_post()
            created += 1
            # payment timing
            pay_date = None
            if key == 'joko' and m == 9:        # leave unpaid (S08)
                pass
            elif key == 'gilang' and m == 7:    # prior-period paid next month
                pay_date = date(2025, 8, 5)
            else:
                pay_date = date(2025, m, 15)
            if pay_date:
                S['account.payment.register'].with_context(
                    active_model='account.move', active_ids=[inv.id]).create({
                    'payment_date': pay_date,
                    'journal_id': bank_journal.id,
                    'amount': inv.amount_total,
                }).action_create_payments()
                paid += 1
            else:
                unpaid += 1

    S.cr.commit()
    print('Invoices created: %d | paid: %d | left unpaid: %d' % (created, paid, unpaid))

    # 5. open + calculate chronologically
    for m in MONTHS:
        p = periods[m]
        if p.state == 'draft':
            p.action_open()
        if p.state in ('open', 'calculated'):
            p.action_calculate()

    S.cr.commit()

    # 6. summary
    payouts = S['incentive.payout'].search(
        [('period_id', 'in', [p.id for p in periods.values()])], order='period_id, employee_id')
    print('\n%-9s %-18s %12s %7s %5s %14s %14s %12s %14s' % (
        'Period', 'Employee', 'Net Sales', 'Ach%', 'Tier', 'Payout Cur', 'Payout Prior', 'Bonus', 'Total'))
    print('-' * 120)
    for p in payouts:
        print('%-9s %-18s %12.0f %6.1f%% %5s %14.0f %14.0f %12.0f %14.0f' % (
            p.period_id.name, p.employee_id.name, p.net_sales, p.achievement_pct * 100,
            (p.tier_id.name or '-'), p.payout_current, p.payout_prior, p.payout_bonus,
            p.total_payout))
    tot = sum(p.total_payout for p in payouts)
    print('-' * 120)
    print('Total payout (Jul-Dec 2025): %.0f' % tot)


main()
