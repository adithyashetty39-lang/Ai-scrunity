from typing import Optional

from pydantic import BaseModel, Field


class PaperMetadata(BaseModel):
    course_code: Optional[str] = None
    course_title: Optional[str] = None
    semester: Optional[str] = None
    cie_number: Optional[str] = None
    date: Optional[str] = None
    duration: Optional[str] = None
    max_marks: Optional[int] = None
    institution: Optional[str] = None
    academic_year: Optional[str] = None
    ia_test_no: Optional[str] = None
    header_issues: list[str] = Field(default_factory=list)


class QuestionItem(BaseModel):
    q_no: str = Field(description="e.g. '1a', '2b'")
    question_text: str
    allocated_marks: int
    stated_co: str = Field(default="", description="e.g. 'CO1'")
    stated_po: str = Field(default="", description="e.g. 'PO1,PO2' when the paper prints Programme Outcomes")
    stated_blooms: str = Field(default="", description="e.g. 'L1'")
    module: Optional[str] = None
    is_or_choice: bool = False
    or_group: Optional[str] = None
    has_diagram: bool = False
    refers_to_figure: bool = False
    page_hint: Optional[str] = None
    set_label: Optional[str] = Field(default=None, description="'A' or 'B' when the paper has two sets")


class QuestionAuditResult(BaseModel):
    q_no: str
    question_text: str = ""
    allocated_marks: int = 0
    stated_co: str = ""
    stated_po: str = ""
    stated_blooms: str = ""
    is_in_syllabus: bool = True
    matched_syllabus_unit: Optional[str] = None
    syllabus_score: float = 0.0
    predicted_blooms: str = ""
    blooms_match: bool = True
    blooms_quality_verdict: str = ""
    co_match: bool = True
    predicted_co: Optional[str] = None
    is_duplicate: bool = False
    historical_overlap: Optional[str] = None
    po_match: bool = True
    predicted_po: Optional[str] = None
    issues_found: list[str] = Field(default_factory=list)
    suggested_rewrite: Optional[str] = None
    upgraded_rewrite: Optional[str] = None


class ChecklistItem(BaseModel):
    category: str
    check: str
    status: str  # PASS, FAIL, WARN
    detail: str


class FormCriterionRow(BaseModel):
    """One row of the printed Scrutiny Format table (Criteria / Yes-No / Comments)."""

    criterion: str = Field(description="Exact wording printed on the scrutiny format")
    answer: str = Field(default="Yes", description="'Yes' or 'No' as it will be ticked")
    comments: str = Field(default="", description="Free-text justification printed in the Comments column")


class FormSetEvaluation(BaseModel):
    set_label: str = Field(description="'A' or 'B'")
    present: bool = Field(default=False, description="False when the paper contains no questions for this set")
    rows: list[FormCriterionRow] = Field(default_factory=list)
    overall_comments: list[str] = Field(default_factory=list, description="Up to three numbered comments")


class FormSignature(BaseModel):
    role: str
    name: str = ""
    designation: str = ""
    signature_date: str = ""


class ScrutinyForm(BaseModel):
    """Every field required to reproduce Scritinyform.pdf."""

    institution: str
    institution_sub: str
    institution_address: str
    department: str
    form_title: str
    course_name: str = ""
    course_code: str = ""
    date: str = ""
    academic_year: str = ""
    semester: str = ""
    ia_test_no: str = ""
    set_a: FormSetEvaluation = Field(default_factory=lambda: FormSetEvaluation(set_label="A"))
    set_b: FormSetEvaluation = Field(default_factory=lambda: FormSetEvaluation(set_label="B"))
    scrutiny_recommendation: str = Field(
        default="Needs revision before approval",
        description="One of: 'Approved as it is', 'Approved with minor changes', 'Needs revision before approval'",
    )
    selected_paper: str = Field(default="", description="'Set A', 'Set B' or empty when not determinable")
    signatures: list[FormSignature] = Field(default_factory=list)
    confidentiality_note: str = ""


class ScrutinyReport(BaseModel):
    metadata: PaperMetadata
    parsed_questions: list[QuestionItem]
    arithmetic_errors: list[str] = Field(default_factory=list)
    formatting_anomalies: list[str] = Field(default_factory=list)
    question_audits: list[QuestionAuditResult] = Field(default_factory=list)
    overall_rbt_distribution: dict[str, float] = Field(default_factory=dict)
    rbt_counts: dict[str, int] = Field(default_factory=dict)
    co_coverage: dict[str, float] = Field(default_factory=dict)
    unit_weightage: dict[str, float] = Field(default_factory=dict)
    hots_percentage: float = 0.0
    lots_percentage: float = 0.0
    checklist: list[ChecklistItem] = Field(default_factory=list)
    final_verdict: str = "NEEDS_REVISION"
    executive_summary: str = ""
    llm_used: bool = False
    form: Optional[ScrutinyForm] = None
    report_id: Optional[str] = None



class ScrutinyRequestOptions(BaseModel):
    cie_number: str = "CIE-1"
    allowed_units: list[str] = Field(default_factory=lambda: ["Module 1", "Module 2"])
    max_marks: int = 50
    hots_threshold: float = 0.40
    answer_any_n: int = 1
    choices_per_module: int = 2
    academic_year: str = ""
    ia_test_no: str = ""
    institution: str = ""


class UpgradeRequest(BaseModel):
    question_text: str
    target_level: str = "L3"
    stated_co: str = "CO1"
    module: str = "Module 1"
    syllabus_excerpt: str = ""
    marks: int = 5
