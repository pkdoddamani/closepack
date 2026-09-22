# ClosePack sample pack — Harbor Bike Co (Aug 2026)

Demo client pack showing how ClosePack turns a simplified QBO-style P&L CSV into a branded monthly PDF for indie bookkeepers.

**Brand:** navy `#0B1F3A` + teal `#0D9488` · Firm placeholder: *Ledger & Co Bookkeeping*  
**Insight:** bookkeepers want *their* commentary, not canned AI — draft bullets are labeled editable.

## Files

| File | Role |
|------|------|
| `harbor-bike-co-pl-aug-2026.csv` | Aug 2026 P&L with Jul columns (primary input) |
| `harbor-bike-co-pl-jul-2026.csv` | Standalone July export (MoM fallback) |
| `build_pack.py` | CSV → PDF builder (reportlab) |
| `Harbor-Bike-Co-ClosePack-Aug-2026.pdf` | Generated pack |

## Regenerate

From this directory, using the repo venv (reportlab already installed):

```bash
cd /workspace/closepack/sample-pack
../.venv/bin/python build_pack.py
```

Or with explicit paths:

```bash
../.venv/bin/python build_pack.py \
  --csv harbor-bike-co-pl-aug-2026.csv \
  --prior-csv harbor-bike-co-pl-jul-2026.csv \
  --out Harbor-Bike-Co-ClosePack-Aug-2026.pdf
```

Requires: Python 3.10+ and `reportlab` (`pip install reportlab`).

## Pack sections

1. Cover — ClosePack + firm + client + period  
2. Snapshot — Revenue, Expenses, Net profit, Cash + MoM deltas  
3. What changed — draft commentary (bookkeeper-owned)  
4. Income detail  
5. Expense detail (COGS + OpEx)  
6. Questions for client call  
7. Disclaimer  

Waitlist: https://pkdoddamani.github.io/closepack/
