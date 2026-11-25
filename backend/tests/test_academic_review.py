import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['SCRUTINY_AI_PROVIDER']='none'
from app.domain import Question,PaperSet,Submission,RuleProfile
from app.academic_review import Batch,Critique,QuestionReview,Verification,Citation,run_academic_review,review_summary
from app.intake import ocr_image
from app.document_reader import ReadDocument,ReadPage,ReadQuestion,read_with_vision
from app.domain import Metadata
from app.model_client import ModelUnavailable


def submission():
    return Submission(profile=RuleProfile(syllabus={'source:page 1':'Stacks and queues.'},coverage_mode='all_uploaded',coverage_confirmed=True),
        sets=[PaperSet(label='A',questions=[Question(q_no=str(n),text=f'Explain stacks, case {n}.',marks=10,stated_level=4) for n in range(1,9)])])


def rows():
    return [QuestionReview(set_label='A',q_no=str(n),predicted_level=2,bloom_explanation='Explanation without analysis requires understanding.',
        syllabus_status='IN_SYLLABUS',syllabus_explanation='The source covers stacks.',citations=[Citation(section='source:page 1',quote='Stacks and queues.')],
        framing_issues=[],suggested_rewrite=None,confidence='MEDIUM') for n in range(1,9)]


class AcademicTests(unittest.TestCase):
    def test_reuploaded_paper_duplicates_block_before_batching_or_model_calls(self):
        data=submission();data.sets[0].questions+= [q.model_copy(deep=True) for q in data.sets[0].questions]
        calls=[]
        result=run_academic_review(data,lambda *args:calls.append(args))
        self.assertEqual(result['status'],'INVALID_QUESTION_IDS')
        self.assertFalse(result['model_used']);self.assertEqual(calls,[])
        self.assertEqual(len(result['duplicate_ids']),8);self.assertIn('Replace the uploaded paper',result['summary'])
        # The production path must block before collapsing IDs into batches too.
        result=run_academic_review(data)
        self.assertEqual(result['status'],'INVALID_QUESTION_IDS')
        self.assertEqual(len(data.sets[0].questions),16)

    def test_every_question_reviewed_and_verified(self):
        def model(schema,prompt):
            if schema is Batch:return Batch(reviews=rows())
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Evidence supports recommendation.') for n in range(1,9)])
        result=run_academic_review(submission(),model)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(len(result['reviews']),8)
        self.assertTrue(all(r['bloom_change_recommended'] for r in result['reviews']))

    def test_missing_question_does_not_become_complete(self):
        result=run_academic_review(submission(),lambda schema,prompt:Batch(reviews=rows()[:-1]))
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(len(result['unreviewed']),8)

    def test_clipped_question_is_not_given_a_definitive_level(self):
        data=submission();data.sets[0].extraction_warnings=['Question 8 appears clipped at the bottom.']
        def model(schema,prompt):
            if schema is Batch:return Batch(reviews=rows())
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        result=run_academic_review(data,model)
        q8=next(r for r in result['reviews'] if r['q_no']=='8')
        self.assertIsNone(q8['predicted_level'])
        self.assertEqual(q8['confidence'],'LOW')

    def test_fabricated_quote_rejected(self):
        fake=rows();fake[0].citations[0].quote='Made-up syllabus'
        result=run_academic_review(submission(),lambda schema,prompt:Batch(reviews=fake))
        self.assertEqual(result['status'],'UNAVAILABLE')

    def test_invalid_citation_gets_one_bounded_repair_then_verification(self):
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:
                result=rows()
                if calls.count(Batch)==1:result[0].citations[0].quote='Made-up evidence'
                else:self.assertIn('failed application validation',prompt)
                return Batch(reviews=result)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        result=run_academic_review(submission(),model)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(calls,[Batch,Batch,Critique])
        self.assertTrue(any(t['tool']=='validate_evidence' and t['status']=='REJECTED' for t in result['trace']))

    def test_evidence_repair_shares_existing_two_attempt_budget(self):
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:
                result=rows()
                if calls.count(Batch)==1:result[0].citations[0].quote='Made-up evidence'
                return Batch(reviews=result)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=False,feedback='Needs professor review.') for n in range(1,9)])
        result=run_academic_review(submission(),model)
        self.assertEqual(calls,[Batch,Batch,Critique])
        self.assertEqual(result['status'],'REVIEW_DISAGREEMENTS')

    def test_full_syllabus_quote_cannot_prove_selected_coverage(self):
        data=submission();data.profile.syllabus={'source:page 1':'Stacks and queues. RUP.'}
        data.profile.coverage_mode='topic_range';data.profile.coverage_start='Stacks';data.profile.coverage_end='queues.'
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:
                result=rows();result[0].citations=[Citation(section='source:page 1',quote='RUP.')]
                if calls.count(Batch)>1:
                    self.assertIn('outside the confirmed covered portion',prompt)
                    result[0].syllabus_status='OUTSIDE_COVERED_PORTION'
                    result[0].syllabus_explanation='RUP appears after the selected ending topic.'
                return Batch(reviews=result)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        result=run_academic_review(data,model)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(result['reviews'][0]['syllabus_status'],'OUTSIDE_COVERED_PORTION')
        self.assertEqual(calls,[Batch,Batch,Critique])

    def test_page_boundaries_and_whole_modules_keep_source_identity(self):
        from app.coverage import resolve_coverage
        from app.domain import MaterialCoverage
        profile = RuleProfile(material_kind='notes', syllabus_document_ids=['first', 'second'],
            syllabus={'first:page 1':'Stacks. Covered start. Queue operations.',
                      'first:page 2':'End of queue topic. Priority scheduling.',
                      'second:page 1':'Stacks. Depth-first traversal.'},
            material_coverage={
                'first':MaterialCoverage(module=1,mode='range',start_page=1,end_page=2,
                    start_topic='Covered start',end_topic='End of queue topic'),
                'second':MaterialCoverage(module=3)})
        result=resolve_coverage(profile)
        self.assertIsNone(result.error)
        self.assertEqual(result.included,{'first:page 1':'Covered start. Queue operations.',
            'first:page 2':'End of queue topic','second:page 1':'Stacks. Depth-first traversal.'})
        self.assertIn('Stacks. ',result.excluded['first:page 1'])
        self.assertIn('Priority scheduling.',result.excluded['first:page 2'][0])
        profile.material_coverage['first'].end_page=1
        self.assertIn('was not found on page 1',resolve_coverage(profile).error)

    def test_ambiguous_coverage_reports_specific_start_before_model_calls(self):
        from app.domain import MaterialCoverage
        data=submission()
        data.profile.syllabus_document_ids=['source']
        data.profile.syllabus={'source:page 1':'Start stacks. A second section: Start stacks. End queues.'}
        data.profile.material_coverage={'source':MaterialCoverage(filename='syllabus.pdf',mode='range',
            start_page=1,end_page=1,start_topic='start stacks',end_topic='end queues')}
        calls=[]
        result=run_academic_review(data,lambda *args:calls.append(args))
        self.assertEqual(calls,[])
        self.assertEqual(result['status'],'COVERAGE_REQUIRED')
        self.assertIn('syllabus.pdf: starting phrase',result['summary'])
        self.assertIn('occurs 2 times on page 1',result['summary'])

    def test_large_module_consults_last_window_for_indirect_application(self):
        import json
        from app.academic_review import PassageSelection, review_passages
        from app.coverage import ResolvedCoverage
        scope=ResolvedCoverage(included={f'module:page {page}':'Cover general tree notation. '*65 for page in range(1,18)})
        scope.included['module:page 18']='A last-in-first-out stack maintains nested undo operations.'
        consulted=set()
        def model(schema,prompt):
            self.assertIs(schema,PassageSelection)
            data=json.loads(prompt.split('\n',1)[1]); matches=[]
            for pid,passage in data['passages'].items():
                consulted.add(passage['section'])
                if passage['section']=='module:page 18':
                    matches.append({'question_id':'A/1','passage_id':pid,'relevance':3})
            return PassageSelection(matches=matches)
        passages, trace=review_passages(scope,{'A/1':'Restore drawing edits in reverse order.'},model)
        self.assertEqual(consulted,set(scope.included))
        self.assertEqual([p['section'] for p in passages.values()],['module:page 18'])
        self.assertGreater(trace[0]['windows'],1)

    def test_summary_never_counts_pending_as_verified(self):
        result=review_summary([{'verification_status':'AGREED'}]*4+[{'verification_status':'PENDING'}]*4,8)
        self.assertIn('8 of 8 questions assessed',result)
        self.assertIn('4 verified, 4 awaiting verification',result)

    def test_verifier_output_limit_retries_each_question_with_saved_recommendation(self):
        import json
        from app.model_client import ModelOutputLimit
        draft = submission()
        draft.sets[0].questions = draft.sets[0].questions[:2]
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:return Batch(reviews=rows()[:2])
            proposals = json.loads(prompt.split('\n',1)[1])['proposals']
            if len(proposals)>1:raise ModelOutputLimit()
            return Critique(decisions=[Verification(set_label='A',q_no=proposals[0]['q_no'],accepted=True,feedback='Supported.')])
        result=run_academic_review(draft,model)
        self.assertEqual(calls,[Batch,Critique,Critique,Critique])
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual([row['q_no'] for row in result['reviews']],['1','2'])

    def test_invalid_pending_evidence_is_rechecked_before_verifier_retry(self):
        pending=[{**row.model_dump(),'verification_status':'PENDING'} for row in rows()]
        pending[0]['citations'][0]['quote']='Unsupported cached quote'
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:return Batch(reviews=rows())
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        result=run_academic_review(submission(),model,previous={'reviews':pending})
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(calls,[Batch,Critique])
        self.assertTrue(any(t['tool']=='revalidate_pending_review' for t in result['trace']))

    def test_failed_repair_retains_verifier_decisions_and_other_cached_reviews(self):
        previous={'reviews':[{**r.model_dump(),'verification_status':'AGREED'} for r in rows()[:4]]}
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:
                result=rows()[4:]
                if calls.count(Batch)>1:result[0].citations[0].quote='Unsupported repair evidence'
                return Batch(reviews=result)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=n!=5,feedback='Check selected topic coverage.' if n==5 else 'Supported.') for n in range(5,9)])
        result=run_academic_review(submission(),model,previous=previous)
        self.assertEqual(calls,[Batch,Critique,Batch])
        self.assertEqual(result['status'],'REVIEW_DISAGREEMENTS')
        self.assertEqual(len(result['reviews']),8)
        self.assertEqual(sum(r['verification_status']=='AGREED' for r in result['reviews']),7)
        rejected=next(r for r in result['reviews'] if r['q_no']=='5')
        self.assertEqual(rejected['verification_status'],'DISAGREEMENT')
        self.assertEqual(rejected['verification_feedback'],'Check selected topic coverage.')

    def test_verifier_format_failure_gets_one_bounded_retry(self):
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:return Batch(reviews=rows())
            if calls.count(Critique)==1:raise ModelUnavailable('AI response failed validation (ValidationError). No complete review was inferred.')
            self.assertIn('at most 300 characters',prompt)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        result=run_academic_review(submission(),model)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(calls,[Batch,Critique,Critique])

    def test_disagreement_routes_to_bounded_repair(self):
        calls=[]
        def model(schema,prompt):
            calls.append(schema)
            if schema is Batch:return Batch(reviews=rows())
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=False,feedback='Insufficient contextual evidence.') for n in range(1,9)])
        result=run_academic_review(submission(),model)
        self.assertEqual(calls.count(Batch),2)
        self.assertEqual(result['status'],'REVIEW_DISAGREEMENTS')
        self.assertTrue(all(r['verification_status']=='DISAGREEMENT' for r in result['reviews']))

    def test_cloud_permission_required(self):
        data=submission();data.ai_mode='google';data.cloud_consent=False
        result=run_academic_review(data)
        self.assertEqual(result['status'],'CONSENT_REQUIRED')

    def test_failed_verifier_retains_work_and_retry_only_verifies(self):
        def first(schema,prompt):
            if schema is Batch:return Batch(reviews=rows())
            raise ModelUnavailable('Temporary quota limit')
        pending=run_academic_review(submission(),first)
        self.assertEqual(pending['status'],'PENDING_VERIFICATION')
        self.assertEqual(len(pending['reviews']),8)
        calls=[]
        def retry(schema,prompt):
            calls.append(schema)
            return Critique(decisions=[Verification(set_label='A',q_no=str(n),accepted=True,feedback='Supported.') for n in range(1,9)])
        complete=run_academic_review(submission(),retry,previous=pending)
        self.assertEqual(calls,[Critique])
        self.assertEqual(complete['status'],'COMPLETE')

    def test_no_cropped_syllabus_course_invention(self):
        source=ReadDocument(metadata=Metadata(),pages=[ReadPage(page=1,text='Module 1: Stacks and queues.')])
        with patch.object(Path,'read_bytes',return_value=b'%PDF-test'):
            pages,metadata,questions,*_=read_with_vision(Path('syllabus.pdf'),'doc','syllabus',call=lambda *args:source)
        self.assertEqual(metadata.course_code,'')
        self.assertEqual(questions,[])

    def test_zero_question_visual_result_rejected(self):
        source=ReadDocument(metadata=Metadata(),pages=[ReadPage(page=1,text='Unreadable scan')])
        with patch.object(Path,'read_bytes',return_value=b'%PDF-test'):
            with self.assertRaises(ValueError):read_with_vision(Path('paper.pdf'),'doc','paper',call=lambda *args:source)

    def test_windows_ocr_awaitable_is_wrapped_in_coroutine(self):
        async def result():
            rect=SimpleNamespace(x=1,y=2,width=3,height=4)
            return SimpleNamespace(lines=[SimpleNamespace(text='Readable scan',words=[SimpleNamespace(text='Readable',bounding_rect=rect)])])
        class Awaitable:
            def __await__(self):return result().__await__()
        module=SimpleNamespace(recognize_pil=lambda image:Awaitable())
        with patch.dict(sys.modules,{'winocr':module}):
            self.assertEqual(ocr_image(None)['text'],'Readable scan')


if __name__=='__main__':unittest.main()
