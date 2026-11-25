"""Deterministic structural & arithmetic validator."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from app.graph.state import ScrutinyState


def arithmetic_node(state: ScrutinyState) -> dict:
    errors = _check_set(
        state.get("parsed_questions") or [],
        int(state.get("max_marks") or 50),
        (state.get("metadata") or {}).get("max_marks"),
    )
    payload: dict = {"arithmetic_errors": errors}
    if state.get("parsed_questions_b"):
        payload["arithmetic_errors_b"] = _check_set(
            state.get("parsed_questions_b") or [],
            int(state.get("max_marks") or 50),
            (state.get("metadata_b") or {}).get("max_marks"),
        )
    return payload


def _check_set(questions: list[dict], max_marks: int, paper_declared) -> list[str]:
    errors: list[str] = []

    if not questions:
        return ["No questions available for arithmetic validation."]

    # Sub-question sums per main question
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        main = re.match(r"^(\d+)", str(q.get("q_no", "")))
        key = main.group(1) if main else str(q.get("q_no"))
        groups[key].append(q)

    has_or_in_paper = any(q.get("is_or_choice") for q in questions)

    for main, items in sorted(groups.items()):
        unmarked = [i["q_no"] for i in items if not i.get("allocated_marks")]
        if unmarked:
            errors.append(f"Q{main}: missing marks on sub-question(s) {', '.join(unmarked)}.")

        ors = [i for i in items if i.get("is_or_choice")]
        mains = [i for i in items if not i.get("is_or_choice")]
        sum_main = sum(int(i.get("allocated_marks") or 0) for i in mains)
        sum_or = sum(int(i.get("allocated_marks") or 0) for i in ors)

        if ors and sum_or and sum_main and sum_or != sum_main:
            errors.append(
                f"Q{main}: OR-choice total ({sum_or} marks) does not match primary option ({sum_main} marks)."
            )

        if has_or_in_paper and not ors and items and len(groups) > 1:
            errors.append(
                f"Q{main}: has no internal choice / OR option (unbalanced choice structure across modules)."
            )

        if ors and mains:
            p_cos = {p.get("stated_co") for p in mains if p.get("stated_co")}
            o_cos = {p.get("stated_co") for p in ors if p.get("stated_co")}
            if p_cos and o_cos and p_cos.isdisjoint(o_cos):
                errors.append(
                    f"Q{main}: OR option maps to disjoint Course Outcomes ({sorted(o_cos)}) vs primary ({sorted(p_cos)})."
                )

    for i, a in enumerate(questions):
        for b in questions[i + 1 :]:
            ratio = SequenceMatcher(
                None, a.get("question_text", "").lower(), b.get("question_text", "").lower()
            ).ratio()
            if ratio >= 0.82:
                errors.append(
                    f"Near-duplicate questions {a.get('q_no')} and {b.get('q_no')} (similarity {ratio:.0%})."
                )

    attempt_marks = _estimate_attempt_total(questions, groups)
    if attempt_marks and abs(attempt_marks - max_marks) > 0:
        errors.append(
            f"Estimated attempt total is {attempt_marks} marks; CIE requirement is {max_marks} marks."
        )

    if paper_declared and int(paper_declared) != max_marks:
        errors.append(
            f"Header Max Marks ({paper_declared}) differs from CIE requirement ({max_marks})."
        )

    return errors


def _estimate_attempt_total(questions: list[dict], groups: dict[str, list[dict]]) -> int:
    """If OR choices exist, student answers one branch per main question."""
    total = 0
    for items in groups.values():
        prim = [i for i in items if not i.get("is_or_choice")]
        ors = [i for i in items if i.get("is_or_choice")]
        prim_sum = sum(int(i.get("allocated_marks") or 0) for i in prim)
        or_sum = sum(int(i.get("allocated_marks") or 0) for i in ors)
        total += max(prim_sum, or_sum) if ors else prim_sum
    if total:
        return total
    return sum(int(q.get("allocated_marks") or 0) for q in questions)
