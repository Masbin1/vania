# Panduan Penggunaan — VIF Sales Incentive (Odoo 19)

Dokumen ini menjelaskan **cara set up dan menjalankan** modul `vif_sales_incentive`
langkah demi langkah, dari nol sampai payout terkunci. Dibuat agar Finance / Admin
tidak bingung urutannya.

> Modul ini mengimplementasikan skema di `Incentive Scheme -Masbin 1.xlsx` dan
> `Odoo Incentive Setup Scenario 1.xlsx` (scenario S01–S22).

---

## 1. Apa yang dilakukan modul ini

Modul menghitung **insentif penjualan** per salesperson per bulan, dengan aturan:

- Insentif hanya dibayar dari **invoice yang sudah lunas** (fully paid).
- Hanya baris invoice dengan **diskon ≤ 35%** yang eligible (per baris, bukan per invoice).
- Besaran insentif pakai **tier** berdasarkan % pencapaian vs target.
- **Invoice bulan lalu yang baru lunas bulan ini** tetap dibayar pakai **tier bulan
  asal invoice**, bukan tier bulan sekarang. ← ini aturan yang paling sering salah.

Hasil akhirnya adalah baris **Payout** per karyawan per periode yang bisa di-review,
disetujui, lalu dikunci (tidak bisa berubah lagi).

---

## 2. Instalasi

Modul butuh: `base`, `hr`, `sale_management`, `account`.

```bash
# letakkan folder vif_sales_incentive di addons path, lalu:
python3 odoo-bin -c odoo.conf -d <db> -i vif_sales_incentive
```

Setelah terpasang, muncul menu **Sales Incentive** di menu utama.

---

## 3. Hak akses (3 grup)

Set user ke salah satu grup berikut (menu Settings → Users & Companies → Groups):

| Grup | Isi | Bisa melihat |
|---|---|---|
| **Salesperson (own data)** | `group_incentive_user` | Hanya data diri sendiri |
| **Sales Manager (subordinates)** | `group_incentive_manager` | Diri + semua bawahan (N+1) |
| **Incentive Administrator** | `group_incentive_admin` | Semua + config + calculate + lock (Finance/C-level) |

> Admin harus di grup **Incentive Administrator** untuk bisa mengubah config,
> cascade target, calculate, approve, dan lock.

---

## 4. Konsep inti (WAJIB paham sebelum set up)

### 4.1 Tiga sekuens — basis hitungannya BEDA

| Sekuens | Basis | Kegunaan |
|---|---|---|
| **SQ1** | Net Sales **SEMUA** invoice bulan berjalan (termasuk yang belum bayar & diskon >35%), dikurangi retur | Hanya untuk **memilih tier** |
| **SQ2** | Hanya baris dengan diskon ≤ 35% | Basis **eligible** |
| **SQ3** | Dari SQ2, hanya yang **sudah lunas** | Jumlah yang benar-benar dikalikan rate |

```
Payout = SQ3 × (base rate 0.75% × allocation tier)
```

### 4.2 Tabel tier (sudah ter-seed)

| Tier | Achievement | Allocation | Payout rate |
|---|---|---|---|
| 0 | ≤ 75% | 0% | 0% (tidak eligible) |
| 1 | 75% – 84.9% | 40% | 0.300% |
| 2 | 85% – 89.9% | 80% | 0.600% |
| 3 | 90% – 99.9% | 90% | 0.675% |
| 4 | 100% – 109.9% | 100% | 0.750% |
| 5 | ≥ 110% | 105% | 0.7875% (hanya scenario full incentive) |

> Batas tier pakai `min ≤ achievement < max` (kecuali tier teratas terbuka).
> Jadi 75% tepat jatuh ke **Tier 1**, sesuai contoh new-hire client (30M/40M).

### 4.3 Dua bucket target (S03)

Setiap salesperson punya **dua bucket** target:

- **Incentive-Based** — target asli (dari rolling forecast).
- **Bonus-Based** — target dinamis hasil redistribusi posisi resign/vacant.

Kalau bonus bucket ada nilainya (> 0), sistem masuk **Scenario 2 (mixed)**:
bucket incentive di-cap di target incentive, sisanya limpah ke bucket bonus
(rate flat 1%), dan **Tier 5 tidak berlaku** untuk bucket incentive (di-cap ke Tier 4).

### 4.4 Status periode (state machine)

```
Draft → Open → Calculated → Approved → Locked
```

- `Draft` — periode baru dibuat.
- `Open` — sudah punya Rule Version, siap diisi target.
- `Calculated` — transaction + payout sudah di-generate.
- `Approved` — angka disetujui Finance.
- `Locked` — angka dibekukan permanen, tidak bisa dihitung ulang.

---

## 5. Data master yang sudah otomatis terisi (seed)

Saat install, modul otomatis membuat:

- **FTE Designations** (menu Configuration → FTE Designations):
  | Kode | Branch FTE | Individual FTE |
  |---|---|---|
  | Lead | 1.5 | 1.5 |
  | Team | 1.0 | 1.0 |
  | Support | 0.25 | 0.0 (tidak punya target individual) |
- **Sales Branches**: JKT (Jakarta), BDG (Bandung), SBY (Surabaya), BLI (Bali), MDN (Medan).
- **Rule & Tiers**: `Incentive Scheme 2H 2026` (1 Jul – 31 Des 2026, base 0.75%, bonus 1%, diskon cap 35%, tier 0–5).
- **Refund Policies**: matriks refund (lihat §6.9).

> Kalaupun sudah ter-seed, tetap cek nilainya sebelum go-live, dan sesuaikan
> tanggal `date_from` / `date_to` rule dengan periode berjalan.

---

## 6. Langkah setup lengkap (urutan yang benar)

### Step 1 — Setup karyawan (menu Employees)

Buka **Employees**, pilih karyawan sales, buka tab **Sales Incentive**:

| Field | Isi |
|---|---|
| **Sales Branch** | cabang (JKT/BDG/SBY/BLI/MDN) |
| **Business Type** | B2B atau B2C |
| **FTE Designation** | Lead / Team / Support |
| **Effective Target Start** | tanggal target mulai efektif (untuk prorata new hire mid-month) |
| **Resignation Date** | tanggal resign (kosongkan jika aktif) |
| **Vacant Position** | centang untuk slot kosong (placeholder headcount) |

Penting:

- Karyawan harus **terhubung ke user Odoo** (field `Related User` di employee).
  Ini dipakai dua hal: (a) invoice otomatis menunjuk salesperson, (b) visibility
  "My Incentive" lewat record rule.
- `Support` otomatis **tidak eligible individual incentive** (turunan dari
  designation-nya), tapi tetap eligible branch incentive.

### Step 2 — Buat Periode (menu Sales Incentive → Operations → Incentive Periods)

Klik **New**, isi:

- **Name**: misal `Jul 2026`.
- **Start Date / End Date**: rentang bulan (misal 1 Jul – 31 Jul).
- **Rule Version**: pilih `Incentive Scheme 2H 2026`.

Klik **Open** (wajib pilih Rule Version dulu, kalau tidak tombol Open akan error).
Status berubah dari Draft → **Open**.

> Cara cepat: dari periode yang sudah ada, klik **Create Next Month** untuk
> membuat periode bulan berikutnya dengan rule yang sama.

### Step 3 — Isi target (cascade atau manual)

Ada dua cara:

#### (a) Cascade otomatis dari target cabang (disarankan)

Menu **Sales Incentive → Operations → Cascade Branch Target**, isi:

- **Period**: periode yang tadi di-Open.
- **Branch**: cabang.
- **Business Type**: B2B / B2C.
- **Scope**: `Individual Target` (pakai kolom FTE individual; Support = 0).
- **Branch Net Sales Target**: angka rolling forecast cabang.
- **Redistribute Vacant Slots**: centang agar target slot kosong dibagikan ke
  tim aktif (masuk ke bucket bonus).

Klik **Preview** → cek baris per karyawan (FTE, proration, incentive, bonus),
lalu **Apply**. Sistem membuat baris **Target** per karyawan:

```
Individual target = branch target × (FTE sendiri / total FTE eligible) × prorata
```

#### (b) Input manual

Menu **Sales Incentive → Operations → Targets** → New, isi per karyawan:
- Period, Employee, Target Type (`Incentive-Based` atau `Bonus-Based`), Amount, Source.

### Step 4 — Posting invoice (transaksi capture)

Tidak perlu input manual. Sistem **membaca invoice customer yang sudah di-post**
secara otomatis saat Calculate. Yang perlu dipastikan:

- Invoice (out_invoice) di-`posted`, dengan `invoice_date` di dalam rentang periode.
- Field **Incentive Salesperson** di invoice sudah benar (default mengikuti
  salesperson invoice; bisa di-override manual).
- Baris invoice punya **diskon** yang benar — flag `Inc. Eligible` di baris invoice
  otomatis **True** jika diskon ≤ 35%, **False** jika > 35%.

### Step 5 — Calculate (generate transaction + payout)

Buka periode, klik **Calculate**.

Yang terjadi (otomatis):

1. **Transactions** dibuat: satu baris per baris invoice (dengan 3 cap periode:
   Source Period, Payment Period, Payout Period).
2. **Payment stamp** di-refresh: invoice yang sudah lunas diberi tanggal & periode pembayaran.
3. **Payout** dihitung per karyawan (SQ1→SQ2→SQ3).

Status berubah ke **Calculated**. Buka stat button **Payouts** / **Transactions**
untuk review.

> Kalau ada invoice/retur baru, klik **Calculate** lagi (atau **Recompute** di baris
> payout) untuk menghitung ulang — selama periode belum `Locked`.

### Step 6 — Approve & Lock (bekukan)

1. Setelah angka dicek Finance, klik **Approve** (status → Approved).
2. Klik **Lock Period** (ada konfirmasi). Status → **Locked**, semua payout
   ditandai `frozen`. Setelah ini **tidak bisa dihitung ulang**. Kalau ada
   koreksi, harus lewat adjustment di periode berikutnya.

> Tombol **Reset to Open** bisa dipakai untuk mundur dari Calculated/Approved
> ke Open (selama belum Locked).

### Step 7 — Iterasi bulan berikutnya (multi-iteration, S08/S09)

Ini bagian yang membedakan dengan sistem insentif biasa. Di bulan Juli misalnya:

- Invoice **Juni** yang baru lunas di **Juli** tetap tercatat sebagai transaksi
  periode Juni (source period = Juni), tapi **payment period = Juli**.
- Saat Anda `Calculate` periode **Juli**, sistem otomatis juga me-refresh status
  pembayaran transaksi Juni yang masih menggantung, lalu memasukkannya ke payout
  Juli sebagai **Payout Previous Month** — dengan **rate tier Juni (frozen)**.

Jadi **tidak perlu** melakukan apa pun khusus: cukup jalankan Calculate di periode
berjalan, dan invoice periode sebelumnya yang baru lunas ikut terhitung.

### Step 8 — Resignasi & new hire (S13/S14/S15)

- **Resign / vacant**: isi `Resignation Date` di employee (atau centang `Vacant
  Position`). Target-nya lalu diredistribusikan ke tim aktif (lewat cascade dengan
  `Redistribute Vacant Slots` = on, atau manual via **Target Movements**).
- **New hire mid-month**: isi `Effective Target Start` (misal 18 Aug). Target
  diprorata = hari aktif / hari dalam bulan (contoh client: 18 Aug → 14/31 ≈ 0.4516).
- Semua perpindahan tercatat di **Target Movements** (menu Operations → Target
  Movements) sebagai audit trail: From/To, jumlah, alasan, tanggal efektif.

### Step 9 — Refund / retur (S10/S11/S12)

- Credit note (`out_refund`) otomatis tertangkap sebagai transaction **refund**
  (nilai negatif) dan **mengurangi net sales periode berjalan** — meskipun
  invoice asalnya periode lalu.
- Untuk membatalkan transaksi insentif, gunakan tombol **Reversal** pada
  transaction (membuat transaksi negatif tertaut), **jangan** edit/hapus history.
- Kebijakan refund mengikuti **Refund Policies** (menu Configuration → Refund
  Policies), sudah ter-seed sesuai matriks "Kebijakan Refund (Business Risk)":

  | Stock | WIP | Payment | Initiator | Refund |
  |---|---|---|---|---|
  | Semua | Ya | Partial/Paid | Customer | No Refund |
  | Indent | Tidak | Partial/Paid | Customer | No Refund |
  | Available | Tidak | Partial/Paid | Customer | 99% |
  | Jasa Curtain | Tidak | Partial/Paid | Customer | 99% |
  | Indent/Available/Jasa | Ya | Partial/Paid | VIF | By Agreement |

---

## 7. Contoh perhitungan nyata (Sales C, Juli — mixed)

Data dari Business Use Case:

| Item | Nilai |
|---|---|
| Incentive target | 100.000.000 |
| Bonus target | 50.000.000 → **mixed** |
| Net Sales Juli | 100.000.000 |
| Eligible (diskon ≤35%) | 90.000.000 |
| Paid current month | 70.000.000 |
| Paid previous month (invoice Juni lunas di Juli) | 10.000.000 |

Hasil:

1. **SQ1**: 100M / 100M = 100% → **Tier 4** (rate 0.75%).
2. **SQ2**: eligible 90M. Karena mixed, incentive bucket = min(90M, 100M) = 90M,
   bonus bucket = 0 (belum melewati target incentive).
3. **SQ3**:
   - `Payout Current` = 70.000.000 × 0.75% = **525.000**
   - `Payout Previous` = 10.000.000 × **0.675% (Tier 3 Juni, frozen)** = **67.500**
   - `Bonus` = 0 × 1% = **0**
   - **Total = 592.500** ✓

Perhatikan: 10 juta invoice Juni itu **tidak** dibayar 0.75% (Tier 4 Juli),
melainkan 0.675% (Tier 3 Juni). Itulah kenapa `tier_payout_rate` di-*snapshot*
saat periode asal dihitung dan tidak pernah dihitung ulang.

---

## 8. Menu & objek referensi

| Menu | Model | Isi |
|---|---|---|
| Operations → My Incentive | `incentive.payout` (filter user) | Payout milik sendiri (self-service) |
| Operations → Incentive Periods | `incentive.period` | Periode + state machine |
| Operations → Targets | `incentive.target` | Target per karyawan (2 bucket) |
| Operations → Cascade Branch Target | `incentive.target.cascade` | Wizard cascade RF → individu |
| Operations → Target Movements | `incentive.target.movement` | Audit trail perpindahan target |
| Reporting → Payouts | `incentive.payout` | Semua payout |
| Reporting → Transactions | `incentive.transaction` | Semua transaksi per baris invoice |
| Configuration → Rules & Tiers | `incentive.rule` / `.tier` | Versi rule + tabel tier |
| Configuration → Sales Branches | `incentive.branch` | Cabang |
| Configuration → FTE Designations | `incentive.designation` | Bobot FTE |
| Configuration → Refund Policies | `incentive.refund.policy` | Matriks refund |

---

## 9. Catatan penting (FAQ)

1. **Kenapa payout bisa 0 padahal ada sales?** Kemungkinan: (a) tier 0 (achievement
   ≤ 75%), (b) invoice belum lunas, (c) diskon baris > 35%, atau (d) karyawan belum
   punya baris Target di periode itu.
2. **Partial payment tidak eligible.** Hanya invoice berstatus `paid` yang masuk
   SQ3 (S09). State `partial`, `in_payment` (residual 0 tapi payment belum final),
   dan `reversed` semuanya dikecualikan.
3. **Credit note sebagian (partial refund) — sudah di-net-off.** Credit note
   (`out_refund`) otomatis tertaut ke invoice yang di-reverse (lewat
   `reversed_entry_id`) dan mengurangi basis paid invoice itu, jadi payout
   dihitung dari jumlah yang benar-benar ditagih. Contoh: invoice 10jt lunas,
   credit note 3jt → payout basis 7jt. Batasannya: (a) credit note yang terbit
   *setelah* periode asal sudah di-`Lock` hanya mengurangi tier bulan berjalan
   (tidak bisa net-off retroaktif) — pakai **Reversal** manual untuk kasus ini;
   (b) credit note yang dibuat manual (bukan lewat tombol "Add Credit Note")
   tidak punya link, jadi hanya mengurangi tier.
3. **Jangan ubah angka setelah Lock.** Setelah periode di-Lock, semua payout frozen.
   Koreksi dilakukan lewat adjustment di periode berikutnya.
4. **Invoice harus punya `invoice_user_id`** (salesperson) supaya otomatis tertaut
   ke karyawan yang tepat. Kalau salah, override field **Incentive Salesperson**
   di invoice.
5. **Branch incentive stream (0.75% branch) belum diimplementasikan** di modul —
   masih scope question. Yang berjalan sekarang adalah stream individual.
6. **Angka Net Sales di business use case ada yang tidak tie-out** (Sales B May/Aug
   di sheet) — tidak mempengaruhi engine, tapi baseline UAT perlu dikoreksi.

---

## 10. Checklist go-live (urut)

- [ ] Semua salesperson di-setup: branch, business type, designation, linked user.
- [ ] Rule `Incentive Scheme 2H 2026` dicek tanggal & tier-nya.
- [ ] Periode bulan pertama dibuat + Open.
- [ ] Target di-cascade (atau diinput) sebelum Calculate.
- [ ] Invoice di-posting, salesperson benar.
- [ ] Calculate → review payout → Approve → Lock.
- [ ] Bulan berikutnya: Create Next Month → cascade → Calculate (otomatis ambil
      invoice prior yang baru lunas).