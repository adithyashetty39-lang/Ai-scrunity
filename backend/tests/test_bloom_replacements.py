import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import api
from app.ai_config import ModelUnavailable
from app.bloom_replacements import covered_sources, replacement_plan, suggest_replacement
from app.domain import MaterialCoverage, PaperSet, Question, RuleProfile, Submission
from app.repository import Repository
from app.validation import audit_submission


covered = 'Stacks remove the newest item first. Queues remove the oldest item first.'
excluded = 'Sorting arranges items in ascending order.'
section = 'notes:page 1'


def fixture():
    questions = [
        Question(q_no=number, marks=marks, stated_level=level,
                 text='Trace the removals for an example stack.' if number == '4b' else f'Existing question {number}')
        for number, marks, level in [('1', 10, 1), ('2', 10, 2), ('3a', 4, 2), ('3b', 6, 3),
                                     ('4a', 2, 3), ('4b', 8, 3), *((str(i), 10, 3) for i in range(5, 9))]
    ]
    profile = RuleProfile(rules_confirmed=True, coverage_confirmed=True, syllabus_document_ids=['notes'],
                          syllabus={section: covered + ' ' + excluded},
                          material_coverage={'notes': MaterialCoverage(
                              mode='range', start_page=1, end_page=1, start_topic='Stacks remove',
                              end_topic='remove the oldest item first')})
    return Submission(profile=profile, sets=[PaperSet(label='A', questions=questions)])


def model(schema, prompt, *, provider):
    if schema.__name__ == 'DraftAttempt':
        return schema.model_validate({'candidate': {
            'question': 'An editor must undo the latest change first. Judge whether a stack or a queue meets '
                        'that requirement and justify your choice by comparing both removal orders.',
            'supporting_passage_id': 'p1',
            'marking_points': [
                {'marks': 3, 'expected': 'Choose the stack and explain newest-first removal.'},
                {'marks': 5, 'expected': 'Use the same undo criterion to explain why the queue fails.'},
            ],
        }})
    context = json.loads(prompt.split('\n', 1)[1])
    assert 'requested_level' not in context
    assert excluded not in prompt
    if schema.__name__ == 'IndependentAnswer':
        assert 'proposal' not in context and 'marking_points' not in context
        return schema.model_validate({
            'fully_answerable': True,
            'solution': 'Use a stack. Undo requires newest-first removal. A queue returns the oldest edit first.',
        })
    assert 'independent_solution' in context
    return schema.model_validate({
        'assessed_level': 5, 'syllabus_supported': True, 'self_contained': True,
        'marking_scheme_valid': True, 'distinct_from_existing': True,
        'strategy_matches': True, 'outcomes_fit': True,
        'bloom_reason': 'Students judge competing designs using the undo order criterion.',
        'coverage_reason': (
            'The note describes both removal orders. The proposed task uses those orders to evaluate whether '
            'an editor can undo the newest change first. Students apply the same criterion to both options, '
            'using the stack rule to justify selecting it and the queue rule to justify ruling out that option. '
            'It is a self-contained scenario because the undo requirement and both data structure options are '
            'part of the stem, and the source explains the knowledge that the marking points require.'
        ),
    })


class BloomReplacementTests(unittest.TestCase):
    def test_exact_and_partial_projections(self):
        submission = fixture()
        plan = replacement_plan(submission.sets[0], submission.profile)
        self.assertEqual(plan['target'], {'L1-L2': 24, 'L3-L4': 48, 'L5-L6': 8})
        self.assertEqual(plan['before'], {'L1-L2': 24, 'L3-L4': 56, 'L5-L6': 0})
        exact, = [choice for choice in plan['options'] if choice['q_no'] == '4b']
        self.assertEqual(exact['levels'], [5, 6])
        self.assertEqual(exact['after'], plan['target'])
        self.assertEqual(exact['remaining_marks'], 0)
        partial = next(choice for choice in plan['options'] if choice['q_no'] == '5')
        self.assertEqual(partial['after']['L5-L6'], 10)
        self.assertEqual(partial['remaining_marks'], 2)
        self.assertEqual(plan['options'][0], exact)

    def test_invalid_marks_and_no_improving_single_replacement(self):
        submission = fixture()
        paper = submission.sets[0]
        paper.questions = [Question(q_no=str(i), text='Question', marks=10, stated_level=level)
                           for i, level in enumerate([1, 2, 3, 3, 3, 3, 3, 5], 1)]
        self.assertEqual(replacement_plan(paper, submission.profile)['options'], [])
        paper.questions[0].marks = None
        with self.assertRaisesRegex(ValueError, 'Resolve the marks'):
            replacement_plan(paper, submission.profile)

    def test_coverage_marking_and_blind_level_fail_closed(self):
        submission = fixture()
        paper = submission.sets[0]
        question = next(q for q in paper.questions if q.q_no == '4b')
        sources = covered_sources(submission, paper, lambda _: {
            'name': 'Module 1.txt', 'pages': [{'page': 1, 'text': submission.profile.syllabus[section]}]})
        self.assertNotIn(excluded, sources[section]['text'])
        checks = [
            ('passage', 'did not cite a valid passage'),
            ('marks', 'did not add up'),
            ('unsolvable', 'could not answer'),
            ('level', 'did not agree'),
            ('coverage', 'did not pass independent checks'),
            ('wrong_key', 'a correct answer and marking scheme'),
        ]
        for issue, reason in checks:
            with self.subTest(issue=issue):
                def invalid_model(schema, prompt, *, provider):
                    response = model(schema, prompt, provider=provider)
                    if schema.__name__ == 'DraftAttempt':
                        if issue == 'passage':
                            response.candidate.supporting_passage_id = 'p9'
                        if issue == 'marks':
                            response.candidate.marking_points[0].marks = 2
                    elif schema.__name__ == 'IndependentAnswer':
                        if issue == 'unsolvable':
                            response.fully_answerable = False
                    elif issue == 'level':
                        response.assessed_level = 3
                    elif issue == 'coverage':
                        response.syllabus_supported = False
                    elif issue == 'wrong_key':
                        response.marking_scheme_valid = False
                    return response

                with patch('app.bloom_replacements.generate', side_effect=invalid_model) as mocked:
                    with self.assertRaisesRegex(ModelUnavailable, reason):
                        suggest_replacement(submission, paper, question, 5, 'same_topic', sources, set())
                    expected_calls = {'passage': 1, 'marks': 1, 'unsolvable': 2}
                    self.assertEqual(mocked.call_count, expected_calls.get(issue, 3))

    def test_owner_scoped_job_deduplicates_and_leaves_revision_untouched(self):
        submission = fixture()
        owner = 'a' * 43
        headers = {'X-Workspace-Key': owner}
        other = {'X-Workspace-Key': 'b' * 43}
        pages = [{'page': 1, 'text': submission.profile.syllabus[section]}]
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory))
            repo.save_document(owner, 'notes', 'Module 1.txt', '.txt', b'fixture', pages[0]['text'], pages)
            row = repo.create(owner, submission)
            audit = audit_submission(submission).model_dump(mode='json')
            repo.save_audit(owner, row['id'], 1, audit)
            path = f"/api/submissions/{row['id']}/bloom-replacements"
            body = {'revision': 1, 'set_label': 'A', 'q_no': '4b', 'target_level': 5, 'strategy': 'same_topic'}
            with patch.object(api, 'repo', repo), patch.object(api, 'replacement_jobs', {}), \
                 patch('app.bloom_replacements.generate', side_effect=model) as mocked:
                client = TestClient(api.app)
                plan = client.get(path, params={'revision': 1, 'set_label': 'A'}, headers=headers)
                self.assertEqual(plan.status_code, 200, plan.text)
                denied = client.post(path, headers=other, json=body)
                self.assertEqual(denied.status_code, 404)
                invalid = client.post(path, headers=headers, json={**body, 'target_level': 2})
                self.assertEqual(invalid.status_code, 422)
                mocked.assert_not_called()
                started = client.post(path, headers=headers, json=body)
                self.assertEqual(started.status_code, 202, started.text)
                job = started.json()['job_id']
                api.replacement_jobs[job][-1].result(timeout=4)
                repeated = client.post(path, headers=headers, json=body)
                self.assertEqual(repeated.json()['job_id'], job)
                self.assertEqual(mocked.call_count, 3)
                self.assertEqual(client.get(f'{path}/{job}', headers=other).status_code, 404)
                result = client.get(f'{path}/{job}', headers=headers)
                self.assertEqual(result.status_code, 200, result.text)
                suggestion = result.json()['suggestion']
                self.assertEqual(suggestion['level'], 5)
                self.assertGreater(len(suggestion['coverage_reason']), 420)
                self.assertEqual(suggestion['evidence']['page'], 1)
                self.assertIn(suggestion['evidence']['quote'], covered)
                self.assertEqual(repo.get(owner, row['id'])['submission'], row['submission'])
                self.assertEqual(repo.get(owner, row['id'])['audit'], audit)
                repo.update(owner, row['id'], 1, submission)
                self.assertEqual(client.get(f'{path}/{job}', headers=headers).status_code, 409)
