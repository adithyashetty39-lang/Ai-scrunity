"""RAG-style syllabus / CO / PO alignment agent (TF-IDF cosine + optional Gemini)."""

from __future__ import annotations

import re

from app.graph.state import ScrutinyState
from app.services.llm import generate_json, llm_available
from app.services.obe import (
    audit_programme_outcomes,
    build_co_po_matrix,
    load_obe_map,
)
from app.services.parser import parse_syllabus_units
from app.services.vectorstore import (
    build_syllabus_index,
    extract_co_descriptions,
    historical_matches,
)

IN_SYLLABUS_THRESHOLD = 0.07


def syllabus_node(state: ScrutinyState) -> dict:
    syllabus = state.get("syllabus_text") or ""
    allowed = [_norm_unit(u) for u in (state.get("allowed_units") or [])]
    index = build_syllabus_index(syllabus)
    units = parse_syllabus_units(syllabus)
    cos = extract_co_descriptions(syllabus)
    obe_map = load_obe_map((state.get("metadata") or {}).get("course_code"))

    set_a = state.get("parsed_questions") or []
    set_b = state.get("parsed_questions_b") or []

    audits_a = _audit_set(set_a, index, allowed, cos, obe_map, syllabus)
    result: dict = {
        "question_audits": audits_a,
        "unit_weightage": _unit_weightage(set_a, audits_a),
        "co_po_matrix": build_co_po_matrix(set_a, obe_map),
        "llm_used": llm_available(),
        "_units_indexed": list(units.keys()),
    }

    if set_b:
        audits_b = _audit_set(set_b, index, allowed, cos, obe_map, syllabus)
        result.update(
            {
                "question_audits_b": audits_b,
                "unit_weightage_b": _unit_weightage(set_b, audits_b),
                "co_po_matrix_b": build_co_po_matrix(set_b, obe_map),
            }
        )
    return result


def _audit_set(
    questions: list[dict],
    index,
    allowed: list[str],
    cos: dict[str, str],
    obe_map: dict[str, list[str]],
    syllabus: str = "",
) -> list[dict]:
    llm_batch = _llm_align(questions, syllabus, allowed, cos) if llm_available() and questions else {}

    allowed_cos = set()
    for u in allowed:
        num = re.search(r"\d+", u)
        if num:
            allowed_cos.add(f"CO{num.group(0)}")

    audits: list[dict] = []
    for q in questions:
        hits = index.query(q.get("question_text", ""), k=3)
        best_unit, score, _ = hits[0] if hits else ("", 0.0, "")
        in_syllabus = score >= IN_SYLLABUS_THRESHOLD
        unit_allowed = True
        if allowed and best_unit:
            unit_allowed = _norm_unit(best_unit) in allowed or best_unit == "Full Syllabus"
            if not unit_allowed:
                in_syllabus = False

        predicted_co = _match_co(q.get("question_text", ""), cos, best_unit)
        stated = (q.get("stated_co") or "").upper().replace(" ", "")
        co_match = True
        if stated and predicted_co:
            co_match = stated == predicted_co

        po_result = audit_programme_outcomes(q, predicted_co, obe_map)

        hist = historical_matches(q.get("question_text", ""))
        issues: list[str] = []
        if not in_syllabus:
            issues.append(
                f"Question topic outside prescribed {', '.join(allowed) or 'allowed units'} "
                f"(best match: {best_unit or 'none'} @ {score:.2f})."
            )
        if stated and predicted_co and not co_match:
            issues.append(f"Mapped {stated} but topic aligns more closely with {predicted_co}.")
        if stated and allowed_cos and stated not in allowed_cos:
            issues.append(
                f"Course Outcome {stated} is outside the prescribed CIE scope ({', '.join(sorted(allowed_cos))})."
            )
        issues.extend(po_result["issues"])

        overlap = None
        if hist:
            hid, hscore = hist[0]
            overlap = f"{hid} ({hscore:.0%})"
            if hscore >= 0.80:
                issues.append(f"High overlap with historical paper {overlap}.")

        llm_row = llm_batch.get(str(q.get("q_no")), {})
        if llm_row:
            in_syllabus = bool(llm_row.get("is_in_syllabus", in_syllabus))
            best_unit = llm_row.get("matched_syllabus_unit") or best_unit
            predicted_co = llm_row.get("predicted_co") or predicted_co
            if llm_row.get("issues"):
                issues.extend(llm_row["issues"])

        audits.append(
            {
                "q_no": q.get("q_no"),
                "is_in_syllabus": in_syllabus,
                "matched_syllabus_unit": best_unit or None,
                "syllabus_score": round(float(score), 3),
                "co_match": co_match if stated else True,
                "predicted_co": predicted_co,
                "po_match": po_result["po_match"],
                "predicted_po": po_result["predicted_po"],
                "historical_overlap": overlap,
                "is_duplicate": bool(hist and hist[0][1] >= 0.80),
                "syllabus_issues": issues,
            }
        )
    return audits


def _unit_weightage(questions: list[dict], audits: list[dict]) -> dict[str, float]:
    coverage: dict[str, float] = {}
    total_marks = sum(int(q.get("allocated_marks") or 0) for q in questions) or 1
    for q, a in zip(questions, audits):
        unit = a.get("matched_syllabus_unit") or "Unmapped"
        coverage[unit] = coverage.get(unit, 0) + int(q.get("allocated_marks") or 0)
    return {k: round(v / total_marks, 3) for k, v in coverage.items()}


def _norm_unit(u: str) -> str:
    return " ".join(u.lower().replace("unit", "module").split())


def _match_co(question: str, cos: dict[str, str], best_unit: str = "") -> str | None:
    if best_unit:
        num = re.search(r"\d+", best_unit)
        if num:
            co_cand = f"CO{num.group(0)}"
            if co_cand in cos or not cos:
                return co_cand
    if not cos:
        return None
    from app.services.vectorstore import CorpusIndex

    idx = CorpusIndex([(k, v) for k, v in cos.items()])
    hits = idx.query(question, k=1)
    if hits and hits[0][1] >= 0.05:
        return hits[0][0]
    return None


def _llm_align(questions: list[dict], syllabus: str, allowed: list[str], cos: dict[str, str]) -> dict:
    payload = [
        {"q_no": q.get("q_no"), "text": q.get("question_text"), "stated_co": q.get("stated_co")}
        for q in questions
    ]
    data = generate_json(
        prompt=(
            f"Allowed units for this CIE: {allowed}\n\nSYLLABUS:\n{syllabus[:8000]}\n\n"
            f"COURSE OUTCOMES:\n{cos}\n\nQUESTIONS:\n{payload}\n\n"
            "For each question return JSON object keyed by q_no: "
            "{is_in_syllabus: bool, matched_syllabus_unit: str, predicted_co: str, issues: [str]}."
        ),
        system="You are a university academic auditor. Be strict about module boundaries.",
    )
    return data if isinstance(data, dict) else {}
