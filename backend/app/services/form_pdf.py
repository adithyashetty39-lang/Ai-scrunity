"""Render Scritinyform.pdf's exact two-page layout with audit results filled in."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import Color, black, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.config import LOGO_PATH, REPORT_DIR
from app.services.findings_pdf import append_findings

PAGE_W, PAGE_H = 612.0, 792.0

HEADER_FILL = Color(0.816, 0.808, 0.808)
RULE = 1.0

FONT_DIR = r"C:\Windows\Fonts"
_FONT_CACHE: dict[str, str] = {}


def _register_fonts() -> tuple[str, str, str, str]:
    """Register Times New Roman faces; fall back to ReportLab's built-in Times."""
    if _FONT_CACHE:
        return (
            _FONT_CACHE["roman"],
            _FONT_CACHE["bold"],
            _FONT_CACHE["italic"],
            _FONT_CACHE["bolditalic"],
        )

    families = [
        ("roman", "times.ttf", "Times-Roman"),
        ("bold", "timesbd.ttf", "Times-Bold"),
        ("italic", "timesi.ttf", "Times-Italic"),
        ("bolditalic", "timesbi.ttf", "Times-BoldItalic"),
    ]
    for key, filename, fallback in families:
        path = os.path.join(FONT_DIR, filename)
        if os.path.exists(path):
            name = f"TNR-{key.capitalize()}"
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                _FONT_CACHE[key] = name
                continue
            except Exception:
                pass
        _FONT_CACHE[key] = fallback
    return (
        _FONT_CACHE["roman"],
        _FONT_CACHE["bold"],
        _FONT_CACHE["italic"],
        _FONT_CACHE["bolditalic"],
    )


def build_form_pdf(form: dict, report_id: str | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = report_id or stamp
    path = REPORT_DIR / f"Scrutiny-Format-{token}.pdf"

    roman, bold, _, _ = _register_fonts()
    c = canvas.Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Question Paper Scrutiny Format")
    c.setAuthor(form.get("institution") or "")
    c.setSubject(form.get("course_code") or "")

    _page_one(c, form, roman, bold)
    if form.get('draft'):
        _draft_stamp(c, form, bold)
    c.showPage()
    _page_two(c, form, roman, bold)
    if form.get('draft'):
        _draft_stamp(c, form, bold)
    c.showPage()
    if form.get('question_findings'):
        append_findings(c, form, roman, bold)
    else:
        c.save()
    return path


def _draft_stamp(c, form, font):
    c.saveState()
    c.setFillColor(Color(0.65, 0.2, 0.15))
    c.setFont(font, 8)
    c.drawCentredString(PAGE_W / 2, 18, 'DRAFT - NOT APPROVED | ' + form.get('draft_id', ''))
    c.setFillAlpha(0.07)
    c.translate(PAGE_W / 2, PAGE_H / 2)
    c.rotate(35)
    c.setFont(font, 85)
    c.drawCentredString(0, 0, 'DRAFT')
    c.restoreState()


# --------------------------------------------------------------------------------------
# Coordinates: template values are top-down, ReportLab is bottom-up.
# --------------------------------------------------------------------------------------

def _y(top: float) -> float:
    return PAGE_H - top


def _line(c: canvas.Canvas, x1: float, top1: float, x2: float, top2: float, width: float = RULE) -> None:
    c.setLineWidth(width)
    c.setStrokeColor(black)
    c.line(x1, _y(top1), x2, _y(top2))


def _grid(
    c: canvas.Canvas,
    x_left: float,
    x_right: float,
    col_edges: list[float],
    row_tops: list[float],
) -> None:
    c.setLineWidth(RULE)
    c.setStrokeColor(black)
    for i in range(len(row_tops) - 1):
        top = row_tops[i]
        _line(c, x_left, top, x_right, top)
    _line(c, x_left, row_tops[-1], x_right, row_tops[-1])
    for x in col_edges:
        _line(c, x, row_tops[0], x, row_tops[-1])


def _fill_row(c: canvas.Canvas, x0: float, x1: float, top: float, bottom: float, color: Color) -> None:
    c.setFillColor(color)
    c.rect(x0, _y(bottom), x1 - x0, bottom - top, stroke=0, fill=1)
    c.setFillColor(black)


def _text(
    c: canvas.Canvas,
    x: float,
    baseline: float,
    text: str,
    font: str,
    size: float,
) -> None:
    if not text:
        return
    c.setFont(font, size)
    c.setFillColor(black)
    c.drawString(x, _y(baseline), text)


def _center(c: canvas.Canvas, center_x: float, baseline: float, text: str, font: str, size: float) -> None:
    if not text:
        return
    c.setFont(font, size)
    c.setFillColor(black)
    c.drawCentredString(center_x, _y(baseline), text)


def _fit(text: str, font: str, size: float, max_width: float) -> tuple[str, float]:
    """Shrink a single-line value until it fits its cell."""
    if not text:
        return "", size
    width = pdfmetrics.stringWidth(text, font, size)
    while width > max_width and size > 5.5:
        size -= 0.5
        width = pdfmetrics.stringWidth(text, font, size)
    return text, size


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(probe, font, size) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_cell_text(
    c: canvas.Canvas,
    x: float,
    baseline: float,
    text: str,
    font: str,
    size: float,
    max_width: float,
    max_lines: int = 2,
    leading: float = 9.6,
) -> None:
    if not text:
        return
    lines = _wrap(text, font, size, max_width)[:max_lines]
    if len(_wrap(text, font, size, max_width)) > max_lines and lines:
        lines[-1] = lines[-1].rstrip(".,; ") + "…"
    for i, line in enumerate(lines):
        _text(c, x, baseline + i * leading, line, font, size)


# --------------------------------------------------------------------------------------
# Checkboxes (vector, so no glyph/font dependency)
# --------------------------------------------------------------------------------------

def _checkbox(c: canvas.Canvas, x: float, baseline: float, ticked: bool, size: float = 9.4) -> None:
    bottom = _y(baseline) + 1.2
    c.setLineWidth(0.9)
    c.setStrokeColor(black)
    c.rect(x, bottom, size, size, stroke=1, fill=0)
    if ticked:
        c.setLineWidth(1.3)
        c.setStrokeColor(black)
        path = c.beginPath()
        path.moveTo(x + size * 0.18, bottom + size * 0.52)
        path.lineTo(x + size * 0.42, bottom + size * 0.22)
        path.lineTo(x + size * 0.85, bottom + size * 0.82)
        c.drawPath(path, stroke=1, fill=0)


# --------------------------------------------------------------------------------------
# Page 1
# --------------------------------------------------------------------------------------

P1_META_COLS = [32.6, 131.7, 343.8, 452.0, 578.4]
P1_META_ROWS = [155.1, 187.0, 214.9, 243.3]

P1_A_COLS = [30.7, 336.7, 386.2, 580.7]
P1_A_ROWS = [278.5, 301.5, 330.7, 356.6, 385.7, 413.0, 440.3, 467.7]
P1_A_ROW_BASELINES = [323.28, 350.88, 378.36, 406.68, 434.06, 461.42]

P1_B_COLS = [26.8, 332.9, 397.4, 585.0]
P1_B_ROWS = [626.4, 647.7, 694.1, 734.6]
P1_B_ROW_BASELINES = [678.29, 721.61]


def _page_one(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    if LOGO_PATH.exists():
        try:
            c.drawImage(
                str(LOGO_PATH),
                22.5,
                _y(93.5),
                width=54.5,
                height=48.9,
                mask="auto",
                preserveAspectRatio=True,
            )
        except Exception:
            pass

    _center(c, 306, 53.95, form.get("institution") or "", bold, 12)
    _center(c, 306, 66.70, form.get("institution_sub") or "", roman, 11)
    _center(c, 306, 78.47, form.get("institution_address") or "", roman, 10)
    _center(c, 306, 107.21, form.get("department") or "", bold, 14)
    _center(c, 306, 137.09, form.get("form_title") or "", bold, 14)

    _metadata_block(c, form, roman, bold)
    _set_table_page_one(c, form, roman, bold)


def _metadata_block(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _grid(c, P1_META_COLS[0], P1_META_COLS[-1], P1_META_COLS, P1_META_ROWS)

    labels = [
        (39.0, 350.1, 178.17, "Course Name:", "Course Code:"),
        (39.0, 350.1, 208.29, "Date:", "Academic year:"),
        (39.0, 350.1, 236.37, "Semester:", "IA Test No:"),
    ]
    for x1, x2, baseline, left, right in labels:
        _text(c, x1, baseline, left, bold, 12)
        _text(c, x2, baseline, right, bold, 12)

    values = [
        (form.get("course_name") or "", form.get("course_code") or "", 178.17),
        (form.get("date") or "", form.get("academic_year") or "", 208.29),
        (form.get("semester") or "", form.get("ia_test_no") or "", 236.37),
    ]
    for left_val, right_val, baseline in values:
        text, size = _fit(left_val, roman, 11, P1_META_COLS[3] - P1_META_COLS[1] - 8)
        _text(c, P1_META_COLS[1] + 4, baseline, text, roman, size)
        text, size = _fit(right_val, roman, 11, P1_META_COLS[4] - P1_META_COLS[3] - 8)
        _text(c, P1_META_COLS[3] + 4, baseline, text, roman, size)


def _set_table_page_one(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _center(c, 306, 274.16, "Evaluation of Question Paper – Set A", bold, 14)

    _fill_row(c, P1_A_COLS[0] + 1, P1_A_COLS[1], P1_A_ROWS[0], P1_A_ROWS[1], HEADER_FILL)
    _fill_row(c, P1_A_COLS[1] + 0.9, P1_A_COLS[2], P1_A_ROWS[0], P1_A_ROWS[1], HEADER_FILL)
    _fill_row(c, P1_A_COLS[2] + 1, P1_A_COLS[3], P1_A_ROWS[0], P1_A_ROWS[1], HEADER_FILL)
    _grid(c, P1_A_COLS[0], P1_A_COLS[-1], P1_A_COLS, P1_A_ROWS)

    _text(c, 164.2, 297.36, "Criteria", bold, 12)
    _text(c, 344.0, 297.36, "Yes/No", bold, 12)
    _text(c, 456.9, 297.36, "Comments", bold, 12)

    _criteria_rows(
        c,
        form.get("set_a") or {},
        roman,
        bold,
        crit_x=37.1,
        yesno_center=(P1_A_COLS[1] + P1_A_COLS[2]) / 2,
        comment_x=P1_A_COLS[2] + 4,
        comment_width=P1_A_COLS[3] - P1_A_COLS[2] - 8,
        baselines=P1_A_ROW_BASELINES,
    )

    _comments_block(
        c,
        form.get("set_a") or {},
        roman,
        bold,
        title="Overall Comments for Set A:",
        title_baseline=482.30,
        box_top=P1_A_ROWS[-1],
        box_bottom=579.2,
        x_left=P1_A_COLS[0],
        x_right=P1_A_COLS[3],
        item_x=37.1,
        text_x=55.0,
        baselines=[510.02, 537.62, 565.22],
        width=520.0,
    )

    _center(c, 306, 610.09, "Evaluation of Question Paper – Set B", bold, 14)

    _fill_row(c, P1_B_COLS[0] + 0.9, P1_B_COLS[1], P1_B_ROWS[0], P1_B_ROWS[1], HEADER_FILL)
    _fill_row(c, P1_B_COLS[1] + 1, P1_B_COLS[2], P1_B_ROWS[0], P1_B_ROWS[1], HEADER_FILL)
    _fill_row(c, P1_B_COLS[2] + 1, P1_B_COLS[3], P1_B_ROWS[0], P1_B_ROWS[1], HEADER_FILL)
    _grid(c, P1_B_COLS[0], P1_B_COLS[-1], P1_B_COLS, P1_B_ROWS)

    _text(c, 160.3, 644.33, "Criteria", bold, 12)
    _text(c, 347.7, 644.33, "Yes/No", bold, 12)
    _text(c, 465.0, 644.33, "Comments", bold, 12)

    _criteria_rows(
        c,
        form.get("set_b") or {},
        roman,
        bold,
        crit_x=33.1,
        yesno_center=(P1_B_COLS[1] + P1_B_COLS[2]) / 2,
        comment_x=P1_B_COLS[2] + 4,
        comment_width=P1_B_COLS[3] - P1_B_COLS[2] - 8,
        baselines=P1_B_ROW_BASELINES,
    )


def _criteria_rows(
    c: canvas.Canvas,
    form_set: dict,
    roman: str,
    bold: str,
    crit_x: float,
    yesno_center: float,
    comment_x: float,
    comment_width: float,
    baselines: list[float],
) -> None:
    """Draw the criterion text plus the Yes/No tick and comment for the supplied rows."""
    data = (form_set or {}).get("rows") or []
    for i, baseline in enumerate(baselines):
        row = data[i] if i < len(data) else {}
        criterion = row.get("criterion") or ""
        _text(c, crit_x, baseline, criterion, roman, 12)
        answer = (row.get("answer") or "").strip()
        if answer:
            _center(c, yesno_center, baseline, answer, bold, 11)
        _draw_cell_text(
            c,
            comment_x,
            baseline - 7,
            row.get("comments") or "",
            roman,
            8.6,
            comment_width,
            max_lines=2,
            leading=8.8,
        )


def _comments_block(
    c: canvas.Canvas,
    form_set: dict,
    roman: str,
    bold: str,
    title: str,
    title_baseline: float,
    box_top: float,
    box_bottom: float,
    x_left: float,
    x_right: float,
    item_x: float,
    text_x: float,
    baselines: list[float],
    width: float,
) -> None:
    _grid(c, x_left, x_right, [x_left, x_right], [box_top, box_bottom])
    _center(c, (x_left + x_right) / 2, title_baseline, title, bold, 12)

    comments = (form_set or {}).get("overall_comments") or []
    for i, baseline in enumerate(baselines):
        _text(c, item_x, baseline, f"{i + 1})", roman, 12)
        text = comments[i] if i < len(comments) else ""
        _draw_cell_text(c, text_x, baseline, text, roman, 9.2, width, max_lines=2, leading=9.4)


# --------------------------------------------------------------------------------------
# Page 2
# --------------------------------------------------------------------------------------

P2_B_COLS = [26.8, 332.9, 397.4, 585.0]
P2_B_ROWS = [40.0, 85.0, 125.5, 178.2, 224.2]
P2_B_ROW_BASELINES = [69.79, 112.65, 159.21, 208.41]

P2_REC_COLS = [27.1, 306.2, 584.3]
P2_REC_ROWS = [331.4, 401.2, 432.4]

P2_DECL_COLS = [32.5, 210.5, 388.4, 566.1]
P2_DECL_ROWS = [540.7, 573.4, 627.2, 679.9, 731.4]

RECOMMENDATION_LINES = [
    ("Approved as it is", 358.44),
    ("Approved with minor changes", 374.04),
    ("Needs revision before approval", 389.45),
]


def _page_two(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    set_b = form.get("set_b") or {}

    _grid(c, P2_B_COLS[0], P2_B_COLS[-1], P2_B_COLS, P2_B_ROWS)

    rows = set_b.get("rows") or []
    for i, baseline in enumerate(P2_B_ROW_BASELINES):
        row = rows[i + 2] if i + 2 < len(rows) else {}
        _text(c, 33.1, baseline, row.get("criterion") or "", roman, 12)
        if row.get("answer"):
            _center(
                c,
                (P2_B_COLS[1] + P2_B_COLS[2]) / 2,
                baseline,
                row["answer"],
                bold,
                11,
            )
        _draw_cell_text(
            c,
            P2_B_COLS[2] + 4,
            baseline - 7,
            row.get("comments") or "",
            roman,
            8.6,
            P2_B_COLS[3] - P2_B_COLS[2] - 8,
            max_lines=2,
            leading=8.8,
        )

    _grid(c, P2_B_COLS[0], P2_B_COLS[-1], [P2_B_COLS[0], P2_B_COLS[-1]], [224.2, 308.1])
    _center(c, 306, 238.77, "Overall Comments for Set B:", bold, 12)

    comments = set_b.get("overall_comments") or []
    for i, baseline in enumerate([259.68, 280.32, 301.08]):
        _text(c, 33.1, baseline, f"{i + 1})", roman, 12)
        text = comments[i] if i < len(comments) else ""
        _draw_cell_text(c, 51.0, baseline, text, roman, 9.2, 520.0, max_lines=2, leading=9.4)

    _recommendations(c, form, roman, bold)
    _selected_paper(c, form, roman, bold)
    _declaration(c, form, roman, bold)
    _signatures(c, form, roman, bold)


def _recommendations(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _grid(c, P2_REC_COLS[0], P2_REC_COLS[-1], P2_REC_COLS, P2_REC_ROWS)
    _text(c, 33.5, 373.68, "Scrutiny Recommendations:", roman, 12)

    chosen = (form.get("scrutiny_recommendation") or "").strip().lower()
    for label, baseline in RECOMMENDATION_LINES:
        _checkbox(c, 312.5, baseline, ticked=(chosen == label.lower()))
        _text(c, 325.8, baseline, label, roman, 12)


def _selected_paper(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _text(c, 33.5, 424.10, "Selected Question Paper", roman, 12)
    selected = (form.get("selected_paper") or "").strip().lower()

    _checkbox(c, 338.7, 424.94, ticked=(selected == "set a"))
    _text(c, 351.9, 424.94, "Set A", roman, 12)
    _checkbox(c, 454.2, 424.94, ticked=(selected == "set b"))
    _text(c, 467.4, 424.94, "Set B", roman, 12)


def _declaration(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _grid(
        c,
        P2_REC_COLS[0],
        P2_REC_COLS[-1],
        [27.1, 584.3],
        [433.4, 746.3],
    )
    lines = _wrap(form.get("confidentiality_note") or "", roman, 12, 549.0)
    for i, baseline in enumerate([460.94, 474.74, 488.54, 502.34]):
        if i < len(lines):
            _text(c, 33.5, baseline, lines[i], roman, 12)


def _signatures(c: canvas.Canvas, form: dict, roman: str, bold: str) -> None:
    _center(c, 306, 529.94, "Signatures", bold, 12)

    cols = P2_DECL_COLS
    rows = P2_DECL_ROWS

    _fill_row(c, cols[0] + 1, cols[1], rows[0], rows[1], HEADER_FILL)
    _fill_row(c, cols[1] + 1, cols[2], rows[0], rows[1], HEADER_FILL)
    _fill_row(c, cols[2] + 1, cols[3], rows[0], rows[1], HEADER_FILL)
    _grid(c, cols[0], cols[-1], cols, rows)

    _center(c, (cols[0] + cols[1]) / 2, 565.78, "Name", bold, 14)
    _center(c, (cols[1] + cols[2]) / 2, 565.78, "Designation", bold, 14)
    _center(c, (cols[2] + cols[3]) / 2, 565.78, "Signature with Date", bold, 14)

    role_baselines = [609.01, 662.17, 714.25]
    entries = form.get("signatures") or []
    for i, baseline in enumerate(role_baselines):
        entry = entries[i] if i < len(entries) else {}
        _text(c, 38.9, baseline, entry.get("role") or "", roman, 14)
        name, size = _fit(entry.get("name") or "", roman, 11, cols[1] - cols[0] - 12)
        _text(c, 38.9 + 6, baseline + 16, name, roman, size)
        designation, size = _fit(entry.get("designation") or "", roman, 11, cols[2] - cols[1] - 12)
        _text(c, cols[1] + 6, baseline + 16, designation, roman, size)
        date, size = _fit(entry.get("signature_date") or "", roman, 11, cols[3] - cols[2] - 62)
        _text(c, cols[2] + 60, baseline + 16, date, roman, size)


def build(report_payload: dict) -> Path:
    """Convenience wrapper used by the API layer."""
    return build_form_pdf(report_payload.get("form") or {}, report_payload.get("report_id"))
