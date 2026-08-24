# BUKU PANDUAN — VIF Sales Incentive

**Modul Odoo 19 untuk mesin insentif penjualan (Sales Incentive Engine) VIF / Vania**

| | |
|---|---|
| Modul | `vif_sales_incentive` |
| Versi | 19.0.1.0.0 |
| Author | Muhammad Bintang — Linked ERP (linkederp.com) |
| Platform | Odoo 19 (Community + Enterprise) |
| Sumber spesifikasi | `Incentive Scheme -Masbin 1.xlsx` dan `Odoo Incentive Setup Scenario 1.xlsx` |
| Dokumen panduan ini | Pengganti & pelengkap `USER_GUIDE.md` (lebih lengkap) |

---

## DAFTAR ISI

1. [Gambaran Umum](#1-gambaran-umum)
2. [Konsep Skema Insentif](#2-konsep-skema-insentif)
3. [Arsitektur Modul](#3-arsitektur-modul)
4. [Instalasi](#4-instalasi)
5. [Hak Akses & Visibilitas](#5-hak-akses--visibilitas)
6. [Master Data Lengkap](#6-master-data-lengkap)
7. [Setup Karyawan](#7-setup-karyawan)
8. [Setup Target & Cascade](#8-setup-target--cascade)
9. [Siklus Operasional Bulanan](#9-siklus-operasional-bulanan)
10. [Detail Rumus Kalkulasi](#10-detail-rumus-kalkulasi)
11. [Contoh Perhitungan Lengkap](#11-contoh-perhitungan-lengkap)
12. [Refund / Retur](#12-refund--retur)
13. [Resignasi, Vacant, New Hire & Prorata](#13-resignasi-vacant-new-hire--prorata)
14. [Menu & Navigasi](#14-menu--navigasi)
15. [FAQ / Troubleshooting](#15-faq--troubleshooting)
16. [Batasan & Item Terbuka](#16-batasan--item-terbuka)
17. [Checklist Go-Live](#17-checklist-go-live)

---

## 1. Gambaran Umum

Modul ini menghitung **insentif penjualan per salesperson per bulan** berdasarkan skema insentif VIF yang tertuang di dua dokumen Excel. Hasil akhirnya adalah baris **Payout** per karyawan per periode yang bisa di-review, disetujui, lalu dikunci permanen.

Aturan inti yang harus selalu diingat:

1. **Insentif hanya dibayar dari invoice yang sudah lunas** (*fully paid*).
2. Hanya **baris invoice dengan diskon ≤ 35%** yang eligible (dinilai **per baris**, bukan per invoice).
3. Besaran insentif memakai **tier** berdasarkan % pencapaian terhadap target.
4. **Basis kas (cash basis):** transaksi ditangkap di **bulan invoice lunas** (`incentive_full_payment_date`), bukan bulan terbit invoice. Tier pun dihitung dari net sales bulan lunas.
5. Setiap salesperson punya **dua bucket target**: Incentive-Based (tiering) dan Bonus-Based (flat).
6. **Shortfall target** di akhir bulan di-**roll forward per salesperson** ke sisa bulan skema (carry-forward), tidak dicampur antar anggota tim.

Modul menyimpan seluruh proses dalam model terpisah-pisah agar setiap angka bisa diaudit: target, perpindahan target, transaksi per baris invoice, dan payout per periode.

---

## 2. Konsep Skema Insentif

### 2.1 Dua kategori insentif

Dokumen `Incentive Scheme -Masbin 1.xlsx` membagi target penjualan menjadi **2 kategori**:

| No | Kategori | Base Rate | Method | Keterangan |
|---|---|---|---|---|
| 1 | **Incentive-Based Target** | **1,5% total** | Tiering | Target melekat ke tiap sales aktif |
| 2 | **Bonus-Based Target** | **1,00%** | Flat (tidak tiering) | Target berasal dari posisi vacant/resign |

Angka "1,5% total" pada kategori Incentive-Based sebenarnya adalah penjumlahan dua stream:

| Stream | Base Rate | Method |
|---|---|---|
| **Branch Incentives** | 0,0075 (0,75%) | Tiering |
| **Individual Incentives** | 0,0075 (0,75%) | Tiering |
| **Total Incentives** | **0,015 (1,5%)** | — |

> **CATATAN PENTING (status implementasi):** Mesin payout kini **menghitung ketiga stream**: **Individual (0,75%)**, **Branch (0,75%)**, dan **Bonus (1,00%)**. Stream Branch dihitung di `_compute_branch_for_period` — pool cabang = net sales cabang × rate tier cabang, lalu dibagi ke tim sesuai bobot `fte_branch × prorata`. Detail di [§10.7](#107-branch-stream-075).

### 2.2 Tiga sekuens (SQ1, SQ2, SQ3)

Ini bagian yang paling sering salah diimplementasikan. Tiga sekuens memakai **basis yang berbeda**:

| Sekuens | Basis | Kegunaan |
|---|---|---|
| **SQ1** | **Net Sales SEMUA invoice yang lunas** di bulan berjalan (termasuk diskon >35%), dikurangi retur | Hanya untuk **memilih tier** |
| **SQ2** | Hanya baris dengan **diskon ≤ 35%** | Basis **eligible**, lalu di-split ke bucket incentive/bonus |
| **SQ3** | Dari SQ2, hanya yang **sudah lunas** | Jumlah yang benar-benar dikalikan rate |

> **Catatan basis kas:** karena transaksi hanya dibuat dari invoice yang **sudah lunas** di bulan itu (lihat §9 Step 3), semua baris yang tertangkap otomatis lunas — SQ3 secara praktis sama dengan SQ2. Ketiga sekuens tetap dipertahankan agar urutan evaluasi (tier → diskon → pembayaran) transparan.

```
Payout = SQ3 × (base_rate 0,75% × allocation tier)
Branch  = branch_pool × (fte_branch × prorata / Σ fte_branch)   # stream 0,75% cabang
Bonus   = SQ3_bonus × bonus_rate 1,00%
```

### 2.3 Tabel Tier

| Tier | Achievement | Allocation | Payout Rate |
|---|---|---|---|
| 0 | < 75% | 0,00 | 0,0000% (tidak eligible) |
| 1 | 75% – 84,9% | 0,40 | 0,3000% |
| 2 | 85% – 89,9% | 0,80 | 0,6000% |
| 3 | 90% – 99,9% | 0,90 | 0,6750% |
| 4 | 100% – 109,9% | 1,00 | 0,7500% |
| 5 | ≥ 110% | 1,05 | 0,7875% (hanya scenario full-incentive) |

**Konvensi batas tier:** `min ≤ achievement < max`, kecuali tier teratas yang terbuka. Akibatnya **tepat 75,0% jatuh ke Tier 1** (sesuai contoh new-hire client: 30M/40M = 75% → Tier 1). Tier 0 menangkap rentang `[0% , 75%)`.

### 2.4 Scenario 1 vs Scenario 2 (mixed)

- **Scenario 1 (full incentive-based):** seluruh target adalah incentive-based. Tier 5 tersedia.
- **Scenario 2 (mixed incentive + bonus):** saat seorang salesperson punya **target bonus > 0**, sistem masuk Scenario 2. Aturannya:
  1. Bucket incentive **di-cap di target incentive**; sisanya limpah ke bucket bonus (di-cap di target bonus).
  2. **Tier 5 tidak berlaku** untuk bucket incentive → di-cap ke **Tier 4** (S18).
  3. Bucket bonus dibayar **flat 1,00%**, tanpa tiering.

Dokumen mencatat keputusan: "When Incentive-Based Target + Bonus-Based Target fully achieved, VIF will use **Scenario 2**."

### 2.5 FTE (Full Time Equivalent)

FTE dipakai untuk menurunkan target cabang ke individu. Dua kolom karena bobotnya berbeda antara level branch dan individual:

| Role | Branch FTE | Individual FTE | Keterangan |
|---|---|---|---|
| **Lead** | 1,50 | 1,50 | Sales Manager / Branch Manager / Spv Showroom |
| **Team** | 1,00 | 1,00 | Sales Executive / Customer Service |
| **Support** | 0,25 | **0,00** | Sales Support — **tidak punya target individual** |

Konsekuensinya: **Support** eligible untuk branch incentive saja, **tidak** individual incentive. Lead dan Team eligible untuk keduanya.

---

## 3. Arsitektur Modul

### 3.1 Dependensi

```
base, hr, sale_management, account
```

### 3.2 Struktur berkas

```
vif_sales_incentive/
├── __manifest__.py                 # metadata & daftar file
├── models/
│   ├── incentive_branch.py         # cabang (JKT/BDG/SBY/BLI/MDN)
│   ├── incentive_branch_target.py  # target net sales cabang per periode
│   ├── incentive_designation.py    # FTE designation (Lead/Team/Support)
│   ├── incentive_rule.py           # rule version + tier table
│   ├── incentive_period.py         # periode + state machine
│   ├── incentive_target.py         # target per karyawan (2 bucket)
│   ├── incentive_target_movement.py# audit trail perpindahan target
│   ├── incentive_transaction.py    # transaksi per baris invoice
│   ├── incentive_payout.py         # snapshot payout per karyawan
│   ├── incentive_refund_policy.py  # matriks refund
│   ├── hr_employee.py              # field tambahan di hr.employee
│   └── account_move.py             # field tambahan di account.move(.line)
├── wizards/
│   └── incentive_target_cascade.py # wizard cascade RF → individu
├── views/                          # seluruh view + menu
├── data/                           # seed master (rule, tier, period, designation, dll.)
├── security/                       # grup + record rule
└── test_engine.py                  # replay aritmetika (di luar modul)
```

### 3.3 Peta model

| Model | Peran |
|---|---|
| `incentive.period` | Master bulan + state machine + lock keras |
| `incentive.rule` / `.tier` | Versi rule + tabel tier |
| `incentive.branch` | Cabang penjualan |
| `incentive.branch.target` | Target net sales cabang per periode (penyebut tier branch) |
| `incentive.designation` | Bobot FTE (branch vs individual) |
| `incentive.target` | Dua bucket target per karyawan per periode |
| `incentive.target.movement` | Audit trail resign/vacant/new-hire/revisi RF |
| `incentive.transaction` | **Satu baris per baris invoice**; `source_period` = bulan lunas (basis kas) |
| `incentive.payout` | Snapshot payout per karyawan per periode |
| `incentive.refund.policy` | Matriks refund |
| `incentive.target.cascade` (+ `.line`) | Wizard cascade target cabang → individu |
| `hr.employee` | Field insentif di karyawan |
| `account.move` / `.line` | Field insentif di invoice |

---

## 4. Instalasi

### 4.1 Prasyarat

- Odoo 19 dengan addons `hr`, `sale_management`, `account` terpasang.
- Modul diletakkan di dalam **addons_path**.

### 4.2 Konfigurasi addons_path

Pastikan folder modul masuk ke `addons_path`. Pada setup dev Vania, file `vania/odoo.conf` **belum** memuat folder modul, sehingga harus ditambahkan manual:

```ini
addons_path =
    /home/masbintang/linkederp/base/odoo/addons,
    /home/masbintang/linkederp/base/enterprise,
    /home/masbintang/linkederp/omnisurge/Odoo,
    /home/masbintang/linkederp/vania/module        ; ← tambahkan baris ini
```

### 4.3 Perintah install

```bash
python3 /home/masbintang/linkederp/base/odoo/odoo-bin \
  -c /home/masbintang/linkederp/vania/odoo.conf \
  -d <nama_database> \
  -i vif_sales_incentive
```

> `-i` untuk install pertama; `-u vif_sales_incentive` untuk upgrade setelah ada perubahan.

### 4.4 Catatan data demo

`vania/odoo.conf` memakai `without_demo = True`, artinya **data demo (karyawan & target contoh) TIDAK otomatis dimuat**. Dua pilihan:

1. **Install dengan demo:** tambahkan `--demo=all` pada perintah install agar file `data/incentive_demo_data.xml` ikut dimuat.
2. **Seed manual (disarankan untuk UAT):** gunakan skrip `seed_incentive_demo_2025.py` yang sudah tersedia di folder Vania untuk membuat karyawan, target, invoice, pembayaran, dan langsung menghitung payout:

```bash
python3 /home/masbintang/linkederp/base/odoo/odoo-bin shell \
  -c /home/masbintang/linkederp/vania/odoo.conf -d <DB> --no-http \
  < /home/masbintang/linkederp/vania/seed_incentive_demo_2025.py
```

### 4.5 Tahun skema

Data seed bawaan memakai **"Incentive Scheme 2H 2025"** (1 Jul – 31 Des 2025) beserta periode Jul–Des 2025. Untuk go-live, **buat rule & periode baru dengan tahun yang benar** (misal 2H 2026) melalui menu Configuration → Rules & Tiers, lalu buat periode lewat tombol **Create Next Month**.

---

## 5. Hak Akses & Visibilitas

Ada **3 grup** (Settings → Users & Companies → Groups):

| Grup | ID XML | Bisa melihat | Bisa melakukan |
|---|---|---|---|
| **Salesperson (own data)** | `group_incentive_user` | Hanya data diri sendiri | Lihat "My Incentive" |
| **Sales Manager (subordinates)** | `group_incentive_manager` | Diri + seluruh bawahan (N+1, `child_of`) | Review bawahan |
| **Incentive Administrator** | `group_incentive_admin` | Semua | Config, cascade, calculate, approve, lock |

Grup di atas saling bertingkat (`implied_ids`): admin ⊃ manager ⊃ user.

Implementasi visibilitas memakai **record rule** pada 3 model: `incentive.payout`, `incentive.target`, dan `incentive.transaction`, dengan pola domain:

- User: `[('employee_id.user_id', '=', user.id)]`
- Manager: `['|', ('employee_id.user_id','=',user.id), ('employee_id','child_of', user.employee_id.id)]`
- Admin: `[(1,'=',1)]` (semua)

Tambahan: record rule **multi-company** untuk `incentive.period`.

> Agar visibilitas "My Incentive" berfungsi, **karyawan harus terhubung ke user Odoo** (field `Related User` di employee). Tanpa link, record rule user tidak menemukan apa-apa.

---

## 6. Master Data Lengkap

Saat install, modul otomatis **seed** master berikut (semua `noupdate="1"`, artinya tidak ditimpa saat upgrade):

### 6.1 Sales Branch (`incentive.branch`)

| Code | Nama |
|---|---|
| JKT | Jakarta |
| BDG | Bandung |
| SBY | Surabaya |
| BLI | Bali |
| MDN | Medan |

Field: `name`, `code` (unik per company), `sequence`, `company_id`, `manager_id` (Branch Manager), `active`, `employee_ids` (One2many).

**Ideal Team Size** (`ideal_team_size`) — jumlah anggota yang **seharusnya** ada dalam satu tim, termasuk Lead. Diisi manual per cabang, berlaku untuk tim B2B **maupun** B2C (masing-masing tetap dihitung sebagai populasi terpisah). Gunanya menjaga penyebut cascade tetap stabil saat tim kekurangan orang — lihat [§8.5](#85-ideal-team-size--kursi-kosong-ikut-menanggung-target). Nilai **0 = fitur mati** (perilaku lama, penyebut hanya dari orang yang ada).

**Effective FTE** (`effective_fte`, computed) — FTE aktual seluruh cabang **hari ini** (B2B + B2C digabung), memakai bobot `fte_branch`. Angka tampilan saja; tidak ada perhitungan yang membacanya.

> Perhatikan bedanya: `ideal_team_size` **per tim**, `effective_fte` **se-cabang**. Bandung ideal 5 dengan B2B 4,5 FTE + B2C 3,0 FTE akan menampilkan `effective_fte` = 7,5 — bukan angka yang bisa langsung dibandingkan dengan 5. Untuk perbandingan per tim yang akurat, lihat kolom FTE di preview wizard Cascade.

### 6.2 FTE Designation (`incentive.designation`)

| Name | Code | Branch FTE | Individual FTE | Branch Eligible | Individual Eligible |
|---|---|---|---|---|---|
| Lead | LEAD | 1,5 | 1,5 | Ya | Ya |
| Team | TEAM | 1,0 | 1,0 | Ya | Ya |
| Support | SUPPORT | 0,25 | 0,0 | Ya | **Tidak** |

Field: `name`, `code` (unik), `sequence`, `fte_branch`, `fte_individual`, `branch_incentive_eligible`, `individual_incentive_eligible`, `active`.

### 6.3 Rule & Tier (`incentive.rule` + `incentive.rule.tier`)

Rule seed: **"Incentive Scheme 2H 2025"** (2025-07-01 s/d 2025-12-31).

Field penting di `incentive.rule`:

| Field | Nilai | Arti |
|---|---|---|
| `base_rate` | 0,0075 | Base rate stream individual (0,75%) |
| `bonus_rate` | 0,01 | Rate flat bucket bonus (1,00%) |
| `max_discount` | 35,0 | Batas diskon eligible (%) |
| `cap_tier_in_mixed` | True | Cap tier 5 saat mixed |
| `mixed_cap_tier_level` | 4 | Tier maksimum saat mixed |

Tier seed (6 baris):

| Tier | achievement_min | achievement_max | allocation | payout_rate |
|---|---|---|---|---|
| 0 | 0,00 | 0,75 | 0,0 | 0,0000% |
| 1 | 0,75 | 0,85 | 0,4 | 0,3000% |
| 2 | 0,85 | 0,90 | 0,8 | 0,6000% |
| 3 | 0,90 | 1,00 | 0,9 | 0,6750% |
| 4 | 1,00 | 1,10 | 1,0 | 0,7500% |
| 5 | 1,10 | 99,0 (top, terbuka) | 1,05 | 0,7875% |

`payout_rate` adalah computed field = `allocation × rule_id.base_rate`.

### 6.4 Refund Policy (`incentive.refund.policy`)

Matriks "Kebijakan Refund (Business Risk)" — 5 baris seed:

| Name | Stock | WIP | Payment | Initiator | Refund % |
|---|---|---|---|---|---|
| Any stock / WIP / customer | any | Ya | any | customer | 0% |
| Indent / not WIP / customer | indent | Tidak | any | customer | 0% |
| Available / not WIP / customer | available | Tidak | any | customer | 99% |
| Jasa Curtain / not WIP / customer | service | Tidak | any | customer | 99% |
| Company-initiated | any | Ya | any | company | By agreement |

Field: `name`, `sequence`, `stock_type` (available/indent/service/any), `is_wip`, `payment_status` (partial/paid/any), `initiator` (customer/company), `refund_pct`, `by_agreement`, `note`, `active`.

### 6.5 Periode (`incentive.period`)

Seed: **Jul 2025 – Des 2025** (6 periode), state Draft, rule `rule_2h_2025`.

Field: `name`, `date_start`, `date_end`, `company_id`, `rule_id`, `state`, `target_ids`, `payout_ids`, `transaction_ids`, `total_target`, `total_payout`.

### 6.6 Sequence

`ir.sequence` untuk numbering **Target Movement**: prefix `TMV/%(year)s/`, padding 5.

---

## 7. Setup Karyawan

Buka **Employees** → tab **Sales Incentive**. Field tambahan di `hr.employee`:

| Field | Keterangan |
|---|---|
| **Sales Branch** (`incentive_branch_id`) | Cabang JKT/BDG/SBY/BLI/MDN |
| **Business Type** (`incentive_business_type`) | `b2b` atau `b2c` |
| **FTE Designation** (`incentive_designation_id`) | Lead / Team / Support |
| **Effective Target Start** (`incentive_date_start`) | Tanggal target mulai efektif (prorata new hire mid-month) |
| **Resignation Date** (`incentive_date_end`) | Tanggal resign (kosongkan jika aktif) |
| **Vacant Position** (`is_vacant_slot`) | Centang untuk slot kosong (placeholder headcount) |
| **Branch Incentive Eligible** | computed dari designation |
| **Individual Incentive Eligible** | computed dari designation |

**Aturan penting:**

1. **Link user**: karyawan harus terhubung ke user Odoo (`Related User`) agar (a) invoice otomatis menunjuk salesperson, (b) visibilitas "My Incentive" berfungsi.
2. `Support` otomatis **tidak eligible individual incentive** (turunan designation), tapi tetap eligible branch incentive.
3. `_is_incentive_active_on(date)` menentukan status aktif: false jika vacant, atau di luar rentang `date_start`/`date_end`.

### 7.1 Larangan serah-terima kursi di tanggal yang sama

**Tanggal join tidak boleh sama dengan tanggal resign rekan satu tim.** Satu tim = satu **cabang × business type** (Bandung-B2B dan Bandung-B2C adalah dua tim berbeda).

Contoh yang ditolak: Rina resign 21 Agustus, Budi diisi join 21 Agustus di Bandung-B2B. Simpan → `ValidationError`:

> *Rina resigns from Bandung / B2B on 2025-08-21 and Budi joins the same team on the same date. One seat cannot be held by two people on the same day — the joining date must be at least the day AFTER the resignation.*

**Kenapa dilarang:** keduanya terhitung aktif di tanggal 21, jadi tim menanggung satu FTE berlebih dan prorata keduanya dijumlah jadi lebih dari sebulan penuh (21/31 + 11/31 = 32/31). Solusinya: Budi join **22 Agustus**.

Pengecekan berjalan dua arah — mau yang diedit tanggal join-nya, atau tanggal resign rekannya, sama-sama ketahuan. Aturan ini **tidak** bergantung pada `ideal_team_size`, jadi tetap berlaku di cabang yang idealnya belum diisi.

---

## 8. Setup Target & Cascade

Target adalah **dua bucket per karyawan per periode** (`incentive.target`):

- **Incentive-Based** (`target_type='incentive'`) — dari rolling forecast, sumber `rf_cascade` atau `manual`.
- **Bonus-Based** (`target_type='bonus'`) — dinamis dari redistribusi vacant/resign, sumber `redistribution`.

Field di `incentive.target`: `period_id`, `employee_id`, `target_type`, `amount`, `source`, `fte_used`, `date_effective_start`, `date_effective_end`, `proration_ratio`, `movement_ids`, `note`.

Constraint: `unique(period_id, employee_id, target_type)` — satu baris per bucket per periode.

### 8.1 Cascade otomatis (disarankan)

Menu **Sales Incentive → Operations → Cascade Branch Target** (wizard `incentive.target.cascade`). Isi:

| Field | Keterangan |
|---|---|
| **Period** | Periode (harus Draft/Open/Calculated) |
| **Branch** | Cabang |
| **Business Type** | B2B / B2C |
| **Branch Net Sales Target** | Angka rolling forecast cabang (base, tanpa carry-forward) |
| **Carry-Forward Total** | (read-only) Jumlah carry-forward seluruh salesperson bulan ini; otomatis ditambahkan ke target cabang saat Apply |
| **Scope** | `Individual Target` (kolom FTE individual) atau `Branch Pool` (kolom FTE branch) |
| **Redistribute Vacant Slots** | Centang agar porsi slot kosong dibagikan ke tim aktif (masuk bucket bonus) |
| **Overwrite Existing** | Centang untuk menimpa target yang sudah ada |

Rumus cascade (mengikuti Step 5–6 di sheet `<BRANCH> 2H TARGET`):

```
total FTE populasi = FTE aktif + FTE vacant + gap kursi kosong   ← lihat §8.5
individual target = branch target × (FTE sendiri / total FTE populasi) × prorata + carry-forward sendiri
bonus target      = porsi vacant × (FTE sendiri / total FTE aktif) × prorata
branch target (final) = branch target + total carry-forward
```

Alur: **Preview** (muncul baris per karyawan) → cek → **Apply** (membuat `incentive.target` + `incentive.target.movement` untuk bucket bonus, dan menulis `incentive.branch.target` final).

**Kolom di tabel Preview:**

| Kolom | Arti |
|---|---|
| Employee / Designation | Siapa dan bobot FTE-nya |
| **FTE** | Bobot yang dipakai (ikut Scope: individual atau branch) |
| **Prorata** | Hari aktif ÷ hari dalam bulan (1,0 = sebulan penuh) |
| **Base Incentive** | `branch target × (FTE ÷ total FTE) × prorata` — hasil kerja bulan ini saja |
| **Carry-Forward** | Top-up dari shortfall bulan-bulan locked sebelumnya (§8.4) |
| **Total Incentive** | Base + Carry-Forward — inilah yang ditulis ke `incentive.target` |
| **Bonus** | Porsi pool vacant/kursi kosong yang jatuh ke orang ini |

Tiga kolom pertama dipisah supaya kelihatan **asal angkanya**: kalau target seseorang terasa terlalu tinggi, langsung terbaca apakah itu karena bagian bulan ini (Base) atau tunggakan bulan lalu (Carry-Forward). Setiap kolom punya subtotal di baris bawah.

> Kolom **Total Incentive** adalah computed (`base_amount + carry_forward_amount`), tidak disimpan sendiri — jadi tidak mungkin ketiganya jadi tidak konsisten.

### 8.2 Input manual

Menu **Operations → Targets** → New, isi per karyawan: Period, Employee, Target Type, Amount, Source. (Constraint: periode `approved`/`locked` tidak bisa diubah targetnya.)

### 8.3 Target Movement (audit trail)

`incentive.target.movement` mencatat setiap perpindahan target. Field: `reason` (resignation/new_hire/rf_revision/replacement/manual), `from_employee_id`, `to_employee_id`, `amount`, `target_type` (default `bonus`), `fte_share`, `date_effective`.

Tombol **Apply** pada movement akan mematerialisasi nilai ke baris `incentive.target` penerima.

### 8.4 Carry-Forward (rolling forecast per salesperson)

Saat periode **di-Lock**, sistem menghitung **shortfall** setiap salesperson dan menyimpannya ke baris target incentive-nya. Shortfall = `target − net sales` (hanya jika positif). Nilai ini lalu **dibagi rata ke sisa bulan skema** (`rule.date_to`) dan disimpan sebagai `carry_forward_amount`.

Field snapshot di `incentive.target`:

| Field | Arti |
|---|---|
| `shortfall_amount` | Target − net sales saat lock (0 jika tercapai) |
| `carry_forward_amount` | Shortfall ÷ sisa bulan skema (mis. 100.000 ÷ 5 = 20.000/bulan) |
| `months_remaining` | Jumlah bulan tersisa setelah periode ini, sampai `date_to` rule |

**Aturan penting — per employee, bukan per cabang.** Carry-forward **tidak** dijumlah per tim. Setiap salesperson yang tidak mencapai target pribadinya menanggung shortfall-nya sendiri, dan top-up hanya masuk ke bucket bulan-bulan depannya sendiri. Contoh: target Juli 2.000.000, 2 dari 3 orang capai target, 1 orang kurang 100.000 → hanya orang itu yang dapat tambahan 100.000 ÷ 5 = 20.000/bulan di Ags–Des.

Saat **Cascade** bulan berikutnya, wizard membaca `carry_forward_amount` milik masing-masing salesperson dari periode-periode locked sebelumnya (`_carry_forward`). Di tabel Preview angkanya muncul di kolom **Carry-Forward** — terpisah dari **Base Incentive**, lalu dijumlahkan jadi **Total Incentive**. Akumulasi antar bulan otomatis menumpuk (carry Juli + carry Ags, dst.) tanpa dobel-hitung basis.

### 8.5 Ideal Team Size — kursi kosong ikut menanggung target

**Masalah yang diselesaikan:** tim idealnya 5 orang tapi isinya cuma 4. Tanpa aturan ini, penyebut cascade hanya 4,5 FTE — artinya porsi kursi yang kosong **dibagikan ke empat orang yang ada**, sehingga target pribadi mereka naik diam-diam hanya karena rekannya belum diganti. Itu bukan kenaikan yang disepakati siapa pun.

**Aturannya:** kursi yang ideal-nya menuntut tapi belum ada record-nya sama sekali (`gap`) tetap dihitung di penyebut, dengan bobot **1,0 FTE** (setara Team). Porsinya tidak hilang — masuk ke **pool bonus** dan dibagikan ke orang yang bekerja sebulan penuh.

```
gap           = max(0, ideal_team_size − jumlah record di tim)
total FTE     = FTE aktif + FTE vacant + gap
porsi gap     = branch target × (gap / total FTE)   → masuk pool bonus
```

**Contoh:** Bandung-B2B ideal 5, isi 1 Lead (1,5) + 3 Team (1,0) = 4,5 FTE. Target cabang 5.500.000.

| | Tanpa ideal (penyebut 4,5) | Dengan ideal 5 (penyebut 5,5) |
|---|---|---|
| Target Lead | 1.833.333 | **1.500.000** |
| Target tiap Team | 1.222.222 | **1.000.000** |
| Masuk pool bonus | — | **1.000.000** |

Angka kolom kanan adalah target "seharusnya" seorang Team di tim penuh — tidak bergeser hanya karena satu kursi kosong.

**Jumlah record, bukan jumlah orang aktif.** Yang dihitung adalah banyaknya record di tim itu, termasuk record `Vacant Position`. Kalau kursi ke-5 sudah dibuat sebagai record vacant slot, `gap` = 0 — supaya kursi kosong yang sama tidak ditagih dua kali.

**Batasannya:** kursi kosong selalu dihitung 1,0 FTE. Kalau yang kosong justru posisi **Lead** (1,5), angkanya sedikit di bawah semestinya — untuk kasus itu buat record `Vacant Position` dengan designation Lead, jangan andalkan gap.

`ideal_team_size` = 0 → gap tidak dihitung, perilaku persis seperti sebelumnya.

### 8.6 Kapan sistem menghitung ulang saat ada yang resign?

**Jawaban singkat: tidak ada yang otomatis.** Mengisi `Resignation Date` di employee **tidak** menghitung apa-apa. Ini disengaja — target adalah komitmen yang sudah disepakati; kalau angkanya bisa bergeser sendiri saat HR mengedit data, orang kehilangan kendali atas kapan angka berubah, dan bisa menabrak proses tutup bulan yang sedang berjalan.

Angka baru muncul hanya saat ada orang menjalankan wizard. Ada **dua hitungan terpisah, dua tombol berbeda**:

| Yang dihitung | Dipicu oleh | Membaca prorata di |
|---|---|---|
| **Target** (`incentive.target`) | Wizard **Cascade** → Preview → Apply | `incentive_target_cascade.py` |
| **Payout** (`incentive.payout`) | Tombol **Calculate** di Branch Target / Period | `incentive_payout.py` |

Urutan kerja yang benar:

```
HR isi tanggal resign 20 Agu   → belum terjadi apa-apa
Re-run Cascade Agustus         → target berubah: 20/31 untuk yang resign,
                                  11/31 masuk pool bonus sisa tim
Calculate di Branch Target     → payout ikut angka baru
```

**Contoh:** tim ideal 4 (1 Lead + 3 Member), target 4.500.000, satu Member resign 20 Agustus (Agustus = 31 hari).

- Yang resign: 1.000.000 × 20/31 = **645.161**
- Sisa 11/31 = **354.839** → dibagi ke 3 orang yang bekerja sebulan penuh menurut FTE (1,5 + 1,0 + 1,0 = 3,5):
  - Lead: 354.839 × 1,5/3,5 = **152.074**
  - Tiap Member: 354.839 × 1,0/3,5 = **101.383**

Total cabang tetap 4.500.000 — prorata memindahkan uang antar bucket, tidak pernah menghilangkannya.

### 8.7 Banner "Population Changed" — pengaman lupa re-cascade

Risiko nyata dari §8.6 bukan angka yang berubah sendiri, melainkan sebaliknya: **tanggal resign sudah diisi, tapi tidak ada yang ingat menjalankan Cascade ulang**, lalu bulan ditutup memakai angka lama. Tanpa error, tanpa tanda — hanya salah.

Karena itu `incentive.branch.target` punya field computed `needs_recascade`:

- **Banner kuning** di atas form Branch Target, menyebut siapa penyebabnya.
- **Baris berwarna oranye** di list Branch Target, plus kolom **Re-cascade** — kelihatan dari daftar tanpa perlu membuka satu per satu saat tutup bulan.
- **Tombol Calculate diblokir** (`UserError`) selama bendera menyala — di tombol per cabang maupun `Calculate` di level Period, supaya tidak ada jalan pintas.

Dua kondisi yang ditangkap:

| Kondisi | Pesan |
|---|---|
| Hari kerja seseorang berubah (resign / tanggal join diedit) | *Working days changed for: \<nama\>* |
| Ada yang join tapi belum punya baris target | *No target yet for: \<nama\>* |

Cara mematikannya cuma satu: **jalankan Cascade ulang**. Setelah Apply, bendera padam sendiri.

Baris ber-status `locked` tidak pernah ditandai — memang tidak boleh diubah lagi.

> **Teknis:** tidak memakai timestamp. Cascade sudah menyimpan `proration_ratio` di tiap baris target, jadi cukup dibandingkan dengan hasil hitungan hari ini. Konsekuensinya field ini **tidak stored** — tidak bisa dipakai filter atau group-by di search view.
>
> **Batasan:** deteksi "orang baru" hanya melihat karyawan yang punya FTE individual. Hire posisi **Support** pada cascade scope Branch tidak terdeteksi, karena baris target tidak menyimpan scope mana yang dipakai saat cascade.

---

## 9. Siklus Operasional Bulanan

Urutan yang benar setiap bulan:

### Step 1 — Buka periode

Menu **Incentive Periods** → pilih/buat periode → klik **Open**.

- Wajib pilih **Rule Version** dulu; jika belum, `action_open` akan error.
- Status: Draft → **Open**.
- `Create Next Month` = membuat periode bulan berikutnya dengan rule yang sama.

### Step 2 — Isi target

Cascade (disarankan) atau manual — lihat [§8](#8-setup-target--cascade).

### Step 3 — Posting invoice

Tidak ada input manual untuk transaksi. Sistem **membaca invoice customer yang sudah `posted`** otomatis saat Calculate. Pastikan:

- Invoice `out_invoice`/`out_refund` berstatus `posted` dan **sudah lunas** — `incentive_full_payment_date` (Fully Paid On) berada di dalam rentang periode. Basis kas: yang menentukan masuk periode mana adalah **tanggal lunas**, bukan `invoice_date`.
- **Incentive Salesperson** (`incentive_employee_id`) sudah benar — default mengikuti `invoice_user_id`, bisa di-override.
- Diskon baris benar — field `Incentive Eligible` di baris invoice otomatis True/False sesuai cap 35%.

### Step 4 — Calculate

Klik **Calculate** pada periode. Yang terjadi otomatis:

1. Cek **Population Changed** — kalau ada Branch Target yang timnya berubah sejak cascade terakhir, Calculate **ditolak** (lihat §8.7). Jalankan Cascade ulang dulu.
2. `_generate_for_period` — membuat **transaction** (satu baris per baris invoice) untuk setiap invoice yang **lunas** di bulan ini (`incentive_full_payment_date` dalam rentang periode). `source_period_id` = bulan lunas (basis kas).
3. `_refresh_payment_stamp` — mengisi tanggal & periode pembayaran untuk invoice yang sudah lunas.
4. `_compute_for_period` → `_run` — menghitung **payout** per karyawan (SQ1→SQ2→SQ3).

Status: Open → **Calculated**.

> Calculate bisa dijalankan per cabang (tombol di form Branch Target) atau sekaligus se-periode. Blokir Population Changed berlaku di **kedua** jalur.

### Step 5 — Approve & Lock

1. **Approve** (harus status Calculated) → status **Approved**.
2. **Lock Period** (harus status Approved) → status **Locked**, semua payout `is_frozen=True`. Sekaligus sistem **menghitung shortfall + carry-forward** setiap salesperson (lihat §8.4). Setelah ini **tidak bisa dihitung ulang**. Koreksi harus lewat adjustment di periode berikutnya.

> **Reset to Open** bisa dipakai mundur dari Calculated/Approved (selama belum Locked).

### Step 6 — Iterasi bulan berikutnya

- Invoice **Juni** yang baru lunas di **Juli** tercatat sebagai transaksi **Juli** (basis kas — `source_period_id` = bulan lunas), sehingga ikut menentukan tier Juli.
- Target bulan berikutnya otomatis mendapat **carry-forward** dari shortfall bulan yang sudah di-Lock (lihat §8.4), lewat wizard Cascade.
- Tidak perlu langkah khusus — cukup Create Next Month → Cascade (Preview → Apply) → Calculate bulan berjalan.

---

## 10. Detail Rumus Kalkulasi

Mesin utama ada di `incentive.payout._run()`. Berikut detail per tahap.

### 10.1 Target

```
t_inc = incentive.target._get_amount(employee, period, 'incentive')
t_bon = incentive.target._get_amount(employee, period, 'bonus')
is_mixed = bool(t_bon)   # Scenario 2 jika t_bon > 0
```

### 10.2 SQ1 — Pilih tier dari net sales TANPA filter

```
gross   = Σ base_amount transaksi 'invoice' pada source period
returns = |Σ base_amount transaksi 'refund' pada source period|
net     = gross − returns
achievement = net / t_inc            (0 jika t_inc = 0)
tier    = rule._get_tier(achievement, is_mixed)
payout_rate = tier.payout_rate       (= allocation × base_rate)
```

- Tier dipilih dari **net sales seluruh invoice yang lunas di bulan itu** (termasuk diskon >35%). Ini dikonfirmasi dokumen: Sales B May net 86M → 86% → Tier 2, padahal eligible-nya cuma 70M (jika memakai eligible, jadinya Tier 0 — salah).
- Tier di-**freeze** ke baris transaksi via `_stamp_tier` (lihat 10.5).

### 10.3 SQ2 — Eligible base + split bucket

```
eligible_tx = transaksi invoice dengan is_discount_eligible = True
excluded    = Σ base_amount invoice dengan is_discount_eligible = False
eligible_base = Σ base_amount eligible_tx

jika mixed:
    elig_inc = min(eligible_base, t_inc)
    elig_bon = min(max(eligible_base − t_inc, 0), t_bon)
jika tidak:
    elig_inc = eligible_base
    elig_bon = 0
```

Split ke per baris (baris terbesar dulu, **satu baris boleh terbelah** di batas bucket):

```
remaining_inc = elig_inc ; remaining_bon = elig_bon
untuk tiap baris (urut base_amount desc):
    inc = min(base_amount, remaining_inc) ; remaining_inc -= inc
    bon = min(base_amount − inc, remaining_bon) ; remaining_bon -= bon
    baris.incentive_alloc = inc ; baris.bonus_alloc = bon
```

Ini menjawab bug yang pernah terjadi: sebuah baris 100 ribu yang melewati sisa bucket incentive **harus terbelah** — sebagian ke incentive, sisanya ke bonus — **bukan** dibuang ke excluded.

### 10.4 SQ3 — Hanya yang lunas

```
paid_current_tx = eligible_tx yang is_payment_eligible dan payment_period == periode ini
paid_current = Σ _net_alloc()[0]  (porsi incentive)
paid_bonus   = Σ _net_alloc()[1]  (porsi bonus)
```

`_net_alloc()` = (incentive, bonus) porsi net base setelah net-off retur, diproporsikan dari split gross.

> Dengan basis kas, semua transaksi tertangkap dari invoice yang sudah lunas, sehingga `payment_period` selalu sama dengan periode berjalan dan tidak ada baris "prior period" (`paid_prior = 0`).

### 10.5 Payout

```
payout_current = paid_current × rate                      (rate tier periode ini)
payout_bonus   = paid_bonus × rule.bonus_rate
total_payout   = payout_current + payout_bonus
```

### 10.6 Aturan "fully paid"

`_incentive_full_payment_date()` hanya mengembalikan tanggal jika `payment_state` adalah `paid` atau `in_payment` (residual nol). Status lain (`partial`, `not_paid`, `reversed`, `blocked`) **tidak eligible**. Tanggal lunas diambil dari tanggal rekonsiliasi terakhir (max `partial.max_date`), atau `invoice_date` jika tidak ada.

### 10.7 Branch stream (0,75%)

Stream branch dihitung terpisah di `_compute_branch_for_period`, untuk tiap cabang × business type yang punya `incentive.branch.target` pada periode itu:

```
net_branch  = Σ gross invoice − |Σ refund| (seluruh transaksi cabang pada periode)
achievement = net_branch / branch_target
tier        = rule._get_tier(achievement)          # branch TIDAK di-cap tier 5
rate        = tier.payout_rate                     (= allocation × base_rate 0,75%)
paid        = Σ _net_base() invoice eligible (diskon ≤35% & lunas)
pool        = paid × rate

bobot per orang = fte_branch × prorata
share          = bobot / Σ bobot
branch_payout  = pool × share
```

Hasilnya ditulis ke field `branch_*` di `incentive.payout` dan dijumlah ke `total_payout` bersama `payout_current` + `payout_bonus`. Stream ini juga memberi payout kepada **Support** (yang tidak punya target individual) karena bobotnya memakai `fte_branch`.

---

## 11. Contoh Perhitungan Lengkap

### 11.1 Full incentive — Sales B, Mei (Tier 2)

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Net sales | 86.000.000 |
| Eligible (diskon ≤35%) | 70.000.000 |
| Paid current | 60.000.000 |

1. SQ1: 86M / 100M = 86% → **Tier 2** (0,600%).
2. SQ2: eligible 70M.
3. SQ3: 60M lunas.
4. Payout = 60.000.000 × 0,600% = **360.000**.

### 11.2 Full incentive — Sales D, Juli (Tier 5)

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Net sales | 110.000.000 |
| Eligible | 105.000.000 |
| Paid current | 105.000.000 |

1. SQ1: 110M / 100M = 110% → **Tier 5** (0,7875%).
2. Payout = 105.000.000 × 0,7875% = **826.875**.

### 11.3 Basis kas — invoice terbit Juni, lunas Juli

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Net Juli (termasuk invoice terbit Juni yang lunas Juli) | 100.000.000 → Tier 4 (0,75%) |
| Eligible | 90.000.000 |
| Paid current | 80.000.000 (di dalamnya 10.000.000 berasal dari invoice terbit Juni) |

1. Invoice terbit Juni yang baru lunas di Juli **dipindah** ke transaksi Juli (basis kas), sehingga ikut menentukan tier dan payout Juli.
2. SQ1: 100M / 100M = 100% → Tier 4 (0,75%).
3. `Payout` = 80.000.000 × 0,75% = **600.000**.

### 11.4 Mixed — Sales B, Juli (bonus tercapai)

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Target bonus | 50.000.000 → **mixed** |
| Net sales | 145.000.000 |
| Eligible | 145.000.000 |
| Paid current | 145.000.000 (seluruh eligible lunas) |

1. SQ1: 145M / 100M = 145% → Tier 5 → **di-cap ke Tier 4** (mixed) = 0,75%.
2. SQ2 split: incentive = min(145M, 100M) = **100M**; bonus = min(145M − 100M, 50M) = **45M**.
3. `Payout Current` = 100M × 0,75% = **750.000**.
4. `Bonus` = 45M × 1% = **450.000**.
5. **Total = 1.200.000**

### 11.5 Mixed — Sales C, Agustus (bonus tercapai sebagian)

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Target bonus | 30.000.000 |
| Net sales | 105.000.000 |
| Paid current | 100.000.000 (incentive) + 5.000.000 (bonus) |

1. SQ1: 105M / 100M = 105% → Tier 4 (0,75%).
2. Split: incentive = 100M; bonus = 5M.
3. `Payout` = 100M × 0,75% = **750.000**; `Bonus` = 5M × 1% = **50.000**.
4. **Total = 800.000** ✓ (UAT TC15)

### 11.6 Mixed — Sales B, Agustus (bonus gagal)

| Item | Nilai |
|---|---|
| Target incentive | 100.000.000 |
| Target bonus | 30.000.000 |
| Net sales | 95.000.000 |

1. SQ1: 95M / 100M = 95% → Tier 3 (0,675%).
2. Split: incentive = min(90M, 100M) = 90M; bonus = 0 (belum melewati target incentive).
3. Payout = 65.000.000 (paid) × 0,675% = **438.750** ✓ (UAT TC16)

### 11.7 New hire prorata — Sales E/F, Agustus

| Item | Nilai |
|---|---|
| Target incentive (join 18 Aug, prorata 14/31) | 40.000.000 |
| Net sales | 30.000.000 |
| Paid current | 20.000.000 |

1. SQ1: 30M / 40M = 75% → **Tier 1** (0,3%).
2. Payout = 20.000.000 × 0,3% = **60.000** ✓ (UAT TC17)

### 11.8 Contoh diskon gate (per baris)

Invoice 1 dengan 3 baris:

| SKU | Diskon | Price | Total | Rate | Payout |
|---|---|---|---|---|---|
| A | 20% | 100.000 | 20.000 | 0,75% | 150 |
| B | 10% | 500.000 | 50.000 | 0,75% | 375 |
| C | 40% | 300.000 | 120.000 | — | 0 (>> tidak eligible) |

A & B eligible, C **tidak** (diskon 40% > 35%). Total eligible = 190.000.

---

## 12. Refund / Retur

### 12.1 Alur otomatis (credit note langsung dari invoice)

Credit note (`out_refund`) yang di-**post** langsung memotong insentif, tanpa perlu menunggu tombol Generate:

- Saat credit note di-post terhadap invoice yang punya transaksi insentif, otomatis tercipta transaction **refund** (nilai negatif) tertaut ke transaksi invoice via `reversal_of_id`, sehingga `_net_base()` mengurangi payout.
- Berlaku untuk credit note yang dibuat **langsung dari invoice** (tombol "Add Credit Note" Odoo) maupun lewat wizard (§12.2) — keduanya di-link ke invoice via `reversed_entry_id`.

### 12.2 Reversal manual (buat credit note, nominal bisa diatur)

Tombol **Create Credit Note / Refund** pada transaction membuka wizard `Refund Invoice` untuk membuat credit note sekaligus membatalkan transaksi insentifnya. Isi wizard:

| Field | Keterangan |
|---|---|
| Invoice | Invoice asal transaksi (read-only) |
| Invoice Line Amount | Nominal baris invoice (`base_amount`) — "dari berapa" |
| Refundable | Sisa yang masih bisa di-refund (setelah dikurangi refund sebelumnya) |
| Refund Amount | Nominal yang mau di-refund — **bisa diedit**, tapi tidak boleh melebihi Refundable |

Saat konfirmasi (tombol **Create Credit Note & Refund**):

1. Membuat **credit note** (`out_refund`) untuk invoice dengan nominal sesuai Refund Amount, di-**post**, dan di-link ke invoice via `reversed_entry_id`.
2. Membuat transaksi **refund** negatif (`base_amount = −Refund Amount`) tertaut ke transaksi asal via `reversal_of_id`, sehingga `_net_base()` memotong payout.
3. Jika Refund Amount menutup seluruh sisa (Refund Amount = Refundable), transaksi asal ditandai `reversed`.

**Validasi:** Refund Amount harus **> 0** dan **≤ Refundable** — tidak boleh melebihi nominal invoice yang sudah dibuat.

### 12.3 Net-off credit note sebagian

Credit note (`out_refund`) otomatis tertaut ke invoice yang di-reverse dan mengurangi basis paid invoice itu via `_net_base()`, sehingga payout dihitung dari jumlah yang benar-benar ditagih. Contoh: invoice 10jt lunas, credit note 3jt → basis payout 7jt.

**Batasan:**
- Credit note yang terbit **setelah** periode asal sudah di-`Lock` hanya mengurangi tier bulan berjalan (tidak net-off retroaktif) — pakai tombol **Create Credit Note / Refund** (§12.2).
- Credit note **langsung dari invoice** ("Add Credit Note") tetap di-link via `reversed_entry_id`, jadi ikut memotong payout — sama seperti wizard §12.2. Yang **tidak** ikut: credit note yang ditulis manual tanpa link ke invoice (misal `out_refund` journal entry yang `reversed_entry_id`-nya kosong).

### 12.4 Kebijakan refund

Mengikuti matriks **Refund Policies** (§6.4). Method `_match(stock_type, is_wip, payment_status, initiator)` mengembalikan policy pertama yang cocok.

---

## 13. Resignasi, Vacant, New Hire & Prorata

### 13.1 Resign / vacant

- Isi `Resignation Date` di employee (atau centang `Vacant Position`).
- **Tidak ada perhitungan yang jalan saat itu juga.** Angka baru muncul setelah Cascade dijalankan ulang — lihat §8.6 untuk urutan lengkapnya beserta contoh angka.
- Kalau lupa re-cascade, Branch Target menyalakan banner **Population Changed** dan memblokir Calculate (§8.7).
- Target-nya diredistribusikan ke tim aktif (cascade dengan `Redistribute Vacant Slots` = on, atau manual via Target Movements).
- Porsi redistribusi masuk ke **bucket bonus** penerima (`target_type='bonus'`).
- Kursi yang ditinggalkan dan belum diisi record apa pun tetap menanggung porsinya lewat `ideal_team_size` (§8.5) — target orang yang bertahan tidak ikut naik.
- Pengganti **tidak boleh** dientri mulai di tanggal yang sama dengan tanggal resign — simpan akan ditolak (§7.1).

### 13.2 New hire mid-month

- Isi `Effective Target Start` (misal 18 Aug).
- Prorata = hari aktif / hari dalam bulan (**hari masuk dihitung**). Contoh client: 18 Aug → 14/31 ≈ 0,4516.
- `_incentive_proration(period)` menghitung `active_days / total_days`.

### 13.3 Audit trail

Semua perpindahan tercatat di **Target Movements** (From/To, jumlah, alasan, tanggal efektif, FTE share).

---

## 14. Menu & Navigasi

| Menu | Model | Isi |
|---|---|---|
| Operations → My Incentive | `incentive.payout` (filter user) | Payout sendiri (self-service) |
| Operations → Incentive Periods | `incentive.period` | Periode + state machine |
| Operations → Targets | `incentive.target` | Target per karyawan (2 bucket) |
| Operations → Cascade Branch Target | `incentive.target.cascade` | Wizard cascade RF → individu |
| Operations → Target Movements | `incentive.target.movement` | Audit trail perpindahan target |
| Reporting → Payouts | `incentive.payout` | Semua payout |
| Reporting → Transactions | `incentive.transaction` | Transaksi per baris invoice |
| Configuration → Rules & Tiers | `incentive.rule` / `.tier` | Versi rule + tabel tier |
| Configuration → Sales Branches | `incentive.branch` | Cabang |
| Configuration → FTE Designations | `incentive.designation` | Bobot FTE |
| Configuration → Refund Policies | `incentive.refund.policy` | Matriks refund |

**Field penting di `incentive.branch.target`:** period_id, branch_id, business_type, amount (Branch Net Sales Target), carry_forward_amount, amount_total, state (draft/calculated/approved/locked), payout_total, **needs_recascade** (kolom "Re-cascade", baris jadi oranye kalau menyala), **recascade_reason**.

**Field penting di `incentive.branch`:** name, code, **ideal_team_size**, **effective_fte**, employee_ids, company_id.

**Kolom preview `incentive.target.cascade.line`:** employee_id, designation_id, fte, proration, **base_amount** (Base Incentive), **carry_forward_amount** (Carry-Forward), **incentive_amount** (Total Incentive — computed base + carry), bonus_amount.

**Field penting di `incentive.transaction` (list view):** Move, Employee, Branch, Product, Invoice Date, Source Period, Payment Period, Discount, is_discount_eligible, is_payment_eligible, bucket, incentive_alloc, bonus_alloc, base_amount, tier_id, tier_payout_rate, payout_amount, state.

**Field penting di `incentive.payout`:** target_incentive, target_bonus, target_total, is_mixed, gross_sales, sales_return, net_sales, achievement_pct, tier_id, payout_rate, eligible_incentive, eligible_bonus, excluded_discount, paid_current_month, paid_prior_month, paid_bonus, payout_current, payout_prior, payout_bonus, branch_target, branch_net_sales, branch_achievement_pct, branch_tier_id, branch_payout_rate, branch_pool, branch_fte, branch_fte_share, branch_payout, total_payout, is_eligible, is_frozen.

> **Catatan basis kas:** pada `incentive.transaction`, `Source Period` = `Payment Period` = bulan lunas. Field `paid_prior_month` dan `payout_prior` pada `incentive.payout` tetap ada untuk kompatibilitas tapi selalu 0.

---

## 15. FAQ / Troubleshooting

1. **Kenapa payout 0 padahal ada sales?**
   - (a) tier 0 (achievement < 75%),
   - (b) invoice belum lunas,
   - (c) diskon baris > 35%,
   - (d) karyawan belum punya baris Target di periode itu.

2. **Partial payment tidak eligible.** Hanya invoice berstatus `paid` yang masuk SQ3. `partial`, `in_payment` (residual 0 tapi belum final), `not_paid`, `reversed`, `blocked` dikecualikan.

3. **Credit note sebagian sudah di-net-off** (lihat §12.3). Batasan retroaktif & credit note manual.

4. **Jangan ubah angka setelah Lock.** Setelah Lock, semua payout frozen. Koreksi lewat adjustment periode berikutnya.

5. **Invoice harus punya `invoice_user_id`** (salesperson) agar tertaut ke karyawan yang tepat. Override field **Incentive Salesperson** jika komisi milik orang lain.

6. **Kenapa karyawan tidak muncul di "My Incentive"?** Kemungkinan tidak terhubung ke user Odoo (`Related User`), atau tidak punya baris target, atau designation Support (tidak ada individual target).

7. **Tombol Open error?** Belum memilih Rule Version.

8. **Tombol Calculate error?** Tiga sebab: periode masih Draft (harus Open dulu), sudah Locked, atau ada Branch Target ber-banner **Population Changed** — jalankan wizard Cascade ulang untuk cabang tersebut (§8.7).

9. **Kenapa tier bisa beda antara net dan eligible?** Memang begitu — tier memakai net (SQ1), bukan eligible (SQ2). Lihat §10.2.

10. **Simpan employee ditolak: "One seat cannot be held by two people on the same day"?** Tanggal join pengganti sama persis dengan tanggal resign orang yang digantikan. Majukan tanggal join minimal satu hari (§7.1).

11. **Banner "Population Changed" tidak mau padam?** Bendera hanya padam setelah wizard Cascade di-**Apply** (bukan sekadar Preview), untuk cabang & business type yang bersangkutan.

12. **Target semua orang naik padahal tidak ada kesepakatan?** Kemungkinan `Ideal Team Size` di cabang itu belum diisi, sehingga porsi kursi yang kosong terbagi ke tim yang tersisa (§8.5).

13. **Target seseorang di Preview kelihatan kebesaran?** Lihat kolom **Base Incentive** vs **Carry-Forward**. Kalau selisihnya ada di Carry-Forward, itu tunggakan shortfall bulan-bulan locked sebelumnya — bukan salah hitung (§8.4).

---

## 16. Batasan & Item Terbuka

1. ~~Stream Branch Incentive (0,75%) belum dihitung.~~ **✅ Sudah dihitung** — stream branch (0,75%) dihitung di `_compute_branch_for_period` dan masuk ke `total_payout` lewat field `branch_payout`. Target cabang memakai `incentive.branch.target`. Lihat §10.7.
2. **Konteks bonus di doc "derived from vacant position".** Bonus target secara operasional adalah angka per orang (sudah didukung), tapi derivasi otomatis dari vacant masih lewat cascade/manual, belum sepenuhnya otomatis dari posisi vacant.
3. **Batas Tier 0/1.** Tabel menulis Tier 0 = `≤75%` dan Tier 1 = `75%–84,9%` (overlap di 75%). Implementasi memakai `min ≤ ach < max` sehingga 75,0% → Tier 1 (sesuai contoh new-hire client). Konfirmasi ke client sebelum go-live.
4. **Net Sales di Business Use Case tidak tie-out.** Sales B May: 90M − 11M = 79M, tapi sheet menulis 86M. Sales B Aug: 80M − 0 = 80M, tapi sheet menulis 95M. Tidak mempengaruhi engine, tapi baseline UAT perlu dikoreksi.
5. **Bonus rate "tbd" di satu tabel, 1,00% di simulasi.** Dikonfigurasi 1,00%.
6. ~~Support mendapat branch incentive tapi tidak punya target individual — achievement apa yang menggerakkan tier branch-nya?~~ **✅ Terjawab** — tier branch digerakkan oleh pencapaian cabang (`branch_net_sales / branch_target`), bukan target individual; Support mendapat porsi pool branch dari bobot `fte_branch`.
7. **Refund auto-reversal penuh belum otomatis** — 3 kasus UAT refund masih "NEED UPDATE". Yang tersedia: matriks policy + reversal manual + net-off credit note otomatis.
8. **Kursi kosong selalu dihitung 1,0 FTE.** Kalau yang kosong posisi Lead (1,5), pakai record `Vacant Position` berdesignation Lead (§8.5).
9. **Deteksi Population Changed melewatkan hire posisi Support** pada cascade scope Branch — baris target tidak menyimpan scope yang dipakai saat cascade (§8.7).
10. **`needs_recascade` tidak stored** — tidak bisa dipakai sebagai filter atau group-by di search view; tersedia sebagai kolom list + banner form.

---

## 17. Checklist Go-Live

- [ ] `addons_path` memuat folder modul (lihat §4.2).
- [ ] Semua salesperson di-setup: branch, business type, designation, linked user.
- [ ] **`Ideal Team Size` diisi di setiap Sales Branch** — jumlah anggota satu tim seharusnya, lead termasuk (§8.5). Kosong/0 = kursi kosong tidak ditanggung.
- [ ] Cek `Effective FTE` di form branch cocok dengan populasi nyata sebelum cascade pertama.
- [ ] Rule dibuat/disesuaikan dengan tahun & tier yang benar (misal "2H 2026").
- [ ] Periode bulan pertama dibuat + Open.
- [ ] Target di-cascade (atau diinput) sebelum Calculate.
- [ ] Invoice di-posting, `incentive_employee_id` benar.
- [ ] Sebelum Calculate: pastikan tidak ada Branch Target ber-kolom **Re-cascade** menyala (§8.7).
- [ ] Calculate → review payout → Approve → Lock.
- [ ] Bulan berikutnya: Create Next Month → cascade (Preview → Apply, carry-forward otomatis masuk) → Calculate (otomatis ambil invoice yang lunas bulan ini).
- [ ] (Jika go-live penuh) Putuskan scope stream branch incentive 0,75% (lihat §16.1).

---

*Dokumen ini adalah panduan resmi modul `vif_sales_incentive`. Untuk detail teknis tingkat kode, lihat docstring di masing-masing file `models/*.py`.*
