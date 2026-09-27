#!/usr/bin/env python3
"""
ClosePack sample builder — CSV → branded monthly client PDF.

Reads a simplified QBO-style P&L CSV (Account, current month, prior month)
and writes a navy/teal branded ClosePack PDF for indie bookkeepers.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand
NAVY = colors.HexColor("#0B1F3A")
TEAL = colors.HexColor("#0D9488")
TEAL_LIGHT = colors.HexColor("#CCFBF1")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
ROW_ALT = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#E2E8F0")
WHITE = colors.white
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#DC2626")

FIRM_NAME = "Ledger & Co Bookkeeping"
CLIENT_NAME = "Harbor Bike Co"
PERIOD_LABEL = "August 2026"
PRIOR_LABEL = "July 2026"


@dataclass
class LineItem:
    account: str
    current: float
    prior: float

    @property
    def delta(self) -> float:
        return self.current - self.prior

    @property
    def delta_pct(self) -> float | None:
        if self.prior == 0:
            return None if self.current == 0 else None
        return (self.current - self.prior) / abs(self.prior) * 100.0


def parse_money(raw: str) -> float:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    return float(s)


def load_pl(csv_path: Path) -> tuple[list[LineItem], dict[str, LineItem]]:
    """Load P&L CSV with columns Account, current, prior (or merge Jul CSV)."""
    rows: list[LineItem] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        # Prefer named month columns if present
        cur_col = next((c for c in fields if re.search(r"aug", c, re.I)), None)
        pri_col = next((c for c in fields if re.search(r"jul", c, re.I)), None)
        if not cur_col:
            # Account, amount only — prior filled later
            amount_cols = [c for c in fields if c.lower() != "account"]
            cur_col = amount_cols[0] if amount_cols else None
            pri_col = amount_cols[1] if len(amount_cols) > 1 else None

        for r in reader:
            acct = (r.get("Account") or r.get("account") or "").strip()
            if not acct or not cur_col:
                continue
            cur = parse_money(r.get(cur_col, "0"))
            pri = parse_money(r.get(pri_col, "0")) if pri_col else 0.0
            rows.append(LineItem(acct, cur, pri))

    by_name = {r.account: r for r in rows}
    return rows, by_name


def merge_prior(rows: list[LineItem], prior_path: Path | None) -> list[LineItem]:
    if not prior_path or not prior_path.exists():
        return rows
    prior_rows, prior_map = load_pl(prior_path)
    # If prior CSV is single-column, values landed in .current
    if prior_rows and all(r.prior == 0 for r in prior_rows):
        prior_map = {r.account: LineItem(r.account, 0.0, r.current) for r in prior_rows}
        # rebuild: use prior.current as prior amount
        prior_amounts = {r.account: r.current for r in prior_rows}
    else:
        prior_amounts = {r.account: r.current for r in prior_rows}

    merged = []
    for r in rows:
        if r.prior == 0 and r.account in prior_amounts:
            merged.append(LineItem(r.account, r.current, prior_amounts[r.account]))
        else:
            merged.append(r)
    return merged


def classify(rows: list[LineItem]) -> dict[str, list[LineItem]]:
    income, cogs, expenses, special = [], [], [], {}
    for r in rows:
        a = r.account
        low = a.lower()
        if low.startswith("net income") or low.startswith("net profit"):
            special["net"] = r
        elif low.startswith("cash"):
            special["cash"] = r
        elif low.startswith("income:") or low.startswith("revenue"):
            income.append(r)
        elif low.startswith("cogs:"):
            cogs.append(r)
        elif low.startswith("expenses:") or low.startswith("opex"):
            expenses.append(r)
        else:
            # heuristic
            if "income" in low or "revenue" in low or "sales" in low:
                income.append(r)
            elif "cogs" in low:
                cogs.append(r)
            else:
                expenses.append(r)
    return {"income": income, "cogs": cogs, "expenses": expenses, "special": special}


def money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def delta_str(item: LineItem) -> str:
    d = item.delta
    arrow = "▲" if d > 0 else ("▼" if d < 0 else "–")
    pct = item.delta_pct
    if pct is None:
        return f"{arrow} {money(d)}"
    return f"{arrow} {money(d)} ({pct:+.1f}%)"


def delta_color(delta: float, *, good_when_up: bool = True) -> colors.Color:
    if abs(delta) < 0.5:
        return MUTED
    up = delta > 0
    good = up if good_when_up else not up
    return GREEN if good else RED


def build_styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "cover_brand": ParagraphStyle(
            "cover_brand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "cover_tag": ParagraphStyle(
            "cover_tag",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            textColor=TEAL_LIGHT,
            alignment=TA_CENTER,
            spaceAfter=24,
        ),
        "cover_client": ParagraphStyle(
            "cover_client",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "cover_period": ParagraphStyle(
            "cover_period",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=14,
            textColor=colors.HexColor("#94A3B8"),
            alignment=TA_CENTER,
            spaceAfter=36,
        ),
        "cover_firm": ParagraphStyle(
            "cover_firm",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            textColor=TEAL,
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=SLATE,
            leading=14,
            spaceAfter=4,
        ),
        "draft_label": ParagraphStyle(
            "draft_label",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=TEAL,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=SLATE,
            leading=14,
            leftIndent=12,
            spaceAfter=5,
        ),
        "question": ParagraphStyle(
            "question",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=SLATE,
            leading=14,
            leftIndent=14,
            spaceAfter=6,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            leading=11,
            alignment=TA_LEFT,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "kpi_delta": ParagraphStyle(
            "kpi_delta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            alignment=TA_CENTER,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=SLATE,
            leading=11,
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=NAVY,
            leading=11,
        ),
        "cell_right": ParagraphStyle(
            "cell_right",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=SLATE,
            alignment=TA_RIGHT,
            leading=11,
        ),
        "th": ParagraphStyle(
            "th",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        "th_right": ParagraphStyle(
            "th_right",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=WHITE,
            alignment=TA_RIGHT,
        ),
    }
    return styles


def section_rule():
    return HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceBefore=2, spaceAfter=8)


def kpi_card(label: str, value: str, delta_text: str, dcolor: colors.Color, styles: dict, width: float):
    delta_style = ParagraphStyle(
        f"kpi_d_{label}",
        parent=styles["kpi_delta"],
        textColor=dcolor,
    )
    data = [
        [Paragraph(label.upper(), styles["kpi_label"])],
        [Paragraph(value, styles["kpi_value"])],
        [Paragraph(delta_text, delta_style)],
    ]
    t = Table(data, colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), ROW_ALT),
                ("BOX", (0, 0), (-1, -1), 1, BORDER),
                ("TOPPADDING", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
                ("TOPPADDING", (0, 1), (-1, 1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return t


def detail_table(title: str, items: list[LineItem], styles: dict, *, good_when_up: bool, content_width: float):
    header = [
        Paragraph("Account", styles["th"]),
        Paragraph(PERIOD_LABEL, styles["th_right"]),
        Paragraph(PRIOR_LABEL, styles["th_right"]),
        Paragraph("Change", styles["th_right"]),
    ]
    data = [header]
    total_cur = total_pri = 0.0
    for it in items:
        total_cur += it.current
        total_pri += it.prior
        dcol = delta_color(it.delta, good_when_up=good_when_up)
        dstyle = ParagraphStyle("_d", parent=styles["cell_right"], textColor=dcol)
        name = it.account.split(":", 1)[-1].strip() if ":" in it.account else it.account
        data.append(
            [
                Paragraph(name, styles["cell"]),
                Paragraph(money(it.current), styles["cell_right"]),
                Paragraph(money(it.prior), styles["cell_right"]),
                Paragraph(delta_str(it), dstyle),
            ]
        )

    # totals row
    tot_delta = total_cur - total_pri
    tot_pct = (tot_delta / abs(total_pri) * 100.0) if total_pri else 0.0
    arrow = "▲" if tot_delta > 0 else ("▼" if tot_delta < 0 else "–")
    dcol = delta_color(tot_delta, good_when_up=good_when_up)
    dstyle = ParagraphStyle("_td", parent=styles["cell_right"], textColor=dcol, fontName="Helvetica-Bold")
    data.append(
        [
            Paragraph("Total", styles["cell_bold"]),
            Paragraph(money(total_cur), ParagraphStyle("_tr", parent=styles["cell_right"], fontName="Helvetica-Bold", textColor=NAVY)),
            Paragraph(money(total_pri), ParagraphStyle("_tr2", parent=styles["cell_right"], fontName="Helvetica-Bold", textColor=NAVY)),
            Paragraph(f"{arrow} {money(tot_delta)} ({tot_pct:+.1f}%)", dstyle),
        ]
    )

    col_w = [content_width * 0.40, content_width * 0.20, content_width * 0.20, content_width * 0.20]
    t = Table(data, colWidths=col_w, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, -1), (-1, -1), TEAL_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0, NAVY),
        ("LINEABOVE", (0, -1), (-1, -1), 1, TEAL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 1, BORDER),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
        style_cmds.append(("LINEBELOW", (0, i), (-1, i), 0.5, BORDER))
    t.setStyle(TableStyle(style_cmds))
    return [Paragraph(title, styles["h2"]), t, Spacer(1, 8)]


def draft_commentary(parts: dict) -> list[str]:
    """Assemble editable-style draft bullets from MoM swings (bookkeeper owns final copy)."""
    income = parts["income"]
    expenses = parts["expenses"]
    cogs = parts["cogs"]
    special = parts["special"]

    bullets: list[str] = []

    # Revenue swing
    if income:
        top = max(income, key=lambda x: abs(x.delta))
        name = top.account.split(":")[-1].strip()
        if top.delta > 0:
            bullets.append(
                f"<b>{name}</b> rose {money(top.delta)} MoM — strong August traffic / new-bike demand. "
                f"(Draft note: confirm if promo or seasonal.)"
            )
        else:
            bullets.append(
                f"<b>{name}</b> softened by {money(abs(top.delta))} vs July. "
                f"(Draft note: ask client what shifted on the floor.)"
            )

    # Marketing spend
    mkt = next((e for e in expenses if "marketing" in e.account.lower()), None)
    if mkt and mkt.delta > 200:
        bullets.append(
            f"<b>Marketing & Ads</b> up {money(mkt.delta)} — likely tied to late-summer campaigns. "
            f"Worth reviewing ROAS before next month's budget."
        )

    # Tools / one-time
    tools = next((e for e in expenses if "tool" in e.account.lower()), None)
    if tools and tools.delta > 200:
        bullets.append(
            f"<b>Tools & Equipment</b> jumped {money(tools.delta)} (one-time shop investment?). "
            f"Flag as non-recurring so run-rate OpEx stays clear."
        )

    # Service income
    svc = next((i for i in income if "service" in i.account.lower()), None)
    if svc and svc.delta > 0:
        bullets.append(
            f"<b>Service & Repair</b> +{money(svc.delta)} — healthy attachment to bike sales; "
            f"labor utilization looks stronger than July."
        )

    # Cash
    cash = special.get("cash")
    if cash:
        direction = "improved" if cash.delta >= 0 else "dipped"
        bullets.append(
            f"<b>Cash on hand</b> {direction} to {money(cash.current)} "
            f"({delta_str(cash)}). Keep an eye on inventory restock timing into fall."
        )

    # Net
    net = special.get("net")
    if net and abs(net.delta) > 50:
        if len(bullets) >= 5:
            bullets = bullets[:4]
        bullets.append(
            f"<b>Net income</b> landed at {money(net.current)} "
            f"({delta_str(net)} vs July) — margin story is mostly mix + stepped-up marketing."
        )

    return bullets[:5]


def client_questions(parts: dict) -> list[str]:
    qs = [
        "Any large bike orders or wholesale deals expected in September that we should accrue?",
        "Was the Tools & Equipment spend a one-time purchase, or part of an ongoing upgrade plan?",
        "Should we keep Marketing at the August level through fall peak, or pull back?",
        "Any owner draws, loan payments, or inventory deposits not yet in the books?",
        "Confirm: are used-bike consignments fully recorded, or are some still on memo?",
    ]
    return qs


def build_pdf(rows: list[LineItem], out_path: Path) -> None:
    styles = build_styles()
    parts = classify(rows)
    income, cogs, expenses = parts["income"], parts["cogs"], parts["expenses"]
    special = parts["special"]

    total_rev = sum(i.current for i in income)
    prior_rev = sum(i.prior for i in income)
    total_cogs = sum(c.current for c in cogs)
    prior_cogs = sum(c.prior for c in cogs)
    total_opex = sum(e.current for e in expenses)
    prior_opex = sum(e.prior for e in expenses)
    total_exp = total_cogs + total_opex
    prior_exp = prior_cogs + prior_opex

    net = special.get("net") or LineItem(
        "Net Income",
        total_rev - total_exp,
        prior_rev - prior_exp,
    )
    cash = special.get("cash")

    page_w, page_h = letter
    margin = 0.7 * inch
    content_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.6 * inch,
        bottomMargin=0.65 * inch,
        title=f"ClosePack — {CLIENT_NAME} — {PERIOD_LABEL}",
        author=FIRM_NAME,
    )

    story = []

    # ── Cover ───────────────────────────────────────────────────────────────
    cover_data = [
        [Paragraph("ClosePack", styles["cover_brand"])],
        [Paragraph("Monthly client pack · assembled for bookkeepers", styles["cover_tag"])],
        [Spacer(1, 18)],
        [Paragraph(CLIENT_NAME, styles["cover_client"])],
        [Paragraph(PERIOD_LABEL, styles["cover_period"])],
        [Paragraph(f"Prepared by {FIRM_NAME}", styles["cover_firm"])],
        [Paragraph("Firm logo placeholder", ParagraphStyle(
            "logo_ph", parent=styles["cover_firm"], fontSize=8, textColor=MUTED, spaceBefore=8
        ))],
    ]
    cover = Table(cover_data, colWidths=[content_w])
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("TOPPADDING", (0, 0), (-1, 0), 48),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 40),
                ("LEFTPADDING", (0, 0), (-1, -1), 24),
                ("RIGHTPADDING", (0, 0), (-1, -1), 24),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    # teal accent bar under cover
    accent = Table([[""]], colWidths=[content_w], rowHeights=[6])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL)]))
    story.append(cover)
    story.append(accent)
    story.append(Spacer(1, 18))

    # ── Snapshot KPIs ────────────────────────────────────────────────────────
    story.append(Paragraph("Snapshot", styles["h1"]))
    story.append(section_rule())

    rev_item = LineItem("Revenue", total_rev, prior_rev)
    exp_item = LineItem("Expenses", total_exp, prior_exp)
    gap = 10
    card_w = (content_w - 3 * gap) / 4
    cards = [
        kpi_card("Revenue", money(total_rev), delta_str(rev_item), delta_color(rev_item.delta, good_when_up=True), styles, card_w),
        kpi_card("Expenses", money(total_exp), delta_str(exp_item), delta_color(exp_item.delta, good_when_up=False), styles, card_w),
        kpi_card("Net profit", money(net.current), delta_str(net), delta_color(net.delta, good_when_up=True), styles, card_w),
    ]
    if cash:
        cards.append(
            kpi_card("Cash", money(cash.current), delta_str(cash), delta_color(cash.delta, good_when_up=True), styles, card_w)
        )
    else:
        cards.append(kpi_card("Cash", "—", "not in export", MUTED, styles, card_w))

    kpi_row = Table(
        [[cards[0], "", cards[1], "", cards[2], "", cards[3]]],
        colWidths=[card_w, gap, card_w, gap, card_w, gap, card_w],
    )
    kpi_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(kpi_row)
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"MoM comparison vs {PRIOR_LABEL}. Figures assembled from client QBO/Xero-style P&amp;L export.",
            styles["draft_label"],
        )
    )

    # ── What changed ─────────────────────────────────────────────────────────
    story.append(Paragraph("What changed", styles["h1"]))
    story.append(section_rule())
    story.append(
        Paragraph(
            "✎ DRAFT COMMENTARY — editable by the bookkeeper. ClosePack drafts the assembly; "
            "you own the narrative. Replace or rewrite before sending to the client.",
            styles["draft_label"],
        )
    )
    for b in draft_commentary(parts):
        story.append(Paragraph(f"• {b}", styles["bullet"]))

    # ── Income detail ───────────────────────────────────────────────────────
    story.append(Paragraph("Income detail", styles["h1"]))
    story.append(section_rule())
    story.extend(detail_table("Revenue lines", income, styles, good_when_up=True, content_width=content_w))

    # ── Expense detail ───────────────────────────────────────────────────────
    story.append(Paragraph("Expense detail", styles["h1"]))
    story.append(section_rule())
    if cogs:
        story.extend(detail_table("Cost of goods sold", cogs, styles, good_when_up=False, content_width=content_w))
    if expenses:
        story.extend(detail_table("Operating expenses", expenses, styles, good_when_up=False, content_width=content_w))

    # ── Questions ────────────────────────────────────────────────────────────
    story.append(Paragraph("Questions for client call", styles["h1"]))
    story.append(section_rule())
    story.append(
        Paragraph(
            "Optional checklist — use on the monthly close call. Strike what doesn’t apply.",
            styles["draft_label"],
        )
    )
    for i, q in enumerate(client_questions(parts), 1):
        story.append(Paragraph(f"[ ]  {q}", styles["question"]))

    # ── Disclaimer ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(Paragraph("Disclaimer", styles["h1"]))
    story.append(section_rule())
    story.append(
        Paragraph(
            "This ClosePack was prepared from the client’s bookkeeping records (QBO/Xero-style CSV export) "
            f"by {FIRM_NAME} for discussion purposes. It is not an audit, review, or compilation under "
            "professional standards, and it does not constitute tax, legal, or investment advice. "
            "Draft commentary is a starting point for the bookkeeper’s own plain-English notes — "
            "edit before client delivery. Figures may be rounded. "
            "Waitlist &amp; product: https://pkdoddamani.github.io/closepack/",
            styles["disclaimer"],
        )
    )

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1.5)
        canvas.line(margin, 0.45 * inch, page_w - margin, 0.45 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 0.28 * inch, f"ClosePack · {CLIENT_NAME} · {PERIOD_LABEL}")
        canvas.drawRightString(page_w - margin, 0.28 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    def _first_page(canvas, doc_):
        _footer(canvas, doc_)

    doc.build(story, onFirstPage=_first_page, onLaterPages=_footer)


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build a ClosePack sample PDF from P&L CSV(s).")
    parser.add_argument(
        "--csv",
        type=Path,
        default=here / "harbor-bike-co-pl-aug-2026.csv",
        help="Primary P&L CSV (Account + Aug + optional Jul columns)",
    )
    parser.add_argument(
        "--prior-csv",
        type=Path,
        default=here / "harbor-bike-co-pl-jul-2026.csv",
        help="Optional prior-month CSV (used if primary lacks Jul column)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=here / "Harbor-Bike-Co-ClosePack-Aug-2026.pdf",
        help="Output PDF path",
    )
    args = parser.parse_args()

    rows, _ = load_pl(args.csv)
    # If prior column already present, merge is a no-op for those values;
    # still merge to fill any zeros from a single-month primary.
    rows = merge_prior(rows, args.prior_csv if args.prior_csv.exists() else None)

    if not rows:
        raise SystemExit(f"No rows loaded from {args.csv}")

    build_pdf(rows, args.out)
    size = args.out.stat().st_size
    print(f"Wrote {args.out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
