"""Versioned scrutiny data. Unknown evidence never defaults to success."""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Status(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    NEEDS_REVIEW = 'NEEDS_REVIEW'


class Evidence(Model):
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


FacultyBloomAction = Literal['accepted','overridden','deferred']


class FacultyBloomDecision(Model):
    action: FacultyBloomAction
    suggested_level: int | None = Field(default=None, ge=1, le=6)
    note: str = Field(default='', max_length=500)


class Question(Model):
    q_no: str = Field(pattern=r'^[1-8][ab]?$')
    text: str = Field(min_length=1)
    marks: Decimal | None = Field(default=None, gt=0, le=10)
    co: list[str] = Field(default_factory=list)
    po: list[str] = Field(default_factory=list)
    stated_level: int | None = Field(default=None, ge=1, le=6)
    reviewed_level: int | None = Field(default=None, ge=1, le=6)
    faculty_bloom_decision: FacultyBloomDecision | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    extraction_confirmed: bool = False

    @model_validator(mode='after')
    def check_faculty_decision(self):
        decision = self.faculty_bloom_decision
        if decision is None:
            return self
        if decision.action == 'deferred' and self.reviewed_level is not None:
            raise ValueError('A deferred Bloom’s decision must leave the reviewed level open.')
        if decision.action in ('accepted','overridden') and self.reviewed_level is None:
            raise ValueError('A resolved faculty Bloom’s decision requires a reviewed level.')
        if decision.action == 'accepted' and self.reviewed_level != decision.suggested_level:
            raise ValueError('The accepted level must match the AI suggestion recorded with the decision.')
        return self


class Metadata(Model):
    course_code: str = ''
    course_name: str = ''
    semester: str = ''
    date: str = ''
    academic_year: str = ''
    ia_test_no: str = ''
    duration: str = ''
    max_marks: Decimal | None = Field(default=None, gt=0)


class PaperSet(Model):
    label: Literal['A', 'B']
    metadata: Metadata = Field(default_factory=Metadata)
    questions: list[Question] = Field(default_factory=list, max_length=16)
    document_ids: list[str] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
    faculty_checks: dict[Literal['syllabus', 'assessment', 'outcomes', 'format'], Literal['confirmed', 'needs_revision']] = Field(default_factory=dict)


class MaterialCoverage(Model):
    filename: str = Field(default='', max_length=255)
    module: int | None = Field(default=None, ge=1)
    mode: Literal['entire','range'] = 'entire'
    start_page: int | None = Field(default=None, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    start_topic: str = Field(default='', max_length=300)
    end_topic: str = Field(default='', max_length=300)


class RuleProfile(Model):
    id: str = 'professor-cie'
    version: int = Field(default=1, ge=1)
    department: str = ''
    course_code: str = ''
    course_name: str = ''
    course_evidence_verified: bool = False
    required_sets: list[Literal['A', 'B']] = Field(default_factory=lambda: ['A'])
    offered_marks: Decimal = Decimal(80)
    attempted_marks: Decimal = Decimal(50)
    full_question_marks: Decimal = Decimal(10)
    compulsory: list[int] = Field(default_factory=lambda: [1, 2])
    alternatives: list[list[int]] = Field(default_factory=lambda: [[3, 4], [5, 6], [7, 8]])
    bloom_targets: dict[str, Decimal] = Field(default_factory=lambda: {'L1-L2': Decimal(30), 'L3-L4': Decimal(60), 'L5-L6': Decimal(10)})
    bloom_basis: Literal['offered'] = 'offered'
    tolerance_percentage_points: Decimal = Field(default=Decimal(0), ge=0, le=0)
    coverage_start: str = ''
    coverage_end: str = ''
    coverage_confirmed: bool = False
    coverage_mode: Literal['topic_range','all_uploaded'] = 'topic_range'
    material_kind: Literal['syllabus','notes'] = 'syllabus'
    rules_confirmed: bool = False
    syllabus_document_ids: list[str] = Field(default_factory=list)
    mapping_document_ids: list[str] = Field(default_factory=list)
    material_coverage: dict[str, MaterialCoverage] = Field(default_factory=dict)
    covered_modules: list[str] = Field(default_factory=list)
    syllabus: dict[str, str] = Field(default_factory=dict)
    outcomes: dict[str, str] = Field(default_factory=dict)
    co_po: dict[str, dict[str, int]] = Field(default_factory=dict)
    source_documents: list[str] = Field(default_factory=list)
    approved_blueprint_id: str | None = None
    approved_paper_template_id: str | None = None
    approved_by: str | None = None

    @model_validator(mode='after')
    def check_pattern(self):
        # Older drafts stored both sets as required. The current rule only requires A.
        self.required_sets = ['A']
        if self.compulsory != [1, 2] or self.alternatives != [[3, 4], [5, 6], [7, 8]]:
            raise ValueError('This profile version supports compulsory Q1/Q2 and pairs Q3/4, Q5/6, Q7/8.')
        if (self.offered_marks, self.attempted_marks, self.full_question_marks) != (80, 50, 10):
            raise ValueError('The confirmed examination pattern is 80 offered / 50 attempted / 10 per full question.')
        if set(self.bloom_targets) != {'L1-L2', 'L3-L4', 'L5-L6'} or sum(self.bloom_targets.values()) != 100:
            raise ValueError('Bloom bucket percentages must total 100.')
        if any(v < 0 or v > 100 for v in self.bloom_targets.values()):
            raise ValueError('Invalid Bloom percentage.')
        if any(v not in (1, 2, 3) for row in self.co_po.values() for v in row.values()):
            raise ValueError('CO-PO correlation strengths must be 1, 2, or 3.')
        return self


class Submission(Model):
    schema_version: Literal[2] = 2
    title: str = Field(default='Untitled scrutiny', min_length=1, max_length=160)
    cloud_consent: bool = False
    ai_mode: Literal['local','google','cloud'] = 'local'
    cloud_provider_id: str | None = Field(default=None,max_length=64)
    profile: RuleProfile = Field(default_factory=RuleProfile)
    sets: list[PaperSet] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def unique_sets(self):
        labels = [s.label for s in self.sets]
        if len(labels) != len(set(labels)):
            raise ValueError('Duplicate set labels are not allowed.')
        return self


class Finding(Model):
    code: str
    status: Status
    message: str
    question_ids: list[str] = Field(default_factory=list)


class Criterion(Model):
    key: str
    label: str
    status: Status
    findings: list[Finding] = Field(default_factory=list)


class AnswerPath(Model):
    questions: list[int]
    marks: Decimal | None


class SetAudit(Model):
    label: Literal['A', 'B']
    offered_marks: Decimal | None
    paths: list[AnswerPath]
    declared_blooms: dict[str, Decimal] | None
    reviewed_blooms: dict[str, Decimal] | None
    criteria: list[Criterion]


class Audit(Model):
    status: Literal['NEEDS_REVISION', 'BLOCKED', 'READY_FOR_FACULTY_REVIEW']
    final_approval: Literal[False] = False
    blockers: list[str]
    sets: list[SetAudit]
    profile_id: str
    profile_version: int
    agent: dict = Field(default_factory=dict)
