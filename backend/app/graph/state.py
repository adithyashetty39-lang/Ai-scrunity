from typing import Any, TypedDict


class ScrutinyState(TypedDict, total=False):
    paper_text: str
    paper_text_b: str
    syllabus_text: str
    allowed_units: list[str]
    max_marks: int
    hots_threshold: float
    cie_number: str
    academic_year: str
    ia_test_no: str
    assessment_plan: str
    answer_any_n: int
    choices_per_module: int
    formatting_anomalies: list[str]
    metadata: dict[str, Any]
    metadata_b: dict[str, Any]
    parsed_questions: list[dict[str, Any]]
    parsed_questions_b: list[dict[str, Any]]
    arithmetic_errors: list[str]
    arithmetic_errors_b: list[str]
    question_audits: list[dict[str, Any]]
    question_audits_b: list[dict[str, Any]]
    blooms_audits: list[dict[str, Any]]
    blooms_audits_b: list[dict[str, Any]]
    overall_rbt_distribution: dict[str, float]
    overall_rbt_distribution_b: dict[str, float]
    rbt_counts: dict[str, int]
    rbt_counts_b: dict[str, int]
    co_coverage: dict[str, float]
    co_coverage_b: dict[str, float]
    unit_weightage: dict[str, float]
    unit_weightage_b: dict[str, float]
    hots_percentage: float
    hots_percentage_b: float
    lots_percentage: float
    lots_percentage_b: float
    checklist: list[dict[str, Any]]
    set_checklists: dict[str, list[dict[str, Any]]]
    final_verdict: str
    executive_summary: str
    llm_used: bool
    form: dict[str, Any]
