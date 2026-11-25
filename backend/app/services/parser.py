"""Layout-aware CIE paper parser (PDF/DOCX/TXT) into QuestionItem JSON."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas import PaperMetadata, QuestionItem
from app.services.blooms_rubric import normalize_level

HEADER_PATTERNS = {
    "course_code": r"(?:course\s*code|sub(?:ject)?\s*code|code)\s*[:\-]\s*([A-Z0-9]{5,10})",
    "course_title": r"(?:course\s*(?:title|name)|subject)\s*[:\-]\s*(.+)",
    "semester": r"(?:semester|sem)\s*[:\-]\s*([IVX0-9]+(?:\s*(?:st|nd|rd|th))?)",
    "cie_number": r"(?:continuous\s*internal\s*evaluation\s*[\-—–]\s*)?(CIE[\s\-]*[123]|internal\s*assessment[\s\-]*[123]|ia[\s\-]*[123])",
    "date": r"(?:date)\s*[:\-]\s*([0-9]{1,2}[\/\-.][0-9]{1,2}[\/\-.][0-9]{2,4})",
    "duration": r"(?:duration|time)\s*[:\-]\s*([0-9]+(?:\.[0-9]+)?\s*(?:min|minutes|hour|hours|hr|hrs).*)",
    "max_marks": r"(?:max(?:imum)?\s*marks|marks)\s*[:\-]\s*(\d{1,3})",
    "academic_year": r"(?:academic\s*year|a\.?\s*y\.?)\s*[:\-]\s*([0-9]{4}\s*[\-–/]\s*[0-9]{2,4})",
    "ia_test_no": r"(?:ia\s*test\s*(?:no|number)|test\s*(?:no|number)|cie\s*(?:no|number))\s*[:\-]\s*([A-Za-z0-9\-/ ]{1,20})",
}

SET_HEADING = re.compile(
    r"^\s*(?:question\s*paper\s*)?[-–—\s]*(?:set|paper)\s*[-–—:\s]*\(?\s*([AB])\s*\)?\s*$",
    re.I,
)


FIGURE_KEYWORDS = [
    r"\brefer\s+to\s+(?:the\s+)?(?:figure|fig|diagram|chart|graph|table)",
    r"\bshown\s+in\s+(?:the\s+)?(?:figure|fig|diagram|chart|graph|table)",
    r"\bgiven\s+in\s+(?:the\s+)?(?:figure|fig|diagram|chart|graph)",
    r"\bsee\s+(?:the\s+)?(?:figure|fig|diagram)",
    r"\bfigure\s+below\b",
    r"\bdiagram\s+below\b",
]


def extract_text(path: Path) -> tuple[str, list[str]]:
    anomalies: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, anomalies)
    if suffix in {".docx", ".doc"}:
        return _extract_docx(path, anomalies)
    return path.read_text(encoding="utf-8", errors="ignore"), anomalies


def _extract_pdf(path: Path, anomalies: list[str]) -> tuple[str, list[str]]:
    import pdfplumber

    chunks: list[str] = []
    has_images = False
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            anomalies.append("PDF has no pages.")
        for i, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            if tables:
                for table in tables:
                    chunks.append(_table_to_text(table))
            text = page.extract_text() or ""
            if text and not tables:
                chunks.append(text)
            elif text and tables:
                chunks.append(text)

            # Check for hidden or white-on-white text
            hidden = page.filter(lambda obj: obj.get("non_stroking_color") == (1, 1, 1) or obj.get("non_stroking_color") == [1, 1, 1])
            try:
                hidden_text = hidden.extract_text() if hidden else ""
                if hidden_text and hidden_text.strip():
                    anomalies.append(f"Possible hidden/white text detected on page {i}.")
            except Exception:
                pass

            if page.images:
                has_images = True
                anomalies.append(f"Page {i} contains {len(page.images)} image/diagram(s).")

    joined = "\n".join(chunks).strip()
    if not joined:
        # Scanned PDF without text stream — run automatic OCR fallback
        ocr_text = _run_ocr_on_pdf(path)
        if ocr_text:
            joined = ocr_text
            anomalies.append("Applied automatic layout-aware OCR to scanned PDF pages.")
        else:
            anomalies.append("No extractable text found; the PDF appears to be a scanned raster image without OCR.")
    return joined, anomalies


def _run_ocr_sync(path: Path) -> str:
    import asyncio
    import pypdfium2 as pdfium
    import winocr

    async def _process_all():
        pdf = pdfium.PdfDocument(str(path))
        extracted_pages = []
        for page in pdf:
            pil_img = page.render(scale=2).to_pil()
            res = await winocr.recognize_pil(pil_img)
            if res and res.lines:
                page_text = "\n".join(l.text.strip() for l in res.lines if l.text.strip())
                if page_text:
                    extracted_pages.append(page_text)
        return "\n\n".join(extracted_pages)

    return asyncio.run(_process_all())


def _run_ocr_on_pdf(path: Path) -> str:
    """Extract text from scanned PDF pages using Windows native OCR in an isolated thread."""
    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_ocr_sync, path)
            return future.result(timeout=45.0)
    except Exception:
        return ""


def _extract_docx(path: Path, anomalies: list[str]) -> tuple[str, list[str]]:
    from docx import Document

    doc = Document(path)
    parts: list[str] = []
    for table in doc.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        parts.append(_table_to_text(rows))
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    if not parts:
        anomalies.append("DOCX contained no readable paragraphs or tables.")
    return "\n".join(parts), anomalies


def _table_to_text(table: list[list]) -> str:
    lines = []
    for row in table:
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_metadata(text: str) -> PaperMetadata:
    meta = PaperMetadata()
    header = "\n".join(text.splitlines()[:50])
    issues: list[str] = []

    code = re.search(HEADER_PATTERNS["course_code"], header, re.I)
    meta.course_code = code.group(1).strip() if code else None

    title = re.search(HEADER_PATTERNS["course_title"], header, re.I)
    if title:
        raw_title = title.group(1).strip().splitlines()[0]
        meta.course_title = re.sub(r"\s{2,}", " ", raw_title)[:120]

    sem = re.search(HEADER_PATTERNS["semester"], header, re.I)
    meta.semester = sem.group(1).strip() if sem else None

    cie = re.search(HEADER_PATTERNS["cie_number"], header, re.I)
    meta.cie_number = cie.group(1).upper().replace(" ", "-") if cie else None

    date = re.search(HEADER_PATTERNS["date"], header, re.I)
    meta.date = date.group(1) if date else None

    dur = re.search(HEADER_PATTERNS["duration"], header, re.I)
    if dur:
        raw_dur = dur.group(1).strip().splitlines()[0]
        meta.duration = re.sub(r"\s{2,}", " ", raw_dur)[:40]

    marks = re.search(HEADER_PATTERNS["max_marks"], header, re.I)
    meta.max_marks = int(marks.group(1)) if marks else None

    ay = re.search(HEADER_PATTERNS["academic_year"], header, re.I)
    if ay:
        meta.academic_year = re.sub(r"\s*[\-–/]\s*", "-", ay.group(1).strip())

    ia = re.search(HEADER_PATTERNS["ia_test_no"], header, re.I)
    if ia:
        meta.ia_test_no = re.sub(r"\s{2,}", " ", ia.group(1)).strip()[:20]

    for line in header.splitlines()[:5]:
        line = line.strip()
        if re.search(r"\b(?:college|institute|university|department|school|academy)\b", line, re.I):
            meta.institution = line
            break

    required = {
        "Course Code": meta.course_code,
        "Course Title": meta.course_title,
        "Semester": meta.semester,
        "Date": meta.date,
        "Duration": meta.duration,
        "Max Marks": meta.max_marks,
    }
    for label, value in required.items():
        if not value:
            issues.append(f"Missing header field: {label}")
    meta.header_issues = issues
    return meta


def _extract_meta_tokens(line: str) -> tuple[str, int, str, str, str]:
    """Extract (clean_stem, marks, co, rbt, po) from a question line.
    Handles formats like:
      - 'stem text 5 CO1 L1'
      - 'stem text [10] [CO2] [L3]'
      - 'stem text (10 marks, CO1, L2)'
      - 'stem text 8 Marks CO2 L2'
      - 'stem text CO2 L3 9'
      - 'stem text 5 [CO1] [PO1,PO2] [L1]'
    """
    marks = 0
    co = ""
    rbt = ""
    po = ""
    stem = line.strip()

    # Programme Outcome cluster: PO1, PO1,PO2, PO 3 etc.
    po_cluster = re.search(r"\bPO\s*\d(?:\s*[,/&]\s*PO\s*\d)*", stem, re.I)
    if po_cluster:
        po = ",".join(
            f"PO{m}" for m in re.findall(r"PO\s*(\d{1,2})", po_cluster.group(0), re.I)
        )
        stem = stem[: po_cluster.start()] + stem[po_cluster.end() :]

    # Look for trailing sequence of metadata tokens
    # e.g., 5 CO1 L1, 10 CO1 L2, 10 Marks CO1 L3, etc.
    tail_pattern = re.compile(
        r"""
        [\s\[(,-]+
        (?P<token1>\d{1,2}(?:\s*marks?|\s*m)?|CO\s*[1-6]|(?:RBT\s*)?L\s*[1-6]|BT\s*[1-6]|BL\s*[1-6])
        (?:[\s\],/–-]+(?P<token2>\d{1,2}(?:\s*marks?|\s*m)?|CO\s*[1-6]|(?:RBT\s*)?L\s*[1-6]|BT\s*[1-6]|BL\s*[1-6]))?
        (?:[\s\],/–-]+(?P<token3>\d{1,2}(?:\s*marks?|\s*m)?|CO\s*[1-6]|(?:RBT\s*)?L\s*[1-6]|BT\s*[1-6]|BL\s*[1-6]))?
        [\s\])]*$
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    tail_match = tail_pattern.search(stem)
    if tail_match:
        tokens = [tail_match.group("token1"), tail_match.group("token2"), tail_match.group("token3")]
        matched_tokens = False
        for tok in tokens:
            if not tok:
                continue
            tok_clean = tok.strip().lower()
            num_m = re.match(r"^(\d{1,2})(?:\s*marks?|\s*m)?$", tok_clean)
            if num_m:
                marks = int(num_m.group(1))
                matched_tokens = True
            elif re.match(r"^co\s*([1-6])$", tok_clean):
                co = "CO" + re.search(r"[1-6]", tok_clean).group(0)
                matched_tokens = True
            elif re.match(r"^(?:rbt\s*|bt\s*|bl\s*)?l\s*([1-6])$", tok_clean) or re.match(r"^(?:bt|bl)\s*([1-6])$", tok_clean):
                rbt = "L" + re.search(r"[1-6]", tok_clean).group(0)
                matched_tokens = True

        if matched_tokens:
            stem = stem[: tail_match.start()].strip()

    # If any token is still missing, check inline anywhere in the stem
    if not marks:
        m = re.search(r"\[(\d{1,2})\s*(?:marks?|m)?\]|\((\d{1,2})\s*(?:marks?|m)?\)|(\d{1,2})\s*(?:marks?)\b", stem, re.I)
        if m:
            marks = int(next(g for g in m.groups() if g))
            stem = stem[: m.start()] + stem[m.end() :]
    if not co:
        c = re.search(r"\bCO\s*([1-6])\b", stem, re.I)
        if c:
            co = f"CO{c.group(1)}"
            stem = stem[: c.start()] + stem[c.end() :]
    if not rbt:
        r = re.search(r"\b(?:RBT\s*|BT\s*|BL\s*)?L\s*([1-6])\b", stem, re.I)
        if r:
            rbt = f"L{r.group(1)}"
            stem = stem[: r.start()] + stem[r.end() :]

    return _clean_question_text(stem), marks, co, normalize_level(rbt), po


def parse_questions(text: str, set_label: str | None = None) -> list[QuestionItem]:
    questions: list[QuestionItem] = []
    current_main = "1"
    current_module: str | None = None
    is_or_branch = False
    pending_or = False
    current_or_group: str | None = None

    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]

    for raw in lines:
        if not raw:
            continue

        # Skip headers / labels
        low = raw.lower()
        if low in {"q.no", "questions", "marks", "co", "rbt", "bl", "sl.no", "part a", "part b"}:
            continue

        # Set separator inside a single uploaded paper ("SET A" / "SET B")
        set_marker = SET_HEADING.match(raw)
        if set_marker:
            set_label = set_marker.group(1).upper()
            current_main = "1"
            is_or_branch = False
            pending_or = False
            current_or_group = None
            continue

        # Module / Unit header
        mod = re.search(r"(?:module|unit)\s*([ivx0-9]+)", raw, re.I)
        if mod and len(raw) < 50:
            current_module = _normalize_module(raw)
            # Reset OR branch when starting a new module
            is_or_branch = False
            pending_or = False
            current_or_group = None
            continue

        # OR divider
        if re.fullmatch(r"(?:-{2,}\s*)?(?:OR|O\s*R)(?:\s*-{2,})?", raw, re.I):
            pending_or = True
            continue

        # Match table rows: e.g. "1 a | Define... | 5 | CO1 | L1"
        pipe_cells = [c.strip() for c in raw.split("|") if c.strip()]
        if len(pipe_cells) >= 3 and _looks_like_qno(pipe_cells[0]):
            q_no = _clean_qno(pipe_cells[0])
            body = pipe_cells[1]
            remaining = " ".join(pipe_cells[2:])
            clean_body, marks, co, rbt, po = _extract_meta_tokens(f"{body} {remaining}")
            
            main_num = re.match(r"^(\d+)", q_no)
            detected_main = main_num.group(1) if main_num else current_main
            if pending_or:
                is_or_branch = True
                current_or_group = f"Q{current_main}"
                pending_or = False
            elif detected_main != current_main:
                is_or_branch = False
                current_or_group = None
            current_main = detected_main

            refers = _check_figure_ref(clean_body)
            questions.append(
                QuestionItem(
                    q_no=q_no,
                    question_text=clean_body,
                    allocated_marks=marks,
                    stated_co=co,
                    stated_po=po,
                    stated_blooms=rbt,
                    module=current_module,
                    is_or_choice=is_or_branch,
                    or_group=current_or_group if is_or_branch else None,
                    refers_to_figure=refers,
                    has_diagram=False,
                    set_label=set_label,
                )
            )
            continue

        # Match Sub-question row: "1 a) ...", "1a. ...", "a) ...", "1 (a) ..."
        sub = re.match(
            r"^(?:(?:q(?:uestion)?\s*)?(\d{1,2})\s*[\.\-\)]?\s*)?\(?([a-h])\)?[.\:\-\)]\s*(.+)$",
            raw,
            re.I,
        )
        # Match Main question row: "1) ...", "Q1. ...", "1. ..."
        main = re.match(r"^(?:q(?:uestion)?\s*)?(\d{1,2})[\).\:\-]\s*(.*)$", raw, re.I)

        q_no = None
        body = None

        if sub:
            prefix_num = sub.group(1)
            letter = sub.group(2).lower()
            detected_main = prefix_num if prefix_num else current_main
            if pending_or:
                is_or_branch = True
                current_or_group = f"Q{current_main}"
                pending_or = False
            elif detected_main != current_main:
                is_or_branch = False
                current_or_group = None
            current_main = detected_main
            q_no = f"{current_main}{letter}"
            body = sub.group(3)
        elif main:
            rest = main.group(2).strip()
            # If section instruction line, skip
            if rest.lower().startswith(("answer any", "note:", "each question", "compulsory")):
                current_main = main.group(1)
                continue
            
            # Check if this main question line actually embeds sub-question: "1 a) ..."
            nested_sub = re.match(r"^\(?([a-h])\)?[.\:\-\)]\s*(.+)$", rest, re.I)
            if nested_sub:
                detected_main = main.group(1)
                if pending_or:
                    is_or_branch = True
                    current_or_group = f"Q{current_main}"
                    pending_or = False
                elif detected_main != current_main:
                    is_or_branch = False
                    current_or_group = None
                current_main = detected_main
                q_no = f"{current_main}{nested_sub.group(1).lower()}"
                body = nested_sub.group(2)
            else:
                detected_main = main.group(1)
                if pending_or:
                    is_or_branch = True
                    current_or_group = f"Q{current_main}"
                    pending_or = False
                elif detected_main != current_main:
                    is_or_branch = False
                    current_or_group = None
                current_main = detected_main
                q_no = f"{current_main}a" if " " in rest else current_main
                body = rest
        else:
            continue

        if not body or len(body.strip()) < 5:
            continue

        clean_body, marks, co, rbt, po = _extract_meta_tokens(body)
        refers = _check_figure_ref(clean_body)

        questions.append(
            QuestionItem(
                q_no=q_no,
                question_text=clean_body,
                allocated_marks=marks,
                stated_co=co,
                stated_po=po,
                stated_blooms=rbt,
                module=current_module,
                is_or_choice=is_or_branch,
                or_group=current_or_group if is_or_branch else None,
                refers_to_figure=refers,
                has_diagram=False,
                set_label=set_label,
            )
        )

    if not questions:
        questions = _parse_ocr_action_questions(lines, current_module, set_label)

    return _dedupe_keep_order(questions)


def split_sets(text: str) -> dict[str, str]:
    """Split one paper text containing 'SET A' / 'SET B' headings into per-set bodies."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        marker = SET_HEADING.match(re.sub(r"[ \t]+", " ", raw).strip())
        if marker:
            current = marker.group(1).upper()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(raw)
    return {k: "\n".join(v).strip() for k, v in out.items() if "\n".join(v).strip()}


def _parse_ocr_action_questions(
    lines: list[str],
    default_module: str | None = None,
    set_label: str | None = None,
) -> list[QuestionItem]:
    """Fallback parser for OCR scanned question papers where column numbers were separated from text."""
    action_verbs = r"^(?:Describe|Draw|Develop|Explain|Analyze|Analyse|Define|Write|List|Compute|Design|Discuss|Illustrate|Compare|Construct|State)\b"
    questions: list[QuestionItem] = []
    current_q_lines: list[str] = []
    is_or = False
    current_module = default_module
    q_counter = 1

    full_text = "\n".join(lines)
    cos_found = [f"CO{c}" for c in re.findall(r"\bCO\s*([1-6])\b", full_text, re.I)]
    rbts_found = [f"L{r}" for r in re.findall(r"\bL\s*([1-6])\b", full_text, re.I)]

    def _flush_question(q_lines: list[str], or_flag: bool, idx: int):
        if not q_lines:
            return
        full_stem = " ".join(q_lines)
        clean_stem, marks, co, rbt, po = _extract_meta_tokens(full_stem)
        if not marks:
            marks = 10
        if not co and idx - 1 < len(cos_found):
            co = cos_found[idx - 1]
        if not rbt and idx - 1 < len(rbts_found):
            rbt = rbts_found[idx - 1]
        refers = _check_figure_ref(clean_stem)
        questions.append(
            QuestionItem(
                q_no=str(idx),
                question_text=clean_stem,
                allocated_marks=marks,
                stated_co=co,
                stated_po=po,
                stated_blooms=rbt,
                module=current_module,
                is_or_choice=or_flag,
                or_group=f"Q{idx - 1}" if or_flag else None,
                refers_to_figure=refers,
                has_diagram=False,
                set_label=set_label,
            )
        )

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        mod = re.search(r"(?:module|unit)\s*([ivx0-9]+)", line_clean, re.I)
        if mod and len(line_clean) < 50:
            current_module = _normalize_module(line_clean)
            continue
        if re.fullmatch(r"(?:-{2,}\s*)?\(?(?:OR|O\s*R)\)?(?:\s*-{2,})?", line_clean, re.I):
            if current_q_lines:
                _flush_question(current_q_lines, is_or, q_counter)
                q_counter += 1
                current_q_lines = []
            is_or = True
            continue
        if re.match(action_verbs, line_clean, re.I):
            if current_q_lines:
                _flush_question(current_q_lines, is_or, q_counter)
                q_counter += 1
                current_q_lines = []
                is_or = False
            current_q_lines.append(line_clean)
        elif current_q_lines:
            # Skip stray table column numbers from OCR
            if re.fullmatch(r"\d{1,2}", line_clean):
                continue
            current_q_lines.append(line_clean)

    if current_q_lines:
        _flush_question(current_q_lines, is_or, q_counter)

    return _dedupe_keep_order(questions)


def _looks_like_qno(token: str) -> bool:
    clean = re.sub(r"[\s\.\)\(\:\-]", "", token).lower()
    return bool(re.match(r"^(?:q)?\d{1,2}[a-h]?$", clean, re.I))


def _clean_qno(token: str) -> str:
    clean = re.sub(r"[\s\.\)\(\:\-]", "", token).lower()
    clean = re.sub(r"^q", "", clean)
    return clean


def _check_figure_ref(text: str) -> bool:
    for pat in FIGURE_KEYWORDS:
        if re.search(pat, text, re.I):
            return True
    return False


def _clean_question_text(text: str) -> str:
    # Remove metadata remnants
    text = re.sub(r"\bCO\s*[1-6]\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:RBT\s*|BT\s*|BL\s*)?L\s*[1-6]\b", "", text, flags=re.I)
    text = re.sub(r"\[\d{1,2}\s*(?:marks?|m)?\]", "", text, flags=re.I)
    text = re.sub(r"\(\d{1,2}\s*(?:marks?|m)?\)", "", text, flags=re.I)
    text = re.sub(r"\b\d{1,2}\s*marks?\b", "", text, flags=re.I)
    text = re.sub(r"\s+\|\s+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" -:|,")


def _normalize_module(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"(?:module|unit)\s*([ivx0-9]+)", raw, re.I)
    if not m:
        return "Module 1"
    token = m.group(1).lower()
    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
    num = roman.get(token, token)
    return f"Module {num}"


def _dedupe_keep_order(items: list[QuestionItem]) -> list[QuestionItem]:
    seen_stems: set[str] = set()
    out: list[QuestionItem] = []
    idx = 1
    for item in items:
        # Normalize stem by alphanumeric characters to prevent duplicate questions from repeated file uploads
        stem_norm = re.sub(r"[^a-z0-9]", "", item.question_text.lower())[:65] if item.question_text else ""
        if not stem_norm or stem_norm in seen_stems:
            continue
        seen_stems.add(stem_norm)
        
        # If the question number was a generated integer > len, re-index cleanly
        clean_item = item.model_copy()
        if re.fullmatch(r"\d+", item.q_no) and int(item.q_no) > len(items):
            clean_item.q_no = str(idx)
        out.append(clean_item)
        idx += 1
    return out


def parse_syllabus_units(text: str) -> dict[str, str]:
    units: dict[str, str] = {}
    current = "General"
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        
        # Check for multi-file document separation banner
        doc_match = re.search(r"===\s*\[DOCUMENT:\s*(.+?)\]\s*===", stripped, re.I)
        if doc_match:
            doc_name = doc_match.group(1).lower()
            mod_num_m = re.search(r"(?:module|mod|unit|sem)[\s\-_]*([1-6])\b", doc_name)
            if mod_num_m:
                if buf:
                    units[current] = "\n".join(buf).strip()
                current = f"Module {mod_num_m.group(1)}"
                buf = [line]
                continue

        m = re.search(r"^(?:module|unit)\s*([ivx0-9]+)", stripped, re.I)
        if m and len(stripped) < 100:
            if buf:
                units[current] = "\n".join(buf).strip()
            current = _normalize_module(stripped)
            buf = [line]
        else:
            buf.append(line)
    if buf:
        units[current] = "\n".join(buf).strip()
    if len(units) <= 1:
        units["Full Syllabus"] = text
    return units
