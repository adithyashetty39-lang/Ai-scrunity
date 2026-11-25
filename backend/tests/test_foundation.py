import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SCRUTINY_AI_PROVIDER']='none'

from app.domain import Metadata, PaperSet, Question, RuleProfile, Submission
from app.validation import audit_submission, validate_set, distribution
from app.intake import parse_proposals, check_file
from app.repository import Repository, Conflict
from app.agent_workflow import Action, run_agent


def paper(label='A'):
    return PaperSet(label=label, metadata=Metadata(course_code='TEST123',course_name='Synthetic course',max_marks=50),
        questions=[Question(q_no=str(n),text=f'Synthetic question {n}.',marks=10,co=['CO1'],po=['PO11'],stated_level=3) for n in range(1,9)])


def profile():
    return RuleProfile(course_code='TEST123',syllabus={'page1':'Arrays. Stacks. Queues.'},coverage_start='Arrays.',coverage_end='Queues.',coverage_confirmed=True)


class RulesTests(unittest.TestCase):
    def test_all_eight_paths_and_offered_total(self):
        audit=validate_set(paper(),profile())
        self.assertEqual(audit.offered_marks,80)
        self.assertEqual(len(audit.paths),8)
        self.assertTrue(all(path.marks==50 and path.questions[:2]==[1,2] for path in audit.paths))
        self.assertEqual(next(c for c in audit.criteria if c.key=='marks').status,'PASS')

    def test_wrong_alternative_detected_on_affected_paths(self):
        p=paper();p.questions[4].marks=Decimal(9)
        audit=validate_set(p,profile())
        self.assertEqual(sum(path.marks==49 for path in audit.paths),4)
        self.assertEqual(next(c for c in audit.criteria if c.key=='marks').status,'FAIL')

    def test_missing_marks_remain_unknown(self):
        p=paper();p.questions[0].marks=None
        audit=validate_set(p,profile())
        self.assertIsNone(audit.offered_marks)
        self.assertTrue(all(path.marks is None for path in audit.paths))
        self.assertNotEqual(next(c for c in audit.criteria if c.key=='marks').status,'PASS')

    def test_subparts_and_exact_bloom_targets(self):
        p=paper();p.questions=[Question(q_no=q,text='Synthetic exercise.',marks=m,stated_level=l) for q,m,l in [('1',10,1),('2',10,1),('3a',4,1),('3b',6,3),('4',10,3),('5',10,3),('6',10,3),('7',10,3),('8a',2,3),('8b',8,5)]]
        audit=validate_set(p,profile())
        self.assertEqual(audit.declared_blooms,{'L1-L2':30,'L3-L4':60,'L5-L6':10})
        self.assertFalse(any(f.code=='BLOOM_DISTRIBUTION' for c in audit.criteria for f in c.findings))
        self.assertTrue(all(path.marks==50 for path in audit.paths))

    def test_declared_and_reviewed_distributions_separate(self):
        p=paper();p.questions[0].reviewed_level=1
        self.assertEqual(distribution(p.questions)['L3-L4'],100)
        self.assertIsNone(distribution(p.questions,True))
        for q in p.questions:q.reviewed_level=1
        self.assertEqual(distribution(p.questions,True)['L1-L2'],100)

    def test_set_b_optional_and_no_false_approval(self):
        prior_profile = profile().model_dump()
        prior_profile['required_sets'] = ['A', 'B']
        migrated = RuleProfile.model_validate(prior_profile)
        result=audit_submission(Submission(profile=migrated,sets=[paper(), PaperSet(label='B')]))
        self.assertFalse(result.final_approval)
        self.assertEqual(migrated.required_sets, ['A'])
        self.assertFalse(any('Set B' in b for b in result.blockers))
        self.assertEqual([s.label for s in result.sets], ['A'])

    def test_course_mismatch(self):
        p=paper();p.metadata.course_code='OTHER123'
        result=validate_set(p,profile())
        self.assertEqual(next(c for c in result.criteria if c.key=='syllabus').status,'FAIL')

    def test_duplicate_ids_not_dropped(self):
        p=paper();p.questions[1].q_no='1'
        result=validate_set(p,profile())
        self.assertTrue(any(f.code=='DUPLICATE_ID' for c in result.criteria for f in c.findings))

    def test_range_must_exist_in_order(self):
        r=profile();r.coverage_start='Queues.';r.coverage_end='Arrays.'
        result=validate_set(paper(),r)
        self.assertTrue(any(f.code=='COVERAGE_NOT_FOUND' for c in result.criteria for f in c.findings))


class ExtractionTests(unittest.TestCase):
    def test_word_rows_survive_paragraph_breaks_inside_cells(self):
        from docx import Document
        from app.intake import read_document
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'paper.docx'
            doc = Document()
            table = doc.add_table(rows=3,cols=3)
            for row, values in zip(table.rows,[('Question No.','5','6'),('Blooms Level','L4','L4'),('PO','','')]):
                for cell,value in zip(row.cells, values):cell.text=value
            body = doc.add_table(rows=2,cols=3)
            for row,values in zip(body.rows,[('5','Analyze the first scenario.\nExplain the result.','10'),('6\n\n','Analyze the second scenario.\n','10')]):
                for cell,value in zip(row.cells, values):cell.text=value
            doc.save(path)
            pages,_ = read_document(path)
            _, questions,_ = parse_proposals(pages,'word-paper')
        self.assertEqual([q.q_no for q in questions],['5','6'])
        self.assertEqual([q.stated_level for q in questions],[4,4])
        self.assertEqual([q.marks for q in questions],[10,10])
        self.assertEqual(questions[0].text,'Analyze the first scenario. Explain the result.')

    def test_word_table_labels_and_marks_stay_with_their_question_columns(self):
        text = '\n'.join([
            'Question No. | 1 | 2 | 3a | 3b',
            'Course Outcome | CO1 | CO2 | CO1 | CO2',
            'Program Outcome | PO1 | PO2 | PO11 | PO3',
            'Blooms Level | L2 |  | L3 | L4',
            'Blooms Level Weightage (%) | L1 | L2 | L3 | L4',
            '1 | Explain two uses of stacks. | 10',
            '2 | State the queue size. | 10',
            ' | (OR) | ',
            '3 a | Apply the operation shown in fig 1. | 4',
            'b) | Analyze outcomes. | 6',
            ' | fig 1 fig 2 | ',
        ])
        _, questions, warnings = parse_proposals([{'page':1,'text':text}], 'word-paper')
        self.assertEqual([q.q_no for q in questions], ['1','2','3a','3b'])
        self.assertEqual([q.stated_level for q in questions], [2,None,3,4])
        self.assertEqual([q.marks for q in questions], [10,10,4,6])
        self.assertEqual(questions[2].po, ['PO11'])
        self.assertEqual(questions[-1].text, 'Analyze outcomes.')
        self.assertTrue(any('Bloom' in warning for warning in warnings))

    def test_multiline_and_po11(self):
        text='1 a) Explain the following scenario:\nA stack of three items. 5 CO1 PO11 L2\nb) Apply the procedure. 5 CO1 PO10 L3'
        _,questions,_=parse_proposals([{'page':1,'text':text}],'doc')
        self.assertEqual([q.q_no for q in questions],['1a','1b'])
        self.assertIn('three items',questions[0].text)
        self.assertEqual(questions[0].marks,5)
        self.assertEqual(questions[0].po,['PO11'])
        self.assertEqual(questions[1].po,['PO10'])

    def test_duplicates_retained(self):
        _,questions,_=parse_proposals([{'page':1,'text':'1) Define a stack. 10\n2) Define a stack. 10'}],'doc')
        self.assertEqual(len(questions),2)

    def test_no_invented_marks_or_unnumbered_questions(self):
        _,questions,_=parse_proposals([{'page':1,'text':'1) Explain stacks.\nOR\n2) Explain queues.'}],'doc')
        self.assertTrue(all(q.marks is None for q in questions))

    def test_magic_bytes(self):
        with self.assertRaises(ValueError):check_file(b'not a PDF','.pdf')

    def test_cross_page_evidence_retains_page_locations(self):
        _,questions,_=parse_proposals([{'page':1,'text':'1) Explain this scenario:'},{'page':2,'text':'A stack of items. 10 CO1 PO11 L2'}],'doc')
        self.assertEqual(len(questions),1)
        self.assertEqual([e.page for e in questions[0].evidence],[1,2])
        self.assertEqual(questions[0].marks,10)


class StorageTests(unittest.TestCase):
    def test_owner_isolation_revision_conflict_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Repository(Path(directory));payload=Submission(profile=profile(),sets=[paper()])
            first=repo.create('owner-a',payload)
            with self.assertRaises(KeyError):repo.get('owner-b',first['id'])
            payload.title='Edited'
            updated=repo.update('owner-a',first['id'],1,payload)
            self.assertEqual(updated['revision'],2)
            self.assertEqual(repo.get('owner-a',first['id'],1)['submission']['title'],'Untitled scrutiny')
            with self.assertRaises(Conflict):repo.update('owner-a',first['id'],1,payload)
            with self.assertRaises(KeyError):repo.get('owner-a','invalid-id')


class AgentTests(unittest.TestCase):
    def test_agent_uses_tools_and_exact_evidence_without_approval(self):
        class Planner:
            def __init__(self):self.index=0
            def choose(self,context):
                actions=[Action(tool='retrieve_syllabus',query='stacks'),Action(tool='propose_finding',set_label='A',question_id='1',module='page1',quote='Stacks.',summary='Check this syllabus passage.'),Action(tool='finish',summary='Professor review needed.')]
                result=actions[self.index];self.index+=1;return result
        submission=Submission(profile=profile(),sets=[paper()])
        result=run_agent(submission,Planner())
        self.assertTrue(result['model_used'])
        self.assertEqual(len(result['trace']),3)
        self.assertEqual(len(result['proposals']),1)
        self.assertFalse(audit_submission(submission).final_approval)

    def test_fabricated_evidence_rejected(self):
        class Planner:
            def choose(self,context):return Action(tool='propose_finding',set_label='A',question_id='1',module='page1',quote='Invented quotation',summary='Unsupported')
        result=run_agent(Submission(profile=profile(),sets=[paper()]),Planner(),max_steps=2)
        self.assertEqual(len(result['trace']),2)
        self.assertEqual(result['proposals'],[])
        self.assertTrue(all(t['result']['status']=='REJECTED' for t in result['trace']))

    def test_invalid_model_output_cannot_crash_audit(self):
        class Planner:
            def choose(self,context):return {'tool':'approve_everything'}
        result=run_agent(Submission(profile=profile(),sets=[paper()]),Planner())
        self.assertFalse(result['model_used'])
        self.assertEqual(result['trace'][0]['status'],'ERROR')


if __name__=='__main__':unittest.main()
