"""Shared question explanations for Findings and the exported report."""
import re

from app.paper_figures import SUPPLIED_FIGURE, question_figure_text
from app.validation import mapped_outcomes


def check(label, status, reason, suggestion):
    return {'label': label, 'status': status, 'reason': reason, 'suggestion': suggestion}


def level(value):
    return f'L{value}' if value else 'Unresolved'


def faculty_bloom_finding(question):
    decision = question.faculty_bloom_decision
    if decision is None:
        return None
    if decision.action == 'accepted':
        label = f'Accepted AI suggestion ({level(question.reviewed_level)})'
    elif decision.action == 'overridden':
        label = f'Overridden to {level(question.reviewed_level)}'
    else:
        label = 'Deferred'
    return {**decision.model_dump(mode='json'),'label':label}


def bloom_check(question, review):
    printed, suggested, faculty = question.stated_level, review.get('predicted_level'), question.reviewed_level
    reason = review.get('bloom_explanation') or 'A cognitive level must be justified by the work a student has to do.'
    if faculty and printed and faculty != printed:
        return check('Bloom’s level', 'Needs revision',
                     f'The paper prints {level(printed)}, but the professor recorded {level(faculty)}. {reason}',
                     f'Align the printed label with the faculty decision ({level(faculty)}) or revise and reassess the task.')
    if not suggested or not printed:
        detail = 'The printed Bloom’s label is missing or unreadable.' if not printed else 'An AI level could not be established.'
        action = 'Check the original paper and enter the printed label.' if not printed else 'Resolve the review issue below and verify the cognitive demand against the expected answer.'
        return check('Bloom’s level', 'Needs review', f'{detail} {reason}', action)
    if review.get('verification_status') != 'AGREED':
        return check('Bloom’s level', 'Needs review', reason,
                     f'Compare printed {level(printed)} with proposed {level(suggested)} and confirm the level using the expected answer.')
    if printed != suggested:
        return check('Bloom’s level', 'Suggested change', reason,
                     f'Consider changing the printed label from {level(printed)} to {level(suggested)} if the expected answer matches this analysis. To retain {level(printed)}, rewrite the task to require that level of thinking.')
    return check('Bloom’s level', 'Supported', reason, f'Retain {level(printed)} if the marking scheme rewards the same cognitive work.')


def syllabus_check(review):
    status = review.get('syllabus_status')
    reason = review.get('syllabus_explanation') or 'There is no accepted syllabus finding for this question yet.'
    if status == 'IN_SYLLABUS' and review.get('verification_status') == 'AGREED' and review.get('citations'):
        return check('Syllabus coverage', 'Supported', reason, 'Keep the assessed concept within the cited exam coverage.')
    if status == 'OUTSIDE_COVERED_PORTION' and review.get('verification_status') == 'AGREED':
        return check('Syllabus coverage', 'Suggested change', reason,
                     'Replace this task with one that uses a concept inside the confirmed range, or correct the range if it was entered incorrectly.')
    return check('Syllabus coverage', 'Needs review', reason,
                 'Check the topic against the confirmed pages and phrases. Attach the relevant material or retry the AI review if its evidence is incomplete.')


def outcome_check(question, profile, review):
    missing, allowed, unsupported = mapped_outcomes(question, profile)
    detail = review.get('outcome_explanation')
    if unsupported:
        choices = ', '.join(sorted(allowed))
        reasons = f'Printed {", ".join(unsupported)} falls outside the supplied matrix for {", ".join(question.co)}. Listed options are {choices}.'
        return check('CO–PO mapping', 'Needs revision', reasons + (f' AI content check: {detail}' if detail else ''),
                     f'Check the course outcome against the expected answer. If the printed CO is correct, use a supported PO ({choices}) that the task actually assesses.')
    if not question.co or not question.po or missing:
        missing_text = f'Course outcome evidence or matrix rows are missing for {", ".join(missing)}.' if missing else 'One or both printed CO and PO labels are missing.'
        return check('CO–PO mapping', 'Needs review', missing_text + (f' AI content check: {detail}' if detail else ''),
                     'Verify the paper labels and supply the approved outcome statements and matrix, then check that the task assesses the indicated outcome.')
    reason = f'The printed {", ".join(question.po)} is listed for {", ".join(question.co)} in the supplied matrix.'
    return check('CO–PO mapping', 'Matrix match', reason + (f' AI content check: {detail}' if detail else ''),
                 'Confirm the expected answer demonstrates the stated course outcome before keeping these labels.')


def marks_check(question, group, expected):
    if any(part.marks is None for part in group):
        return check('Printed marks', 'Needs review', 'One or more marks in this full question are unread or missing.',
                     f'Compare the marks with the paper and make the full question total {expected:g} marks.')
    total = sum(part.marks for part in group)
    reason = f'This item shows {question.marks:g} marks. The full question totals {total:g} marks.'
    if total != expected:
        return check('Printed marks', 'Needs revision', reason + f' The required total is {expected:g}.',
                     f'Revise the allocation so the full question totals {expected:g} marks.')
    valid_parts = (len(group) == 1 and group[0].q_no.isdigit()) or (
        len(group) == 2 and {part.q_no[-1] for part in group} == {'a','b'})
    if not valid_parts:
        return check('Printed marks', 'Needs revision', reason + ' The question structure does not match the required part labels.',
                     'Use one full question or two distinct subparts labelled a and b.')
    if any(part.marks != part.marks.to_integral_value() for part in group):
        return check('Printed marks', 'Needs review', reason + ' The allocation includes fractional marks.',
                     'Check that the department allows fractional subpart marks.')
    return check('Printed marks', 'Matches plan', reason + f' This meets the {expected:g}-mark rule.',
                 'Keep this allocation if the marking scheme matches the task’s workload.')


def wording_check(question, paper, review, full_marks, has_figure_check):
    label = 'Question wording' if has_figure_check else 'Question wording and figures'
    question_tag = rf'\b(?:Q(?:uestion)?\s*){re.escape(question.q_no)}\b'
    source_notes = [warning for warning in paper.extraction_warnings
                    if 'embedded figure' not in warning.lower() and re.search(question_tag, warning, re.I)]
    issues = list(dict.fromkeys([*review.get('framing_issues', []), *source_notes]))
    explanation = review.get('framing_explanation')
    if issues:
        details = list(dict.fromkeys(filter(None, [explanation, *issues])))
        suggestion = review.get('framing_suggestion') or 'Check each issue against the original. Verify any referenced figure, values and instructions, and use the suggested wording below if provided.'
        if re.search(r'\b(?:reduce|lower|decrease|increase|raise)\b[^.!?]{0,50}\b(?:marks?|points|allocation)\b', suggestion, re.I):
            suggestion = f'Adjust the task’s workload or revise the allocation within parts a and b. Keep the full question at {full_marks:g} marks.'
        return check(label, 'Needs attention', '\n'.join(details),
                     suggestion)
    if explanation and review.get('verification_status') == 'AGREED':
        return check(label, 'Supported', explanation,
                     'Keep the instruction if it agrees with the original paper and marking scheme.')
    return check(label, 'Needs review',
                 explanation or 'There is no verified explanation of the question wording.',
                 'Check that the question states the task, provides the necessary information, and makes the expected answer clear.')


def figure_check(question, paper, review, sources, attempted):
    figure_warning = any(re.match(rf'^Q{re.escape(question.q_no)}:\s.*embedded figure', warning, re.I)
                         for warning in paper.extraction_warnings)
    if not (attempted or sources or figure_warning or SUPPLIED_FIGURE.search(question_figure_text(question))):
        return None
    label = 'Figure assessment'
    assessment = review.get('figure_assessment')
    if assessment and sources:
        status = {'SUFFICIENT':'Supported','INCOMPLETE':'Needs attention',
                  'UNREADABLE':'Needs review','UNCERTAIN':'Needs review'}[assessment['status']]
        reason = '\n'.join([assessment['explanation'], *assessment.get('observations',[])])
        if review.get('verification_status') != 'AGREED':
            status = 'Needs review'
            reason = 'The verifier has not confirmed this visual assessment.\n' + reason
        return check(label,status,reason,assessment['suggestion'])
    if sources:
        return check(label,'Needs review','The original visual source is available, but no validated visual assessment was saved.',
                     'Preview the source and retry evaluation. If the assessment remains unresolved, verify the required figure details during faculty review.')
    if attempted:
        return check(label,'Needs review','The question refers to a visual, but the app could not link a viewable figure or page to it.',
                     'Check the original paper for a readable, unique caption matching the question reference, including in the figures after the questions.')
    return check(label,'Needs review','This saved review has no visual assessment.',
                 'Run evaluation again to check the figure in the saved source paper.')


def review_recovery(status, reason):
    if status == 'COVERAGE_REQUIRED' or 'evidence' in reason.lower() or 'quote' in reason.lower():
        return 'Confirm the selected pages and topic phrases. Attach the relevant notes if the syllabus only names a broad topic, then retry this assessment.'
    if status == 'CONSENT_REQUIRED':
        return 'Confirm cloud processing for the configured provider, then retry evaluation.'
    if 'quota' in reason.lower() or 'rate limit' in reason.lower():
        return 'Check the provider’s remaining credit or rate limit, then retry evaluation when the provider is available.'
    if status == 'INVALID_QUESTION_IDS':
        return 'Resolve the duplicate question numbers in the paper, then rerun evaluation.'
    return 'Retry evaluation for the missing assessment. If the provider still fails, use the original question and syllabus for faculty review.'


def question_reviews(submission, audit):
    agent = audit.agent
    reviews = {(row['set_label'], row['q_no']):row for row in agent.get('reviews', [])}
    questions = []
    for paper in submission.sets:
        for question in paper.questions:
            key = (paper.label, question.q_no)
            review = reviews.get(key, {})
            source_key = '/'.join(key)
            figure_sources = agent.get('figure_sources', {})
            sources = figure_sources.get(source_key, [])
            visual = figure_check(question, paper, review, sources, source_key in figure_sources)
            checks = [bloom_check(question, review), syllabus_check(review),
                      outcome_check(question, submission.profile, review),
                      marks_check(question, [part for part in paper.questions if part.q_no[0] == question.q_no[0]],
                                  submission.profile.full_question_marks),
                      wording_check(question, paper, review, submission.profile.full_question_marks, visual is not None)]
            if visual:
                checks.append(visual)
            if not review:
                reason = agent.get('question_errors', {}).get('/'.join(key))
                if not reason:
                    summary = agent.get('summary', '')
                    match = re.search(rf'AI cited unsupported evidence for {re.escape("/".join(key))}\.', summary)
                    reason = match.group() if match else summary if agent.get('status') not in ('PARTIAL','REVIEW_DISAGREEMENTS') else ''
                reason = reason or 'No validated AI assessment was saved for this question.'
                checks.insert(0, check('AI review', 'Incomplete', reason, review_recovery(agent.get('status'), reason)))
            elif review.get('verification_status') != 'AGREED':
                checks.insert(0, check('Independent verification', 'Needs review',
                                       review.get('verification_feedback') or 'The independent check has not confirmed this recommendation.',
                                       'Retry evaluation or have the professor check the recommendation against the original sources.'))
            citations = []
            for citation in review.get('citations', []):
                document, separator, page = citation['section'].partition(':page ')
                selection = submission.profile.material_coverage.get(document)
                source = selection.filename or (f'Module {selection.module}' if selection.module else 'Syllabus source') if selection else 'Syllabus source'
                citations.append({**citation, 'source':f'{source}, page {page}' if separator else document,
                                  'document_id':document if document in submission.profile.syllabus_document_ids else None})
            questions.append({
                'set_label':paper.label, 'q_no':question.q_no, 'text':question.text,
                'printed_level':level(question.stated_level), 'suggested_level':level(review.get('predicted_level')),
                'faculty_level':level(question.reviewed_level),
                'faculty_bloom_decision':faculty_bloom_finding(question),
                'marks':str(question.marks) if question.marks is not None else 'Unknown',
                'co':', '.join(question.co) or 'Unread', 'po':', '.join(question.po) or 'Unread',
                'checks':checks, 'citations':citations, 'figure_sources':sources, 'rewrite':review.get('suggested_rewrite'),
                'verification_status':review.get('verification_status'), 'confidence':review.get('confidence'),
                'verification_feedback':review.get('verification_feedback'),
            })
    return questions
