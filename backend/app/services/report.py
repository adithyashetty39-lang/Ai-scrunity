"""NBA/NAAC-ready annexure PDF: detailed audit findings behind the Scrutiny Format."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import REPORT_DIR

NAVY = colors.HexColor("#1b2a4a")
CRIMSON = colors.HexColor("#9b2335")
GOLD = colors.HexColor("#c4a35a")
CREAM = colors.HexColor("#f7f1e3")


def build_annexure(report: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"Scrutiny-Annexure-{report.get('report_id') or stamp}.pdf"

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleNavy",
        parent=styles["Title"],
        textColor=NAVY,
        fontName="Times-Bold",
        fontSize=18,
        leading=22,
    )
    h = ParagraphStyle("H", parent=styles["Heading2"], textColor=NAVY, fontName="Times-Bold")
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName="Times-Roman", fontSize=10, leading=14)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontName="Times-Roman", fontSize=8, leading=11)

    story = []
    meta = report.get("metadata") or {}
    story.append(Paragraph("Question Paper Scrutiny - Detailed Annexure", title))
    story.append(Paragraph("Attachment to the departmental Question Paper Scrutiny Format", body))
    story.append(Spacer(1, 6))

    verdict = report.get("final_verdict", "NEEDS_REVISION")
    vcolor = colors.HexColor("#1f7a4d") if verdict == "APPROVED" else CRIMSON
    banner = Table(
        [[Paragraph(f"<b>VERDICT: {verdict}</b>", ParagraphStyle("V", parent=body, textColor=colors.white, alignment=1))]],
        colWidths=[180 * mm],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), vcolor),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 8))

    info = [
        ["Course Name", meta.get("course_title") or "-", "Course Code", meta.get("course_code") or "-"],
        ["Semester", meta.get("semester") or "-", "Academic Year", meta.get("academic_year") or "-"],
        ["Date", meta.get("date") or "-", "IA Test No", meta.get("ia_test_no") or meta.get("cie_number") or "-"],
        ["Duration", meta.get("duration") or "-", "Max Marks", str(meta.get("max_marks") or "-")],
    ]
    t = Table(info, colWidths=[30 * mm, 55 * mm, 32 * mm, 63 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), CREAM),
                ("BACKGROUND", (2, 0), (2, -1), CREAM),
                ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.3, GOLD),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Executive Summary", h))
    story.append(Paragraph(report.get("executive_summary") or "", body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Scrutiny Checklist", h))
    rows = [["Category", "Check", "Status", "Detail"]]
    for c in report.get("checklist") or []:
        rows.append(
            [
                Paragraph(c.get("category", ""), small),
                Paragraph(c.get("check", ""), small),
                c.get("status", ""),
                Paragraph(c.get("detail", ""), small),
            ]
        )
    ct = Table(rows, colWidths=[32 * mm, 48 * mm, 22 * mm, 78 * mm])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c1b1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    status_bg = {
        "PASS": colors.HexColor("#e5f4ea"),
        "FAIL": colors.HexColor("#fde8ea"),
        "WARN": colors.HexColor("#fff4d6"),
    }
    for i, c in enumerate(report.get("checklist") or [], start=1):
        style_cmds.append(("BACKGROUND", (2, i), (2, i), status_bg.get(c.get("status"), colors.white)))
    ct.setStyle(TableStyle(style_cmds))
    story.append(ct)
    story.append(Spacer(1, 10))

    charts = _charts(report)
    if charts:
        story.append(Paragraph("CO-RBT Distribution", h))
        story.append(charts)
        story.append(Spacer(1, 8))

    story.append(Paragraph("Question-wise Findings", h))
    qrows = [["Q", "Stated", "Predicted", "CO", "PO", "Syllabus", "Issues"]]
    for a in report.get("question_audits") or []:
        issues = "; ".join(a.get("issues_found") or []) or "-"
        qrows.append(
            [
                str(a.get("q_no")),
                f"{a.get('stated_blooms') or '-'} / {a.get('stated_co') or '-'}",
                a.get("predicted_blooms") or "-",
                "Y" if a.get("co_match") else "N",
                "Y" if a.get("po_match") else "N",
                "Y" if a.get("is_in_syllabus") else "N",
                Paragraph(issues, small),
            ]
        )
    qt = Table(qrows, colWidths=[12 * mm, 30 * mm, 18 * mm, 10 * mm, 10 * mm, 16 * mm, 84 * mm])
    qt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9c1b1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(qt)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Committee Use", h))
    story.append(
        Paragraph(
            "Subject Expert 1 ______________________ &nbsp;&nbsp; Subject Expert 2 ______________________ "
            "&nbsp;&nbsp; Scrutiny Chair ______________________",
            body,
        )
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="CIE Scrutiny Annexure",
    )
    doc.build(story)
    return path


def _bar_panel(title: str, data: dict, fill: colors.Color) -> Drawing:
    drawing = Drawing(250, 160)
    drawing.add(String(8, 148, title, fontName="Times-Bold", fontSize=10, fillColor=NAVY))
    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 20
    chart.height = 110
    chart.width = 200
    chart.data = [[round(v * 100, 1) for v in data.values()]]
    chart.categoryAxis.categoryNames = list(data.keys())
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.bars[0].fillColor = fill
    chart.categoryAxis.labels.fontSize = 8
    drawing.add(chart)
    return drawing


def _charts(report: dict):
    rbt = report.get("overall_rbt_distribution") or {}
    co = report.get("co_coverage") or {}
    if not rbt and not co:
        return None
    left = _bar_panel("RBT mark share (%)", rbt or {"-": 0}, NAVY)
    right = _bar_panel("Module mark share (%)", co or {"-": 0}, CRIMSON)
    return Table([[left, right]], colWidths=[90 * mm, 90 * mm])
