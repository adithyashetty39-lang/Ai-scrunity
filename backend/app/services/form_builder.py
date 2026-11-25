"""Build the printable Scrutiny Format payload from audit results."""

from __future__ import annotations

from app.config import (
    DEPARTMENT_NAME,
    FORM_TITLE,
    INSTITUTION_ADDRESS,
    INSTITUTION_NAME,
    INSTITUTION_SUB,
)
from app.schemas import FormCriterionRow, FormSetEvaluation, FormSignature, ScrutinyForm

CRITERIA = [
    "The Questions set are within the syllabus Covered",
    "Are questions as per assessment plan?",
    "Are all questions mapped to CO/ PO Properly?",
    "Are all questions distributed properly using Bloom's level?",
    "The marks for questions are properly distributed?",
    "Does it follow the format given?",
]

CONFIDENTIALITY = (
    "We hereby declare that the question papers reviewed during this scrutiny process will be treated as "
    "strictly confidential. We agree that the contents of the question papers, including the questions and "
    "related discussions, will not be disclosed or discussed with any teacher, student, or any other "
    "unauthorized person before the internal. We further assure that we will maintain complete confidentiality "
    "and uphold the integrity of the process."
)

RECOMMENDATIONS = [
    "Approved as it is",
    "Approved with minor changes",
    "Needs revision before approval",
]


def build_form(
    report: dict,
    set_a: FormSetEvaluation,
    set_b: FormSetEvaluation,
) -> ScrutinyForm:
    meta = report.get("metadata") or {}
    recommendation, selected = _decide_recommendation(set_a, set_b)

    return ScrutinyForm(
        institution=INSTITUTION_NAME,
        institution_sub=INSTITUTION_SUB,
        institution_address=INSTITUTION_ADDRESS,
        department=DEPARTMENT_NAME,
        form_title=FORM_TITLE,
        course_name=meta.get("course_title") or "",
        course_code=meta.get("course_code") or "",
        date=meta.get("date") or "",
        academic_year=meta.get("academic_year") or report.get("academic_year") or "",
        semester=meta.get("semester") or "",
        ia_test_no=meta.get("ia_test_no") or report.get("ia_test_no") or meta.get("cie_number") or "",
        set_a=set_a,
        set_b=set_b,
        scrutiny_recommendation=recommendation,
        selected_paper=selected,
        signatures=_default_signatures(report),
        confidentiality_note=CONFIDENTIALITY,
    )


def evaluate_set(
    set_label: str,
    questions: list[dict],
    audits: list[dict],
    arithmetic_errors: list[str],
    hots_percentage: float,
    hots_threshold: float,
    plan_result: dict,
    obe_result: dict,
    header_issues: list[str],
    formatting_anomalies: list[str],
) -> FormSetEvaluation:
    if not questions:
        return FormSetEvaluation(
            set_label=set_label,
            present=False,
            rows=[
                FormCriterionRow(
                    criterion=c,
                    answer="No",
                    comments="Set not submitted for scrutiny.",
                )
                for c in CRITERIA
            ],
            overall_comments=[],
        )

    out_of_syllabus = [a["q_no"] for a in audits if not a.get("is_in_syllabus", True)]
    co_bad = [a["q_no"] for a in audits if not a.get("co_match", True)]
    po_bad = [a["q_no"] for a in audits if not a.get("po_match", True)]
    rbt_bad = [a["q_no"] for a in audits if a.get("stated_blooms") and not a.get("blooms_match", True)]
    plan_issues = plan_result.get("issues") or []
    hots_ok = hots_percentage + 1e-9 >= hots_threshold

    rows = [
        FormCriterionRow(
            criterion=CRITERIA[0],
            answer="No" if out_of_syllabus else "Yes",
            comments=(
                f"Out of syllabus on {', '.join(out_of_syllabus)}."
                if out_of_syllabus
                else "All questions fall within the prescribed modules."
            ),
        ),
        FormCriterionRow(
            criterion=CRITERIA[1],
            answer="No" if plan_issues else "Yes",
            comments=(
                "; ".join(plan_issues[:2])
                if plan_issues
                else f"Conforms to the assessment plan ({plan_result.get('plan') or 'module weightage verified'})."
            ),
        ),
        FormCriterionRow(
            criterion=CRITERIA[2],
            answer="No" if (co_bad or po_bad) else "Yes",
            comments=_co_po_comment(co_bad, po_bad, obe_result),
        ),
        FormCriterionRow(
            criterion=CRITERIA[3],
            answer="No" if (rbt_bad or not hots_ok) else "Yes",
            comments=_blooms_comment(rbt_bad, hots_percentage, hots_threshold),
        ),
        FormCriterionRow(
            criterion=CRITERIA[4],
            answer="No" if arithmetic_errors else "Yes",
            comments=(
                "; ".join(arithmetic_errors[:2])
                if arithmetic_errors
                else "Sub-question sums, choice parity and attempt total verified."
            ),
        ),
        FormCriterionRow(
            criterion=CRITERIA[5],
            answer="No" if (header_issues or formatting_anomalies) else "Yes",
            comments=(
                "; ".join((header_issues + formatting_anomalies)[:2])
                if (header_issues or formatting_anomalies)
                else "Header, numbering and Bloom's/CO annotations follow the prescribed format."
            ),
        ),
    ]

    return FormSetEvaluation(
        set_label=set_label,
        present=True,
        rows=rows,
        overall_comments=_overall_comments(rows, out_of_syllabus, co_bad, po_bad, rbt_bad, arithmetic_errors, hots_percentage),
    )


def _co_po_comment(co_bad: list[str], po_bad: list[str], obe_result: dict) -> str:
    parts = []
    if co_bad:
        parts.append(f"CO mismatch on {', '.join(co_bad)}")
    if po_bad:
        parts.append(f"PO mapping not articulated on {', '.join(po_bad)}")
    if not parts:
        covered = ", ".join(sorted((obe_result.get("co_po_matrix") or {}).keys()))
        return f"Every question is mapped to the correct CO and PO ({covered or 'matrix verified'})."
    return "; ".join(parts) + "."


def _blooms_comment(rbt_bad: list[str], hots: float, threshold: float) -> str:
    parts = []
    if rbt_bad:
        parts.append(f"stated level not supported by the stem on {', '.join(rbt_bad)}")
    if hots + 1e-9 < threshold:
        parts.append(f"HOTS share is {hots:.0%} against the required {threshold:.0%}")
    if not parts:
        return f"L1-L6 spread is balanced; HOTS share is {hots:.0%}."
    return "; ".join(parts) + "."


def _overall_comments(
    rows: list[FormCriterionRow],
    out_of_syllabus: list[str],
    co_bad: list[str],
    po_bad: list[str],
    rbt_bad: list[str],
    arithmetic_errors: list[str],
    hots: float,
) -> list[str]:
    comments: list[str] = []
    if out_of_syllabus:
        comments.append(f"Questions {', '.join(out_of_syllabus)} are outside the prescribed modules and must be replaced.")
    if co_bad or po_bad:
        comments.append(f"Revise the CO/PO annotation on {', '.join(sorted(set(co_bad + po_bad)))}.")
    if rbt_bad:
        comments.append(f"Re-word or re-label the stated Bloom's level on {', '.join(rbt_bad)}.")
    if arithmetic_errors:
        comments.append("Correct the mark distribution and internal-choice parity.")
    if len(comments) < 3:
        failed = [r.criterion for r in rows if r.answer == "No"]
        if failed:
            comments.append(f"Address the remaining gaps under: {failed[0]}.")
        else:
            comments.append(f"The set is acceptable; HOTS share is {hots:.0%}.")
    if len(comments) < 3:
        comments.append("Resubmit the revised set with corrected annotations for re-scrutiny.")
    return comments[:3]


def _decide_recommendation(set_a: FormSetEvaluation, set_b: FormSetEvaluation) -> tuple[str, str]:
    present = [s for s in (set_a, set_b) if s.present]
    if not present:
        return RECOMMENDATIONS[2], ""

    counts = {s.set_label: sum(1 for r in s.rows if r.answer == "No") for s in present}
    total_failures = sum(counts.values())
    if total_failures == 0:
        recommendation = RECOMMENDATIONS[0]
    elif total_failures <= 2:
        recommendation = RECOMMENDATIONS[1]
    else:
        recommendation = RECOMMENDATIONS[2]

    selected = ""
    if len(present) == 2:
        a, b = counts.get("A", 99), counts.get("B", 99)
        if a < b:
            selected = "Set A"
        elif b < a:
            selected = "Set B"
    return recommendation, selected


def _default_signatures(report: dict) -> list[FormSignature]:
    date = (report.get("metadata") or {}).get("date") or ""
    return [
        FormSignature(role="Subject Expert 1", signature_date=date),
        FormSignature(role="Subject Expert 2", signature_date=date),
        FormSignature(role="Scrutiny Chair", signature_date=date),
    ]
