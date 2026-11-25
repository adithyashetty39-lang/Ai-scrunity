"""Departmental report geometry; no unchecked recommendation or signature."""
from app.config import DEPARTMENT_NAME, FORM_TITLE, INSTITUTION_ADDRESS, INSTITUTION_NAME, INSTITUTION_SUB
from app.domain import Audit, Submission
from app.question_findings import question_reviews
from app.services.form_builder import CONFIDENTIALITY
from app.services.form_pdf import build_form_pdf
from app.validation import CRITERIA


def export_draft(submission: Submission, audit: Audit, rid: str, revision: int):
    meta = submission.sets[0].metadata if submission.sets else None
    form = {'institution': INSTITUTION_NAME, 'institution_sub': INSTITUTION_SUB,
        'institution_address': INSTITUTION_ADDRESS, 'department': DEPARTMENT_NAME, 'form_title': FORM_TITLE,
        'confidentiality_note': CONFIDENTIALITY, 'scrutiny_recommendation': '', 'selected_paper': '',
        'draft': True, 'draft_id': f'{rid[:12]} / revision {revision}',
        'question_findings': question_reviews(submission, audit),
        'signatures': [{'role': role} for role in ['Subject Expert 1','Subject Expert 2','Scrutiny Chair']]}
    for field in ('course_code','date','semester','academic_year','ia_test_no'):
        form[field] = getattr(meta, field) if meta else ''
    form['course_name'] = meta.course_name if meta else ''
    for label in ('A','B'):
        result = next((s for s in audit.sets if s.label == label), None)
        academic=[r for r in audit.agent.get('reviews',[]) if r.get('set_label')==label]
        level_changes=[r['q_no'] for r in academic if r.get('bloom_change_recommended')]
        scope_flags=[r['q_no'] for r in academic if r.get('syllabus_status')=='OUTSIDE_COVERED_PORTION']
        rows = []
        for key, text in CRITERIA:
            item = next((c for c in result.criteria if c.key == key), None) if result else None
            answer = 'Yes' if item and item.status == 'PASS' else 'No' if item and item.status == 'FAIL' else ''
            comment = ('Optional set not submitted.' if label == 'B' else 'Required set not submitted.') if not item else 'Checks complete for this criterion.' if item.status == 'PASS' else 'Needs revision; see review findings.' if item.status == 'FAIL' else 'Faculty review required.'
            if item:
                failure = next((failure for failure in item.findings if failure.status == 'FAIL'), None)
                if failure:
                    comment = failure.message
                    if failure.code == 'BLOOM_DISTRIBUTION':
                        comment = 'Printed Bloom percentages differ from the required targets. See overall comments.'
            if key=='blooms' and level_changes and item.status != 'FAIL':comment='AI recommends label changes: '+', '.join(level_changes)+'.'
            if key=='syllabus' and scope_flags:comment='AI flags covered scope on '+', '.join(scope_flags)+'. Review needed.'
            rows.append({'criterion': text, 'answer': answer, 'comments': comment})
        comments=['Optional set not submitted.' if label == 'B' else 'Required set not submitted.'] if result is None else []
        if result:
            marks=next(c for c in result.criteria if c.key=='marks')
            comments.append('Marks: 80 offered; all eight legal selections total 50.' if marks.status=='PASS' else 'Correct the mark/choice issues listed in the scrutiny workspace.')
            values=result.declared_blooms
            if values:
                basis = 'Printed Bloom bands'
                if result.offered_marks is not None and result.offered_marks != submission.profile.offered_marks:
                    basis = f'Bloom bands across {result.offered_marks:g} extracted marks'
                targets = ', '.join(f'{submission.profile.bloom_targets[band]:g}%' for band in values)
                actual = ', '.join(f'{band} {percent:.1f}%' for band,percent in values.items())
                comments.append(f'{basis}: {actual}. Required: {targets}.')
            else:
                comments.append('Printed Bloom distribution could not be verified from the extracted labels.')
            count = sum(q['set_label'] == label for q in form['question_findings'])
            verified = sum(r.get('verification_status') == 'AGREED' for r in academic)
            comments.append(f'AI verified {verified} of {count} question parts. See question-by-question findings for reasons and suggestions.')
        form['set_'+label.lower()] = {'rows': rows, 'overall_comments':comments}
    return build_form_pdf(form, f'{rid}-r{revision}-draft')
