"""Deterministic academic gates; all calculations use exact decimal marks."""
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import product

from app.domain import AnswerPath, Audit, Criterion, Finding, PaperSet, RuleProfile, SetAudit, Status, Submission
from app.coverage import resolve_coverage

CRITERIA = [
    ('syllabus', 'The Questions set are within the syllabus Covered'),
    ('assessment', 'Are questions as per assessment plan?'),
    ('outcomes', 'Are all questions mapped to CO/ PO Properly?'),
    ('blooms', "Are all questions distributed properly using Bloom's level?"),
    ('marks', 'The marks for questions are properly distributed?'),
    ('format', 'Does it follow the format given?'),
]


def finding(code, status, message, ids=()):
    return Finding(code=code, status=status, message=message, question_ids=list(ids))


def criterion(key, findings):
    status = Status.FAIL if any(f.status == Status.FAIL for f in findings) else Status.NEEDS_REVIEW if any(f.status == Status.NEEDS_REVIEW for f in findings) else Status.PASS
    return Criterion(key=key, label=dict(CRITERIA)[key], status=status, findings=findings)


def distribution(questions, reviewed=False):
    if not questions or any(q.marks is None or (q.reviewed_level if reviewed else q.stated_level) is None for q in questions):
        return None
    total = sum(q.marks for q in questions)
    buckets = {k: Decimal(0) for k in ('L1-L2', 'L3-L4', 'L5-L6')}
    for q in questions:
        level = q.reviewed_level if reviewed else q.stated_level
        key = ('L1-L2', 'L3-L4', 'L5-L6')[(level - 1) // 2]
        buckets[key] += q.marks
    return {k: v * 100 / total for k, v in buckets.items()} if total else None


def faculty_finding(paper, key, pending_message):
    decision = paper.faculty_checks.get(key)
    if decision == 'confirmed':
        return finding('FACULTY_CONFIRMED', Status.PASS, 'Professor confirmed this criterion.')
    if decision == 'needs_revision':
        return finding('FACULTY_REVISION_REQUIRED', Status.FAIL, 'Professor marked this criterion as needing revision.')
    return finding('FACULTY_REVIEW_REQUIRED', Status.NEEDS_REVIEW, pending_message)


def mapped_outcomes(question, profile):
    missing = [co for co in question.co if not profile.outcomes.get(co, '').strip() or not profile.co_po.get(co)]
    allowed = {po for co in question.co for po in profile.co_po.get(co, {})}
    return missing, allowed, sorted(set(question.po) - allowed) if allowed else []


def validate_set(paper: PaperSet, profile: RuleProfile) -> SetAudit:
    groups = defaultdict(list)
    issues = []
    for q in paper.questions:
        groups[int(q.q_no.rstrip('ab'))].append(q)
    ids = Counter(q.q_no for q in paper.questions)
    for qid, count in ids.items():
        if count > 1:
            issues.append(finding('DUPLICATE_ID', Status.FAIL, f'{qid} occurs {count} times; none were discarded.', [qid]))
    missing = sorted(set(range(1, 9)) - set(groups))
    if missing:
        issues.append(finding('MISSING_QUESTIONS', Status.FAIL, f'Missing full questions: {missing}.'))
    totals = {}
    for n, questions in sorted(groups.items()):
        labels = [q.q_no for q in questions]
        expected = {str(n)} if len(questions) == 1 and questions[0].q_no == str(n) else {f'{n}a', f'{n}b'}
        if set(labels) != expected or len(labels) != len(expected):
            issues.append(finding('PART_STRUCTURE', Status.FAIL, f'Q{n} must be one full question or parts a and b.', labels))
        if any(q.marks is None for q in questions):
            totals[n] = None
            issues.append(finding('UNKNOWN_MARKS', Status.NEEDS_REVIEW, f'Q{n} contains unread/unconfirmed marks.', labels))
        else:
            totals[n] = sum(q.marks for q in questions)
            if totals[n] != profile.full_question_marks:
                issues.append(finding('QUESTION_TOTAL', Status.FAIL, f'Q{n} totals {totals[n]} marks; expected 10.', labels))
            if any(q.marks != q.marks.to_integral_value() for q in questions):
                issues.append(finding('FRACTIONAL_POLICY', Status.NEEDS_REVIEW, 'Fractional subpart marks need department approval.', labels))
    offered = sum(totals.values()) if totals and all(v is not None for v in totals.values()) else None
    if offered is not None and offered != profile.offered_marks:
        issues.append(finding('OFFERED_TOTAL', Status.FAIL, f'{offered} offered marks; expected 80.'))
    paths = []
    for selection in product(*profile.alternatives):
        numbers = profile.compulsory + list(selection)
        marks = sum(totals[n] for n in numbers) if all(totals.get(n) is not None for n in numbers) else None
        paths.append(AnswerPath(questions=numbers, marks=marks))
        if marks is not None and marks != profile.attempted_marks:
            issues.append(finding('ANSWER_PATH_TOTAL', Status.FAIL, f'Answer path {numbers} totals {marks}; expected 50.'))
    if not issues:
        issues.append(finding('STRUCTURE_VERIFIED', Status.PASS, '80 offered marks; all eight legal answer paths total 50; every full question totals 10.'))

    syllabus = []
    if not paper.metadata.course_code or not profile.course_code:
        syllabus.append(finding('COURSE_UNKNOWN', Status.NEEDS_REVIEW, 'Confirm the course code from the source paper.'))
    elif paper.metadata.course_code.upper() != profile.course_code.upper():
        syllabus.append(finding('COURSE_MISMATCH', Status.FAIL, f'Paper {paper.metadata.course_code} does not match syllabus {profile.course_code}.'))
    coverage = resolve_coverage(profile)
    if coverage.error:
        syllabus.append(finding('COVERAGE_NOT_FOUND', Status.NEEDS_REVIEW, coverage.error))
    elif not profile.coverage_confirmed:
        syllabus.append(finding('COVERAGE_UNKNOWN', Status.NEEDS_REVIEW, 'Confirm the selected coverage before evaluation.'))
    if not profile.course_evidence_verified:
        syllabus.append(finding('SYLLABUS_UNVERIFIED', Status.NEEDS_REVIEW, 'Confirm the extracted syllabus against your uploaded source.'))
    if not profile.syllabus_document_ids:
        syllabus.append(finding('SYLLABUS_SOURCE_MISSING', Status.NEEDS_REVIEW, 'Upload the syllabus for this course.'))
    syllabus.append(faculty_finding(paper, 'syllabus', 'Confirm every question against the covered portion.'))

    outcomes = []
    for q in paper.questions:
        if not q.co or not q.po:
            outcomes.append(finding('MAPPING_MISSING', Status.NEEDS_REVIEW, f'Confirm CO and PO annotations for {q.q_no}.', [q.q_no]))
        missing_co, _, unsupported_po = mapped_outcomes(q, profile)
        for co in missing_co:
            outcomes.append(finding('UNKNOWN_CO', Status.FAIL if profile.course_evidence_verified and profile.outcomes else Status.NEEDS_REVIEW, f'{co} is not in the available course outcome evidence.', [q.q_no]))
        if unsupported_po:
            outcomes.append(finding('PO_OUTSIDE_MATRIX', Status.FAIL, f'{q.q_no} lists PO values outside its CO articulation.', [q.q_no]))
    outcomes.append(faculty_finding(paper, 'outcomes', 'Confirm that the question content matches the indicated course outcomes and their PO mapping.'))

    blooms = []
    if profile.bloom_basis is None or profile.tolerance_percentage_points is None:
        blooms.append(finding('BLOOM_POLICY_UNKNOWN', Status.NEEDS_REVIEW, 'Department must approve the 80/50 calculation basis and explicit tolerance.'))
    samples = []
    if profile.bloom_basis in ('offered', 'both'):
        samples.append(('80-mark offered paper', paper.questions))
    if profile.bloom_basis in ('every_path', 'both'):
        samples.extend((f'path {p.questions}', [q for n in p.questions for q in groups.get(n, [])]) for p in paths)
    for name, questions in samples:
        values = distribution(questions)
        if values is None:
            blooms.append(finding('BLOOM_LABELS_UNKNOWN', Status.NEEDS_REVIEW, f'Cannot calculate declared distribution for {name}.'))
        elif profile.tolerance_percentage_points is not None:
            for bucket, target in profile.bloom_targets.items():
                if abs(values[bucket] - target) > profile.tolerance_percentage_points:
                    blooms.append(finding('BLOOM_DISTRIBUTION', Status.FAIL, f'{name}: {bucket} is {values[bucket]:.2f}%; required {target}% (+/- {profile.tolerance_percentage_points} percentage points).'))
    reviewed_blooms = distribution(paper.questions, reviewed=True)
    unreviewed_levels = [q.q_no for q in paper.questions if q.reviewed_level is None]
    if unreviewed_levels:
        blooms.append(finding('COGNITIVE_REVIEW', Status.NEEDS_REVIEW, 'Record a faculty-reviewed Bloom’s level for each question.', unreviewed_levels))
    changed_levels = [q.q_no for q in paper.questions if q.reviewed_level is not None and q.stated_level is not None and q.reviewed_level != q.stated_level]
    if changed_levels:
        blooms.append(finding('BLOOM_LABEL_MISMATCH', Status.FAIL, 'Revise the printed Bloom’s labels that differ from the faculty-reviewed levels.', changed_levels))

    formatting = []
    meta = paper.metadata
    for field in ('course_code', 'course_name', 'semester', 'date', 'academic_year', 'ia_test_no', 'duration', 'max_marks'):
        if not getattr(meta, field):
            formatting.append(finding('METADATA_MISSING', Status.NEEDS_REVIEW, f'Missing metadata: {field}.'))
    if meta.max_marks is not None and meta.max_marks != profile.attempted_marks:
        formatting.append(finding('HEADER_MARKS', Status.FAIL, 'Header maximum marks must be 50.'))
    unconfirmed = [q.q_no for q in paper.questions if not q.extraction_confirmed or not q.evidence]
    if unconfirmed:
        formatting.append(finding('EXTRACTION_REVIEW', Status.NEEDS_REVIEW, 'Confirm the extracted questions against their source regions.', unconfirmed))
    formatting.append(faculty_finding(paper, 'format', 'Compare the paper layout, figures, and outcome tables with the approved question-paper template.'))
    assessment = list(issues)
    if not profile.rules_confirmed:
        assessment.append(finding('PLAN_UNCONFIRMED', Status.NEEDS_REVIEW, 'Confirm the examination pattern and Bloom targets for your paper.'))
    assessment.append(faculty_finding(paper, 'assessment', 'Check the printed instructions and alternatives against the assessment plan.'))
    by_key = {'syllabus': syllabus, 'assessment': assessment, 'outcomes': outcomes, 'blooms': blooms, 'marks': issues, 'format': formatting}
    return SetAudit(label=paper.label, offered_marks=offered, paths=paths,
                    declared_blooms=distribution(paper.questions), reviewed_blooms=reviewed_blooms,
                    criteria=[criterion(key, by_key[key]) for key, _ in CRITERIA])


def audit_submission(submission: Submission) -> Audit:
    sets = [validate_set(s, submission.profile) for s in submission.sets if s.label == 'A' or s.questions or s.document_ids]
    missing = set(submission.profile.required_sets) - {s.label for s in submission.sets if s.questions}
    blockers = [f'Set {label} is mandatory and has not been supplied.' for label in sorted(missing)]
    for paper in sets:
        blockers.extend(f'Set {paper.label}: {c.label}' for c in paper.criteria if c.status != Status.PASS)
    if not submission.profile.rules_confirmed:
        blockers.append('Professor has not confirmed the examination rules.')
    failed = any(c.status == Status.FAIL for s in sets for c in s.criteria)
    status = 'NEEDS_REVISION' if failed else 'BLOCKED' if blockers else 'READY_FOR_FACULTY_REVIEW'
    return Audit(status=status, blockers=blockers, sets=sets,
                 profile_id=submission.profile.id, profile_version=submission.profile.version)
