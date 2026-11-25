"""Pedagogical & Revised Bloom's Taxonomy auditor."""

from __future__ import annotations

import re

from app.graph.state import ScrutinyState
from app.services.blooms_rubric import LEVEL_NAMES, LEVEL_ORDER, normalize_level, predict_blooms
from app.services.llm import generate_json, llm_available

AMBIGUOUS = [
    (r"\bexplain briefly\b", "Vague instruction 'explain briefly' — specify required depth or parameters."),
    (r"\bwrite a short note\b", "Low-specificity prompt 'write a short note' — replace with a concrete cognitive task."),
    (r"\betc\.?\b", "Open-ended 'etc.' creates marking ambiguity; define all expected items."),
    (r"\bas discussed in class\b", "Relies on unstated classroom context; supply the complete scenario/graph in the question."),
]


def blooms_node(state: ScrutinyState) -> dict:
    result = _audit_set(state.get("parsed_questions") or [])
    payload = {
        "blooms_audits": result["audits"],
        "overall_rbt_distribution": result["distribution"],
        "rbt_counts": result["counts"],
        "hots_percentage": result["hots"],
        "lots_percentage": result["lots"],
    }
    if state.get("parsed_questions_b"):
        b = _audit_set(state.get("parsed_questions_b") or [])
        payload.update(
            {
                "blooms_audits_b": b["audits"],
                "overall_rbt_distribution_b": b["distribution"],
                "rbt_counts_b": b["counts"],
                "hots_percentage_b": b["hots"],
                "lots_percentage_b": b["lots"],
            }
        )
    return payload


def _audit_set(questions: list[dict]) -> dict:
    llm_rows = _llm_blooms(questions) if llm_available() and questions else {}
    results: list[dict] = []
    dist: dict[str, int] = {k: 0 for k in LEVEL_ORDER}
    rbt_counts: dict[str, int] = {k: 0 for k in LEVEL_ORDER}
    hots_marks = 0
    lots_marks = 0
    total_marks = 0

    for q in questions:
        text = q.get("question_text") or ""
        stated = normalize_level(q.get("stated_blooms") or "")
        predicted, verb = predict_blooms(text)
        llm = llm_rows.get(str(q.get("q_no")), {})
        if llm.get("predicted_blooms"):
            predicted = normalize_level(llm["predicted_blooms"]) or predicted

        blooms_match = True
        issues: list[str] = []
        quality_verdict = ""
        if stated and predicted:
            idx_stated = LEVEL_ORDER.index(stated)
            idx_pred = LEVEL_ORDER.index(predicted)
            if idx_stated == idx_pred:
                quality_verdict = f"Verified: Question demonstrates authentic {stated} ({LEVEL_NAMES.get(stated, stated)}) cognitive demand."
            elif idx_stated > idx_pred:
                blooms_match = False
                quality_verdict = (
                    f"Lacks {stated} Quality: Faculty marked {stated}, but action stem only demands {predicted} "
                    f"({LEVEL_NAMES.get(predicted, predicted)})" + (f" with verb '{verb}'." if verb else ".")
                )
                issues.append(
                    f"Cognitive level mismatch: Stated {stated} ({LEVEL_NAMES.get(stated, stated)}) "
                    f"but action stem indicates lower-order {predicted} ({LEVEL_NAMES.get(predicted, predicted)})"
                    + (f" with action verb '{verb}'" if verb else "")
                    + "."
                )
            else:
                quality_verdict = f"Under-labelled: Marked {stated}, but stem appears to demand {predicted}-level reasoning."
                issues.append(
                    f"Potential under-labelling: Stated {stated} but stem appears to demand {predicted}-level reasoning."
                )
        elif predicted:
            quality_verdict = f"Cognitive demand evaluated as {predicted} ({LEVEL_NAMES.get(predicted, predicted)})."

        if q.get("refers_to_figure") and not q.get("has_diagram"):
            issues.append("Question refers to a diagram/figure ('refer to figure...'), but no figure was detected.")

        if not re.search(r"[?.:]$", text.strip()):
            issues.append("Missing terminal punctuation (question mark or period).")

        for pat, msg in AMBIGUOUS:
            if re.search(pat, text, re.I):
                issues.append(msg)

        grammar_flags = llm.get("issues") or []
        issues.extend(grammar_flags)

        rewrite = llm.get("suggested_rewrite")
        upgraded = llm.get("upgraded_rewrite")
        if not rewrite and (not blooms_match or q.get("refers_to_figure") or any("short note" in i or "etc." in i for i in issues)):
            rewrite = _contextual_rewrite(text, stated or "L3", q.get("allocated_marks") or 5)
        if not upgraded:
            upgraded = _contextual_upgrade(text, stated or predicted or "L1", q.get("allocated_marks") or 5)

        marks = int(q.get("allocated_marks") or 0)
        level_for_dist = stated or predicted
        if level_for_dist in dist:
            dist[level_for_dist] += marks
            rbt_counts[level_for_dist] += 1
        total_marks += marks
        if (stated or predicted) in {"L3", "L4", "L5", "L6"}:
            hots_marks += marks
        else:
            lots_marks += marks

        results.append(
            {
                "q_no": q.get("q_no"),
                "question_text": text,
                "allocated_marks": marks,
                "stated_blooms": stated,
                "stated_co": q.get("stated_co") or "",
                "predicted_blooms": predicted,
                "blooms_match": blooms_match if stated else True,
                "blooms_quality_verdict": quality_verdict,
                "blooms_issues": issues,
                "suggested_rewrite": rewrite,
                "upgraded_rewrite": upgraded,
            }
        )

    denom = total_marks or 1
    return {
        "audits": results,
        "distribution": {k: round(v / denom, 3) for k, v in dist.items() if v},
        "counts": rbt_counts,
        "hots": round(hots_marks / denom, 3),
        "lots": round(lots_marks / denom, 3),
    }


def _contextual_rewrite(text: str, target_level: str, marks: int) -> str:
    low = text.lower()
    if "array" in low and ("define" in low or "list" in low):
        return (
            f"Given a 1D/2D array implementation, demonstrate row-major and column-major address calculation "
            f"for an element A[i][j] with base address 1000 and element size 4 bytes. Show complete working. ({marks} Marks, L3)"
        )
    if "sparse matrix" in low and "figure" in low:
        return (
            f"Given a 4x5 sparse matrix represented in 3-tuple format: (0,1,10), (1,3,25), (2,2,30), (3,0,5), "
            f"compute its transpose using the Fast Transpose algorithm. Show row_terms and starting_pos arrays. ({marks} Marks, L3)"
        )
    if "priority queue" in low:
        return (
            f"Analyze the performance and time complexities of implementing a priority queue using (i) an unordered array, "
            f"(ii) a sorted linked list, and (iii) a binary heap for an operating system task scheduler. ({marks} Marks, L4)"
        )
    if "dijkstra" in low:
        return (
            f"Apply Dijkstra's algorithm to compute the shortest paths from source vertex A for the given directed graph "
            f"with edges (A->B: 4, A->C: 2, B->C: 1, B->D: 5, C->D: 8, C->E: 10, D->E: 2). Tabulate step-by-step distances. ({marks} Marks, L3)"
        )
    return (
        f"Apply the concepts in '{text}' to a concrete engineering scenario. Provide explicit input data, "
        f"show step-by-step evaluation, and state resultant complexity. ({marks} Marks, {target_level})"
    )


def _contextual_upgrade(text: str, current_level: str, marks: int) -> str:
    low = text.lower()
    if "array" in low:
        return (
            f"Design an adaptive dynamic array resizing algorithm (amortized analysis). Compare doubling vs 1.5x factor "
            f"in terms of memory overhead and CPU copy latency. ({marks} Marks, L4)"
        )
    if "stack" in low or "postfix" in low or "infix" in low:
        return (
            f"Analyze edge-case vulnerabilities in stack-based expression evaluation (e.g. mismatched parentheses, "
            f"unary operators, divide-by-zero). Propose an enhanced evaluation state machine. ({marks} Marks, L4)"
        )
    if "queue" in low:
        return (
            f"Design a lock-free circular ring buffer (queue) suitable for high-throughput inter-process communication "
            f"between a producer thread and a consumer thread. Specify head/tail pointer invariants. ({marks} Marks, L6)"
        )
    return (
        f"Analyze competing design choices for realizing the core concept of '{text}' under strict memory and latency constraints. "
        f"Justify the optimal trade-off with comparative runtime proofs. ({marks} Marks, L4)"
    )


def _llm_blooms(questions: list[dict]) -> dict:
    payload = [
        {
            "q_no": q.get("q_no"),
            "text": q.get("question_text"),
            "stated_blooms": q.get("stated_blooms"),
            "marks": q.get("allocated_marks"),
        }
        for q in questions
    ]
    data = generate_json(
        prompt=(
            "Audit each CIE question against Revised Bloom's Taxonomy (L1–L6).\n"
            "Flag verb vs context mismatches, ambiguity, grammar issues, missing figure refs.\n"
            "If flagged, suggest a rewrite at the STATED level AND an upgraded rewrite one level higher, "
            "keeping the same syllabus concept.\n"
            f"QUESTIONS:\n{payload}\n"
            "Return a JSON object keyed by q_no with keys: "
            "predicted_blooms, issues (list of strings), suggested_rewrite, upgraded_rewrite."
        ),
        system="You are a Bloom's Taxonomy specialist for engineering CIE papers (VTU/NBA).",
    )
    return data if isinstance(data, dict) else {}
