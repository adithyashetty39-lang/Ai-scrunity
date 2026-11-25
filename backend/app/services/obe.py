"""Outcome-Based Education checks: CO -> PO articulation and assessment-plan conformance."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from app.config import DATA_DIR

OBE_MAP_PATH = DATA_DIR / "obe_map.json"


def load_obe_map(course_code: str | None = None) -> dict[str, list[str]]:
    """Return the CO -> PO articulation matrix for a course (falls back to 'default')."""
    if not OBE_MAP_PATH.exists():
        return {}
    try:
        payload = json.loads(OBE_MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    courses = payload.get("courses") or {}
    key = (course_code or "").strip().upper()
    if key and key in courses:
        return {k.upper(): list(v) for k, v in courses[key].items()}
    fallback = payload.get("default") or {}
    return {k.upper(): list(v) for k, v in fallback.items()}


def _parse_po_set(raw: str) -> set[str]:
    return {f"PO{m}" for m in re.findall(r"PO\s*(\d{1,2})", (raw or "").upper())}


def audit_programme_outcomes(
    question: dict,
    predicted_co: str | None,
    obe_map: dict[str, list[str]],
) -> dict:
    """Validate the printed PO mapping of one question against the CO-PO matrix.

    Returns {'po_match': bool, 'predicted_po': str|None, 'issues': list[str]}.
    """
    stated_co = (question.get("stated_co") or "").upper().replace(" ", "")
    stated_po = _parse_po_set(question.get("stated_po") or "")
    target_co = stated_co or (predicted_co or "").upper()
    expected = set(obe_map.get(target_co, [])) if target_co else set()

    issues: list[str] = []
    predicted_po = ",".join(sorted(expected, key=_po_sort_key)) or None

    if not stated_po:
        if expected:
            issues.append(
                f"Programme Outcome mapping not printed; {target_co} articulates to "
                f"{', '.join(sorted(expected, key=_po_sort_key))}."
            )
        return {"po_match": True, "predicted_po": predicted_po, "issues": issues}

    if not expected:
        issues.append(f"No CO-PO articulation available for {target_co or 'the stated outcome'}; PO mapping unverified.")
        return {"po_match": True, "predicted_po": None, "issues": issues}

    extra = stated_po - expected
    if extra:
        issues.append(
            f"PO mapping {', '.join(sorted(stated_po, key=_po_sort_key))} exceeds the articulation for "
            f"{target_co} ({', '.join(sorted(expected, key=_po_sort_key))})."
        )
    return {"po_match": not extra, "predicted_po": predicted_po, "issues": issues}


def _po_sort_key(value: str) -> int:
    num = re.search(r"\d+", value)
    return int(num.group(0)) if num else 99


def build_co_po_matrix(questions: list[dict], obe_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """Merge printed mappings with the articulation matrix into a CO -> PO table."""
    matrix: dict[str, set[str]] = defaultdict(set)
    for q in questions:
        co = (q.get("stated_co") or "").upper().replace(" ", "")
        if not co:
            continue
        matrix[co].update(_parse_po_set(q.get("stated_po") or ""))
        matrix[co].update(obe_map.get(co, []))
    return {k: sorted(v, key=_po_sort_key) for k, v in sorted(matrix.items())}


def po_coverage(questions: list[dict], obe_map: dict[str, list[str]]) -> dict[str, float]:
    """Mark share per Programme Outcome implied by the CO-PO matrix."""
    totals: dict[str, int] = defaultdict(int)
    for q in questions:
        co = (q.get("stated_co") or "").upper().replace(" ", "")
        pos = _parse_po_set(q.get("stated_po") or "") or set(obe_map.get(co, []))
        marks = int(q.get("allocated_marks") or 0)
        if not pos:
            totals["Unmapped"] += marks
            continue
        share = marks / len(pos)
        for po in pos:
            totals[po] += share
    denom = sum(totals.values()) or 1
    return {k: round(v / denom, 3) for k, v in sorted(totals.items(), key=lambda kv: _po_sort_key(kv[0]))}


# --------------------------------------------------------------------------------------
# Assessment plan conformance
# --------------------------------------------------------------------------------------

class AssessmentPlan:
    """Expected question structure for one CIE, either parsed or derived from options."""

    def __init__(
        self,
        modules: dict[str, int],
        answer_any_n: int,
        choices_per_module: int | None,
        blooms_target: dict[str, float] | None = None,
        source: str = "derived",
    ):
        self.modules = modules
        self.answer_any_n = answer_any_n
        self.choices_per_module = choices_per_module
        self.blooms_target = blooms_target or {}
        self.source = source

    def describe(self) -> str:
        parts = [f"{k}: {v} marks" for k, v in self.modules.items()]
        return "; ".join(parts) + f" (answer any {self.answer_any_n} full question per module)"


def parse_assessment_plan(
    plan_text: str,
    allowed_units: list[str],
    max_marks: int,
    answer_any_n: int = 1,
) -> AssessmentPlan:
    """Parse a free-text assessment plan, else derive the standard CIE pattern."""
    text = (plan_text or "").strip()
    if not text:
        modules = {u: max_marks // max(len(allowed_units), 1) for u in allowed_units}
        return AssessmentPlan(modules, answer_any_n, None)

    modules: dict[str, int] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        mod = re.search(r"(?:module|unit)\s*([ivx\d]+)", line, re.I)
        marks = re.search(r"(\d{1,3})\s*marks", line, re.I)
        if mod and marks:
            modules[_module_label(mod.group(1))] = int(marks.group(1))

    if not modules:
        modules = {u: max_marks // max(len(allowed_units), 1) for u in allowed_units}

    n_match = re.search(r"answer\s*any\s*(\w+)", text, re.I)
    words = {"one": 1, "two": 2, "three": 3, "four": 4}
    n = answer_any_n
    if n_match:
        token = n_match.group(1).lower()
        n = words.get(token, int(token) if token.isdigit() else n)

    blooms_target: dict[str, float] = {}
    for lvl, pct in re.findall(r"(L[1-6])\s*[:\-]?\s*(\d{1,3})\s*%", text, re.I):
        blooms_target[lvl.upper()] = float(pct) / 100.0

    choices = len([q for q in re.findall(r"choice|option", text, re.I)])
    return AssessmentPlan(modules, n, choices or None, blooms_target, source="plan")


def audit_assessment_plan(
    questions: list[dict],
    plan: AssessmentPlan,
    allowed_units: list[str],
    max_marks: int,
) -> dict:
    """Check module coverage, per-module marks and choice structure against the plan."""
    issues: list[str] = []
    by_main: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        main = re.match(r"^(\d+)", str(q.get("q_no", "")))
        by_main[main.group(1) if main else str(q.get("q_no"))].append(q)

    module_totals: dict[str, int] = defaultdict(int)
    for items in by_main.values():
        prim = [i for i in items if not i.get("is_or_choice")]
        ors = [i for i in items if i.get("is_or_choice")]
        prim_marks = sum(int(i.get("allocated_marks") or 0) for i in prim)
        or_marks = sum(int(i.get("allocated_marks") or 0) for i in ors)
        best = max(prim_marks, or_marks) if ors else prim_marks
        unit = _norm_unit(items[0].get("module") or "Unmapped")
        module_totals[unit] += best

    for unit in allowed_units:
        key = _norm_unit(unit)
        if key not in module_totals or module_totals[key] == 0:
            issues.append(f"{unit} carries no questions although the plan requires it.")

    for unit, target in plan.modules.items():
        actual = module_totals.get(_norm_unit(unit), 0)
        if actual and target and actual != target:
            issues.append(f"{unit} weightage is {actual} marks against the planned {target} marks.")

    attempt = sum(module_totals.values())
    planned_total = sum(plan.modules.values())
    if planned_total and attempt and attempt != planned_total:
        issues.append(
            f"Attemptable total is {attempt} marks against a planned {planned_total} marks."
        )

    if plan.choices_per_module and len(by_main) < len(allowed_units):
        issues.append(
            f"{len(by_main)} question group(s) found for {len(allowed_units)} planned module(s)."
        )

    return {
        "conforms": not issues,
        "issues": issues,
        "module_totals": {k: v for k, v in module_totals.items()},
        "plan": plan.describe(),
        "plan_source": plan.source,
    }


def _module_label(token: str) -> str:
    roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
    t = token.strip().lower()
    num = roman.get(t) or (int(t) if t.isdigit() else 0)
    return f"Module {num}" if num else f"Module {token}"


def _norm_unit(u: str) -> str:
    return " ".join(str(u).lower().replace("unit", "module").split())
