# ClosePack sample pack — Harbor Bike Co (Aug 2026)

Demo client pack showing how ClosePack turns a simplified QBO-style P&L CSV into a **bookkeeper-branded** monthly PDF. The firm (Ledger & Co) owns the header and commentary; ClosePack appears only in the footer as the assembly aid.

**Brand:** navy `#0B1F3A` + teal `#0D9488` · Firm placeholder: *Ledger & Co Bookkeeping*  
**Insight:** bookkeepers want *their* commentary, not canned AI — caption notes commentary is editable. ClosePack assembles KPIs, trends, and detail; the bookkeeper owns the narrative.

## Files

| File | Role |
|------|------|
| `harbor-bike-co-pl-aug-2026.csv` | Aug 2026 P&L with Jul columns (primary input) |
| `harbor-bike-co-pl-jul-2026.csv` | Standalone July export (MoM fallback) |
| `build_pack.py` | CSV → PDF builder (reportlab) |
| `Harbor-Bike-Co-ClosePack-Aug-2026.pdf` | Generated pack (linked from closepack.dev) |

Live PDF: https://closepack.dev/sample-pack/Harbor-Bike-Co-ClosePack-Aug-2026.pdf

## Regenerate

Requires Python 3.10+ and reportlab:

```bash
python3 -m venv .venv && .venv/bin/pip install reportlab
cd sample-pack
.venv/bin/python build_pack.py
```

Defaults read `harbor-bike-co-pl-aug-2026.csv` (with Jul column) and write `Harbor-Bike-Co-ClosePack-Aug-2026.pdf`. Explicit paths:

```bash
.venv/bin/python build_pack.py \
  --csv harbor-bike-co-pl-aug-2026.csv \
  --prior-csv harbor-bike-co-pl-jul-2026.csv \
  --out Harbor-Bike-Co-ClosePack-Aug-2026.pdf
```

`--prior-csv` is used when the primary CSV lacks a prior-month column. The builder asserts Harbor Bike totals (rev +$5,480, costs +$4,475, NI +$1,005) before writing.

## Pack sections

1. Header — Ledger & Co logo mark + firm name (big); client + period secondary  
2. Snapshot — Revenue, Total costs, Net profit, Cash + MoM deltas (expense-up in red)  
3. 6-month trend — Revenue / costs / net Mar–Aug (Mar–Jun demo synthetic; Jul–Aug from CSV)  
4. What changed — bookkeeper-owned commentary that reconciles full MoM moves  
5. Revenue detail — income lines with current, prior, $ change, % change  
6. Cost & expense detail — COGS + OpEx with same columns  
7. Questions for client call — clean bullets  
8. Disclaimer + ClosePack footer only  

Site: https://closepack.dev/
