"""Revised Bloom's Taxonomy verb lexicon and heuristic classifier."""

from __future__ import annotations

import re

BLOOMS_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "L6",  # Create
        [
            r"\bdesign\b",
            r"\bformulate\b",
            r"\bpropose\b",
            r"\bcreate\b",
            r"\binvent\b",
            r"\bdevise\b",
            r"\bplan\b",
            r"\bsynthesize\b",
            r"\bgenerate\b",
            r"\bbuild an? (?:system|architecture|framework)\b",
        ],
    ),
    (
        "L5",  # Evaluate
        [
            r"\bevaluate\b",
            r"\bjustify\b",
            r"\bcritique\b",
            r"\bassess\b",
            r"\bjudge\b",
            r"\bappraise\b",
            r"\bvalidate\b",
            r"\bprioritize\b",
            r"\bdefend\b",
            r"\brate\b",
            r"\bbenchmark\b",
        ],
    ),
    (
        "L4",  # Analyze
        [
            r"\banalyze\b",
            r"\banalyse\b",
            r"\bcompare(?:\s+and\s+contrast)?\b",
            r"\bdifferentiate\b",
            r"\bcontrast\b",
            r"\binvestigate\b",
            r"\bdiagnose\b",
            r"\bdebug\b",
            r"\bdeconstruct\b",
            r"\bbreak down\b",
            r"\bdistinguish between\b",
            r"\bcorrelate\b",
            r"\bdeduce\b",
        ],
    ),
    (
        "L3",  # Apply
        [
            r"\bapply\b",
            r"\bdevelop\b",
            r"\bdraw\b",
            r"\bconstruct\b",
            r"\bmodel\b",
            r"\bsketch\b",
            r"\bcompute\b",
            r"\bcalculate\b",
            r"\bsolve\b",
            r"\bconvert\b",
            r"\btrace\b",
            r"\bsimulate\b",
            r"\bwrite\s+(?:an?\s+)?(?:c\s+|python\s+|java\s+)?(?:routine|function|program|procedure|code|algorithm|script)\b",
            r"\bwrite\s+code\b",
            r"\bimplement\b",
            r"\bdemonstrate\b",
            r"\bdetermine\b",
            r"\bshow\s+(?:the\s+)?stack\b",
            r"\bstep[\s\-]by[\s\-]step\b",
            r"\bexecute\b",
            r"\bconstruct an? (?:example|table|parse tree)\b",
        ],
    ),
    (
        "L2",  # Understand
        [
            r"\bexplain\b",
            r"\bdescribe\b",
            r"\bdiscuss\b",
            r"\bsummarize\b",
            r"\bclassify\b",
            r"\binterpret\b",
            r"\billustrate\b",
            r"\boutline\b",
            r"\bdistinguish\b",
            r"\bgive examples?\b",
            r"\bparaphrase\b",
            r"\bclarify\b",
        ],
    ),
    (
        "L1",  # Remember
        [
            r"\bdefine\b",
            r"\blist\b",
            r"\bstate(?!\s+(?:diagram|machine|chart|transition|table|variable|space))\b",
            r"\brecall\b",
            r"\bidentify\b",
            r"\bname\b",
            r"\blabel\b",
            r"\benumerate\b",
            r"\bmention\b",
            r"\bwhat is\b",
            r"\breproduce\b",
            r"\bwho\b",
            r"\bwhen\b",
            r"\bwhere\b",
        ],
    ),
]

LEVEL_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6"]
HOTS_LEVELS = {"L3", "L4", "L5", "L6"}

LEVEL_NAMES = {
    "L1": "L1 (Remember)",
    "L2": "L2 (Understand)",
    "L3": "L3 (Apply)",
    "L4": "L4 (Analyze)",
    "L5": "L5 (Evaluate)",
    "L6": "L6 (Create)",
}

LEVEL_UPGRADE_HINT = {
    "L1": "L3",
    "L2": "L3",
    "L3": "L4",
    "L4": "L5",
    "L5": "L6",
    "L6": "L6",
}


def normalize_level(raw: str) -> str:
    if not raw:
        return ""
    text = raw.upper().replace(" ", "")
    match = re.search(r"L\s*([1-6])|BT\s*([1-6])|BL\s*([1-6])", text)
    if match:
        num = next(g for g in match.groups() if g)
        return f"L{num}"
    return text[:2]


def predict_blooms(question_text: str) -> tuple[str, str]:
    """Analyze question text against Revised Bloom's Taxonomy.
    Returns (predicted_level, matched_verb_or_phrase).
    """
    q = question_text.lower()
    
    # Check if question stem explicitly demands analysis or evaluation
    if re.search(r"\b(?:and\s+)?analy[sz]e(?:\s+(?:how|why|the|its|interactions))?\b", q):
        return "L4", "analyze"
    if re.search(r"\bcompare(?:\s+and\s+contrast)?\b", q):
        return "L4", "compare"
    if re.search(r"\bdifferentiate(?:\s+between)?\b", q):
        return "L4", "differentiate"
    if re.search(r"\bevaluate\b|\bjustify\b|\bcritique\b", q):
        return "L5", "evaluate"

    # Match leading action verb (first word of the stem)
    leading_word_m = re.match(r"^\s*([a-z]+)", q)
    if leading_word_m:
        first_word = leading_word_m.group(1)
        for lvl, patterns in BLOOMS_PATTERNS:
            for pattern in patterns:
                clean_pat = pattern.replace(r"\b", "").replace(r"(?:", "").replace(")?", "").replace("?", "")
                if re.fullmatch(r"[a-z]+", clean_pat) and clean_pat == first_word:
                    return lvl, first_word

    # Scan patterns from L6 down to L1
    for lvl, patterns in BLOOMS_PATTERNS:
        for pattern in patterns:
            m = re.search(pattern, q)
            if m:
                return lvl, m.group(0).strip()

    return "L1", ""


def hots_share(levels: list[str], marks: list[int] | None = None) -> float:
    if not levels:
        return 0.0
    if marks and len(marks) == len(levels):
        total = sum(marks) or 1
        hots = sum(m for lvl, m in zip(levels, marks) if normalize_level(lvl) in HOTS_LEVELS)
        return hots / total
    hots = sum(1 for lvl in levels if normalize_level(lvl) in HOTS_LEVELS)
    return hots / len(levels)
