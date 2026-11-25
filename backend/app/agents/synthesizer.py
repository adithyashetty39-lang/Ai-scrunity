"""Chief scrutiny synthesizer — merge branches into per-set verdicts, checklists and the printed form."""

from __future__ import annotations

from collections import defaultdict

from app.graph.state import ScrutinyState
from app.services.form_builder import build_form, evaluate_set
from app.services.llm import generate_text, llm_available
from app.services.obe import (
    audit_assessment_plan,
    build_co_po_matrix,
    load_obe_map,
    parse_assessment_plan,
)


def synthesizer_node(state: ScrutinyState) -> dict:
    set_a = _evaluate(
        state,
        "A",
        questions=state.get("parsed_questions") or [],
        audits=state.get("question_audits") or [],
        blooms_audits=state.get("blooms_audits") or [],
        arithmetic_errors=state.get("arithmetic_errors") or [],
        rbt_dist=state.get("overall_rbt_distribution") or {},
        hots=float(state.get("hots_percentage") or 0),
        metadata=state.get("metadata") or {},
    )
    set_b = _evaluate(
        state,
        "B",
        questions=state.get("parsed_questions_b") or [],
        audits=state.get("question_audits_b") or [],
        blooms_audits=state.get("blooms_audits_b") or [],
        arithmetic_errors=state.get("arithmetic_errors_b") or [],
        rbt_dist=state.get("overall_rbt_distribution_b") or {},
        hots=float(state.get("hots_percentage_b") or 0),
        metadata=state.get("metadata_b") or state.get("metadata") or {},
    )

    checklists = {"A": set_a["checklist"]}
    if set_b["present"]:
        checklists["B"] = set_b["checklist"]

    fails = sum(1 for c in set_a["checklist"] if c["status"] == "FAIL")
    if set_b["present"]:
        fails += sum(1 for c in set_b["checklist"] if c["status"] == "FAIL")
    verdict = "APPROVED" if fails == 0 else "NEEDS_REVISION"

    form = build_form(
        {
            **(state.get("metadata") or {}),
            "academic_year": state.get("academic_year"),
            "ia_test_no": state.get("ia_test_no"),
        },
        set_a["form_set"],
        set_b["form_set"],
    )

    summary = _summary(state, set_a["merged"] + set_b["merged"], verdict, set_a["checklist"])

    return {
        "question_audits": set_a["merged"],
        "checklist": set_a["checklist"],
        "set_checklists": checklists,
        "final_verdict": verdict,
        "executive_summary": summary,
        "co_coverage": state.get("unit_weightage") or set_a["unit_weightage"],
        "unit_weightage": state.get("unit_weightage") or set_a["unit_weightage"],
        "co_coverage_b": state.get("unit_weightage_b") or set_b["unit_weightage"],
        "rbt_counts": state.get("rbt_counts") or {},
        "form": form.model_dump(),
        "llm_used": bool(state.get("llm_used") or llm_available()),
    }


def _evaluate(
    state: ScrutinyState,
    label: str,
    questions: list[dict],
    audits: list[dict],
    blooms_audits: list[dict],
    arithmetic_errors: list[str],
    rbt_dist: dict,
    hots: float,
    metadata: dict,
) -> dict:
    threshold = float(state.get("hots_threshold") or 0.4)
    allowed_units = state.get("allowed_units") or []
    max_marks = int(state.get("max_marks") or 50)

    merged = _merge(questions, audits, blooms_audits)
    unit_weightage = state.get("unit_weightage_b") if label == "B" else state.get("unit_weightage")
    if not unit_weightage:
        unit_weightage = _unit_weightage(questions, audits)

    plan = parse_assessment_plan(
        state.get("assessment_plan") or "",
        allowed_units,
        max_marks,
        int(state.get("answer_any_n") or 1),
    )
    plan_result = audit_assessment_plan(merged, plan, allowed_units, max_marks)
    obe_map = load_obe_map(metadata.get("course_code"))
    obe_result = {"co_po_matrix": build_co_po_matrix(questions, obe_map)}

    checklist = _build_checklist(
        metadata=metadata,
        audits=merged,
        arithmetic_errors=arithmetic_errors,
        formatting_anomalies=state.get("formatting_anomalies") or [],
        hots=hots,
        threshold=threshold,
        plan_result=plan_result,
        rbt_dist=rbt_dist,
    )

    form_set = evaluate_set(
        set_label=label,
        questions=questions,
        audits=merged,
        arithmetic_errors=arithmetic_errors,
        hots_percentage=hots,
        hots_threshold=threshold,
        plan_result=plan_result,
        obe_result=obe_result,
        header_issues=metadata.get("header_issues") or [],
        formatting_anomalies=state.get("formatting_anomalies") or [],
    )

    return {
        "present": bool(questions),
        "merged": merged,
        "checklist": checklist,
        "form_set": form_set,
        "unit_weightage": unit_weightage,
        "plan_result": plan_result,
    }


def _merge(questions: list[dict], syll_audits: list[dict], bloom_audits: list[dict]) -> list[dict]:
    s_map = {a.get("q_no"): a for a in syll_audits}
    b_map = {a.get("q_no"): a for a in bloom_audits}
    merged = []
    for q in questions:
        qn = q.get("q_no")
        s = s_map.get(qn, {})
        b = b_map.get(qn, {})
        issues: list[str] = []
        issues.extend(s.get("syllabus_issues") or [])
        issues.extend(b.get("blooms_issues") or [])
        merged.append(
            {
                "q_no": qn,
                "question_text": q.get("question_text"),
                "allocated_marks": q.get("allocated_marks"),
                "stated_co": q.get("stated_co"),
                "stated_po": q.get("stated_po"),
                "stated_blooms": q.get("stated_blooms"),
                "module": q.get("module"),
                "set_label": q.get("set_label"),
                "is_in_syllabus": s.get("is_in_syllabus", True),
                "matched_syllabus_unit": s.get("matched_syllabus_unit"),
                "syllabus_score": s.get("syllabus_score", 0),
                "predicted_blooms": b.get("predicted_blooms", ""),
                "blooms_match": b.get("blooms_match", True),
                "blooms_quality_verdict": b.get("blooms_quality_verdict", ""),
                "co_match": s.get("co_match", True),
                "predicted_co": s.get("predicted_co"),
                "po_match": s.get("po_match", True),
                "predicted_po": s.get("predicted_po"),
                "is_duplicate": s.get("is_duplicate", False),
                "historical_overlap": s.get("historical_overlap"),
                "issues_found": issues,
                "suggested_rewrite": b.get("suggested_rewrite"),
                "upgraded_rewrite": b.get("upgraded_rewrite"),
            }
        )
    return merged


def _unit_weightage(questions: list[dict], audits: list[dict]) -> dict[str, float]:
    totals: dict[str, int] = defaultdict(int)
    for q, a in zip(questions, audits):
        unit = a.get("matched_syllabus_unit") or "Unmapped"
        totals[unit] += int(q.get("allocated_marks") or 0)
    denom = sum(totals.values()) or 1
    return {k: round(v / denom, 3) for k, v in sorted(totals.items())}


def _build_checklist(
    metadata: dict,
    audits: list[dict],
    arithmetic_errors: list[str],
    formatting_anomalies: list[str],
    hots: float,
    threshold: float,
    plan_result: dict,
    rbt_dist: dict,
) -> list[dict]:
    header_issues = metadata.get("header_issues") or []

    def item(category: str, check: str, status: str, detail: str) -> dict:
        return {"category": category, "check": check, "status": status, "detail": detail}

    out_of_syl = [a for a in audits if not a.get("is_in_syllabus")]
    rbt_mismatch = [a for a in audits if a.get("stated_blooms") and not a.get("blooms_match")]
    co_mismatch = [a for a in audits if not a.get("co_match")]
    po_mismatch = [a for a in audits if not a.get("po_match")]
    co_out_of_scope = [
        a for a in audits if any("outside the prescribed cie scope" in i.lower() for i in a.get("issues_found") or [])
    ]
    hist = [a for a in audits if a.get("is_duplicate")]
    missing_figs = [a for a in audits if any("figure" in i.lower() for i in a.get("issues_found") or [])]
    ambiguity_flags = [
        a for a in audits if any("vague" in i.lower() or "low-specificity" in i.lower() or "etc." in i.lower() or "classroom" in i.lower() for i in a.get("issues_found") or [])
    ]

    meta_status = "FAIL" if header_issues else "PASS"
    meta_detail = "; ".join(header_issues) if header_issues else f"Valid {metadata.get('course_code') or ''} header: Course Code, Title, Sem, Date, Duration, and Max Marks present."

    arith_status = "FAIL" if arithmetic_errors else "PASS"
    arith_detail = "; ".join(arithmetic_errors) if arithmetic_errors else "Mark arithmetic, sub-question sums, and choice parity verified."

    syl_status = "FAIL" if out_of_syl else "PASS"
    syl_detail = (
        f"Out of syllabus: {', '.join(a['q_no'] for a in out_of_syl)} (topics belong to unallowed modules)."
        if out_of_syl
        else "All questions strictly adhere to prescribed CIE module boundaries."
    )

    plan_issues = plan_result.get("issues") or []
    plan_status = "FAIL" if plan_issues else "PASS"
    plan_detail = "; ".join(plan_issues) if plan_issues else f"Conforms to the assessment plan ({plan_result.get('plan')})."

    if co_out_of_scope or co_mismatch or po_mismatch:
        co_status = "FAIL" if (co_out_of_scope or po_mismatch) else "WARN"
        flagged = [f"{a['q_no']} ({a['stated_co']})" for a in (co_out_of_scope or co_mismatch)]
        flagged += [f"{a['q_no']} (PO)" for a in po_mismatch]
        co_detail = f"CO/PO anomalies on {', '.join(flagged)}."
    else:
        co_status = "PASS"
        co_detail = "Course Outcomes and Programme Outcomes align with question content and prescribed CIE scope."

    rbt_status = "FAIL" if rbt_mismatch else "PASS"
    rbt_detail = (
        f"Cognitive level mismatch on {', '.join(a['q_no'] for a in rbt_mismatch)} (action verbs conflict with stated RBT level)."
        if rbt_mismatch
        else "Stated Bloom's levels accurately reflect action verbs and cognitive load."
    )

    hots_ok = (hots + 1e-9 >= threshold)
    hots_status = "PASS" if hots_ok else "FAIL"
    hots_detail = f"HOTS (L3+) mark share is {hots:.0%} (institutional threshold: {int(threshold * 100)}%)."

    quality_issues = []
    if missing_figs:
        quality_issues.append(f"Missing diagram/figure on {', '.join(a['q_no'] for a in missing_figs)}")
    if ambiguity_flags:
        quality_issues.append(f"Ambiguous phrasing on {', '.join(a['q_no'] for a in ambiguity_flags)}")
    if formatting_anomalies:
        quality_issues.extend(formatting_anomalies)

    qual_status = "FAIL" if missing_figs else ("WARN" if quality_issues else "PASS")
    qual_detail = "; ".join(quality_issues) if quality_issues else "No diagram omissions, typographical errors, or ambiguity defects detected."

    hist_ratio = len(hist) / max(len(audits), 1)
    if hist_ratio >= 0.50:
        hist_status = "FAIL"
        hist_detail = f"High recycling rate: {len(hist)} questions ({hist_ratio:.0%}) copy-pasted from past CIEs ({', '.join(a['q_no'] for a in hist)})."
    elif hist:
        hist_status = "WARN"
        hist_detail = f"{len(hist)} question(s) ({hist_ratio:.0%}) match prior papers ({', '.join(a['q_no'] for a in hist)})."
    else:
        hist_status = "PASS"
        hist_detail = "Paper exhibits low overlap with previous 3 years of indexed CIE papers."

    return [
        item("Metadata & Header", "Course code, title, semester, date, duration, max marks present", meta_status, meta_detail),
        item("Mark Distribution", "Sub-question sums, OR-choice parity, attempt total vs CIE max marks", arith_status, arith_detail),
        item("Syllabus Compliance", "Every question maps to allowed CIE modules", syl_status, syl_detail),
        item("Assessment Plan", "Question structure and module weightage follow the assessment plan", plan_status, plan_detail),
        item("CO & PO Mapping", "Stated CO/PO align with question topic and the articulation matrix", co_status, co_detail),
        item("Bloom's (RBT) Audit", "Stated RBT matches cognitive demand of the stem", rbt_status, rbt_detail),
        item("HOTS Threshold", f"Minimum {int(threshold * 100)}% marks at Higher-Order Thinking Skills (L3+)", hots_status, hots_detail),
        item("Quality & Formatting", "No missing figures, hidden text, or ambiguous phrasing", qual_status, qual_detail),
        item("Historical Deduplication", "Paper is not largely recycled from prior 3 years of CIEs", hist_status, hist_detail),
    ]


def _summary(state: ScrutinyState, audits: list[dict], verdict: str, checklist: list[dict]) -> str:
    fails = [c["category"] for c in checklist if c["status"] == "FAIL"]
    warns = [c["category"] for c in checklist if c["status"] == "WARN"]

    llm = generate_text(
        prompt=(
            f"Write a 120-word formal scrutiny memo for a college examination scrutiny committee.\n"
            f"Verdict: {verdict}\nFailed categories: {fails}\nWarnings: {warns}\n"
            f"HOTS share: {state.get('hots_percentage')}\nRBT: {state.get('overall_rbt_distribution')}\n"
            f"Key defects: {[a['issues_found'] for a in audits if a.get('issues_found')][:6]}\n"
            "Keep tone academic, authoritative, and actionable."
        )
    )
    if llm:
        return llm

    if verdict == "APPROVED":
        return (
            "The question paper meets institutional CIE requirements. Header completeness, mark arithmetic, "
            "module boundaries, and Bloom's Taxonomy cognitive distribution conform to accreditation standards. "
            "The paper is approved for examination administration."
        )

    fail_text = f"Defects detected in: {', '.join(fails)}." if fails else "Revisions recommended."
    return (
        f"SCRUTINY COMMITTEE VERDICT: NEEDS REVISION. {fail_text} "
        "Specific actions required: (1) Rectify cognitive level mismatches where lower-order stems are marked L3/L4; "
        "(2) Eliminate out-of-syllabus questions outside prescribed modules; (3) Restore mark distribution and internal choice parity; "
        "and (4) Provide missing figures and resolve ambiguous prompts before re-submission."
    )
