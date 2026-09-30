#!/usr/bin/env python3
"""
ClosePack sample builder — CSV → branded monthly client PDF.

Assembles a bookkeeper-branded pack (Ledger & Co) from a simplified
QBO-style P&L CSV. ClosePack is the assembly aid; the bookkeeper owns
branding and commentary. ClosePack appears only in the PDF footer.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Group, Circle
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand palette
NAVY = colors.HexColor("#0B1F3A")
TEAL = colors.HexColor("#0D9488")
TEAL_LIGHT = colors.HexColor("#CCFBF1")
TEAL_MID = colors.HexColor("#5EEAD4")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
ROW_ALT = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#E2E8F0")
WHITE = colors.white
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#DC2626")
AMBER = colors.HexColor("#D97706")
LIGHT_RED = colors.HexColor("#FEF2F2")
LIGHT_GREEN = colors.HexColor("#ECFDF5")
CHART_REV = colors.HexColor("#0D9488")
CHART_EXP = colors.HexColor("#F87171")
CHART_NET = colors.HexColor("#0B1F3A")

FIRM_NAME = "Ledger & Co Bookkeeping"
FIRM_INITIALS = "L&C"
CLIENT_NAME = "Harbor Bike Co"
PERIOD_LABEL = "August 2026"
PRIOR_LABEL = "July 2026"

# ---------------------------------------------------------------------------
# Demo synthetic 6-month history (Mar–Jun). Only Jul/Aug come from CSV.
# Invented to trend smoothly into the real Jul/Aug totals — document clearly.
# ---------------------------------------------------------------------------
# Demo synthetic history (Mar–Jun 2026) — not from client books.
# Designed to ramp into real Jul (rev 75,340 / costs 59,125 / net 16,215)
# and Aug (rev 80,820 / costs 63,600 / net 17,220).
SYNTHETIC_TREND = [
    # (label, revenue, total_costs, net)
    ("Mar", 68_400, 55_200, 13_200),
    ("Apr", 70_100, 56_050, 14_050),
    ("May", 72_250, 57_400, 14_850),
    ("Jun", 73_800, 58_200, 15_600),
    # Jul/Aug filled at runtime from CSV
]


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
            return None
        return (self.current - self.prior) / abs(self.prior) * 100.0


def parse_money(raw: str) -> float:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    return float(s)


def load_pl(csv_path: Path) -> tuple[list[LineItem], dict[str, LineItem]]:
    rows: list[LineItem] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        cur_col = next((c for c in fields if re.search(r"aug", c, re.I)), None)
        pri_col = next((c for c in fields if re.search(r"jul", c, re.I)), None)
        if not cur_col:
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

    return rows, {r.account: r for r in rows}


def merge_prior(rows: list[LineItem], prior_path: Path | None) -> list[LineItem]:
    if not prior_path or not prior_path.exists():
        return rows
    prior_rows, _ = load_pl(prior_path)
    if prior_rows and all(r.prior == 0 for r in prior_rows):
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


def classify(rows: list[LineItem]) -> dict:
    income, cogs, expenses = [], [], []
    special: dict = {}
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


def money_signed(v: float) -> str:
    if abs(v) < 0.5:
        return "$0"
    sign = "+" if v > 0 else "-"
    return f"{sign}${abs(v):,.0f}"


def pct_str(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:+.1f}%"


def delta_color(delta: float, *, good_when_up: bool = True) -> colors.Color:
    """Color semantics: revenue/profit up=green; expense/cost up=red (never green)."""
    if abs(delta) < 0.5:
        return MUTED
    up = delta > 0
    good = up if good_when_up else not up
    return GREEN if good else RED


def build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "firm": ParagraphStyle(
            "firm",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=WHITE,
            leading=22,
        ),
        "client": ParagraphStyle(
            "client",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=WHITE,
            leading=16,
        ),
        "period": ParagraphStyle(
            "period",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            textColor=TEAL_MID,
            leading=14,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=4,
            leading=15,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=3,
            leading=12,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=SLATE,
            leading=12,
            spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            textColor=MUTED,
            spaceAfter=4,
            leading=10,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=SLATE,
            leading=12,
            leftIndent=10,
            spaceAfter=3,
        ),
        "question": ParagraphStyle(
            "question",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=SLATE,
            leading=12,
            leftIndent=4,
            spaceAfter=3,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            textColor=MUTED,
            leading=9,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            leading=9,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=NAVY,
            alignment=TA_CENTER,
            leading=17,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=SLATE,
            leading=10,
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=NAVY,
            leading=10,
        ),
        "cell_right": ParagraphStyle(
            "cell_right",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=SLATE,
            alignment=TA_RIGHT,
            leading=10,
        ),
        "th": ParagraphStyle(
            "th",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            textColor=WHITE,
            alignment=TA_LEFT,
            leading=9,
        ),
        "th_right": ParagraphStyle(
            "th_right",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            textColor=WHITE,
            alignment=TA_RIGHT,
            leading=9,
        ),
    }


class LogoMark(Flowable):
    """Simple initials block for Ledger & Co."""

    def __init__(self, size: float = 36):
        super().__init__()
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        c = self.canv
        s = self.size
        c.setFillColor(TEAL)
        c.roundRect(0, 0, s, s, 5, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", s * 0.32)
        text = FIRM_INITIALS
        tw = c.stringWidth(text, "Helvetica-Bold", s * 0.32)
        c.drawString((s - tw) / 2, s * 0.36, text)


def section_rule():
    return HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceBefore=0, spaceAfter=5)


def make_header(styles: dict, content_w: float) -> list:
    """Bookkeeper branding as the BIG header — ClosePack is NOT here."""
    logo = LogoMark(40)
    text_block = Table(
        [
            [Paragraph(FIRM_NAME, styles["firm"])],
            [Paragraph(f"{CLIENT_NAME}  ·  Monthly close pack", styles["client"])],
            [Paragraph(PERIOD_LABEL, styles["period"])],
        ],
        colWidths=[content_w - 56],
    )
    text_block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    inner = Table([[logo, text_block]], colWidths=[48, content_w - 56])
    inner.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("LEFTPADDING", (1, 0), (1, 0), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    wrap = Table([[inner]], colWidths=[content_w])
    wrap.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    accent = Table([[""]], colWidths=[content_w], rowHeights=[4])
    accent.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL)]))
    return [wrap, accent, Spacer(1, 8)]


def kpi_card(label: str, value: str, delta_text: str, dcolor: colors.Color, styles: dict, width: float):
    delta_style = ParagraphStyle(
        f"kpi_d_{label}",
        parent=styles["kpi_label"],
        textColor=dcolor,
        fontName="Helvetica-Bold",
        fontSize=8,
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
                ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return t


def detail_table(
    title: str,
    items: list[LineItem],
    styles: dict,
    *,
    good_when_up: bool,
    content_width: float,
    show_pct: bool = True,
):
    """Full detail: Account | Current | Prior | $ Change | % Change."""
    if show_pct:
        header = [
            Paragraph("Account", styles["th"]),
            Paragraph(PERIOD_LABEL.split()[0][:3], styles["th_right"]),  # Aug
            Paragraph(PRIOR_LABEL.split()[0][:3], styles["th_right"]),  # Jul
            Paragraph("$ Change", styles["th_right"]),
            Paragraph("% Chg", styles["th_right"]),
        ]
    else:
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
        dstyle = ParagraphStyle("_d", parent=styles["cell_right"], textColor=dcol, fontName="Helvetica-Bold")
        name = it.account.split(":", 1)[-1].strip() if ":" in it.account else it.account
        if show_pct:
            data.append(
                [
                    Paragraph(name, styles["cell"]),
                    Paragraph(money(it.current), styles["cell_right"]),
                    Paragraph(money(it.prior), styles["cell_right"]),
                    Paragraph(money_signed(it.delta), dstyle),
                    Paragraph(pct_str(it.delta_pct), dstyle),
                ]
            )
        else:
            data.append(
                [
                    Paragraph(name, styles["cell"]),
                    Paragraph(money(it.current), styles["cell_right"]),
                    Paragraph(money(it.prior), styles["cell_right"]),
                    Paragraph(f"{money_signed(it.delta)} ({pct_str(it.delta_pct)})", dstyle),
                ]
            )

    tot_delta = total_cur - total_pri
    tot_pct = (tot_delta / abs(total_pri) * 100.0) if total_pri else 0.0
    dcol = delta_color(tot_delta, good_when_up=good_when_up)
    dstyle = ParagraphStyle("_td", parent=styles["cell_right"], textColor=dcol, fontName="Helvetica-Bold")
    bold_r = ParagraphStyle("_tr", parent=styles["cell_right"], fontName="Helvetica-Bold", textColor=NAVY)
    if show_pct:
        data.append(
            [
                Paragraph("Total", styles["cell_bold"]),
                Paragraph(money(total_cur), bold_r),
                Paragraph(money(total_pri), bold_r),
                Paragraph(money_signed(tot_delta), dstyle),
                Paragraph(f"{tot_pct:+.1f}%", dstyle),
            ]
        )
        col_w = [
            content_width * 0.34,
            content_width * 0.16,
            content_width * 0.16,
            content_width * 0.18,
            content_width * 0.16,
        ]
    else:
        data.append(
            [
                Paragraph("Total", styles["cell_bold"]),
                Paragraph(money(total_cur), bold_r),
                Paragraph(money(total_pri), bold_r),
                Paragraph(f"{money_signed(tot_delta)} ({tot_pct:+.1f}%)", dstyle),
            ]
        )
        col_w = [content_width * 0.40, content_width * 0.20, content_width * 0.20, content_width * 0.20]

    t = Table(data, colWidths=col_w, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, -1), (-1, -1), TEAL_LIGHT),
        ("LINEABOVE", (0, -1), (-1, -1), 1, TEAL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
        style_cmds.append(("LINEBELOW", (0, i), (-1, i), 0.4, BORDER))
    t.setStyle(TableStyle(style_cmds))
    return [Paragraph(title, styles["h2"]), t, Spacer(1, 4)]


def trend_drawing(rev_aug: float, cost_aug: float, net_aug: float,
                  rev_jul: float, cost_jul: float, net_jul: float,
                  width: float, height: float = 155) -> Drawing:
    """Grouped bar chart: Revenue / Total costs / Net for Mar–Aug 2026.

    Mar–Jun are demo synthetic history (see SYNTHETIC_TREND); Jul–Aug from CSV.
    """
    months = []
    rev, costs, nets = [], [], []
    for label, r, c, n in SYNTHETIC_TREND:
        months.append(label)
        rev.append(r / 1000.0)  # show in $k
        costs.append(c / 1000.0)
        nets.append(n / 1000.0)
    months.extend(["Jul", "Aug"])
    rev.extend([rev_jul / 1000.0, rev_aug / 1000.0])
    costs.extend([cost_jul / 1000.0, cost_aug / 1000.0])
    nets.extend([net_jul / 1000.0, net_aug / 1000.0])

    d = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 28
    chart.height = height - 55
    chart.width = width - 50
    chart.data = [rev, costs, nets]
    chart.categoryAxis.categoryNames = months
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = MUTED
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 90
    chart.valueAxis.valueStep = 15
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.labels.boxAnchor = "e"
    chart.groupSpacing = 8
    chart.barSpacing = 1
    chart.bars[0].fillColor = CHART_REV
    chart.bars[1].fillColor = CHART_EXP
    chart.bars[2].fillColor = CHART_NET
    chart.bars[0].strokeColor = None
    chart.bars[1].strokeColor = None
    chart.bars[2].strokeColor = None
    chart.categoryAxis.strokeColor = BORDER
    chart.valueAxis.strokeColor = BORDER
    chart.valueAxis.gridStrokeColor = colors.HexColor("#F1F5F9")
    chart.valueAxis.gridStrokeWidth = 0.5
    d.add(chart)

    # Legend
    legend = Legend()
    legend.alignment = "right"
    legend.x = 50
    legend.y = height - 14
    legend.dx = 8
    legend.dy = 8
    legend.fontName = "Helvetica"
    legend.fontSize = 7
    legend.fillColor = SLATE
    legend.strokeColor = None
    legend.columnMaximum = 1
    legend.boxAnchor = "w"
    legend.deltax = 90
    legend.colorNamePairs = [
        (CHART_REV, "Revenue ($k)"),
        (CHART_EXP, "Total costs ($k)"),
        (CHART_NET, "Net profit ($k)"),
    ]
    d.add(legend)

    # Axis note
    d.add(String(40, 8, "$ thousands  ·  Mar–Jun demo synthetic history; Jul–Aug from P&L",
                 fontName="Helvetica-Oblique", fontSize=6.5, fillColor=MUTED))
    return d


def build_commentary(parts: dict, totals: dict) -> list[str]:
    """Commentary that reconciles FULL MoM moves from the CSV arithmetic.

    Revenue Δ = +5,480 must be explained by income-line moves.
    Total costs Δ = +4,475 = COGS +2,630 + OpEx +1,845 must be explained
    (COGS bikes biggest, then marketing, tools, payroll — not leave ~3.2k unexplained).
    """
    income = parts["income"]
    cogs = parts["cogs"]
    expenses = parts["expenses"]
    special = parts["special"]

    by = {i.account.split(":")[-1].strip().lower(): i for i in income}
    cogs_by = {c.account.split(":")[-1].strip().lower(): c for c in cogs}
    exp_by = {e.account.split(":")[-1].strip().lower(): e for e in expenses}

    def find(mapping, *keys):
        for k, v in mapping.items():
            for key in keys:
                if key in k:
                    return v
        return None

    new = find(by, "new")
    used = find(by, "used")
    svc = find(by, "service")
    parts_rev = find(by, "parts")
    rentals = find(by, "rental")
    bikes_cogs = find(cogs_by, "bike")
    parts_cogs = find(cogs_by, "parts")
    supplies = find(cogs_by, "supplies", "shop")
    mkt = find(exp_by, "marketing")
    tools = find(exp_by, "tool")
    wages = find(exp_by, "wages")
    tax = find(exp_by, "tax", "benefits")
    fees = find(exp_by, "merchant", "card")
    office = find(exp_by, "office")
    util = find(exp_by, "utilit")

    rev_d = totals["rev_d"]
    cogs_d = totals["cogs_d"]
    opex_d = totals["opex_d"]
    cost_d = totals["cost_d"]
    net_d = totals["net_d"]

    bullets: list[str] = []

    # Revenue reconciliation → must sum to +5480
    rev_bits = []
    if new:
        rev_bits.append(f"New bikes {money_signed(new.delta)}")
    if used:
        rev_bits.append(f"Used {money_signed(used.delta)}")
    if svc:
        rev_bits.append(f"Service {money_signed(svc.delta)}")
    if parts_rev:
        rev_bits.append(f"Parts {money_signed(parts_rev.delta)}")
    if rentals:
        rev_bits.append(f"Rentals {money_signed(rentals.delta)}")
    bullets.append(
        f"<b>Revenue {money_signed(rev_d)}</b> MoM "
        f"({money(totals['rev_pri'])} → {money(totals['rev_cur'])}). "
        f"Drivers: {'; '.join(rev_bits)} "
        f"= <b>{money_signed(rev_d)}</b>. Strong new-bike and service demand offset softer used/rentals."
    )

    # COGS — biggest cost move
    cogs_bits = []
    if bikes_cogs:
        cogs_bits.append(f"Bikes {money_signed(bikes_cogs.delta)}")
    if parts_cogs:
        cogs_bits.append(f"Parts {money_signed(parts_cogs.delta)}")
    if supplies:
        cogs_bits.append(f"Shop supplies {money_signed(supplies.delta)}")
    bullets.append(
        f"<b>COGS {money_signed(cogs_d)}</b> "
        f"({money(totals['cogs_pri'])} → {money(totals['cogs_cur'])}) — largest cost move. "
        f"{'; '.join(cogs_bits)}. Bike COGS tracks the new-bike sales lift."
    )

    # OpEx movers that explain the remaining ~1845
    opex_bits = []
    if mkt:
        opex_bits.append(f"Marketing {money_signed(mkt.delta)}")
    if tools:
        opex_bits.append(f"Tools {money_signed(tools.delta)}")
    if wages:
        opex_bits.append(f"Payroll wages {money_signed(wages.delta)}")
    if tax:
        opex_bits.append(f"Payroll tax {money_signed(tax.delta)}")
    if fees:
        opex_bits.append(f"Merchant fees {money_signed(fees.delta)}")
    if office:
        opex_bits.append(f"Office {money_signed(office.delta)}")
    if util:
        opex_bits.append(f"Utilities {money_signed(util.delta)}")
    bullets.append(
        f"<b>OpEx {money_signed(opex_d)}</b> "
        f"({money(totals['opex_pri'])} → {money(totals['opex_cur'])}). "
        f"Movers: {'; '.join(opex_bits)}. "
        f"Rent, insurance, software, and professional fees were flat. "
        f"Tools looks one-time; marketing stepped up for late summer."
    )

    # Total cost bridge
    bullets.append(
        f"<b>Total costs {money_signed(cost_d)}</b> = COGS {money_signed(cogs_d)} + OpEx {money_signed(opex_d)}. "
        f"Against revenue {money_signed(rev_d)}, <b>net income {money_signed(net_d)}</b> "
        f"({money(totals['net_pri'])} → {money(totals['net_cur'])})."
    )

    cash = special.get("cash")
    if cash:
        bullets.append(
            f"<b>Cash on hand</b> {money(cash.current)} ({money_signed(cash.delta)} MoM). "
            f"Watch inventory restock timing into fall."
        )

    return bullets


def client_questions() -> list[str]:
    return [
        "Any large bike orders or wholesale deals expected in September that we should accrue?",
        "Was the Tools & Equipment spend a one-time purchase, or part of an ongoing upgrade plan?",
        "Should we keep Marketing at the August level through fall peak, or pull back?",
        "Any owner draws, loan payments, or inventory deposits not yet in the books?",
        "Confirm: are used-bike consignments fully recorded, or are some still on memo?",
    ]


def assert_totals(parts: dict) -> dict:
    """Sanity-check arithmetic against the known Harbor Bike CSV totals."""
    income, cogs, expenses = parts["income"], parts["cogs"], parts["expenses"]
    special = parts["special"]

    rev_cur = sum(i.current for i in income)
    rev_pri = sum(i.prior for i in income)
    cogs_cur = sum(c.current for c in cogs)
    cogs_pri = sum(c.prior for c in cogs)
    opex_cur = sum(e.current for e in expenses)
    opex_pri = sum(e.prior for e in expenses)
    cost_cur = cogs_cur + opex_cur
    cost_pri = cogs_pri + opex_pri
    net = special.get("net")
    net_cur = net.current if net else rev_cur - cost_cur
    net_pri = net.prior if net else rev_pri - cost_pri

    # Spec-mandated asserts
    assert abs(rev_cur - 80820) < 0.5, f"Aug revenue expected 80820, got {rev_cur}"
    assert abs(rev_pri - 75340) < 0.5, f"Jul revenue expected 75340, got {rev_pri}"
    assert abs(rev_cur - rev_pri - 5480) < 0.5, f"Rev Δ expected +5480, got {rev_cur - rev_pri}"
    assert abs(cogs_cur - 34040) < 0.5, f"Aug COGS expected 34040, got {cogs_cur}"
    assert abs(cogs_pri - 31410) < 0.5, f"Jul COGS expected 31410, got {cogs_pri}"
    assert abs(cogs_cur - cogs_pri - 2630) < 0.5, f"COGS Δ expected +2630, got {cogs_cur - cogs_pri}"
    assert abs(opex_cur - 29560) < 0.5, f"Aug OpEx expected 29560, got {opex_cur}"
    assert abs(opex_pri - 27715) < 0.5, f"Jul OpEx expected 27715, got {opex_pri}"
    assert abs(opex_cur - opex_pri - 1845) < 0.5, f"OpEx Δ expected +1845, got {opex_cur - opex_pri}"
    assert abs((cogs_cur - cogs_pri) + (opex_cur - opex_pri) - 4475) < 0.5
    assert abs(net_cur - 17220) < 0.5, f"Aug NI expected 17220, got {net_cur}"
    assert abs(net_pri - 16215) < 0.5, f"Jul NI expected 16215, got {net_pri}"
    assert abs(net_cur - net_pri - 1005) < 0.5, f"NI Δ expected +1005, got {net_cur - net_pri}"

    # Income line reconciliation
    income_deltas = {i.account.split(":")[-1].strip(): i.delta for i in income}
    expected_inc = {
        "Bike Sales - New": 4130,
        "Bike Sales - Used": -470,
        "Service & Repair": 1590,
        "Parts & Accessories": 580,
        "Rentals": -350,
    }
    for name, exp_d in expected_inc.items():
        got = income_deltas.get(name)
        assert got is not None and abs(got - exp_d) < 0.5, f"{name} Δ expected {exp_d}, got {got}"
    assert abs(sum(expected_inc.values()) - 5480) < 0.5

    return {
        "rev_cur": rev_cur,
        "rev_pri": rev_pri,
        "rev_d": rev_cur - rev_pri,
        "cogs_cur": cogs_cur,
        "cogs_pri": cogs_pri,
        "cogs_d": cogs_cur - cogs_pri,
        "opex_cur": opex_cur,
        "opex_pri": opex_pri,
        "opex_d": opex_cur - opex_pri,
        "cost_cur": cost_cur,
        "cost_pri": cost_pri,
        "cost_d": cost_cur - cost_pri,
        "net_cur": net_cur,
        "net_pri": net_pri,
        "net_d": net_cur - net_pri,
        "net": net or LineItem("Net Income", net_cur, net_pri),
        "cash": special.get("cash"),
    }


def build_pdf(rows: list[LineItem], out_path: Path) -> None:
    styles = build_styles()
    parts = classify(rows)
    totals = assert_totals(parts)
    income, cogs, expenses = parts["income"], parts["cogs"], parts["expenses"]
    net = totals["net"]
    cash = totals["cash"]

    page_w, page_h = letter
    margin = 0.55 * inch
    content_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title=f"{CLIENT_NAME} — {PERIOD_LABEL} Monthly Pack",
        author=FIRM_NAME,
        subject="ClosePack sample — bookkeeper-branded monthly client pack",
        creator="ClosePack sample builder",
    )

    story: list = []
    story.extend(make_header(styles, content_w))

    # ── Snapshot KPIs ──────────────────────────────────────────────────────
    story.append(Paragraph("Month-end snapshot", styles["h1"]))
    story.append(section_rule())

    gap = 6
    card_w = (content_w - 3 * gap) / 4
    rev_d_txt = f"{money_signed(totals['rev_d'])} ({pct_str(totals['rev_d'] / totals['rev_pri'] * 100)}) MoM"
    cost_d_txt = f"{money_signed(totals['cost_d'])} ({pct_str(totals['cost_d'] / totals['cost_pri'] * 100)}) MoM"
    net_d_txt = f"{money_signed(totals['net_d'])} ({pct_str(totals['net_d'] / totals['net_pri'] * 100)}) MoM"
    cards = [
        kpi_card("Revenue", money(totals["rev_cur"]), rev_d_txt,
                 delta_color(totals["rev_d"], good_when_up=True), styles, card_w),
        kpi_card("Total costs", money(totals["cost_cur"]), cost_d_txt,
                 delta_color(totals["cost_d"], good_when_up=False), styles, card_w),
        kpi_card("Net profit", money(totals["net_cur"]), net_d_txt,
                 delta_color(totals["net_d"], good_when_up=True), styles, card_w),
    ]
    if cash:
        cash_pct = cash.delta_pct
        cash_txt = f"{money_signed(cash.delta)} ({pct_str(cash_pct)}) MoM"
        cards.append(kpi_card("Cash", money(cash.current), cash_txt,
                              delta_color(cash.delta, good_when_up=True), styles, card_w))
    else:
        cards.append(kpi_card("Cash", "—", "not in export", MUTED, styles, card_w))

    kpi_row = Table(
        [[cards[0], "", cards[1], "", cards[2], "", cards[3]]],
        colWidths=[card_w, gap, card_w, gap, card_w, gap, card_w],
    )
    kpi_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(kpi_row)
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(
            f"Vs {PRIOR_LABEL}. COGS {money(totals['cogs_cur'])} + OpEx {money(totals['opex_cur'])} "
            f"= total costs {money(totals['cost_cur'])}.",
            styles["caption"],
        )
    )

    # ── 6-month trend ──────────────────────────────────────────────────────
    story.append(Paragraph("6-month trend (Mar–Aug 2026)", styles["h1"]))
    story.append(section_rule())
    story.append(
        trend_drawing(
            totals["rev_cur"], totals["cost_cur"], totals["net_cur"],
            totals["rev_pri"], totals["cost_pri"], totals["net_pri"],
            content_w, height=128,
        )
    )
    story.append(Spacer(1, 2))

    # ── What changed ───────────────────────────────────────────────────────
    story.append(Paragraph("What changed", styles["h1"]))
    story.append(section_rule())
    story.append(
        Paragraph(
            "Commentary is bookkeeper-owned and editable before client send. ClosePack drafts the assembly; you own the narrative.",
            styles["caption"],
        )
    )
    for b in build_commentary(parts, totals):
        story.append(Paragraph(f"• {b}", styles["bullet"]))

    # ── Income detail ──────────────────────────────────────────────────────
    income_block = [
        Paragraph("Revenue detail", styles["h1"]),
        section_rule(),
        *detail_table("Income lines", income, styles, good_when_up=True, content_width=content_w),
    ]
    story.append(KeepTogether(income_block))

    # ── Expense detail (COGS + OpEx) ────────────────────────────────────────
    story.append(Paragraph("Cost & expense detail", styles["h1"]))
    story.append(section_rule())
    if cogs:
        story.extend(detail_table("Cost of goods sold", cogs, styles, good_when_up=False, content_width=content_w))
    if expenses:
        story.extend(detail_table("Operating expenses", expenses, styles, good_when_up=False, content_width=content_w))

    # ── Questions ──────────────────────────────────────────────────────────
    story.append(Paragraph("Questions for client call", styles["h1"]))
    story.append(section_rule())
    for q in client_questions():
        # Clean checkbox glyph (not ugly ASCII [ ])
        story.append(Paragraph(f"○  {q}", styles["question"]))

    # ── Disclaimer ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Prepared by {FIRM_NAME} from the client’s bookkeeping records (QBO/Xero-style export) "
            "for discussion purposes. Not an audit, review, or compilation; not tax, legal, or investment advice. "
            "Figures may be rounded. Mar–Jun trend bars are demo synthetic history for this sample pack.",
            styles["disclaimer"],
        )
    )

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1.2)
        y = 0.32 * inch
        canvas.line(margin, y + 10, page_w - margin, y + 10)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        # ClosePack ONLY in the small footer
        canvas.drawString(margin, y, "Assembled with ClosePack · closepack.dev")
        canvas.drawCentredString(page_w / 2, y, f"{CLIENT_NAME} · {PERIOD_LABEL}")
        canvas.drawRightString(page_w - margin, y, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build a ClosePack sample PDF from P&L CSV(s).")
    parser.add_argument("--csv", type=Path, default=here / "harbor-bike-co-pl-aug-2026.csv")
    parser.add_argument("--prior-csv", type=Path, default=here / "harbor-bike-co-pl-jul-2026.csv")
    parser.add_argument("--out", type=Path, default=here / "Harbor-Bike-Co-ClosePack-Aug-2026.pdf")
    args = parser.parse_args()

    rows, _ = load_pl(args.csv)
    rows = merge_prior(rows, args.prior_csv if args.prior_csv.exists() else None)
    if not rows:
        raise SystemExit(f"No rows loaded from {args.csv}")

    build_pdf(rows, args.out)
    size = args.out.stat().st_size
    print(f"Wrote {args.out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
