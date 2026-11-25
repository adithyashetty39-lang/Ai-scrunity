import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['SCRUTINY_AI_PROVIDER']='none'
from fastapi.testclient import TestClient
from app import api
from app.domain import Submission
from app.repository import Repository


class WorkspaceTests(unittest.TestCase):
    def test_hosted_access_link_issues_signed_owner_session(self):
        with patch.dict(os.environ,{'SCRUTINY_HOSTED':'1','SCRUTINY_ACCESS_TOKEN':'a-long-synthetic-presentation-code-123'}):
            self.assertEqual(self.client.post('/api/session').status_code,401)
            self.assertEqual(self.client.get('/api/submissions',headers=self.key).status_code,401)
            unlock=self.client.post('/api/session',json={'access_code':'a-long-synthetic-presentation-code-123'})
            self.assertEqual(unlock.status_code,200,unlock.text)
            session=unlock.json()['workspace_key']
            self.assertNotIn('synthetic',session)
            headers={'X-Workspace-Key':session}
            self.assertEqual(self.client.get('/api/submissions',headers=headers).json(),[])
            self.assertEqual(self.client.get('/api/profiles/starter',headers=headers).json()['submission']['ai_mode'],'cloud')
            with patch.dict(os.environ,{'SCRUTINY_ACCESS_TOKEN':'replacement-secret'}):
                self.assertEqual(self.client.get('/api/submissions',headers=headers).status_code,401)

    def test_async_review_job_is_owner_scoped_and_saves_audit(self):
        row=self.create()
        path=f"/api/submissions/{row['id']}/review-job?revision=1"
        submit=api.review_workers.submit
        futures=[]

        def capture_future(*args):
            future=submit(*args)
            futures.append(future)
            return future

        with patch.object(api.review_workers,'submit',side_effect=capture_future):
            self.assertEqual(self.client.post(path,headers=self.key).status_code,202)
            self.assertEqual(self.client.get(path,headers=self.other).status_code,404)
            futures[0].result(timeout=4)
        status=self.client.get(path,headers=self.key).json()
        self.assertEqual(status['status'],'finished',status)
        self.assertEqual(status['record']['audit']['agent']['status'],'NO_QUESTIONS')

    def test_public_provider_config_and_synthetic_connection_check(self):
        env={'SCRUTINY_AI_PROVIDER':'openai','SCRUTINY_AI_KEY':'synthetic-secret','SCRUTINY_AI_MODEL':'test-model'}
        with patch.dict(os.environ,env,clear=True):
            config=self.client.get('/api/ai/config').json()['cloud']
            self.assertTrue(config['configured']);self.assertNotIn('synthetic-secret',str(config))
            with patch.object(api,'generate',return_value=api.ConnectionProbe(ok=True)) as model:
                bad=self.client.post('/api/ai/check',headers=self.key,json={'provider_id':'previous-service'})
                self.assertEqual(bad.status_code,503);model.assert_not_called()
                good=self.client.post('/api/ai/check',headers=self.key,json={'provider_id':config['id']})
                self.assertEqual(good.status_code,200,good.text)
                self.assertIn('synthetic',good.json()['message']);self.assertNotIn('synthetic-secret',good.text)
                self.assertEqual(model.call_args.args[1],'Connection test only. Return the JSON object {"ok":true}.')

    def test_upload_rejects_stale_cloud_permission_before_inference(self):
        with patch.dict(os.environ,{'SCRUTINY_AI_PROVIDER':'openai','SCRUTINY_AI_KEY':'synthetic-secret','SCRUTINY_AI_MODEL':'test-model'},clear=True),patch.object(api,'read_with_vision') as read:
            result=self.client.post('/api/documents',headers=self.key,
                data={'ai_mode':'cloud','allow_cloud':'true','cloud_provider_id':'old-service'},
                files={'file':('paper.txt',b'1) Explain stacks. 10','text/plain')})
            self.assertEqual(result.status_code,422,result.text)
            self.assertIn('changed',result.json()['detail']);read.assert_not_called()

    def test_mapping_photo_upload_routes_to_table_reader(self):
        from io import BytesIO
        from PIL import Image
        from app.domain import Metadata
        image=BytesIO(); Image.new('RGB',(16,16),'white').save(image,format='PNG')
        extracted=([{'page':1,'text':'CO1 | PO2 | 3'}], Metadata(), [], {'CO1':'Apply stacks.'}, {'CO1':{'PO2':3}}, [])
        with patch.object(api,'read_mapping_image',return_value=None),patch.object(api,'read_with_vision',return_value=extracted) as reader:
            response=self.client.post('/api/documents',headers=self.key,data={'role':'mapping'},
                files={'file':('matrix.png',image.getvalue(),'image/png')})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(reader.call_args.args[2],'mapping')
        self.assertEqual(response.json()['co_po'],{'CO1':{'PO2':3}})
        self.assertEqual(response.json()['questions'],[])

    def test_mapping_photo_uses_local_table_positions_without_vision_request(self):
        from io import BytesIO
        from PIL import Image
        from app.mapping_reader import read_matrix

        def word(text,x,y,width=14):
            return {'text':text,'x':x,'y':y,'width':width,'height':10}
        headings = [word('CO/PO',10,10,30)]
        headings.extend(word('P0'+str(number),50+number*40,10) for number in range(1,11))
        headings.extend([word('POI',490,10),word('1',506,10,4)])
        words = headings + [word('COI',17,30),word('3',94,30,4),word('2',500,30,4),
                            word('C02',17,50),word('3',214,50,4),word('1',500,50,4)]
        lines = [{'words':[item]} for item in reversed(words)]
        expected = {'CO1':{'PO1':3,'PO11':2},'CO2':{'PO4':3,'PO11':1}}
        self.assertEqual(read_matrix(lines),expected)
        with patch('app.mapping_reader.ocr_image',return_value={'ocr_lines':lines,'text':'Course Code: TEST123'}), \
             patch.object(api,'read_with_vision') as vision:
            image=BytesIO(); Image.new('RGB',(600,120),'white').save(image,format='PNG')
            result = self.client.post('/api/documents', headers=self.key, data={'role':'mapping'},
                files={'file':('matrix.png',image.getvalue(),'image/png')})
            self.assertEqual(result.status_code,201,result.text)
            self.assertEqual(result.json()['co_po'],expected)
            self.assertEqual(result.json()['metadata']['course_code'],'TEST123')
            vision.assert_not_called()

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.previous=api.repo
        api.repo=Repository(Path(self.directory.name));self.client=TestClient(api.app)
        self.key={'X-Workspace-Key':'A'*40};self.other={'X-Workspace-Key':'B'*40}

    def tearDown(self):
        api.repo=self.previous;self.directory.cleanup()

    def create(self,payload=None):
        result=self.client.post('/api/submissions',json=payload or Submission().model_dump(mode='json'),headers=self.key)
        self.assertEqual(result.status_code,201,result.text)
        return result.json()

    def test_private_records_and_invalid_ids(self):
        row=self.create()
        self.assertEqual(self.client.get('/api/submissions/'+row['id'],headers=self.other).status_code,404)
        self.assertEqual(self.client.get('/api/submissions/not-real',headers=self.key).status_code,404)
        self.assertEqual(self.client.get('/api/submissions/'+row['id']).status_code,422)

    def test_stale_save_and_revision_scoped_audit(self):
        row=self.create();path='/api/submissions/'+row['id']
        body={'expected_revision':1,'submission':row['submission']}
        self.assertEqual(self.client.put(path,json=body,headers=self.key).status_code,200)
        self.assertEqual(self.client.put(path,json=body,headers=self.key).status_code,409)
        audit=self.client.post(path+'/audit?revision=1',headers=self.key)
        self.assertEqual(audit.status_code,200,audit.text)
        self.assertFalse(audit.json()['audit']['final_approval'])
        self.assertIsNone(self.client.get(path+'?revision=2',headers=self.key).json()['audit'])

    def test_upload_does_not_use_client_path(self):
        result=self.client.post('/api/documents',files={'file':('../escaped.txt',b'1) Explain stacks. 10','text/plain')},headers=self.key)
        self.assertEqual(result.status_code,201,result.text)
        doc_id=result.json()['id']
        self.assertFalse((api.repo.root/'escaped.txt').exists())
        self.assertTrue((api.repo.root/'documents'/(doc_id+'.txt')).exists())
        self.assertEqual(self.client.get('/api/documents/'+doc_id,headers=self.other).status_code,404)

    def test_duplicate_syllabus_bytes_are_rejected_even_with_different_filename(self):
        content=b'Module 1: Stacks and queues.'
        first=self.client.post('/api/documents', headers=self.key, data={'role':'syllabus'},
            files={'file':('original.txt',content,'text/plain')})
        self.assertEqual(first.status_code,201,first.text)
        duplicate=self.client.post('/api/documents',headers=self.key,
            data={'role':'syllabus','attached_syllabus_ids':first.json()['id']},
            files={'file':('renamed.txt',content,'text/plain')})
        self.assertEqual(duplicate.status_code,409,duplicate.text)

    def test_rejects_fabricated_source_quotes(self):
        row=self.create();submission=row['submission']
        submission['sets']=[{'label':'A','metadata':{},'document_ids':[],'questions':[{'q_no':'1','text':'Text','marks':10,'evidence':[{'document_id':'fake','page':1,'quote':'invented'}]}]}]
        res=self.client.put('/api/submissions/'+row['id'],headers=self.key,json={'expected_revision':1,'submission':submission})
        self.assertEqual(res.status_code,404)

    def test_uploaded_proposals_can_be_saved_and_audited(self):
        text=b'Course Code: TEST123\nCourse Name: Synthetic course\n1 a) Explain the scenario:\nA stack of items. 5 CO1 PO11 L2\nb) Apply the operation. 5 CO1 PO11 L3'
        doc=self.client.post('/api/documents',headers=self.key,files={'file':('paper.txt',text,'text/plain')}).json()
        submission=Submission().model_dump(mode='json')
        submission['sets']=[{'label':'A','metadata':doc['metadata'],'document_ids':[doc['id']],'questions':doc['questions']}]
        created=self.client.post('/api/submissions',headers=self.key,json=submission)
        self.assertEqual(created.status_code,201,created.text)
        row=created.json()
        audited=self.client.post('/api/submissions/'+row['id']+'/audit?revision=1',headers=self.key)
        self.assertEqual(audited.status_code,200,audited.text)
        self.assertFalse(audited.json()['audit']['final_approval'])

    def test_no_silent_sample_pdf_or_final_approval(self):
        row=self.create();path='/api/submissions/'+row['id']
        self.assertEqual(self.client.get('/api/report.pdf').status_code,410)
        self.assertEqual(self.client.get(path+'/report.pdf?revision=1',headers=self.key).status_code,409)
        self.assertEqual(self.client.post(path+'/finalize',headers=self.key).status_code,409)

    def test_draft_pdf_exact_revision_and_draft_label(self):
        row=self.create({'sets':[{'label':'A','metadata':{'course_code':'TEST123','course_name':'Synthetic course metadata','date':'14/11/2026'}}]});path='/api/submissions/'+row['id']
        self.client.post(path+'/audit?revision=1',headers=self.key)
        response=self.client.get(path+'/report.pdf?revision=1',headers=self.key)
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        self.assertTrue(response.content.startswith(b'%PDF'))
        import pdfplumber
        from io import BytesIO
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            self.assertEqual(len(pdf.pages),2)
            self.assertTrue(all('DRAFT - NOT APPROVED' in page.extract_text() for page in pdf.pages))
            self.assertIn('Synthetic course metadata',pdf.pages[0].extract_text())
            self.assertIn('TEST123',pdf.pages[0].extract_text())
            self.assertIn('14/11/2026',pdf.pages[0].extract_text())

    def test_faculty_bloom_decisions_create_audited_revisions_without_model_calls(self):
        from io import BytesIO
        import pdfplumber

        row = self.create({'sets':[{'label':'A','questions':[
            {'q_no':'1','text':'Trace a stack operation.','marks':10,'stated_level':4},
        ]}]})
        path = f"/api/submissions/{row['id']}"
        audit = api.audit_submission(Submission.model_validate(row['submission']))
        audit.agent = {'status':'COMPLETE','reviews':[{
            'set_label':'A','q_no':'1','predicted_level':3,'verification_status':'AGREED',
            'bloom_explanation':'The task applies a learned procedure.',
        }], 'trace':[{'tool':'independent_verifier'}]}
        api.repo.save_audit(self.key['X-Workspace-Key'],row['id'],1,audit.model_dump(mode='json'))
        command = {'set_label':'A','q_no':'1','expected_revision':1,'expected_suggested_level':3,
                   'action':'accepted','note':'  Use the standard trace.  '}
        decision_url = path+'/faculty-bloom'
        self.assertEqual(self.client.post(decision_url,headers=self.other,json=command).status_code,404)
        with patch.object(api,'run_academic_review') as review:
            mismatch = self.client.post(decision_url,headers=self.key,json={**command,'expected_suggested_level':4})
            self.assertEqual(mismatch.status_code,409)
            accepted = self.client.post(decision_url,headers=self.key,json=command)
            self.assertEqual(accepted.status_code,200,accepted.text)
            accepted = accepted.json()
            self.assertEqual(accepted['revision'],2)
            self.assertEqual(accepted['audit']['agent'],audit.agent)
            self.assertEqual(accepted['audit']['sets'][0]['reviewed_blooms']['L3-L4'],'100')
            finding = accepted['audit']['question_findings'][0]
            self.assertEqual((finding['printed_level'],finding['suggested_level'],finding['faculty_level']),('L4','L3','L3'))
            self.assertEqual(finding['faculty_bloom_decision']['note'],'Use the standard trace.')
            self.assertIn('Accepted AI suggestion',finding['faculty_bloom_decision']['label'])
            self.assertEqual(self.client.post(decision_url,headers=self.key,json=command).status_code,409)
            override = {**command,'expected_revision':2,'action':'overridden','note':'Requires judging a proposed solution.'}
            self.assertEqual(self.client.post(decision_url,headers=self.key,json=override).status_code,422)
            changed = self.client.post(decision_url,headers=self.key,json={**override,'override_level':5})
            self.assertEqual(changed.status_code,200,changed.text)
            self.assertEqual(changed.json()['audit']['sets'][0]['reviewed_blooms']['L5-L6'],'100')
            self.assertEqual(changed.json()['revision'],3)
            defer = {**command,'expected_revision':3,'action':'deferred','note':'Wait for the marking scheme.'}
            pending = self.client.post(decision_url,headers=self.key,json=defer)
            self.assertEqual(pending.status_code,200,pending.text)
            self.assertEqual(pending.json()['revision'],4)
            self.assertEqual(pending.json()['audit']['question_findings'][0]['faculty_level'],'Unresolved')
            self.assertIsNone(pending.json()['audit']['sets'][0]['reviewed_blooms'])
            self.assertEqual(self.client.post(decision_url,headers=self.key,json={**defer,'expected_revision':4}).json()['revision'],4)
            review.assert_not_called()
        original = self.client.get(path+'?revision=1',headers=self.key).json()
        self.assertIsNone(original['submission']['sets'][0]['questions'][0]['reviewed_level'])
        final = self.client.get(path,headers=self.key).json()
        self.assertEqual(final['audit']['question_findings'][0]['faculty_bloom_decision']['label'],'Deferred')
        for rev, label, note in ((2,'Accepted AI suggestion (L3)','Use the standard trace.'),
                                 (3,'Overridden to L5','Requires judging a proposed solution.'),
                                 (4,'Deferred','Wait for the marking scheme.')):
            pdf = self.client.get(f'{path}/report.pdf?revision={rev}',headers=self.key)
            self.assertEqual(pdf.status_code,200)
            with pdfplumber.open(BytesIO(pdf.content)) as report:
                findings = ' '.join(' '.join(page.extract_text().split()) for page in report.pages[2:])
                self.assertIn('Faculty decision - '+label,findings)
                self.assertIn(note,findings)

    def test_embedded_figure_reaches_both_agents_and_is_access_controlled(self):
        from io import BytesIO
        from docx import Document
        from PIL import Image
        import pdfplumber
        from app.academic_review import Batch, Critique, run_academic_review
        from app.model_client import ModelUnavailable

        picture = BytesIO()
        Image.new('RGB',(200,120),'white').save(picture,'PNG')
        picture.seek(0)
        word = Document()
        table = word.add_table(rows=2,cols=3)
        for index, phrase in enumerate(('Trace the supplied game tree.', 'Use Figure 2 to trace the same method.')):
            cells = table.rows[index].cells
            cells[0].text = str(index+1)
            cells[1].text = phrase
            cells[2].text = '10'
        table.cell(0,1).add_paragraph().add_run().add_picture(picture)
        original = BytesIO()
        word.save(original)
        uploaded = self.client.post('/api/documents',headers=self.key,
            files={'file':('tree.docx',original.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        self.assertEqual(uploaded.status_code,201,uploaded.text)
        paper = uploaded.json()
        source = self.client.post('/api/documents',headers=self.key,data={'role':'syllabus'},
            files={'file':('syllabus.txt',b'Game tree evaluation is included.','text/plain')}).json()
        section = f"{source['id']}:page 1"
        row = self.create({'profile':{
            'syllabus_document_ids':[source['id']], 'syllabus':{section:source['pages'][0]['text']},
            'material_coverage':{source['id']:{'mode':'entire'}}, 'coverage_confirmed':True,
        }, 'sets':[{'label':'A','document_ids':[paper['id']], 'questions':paper['questions'],
                    'extraction_warnings':paper['warnings']}]})
        calls = []

        def model(schema,prompt,attachments=()):
            calls.append((schema,attachments))
            self.assertIn('paper_visuals',prompt)
            self.assertEqual(len(attachments),1)
            self.assertTrue(attachments[0][1].startswith(b'\xff\xd8'))
            if len(calls) == 1:
                raise ModelUnavailable('AI response failed validation (ValidationError). No complete review was inferred.')
            if schema is Critique:
                return Critique(decisions=[{'set_label':'A','q_no':q,'accepted':True,'feedback':'Checked against the source.'}
                                           for q in ('1','2')])
            return Batch(reviews=[{'set_label':'A','q_no':q,'predicted_level':3,
                'bloom_explanation':'Trace the given procedure.', 'syllabus_status':'IN_SYLLABUS',
                'syllabus_explanation':'The material covers game trees.', 'citations':[{'section':section,'quote':'Game tree evaluation'}],
                'framing_issues':[], 'suggested_rewrite':None,'confidence':'HIGH',
                'figure_assessment':{'status':'SUFFICIENT','observations':['Leaf values 3 and 5 are visible.'],
                    'explanation':'The leaf values support tracing the tree.','suggestion':'Keep the printed leaf values.'}}
                for q in ('1','2')])

        path = f"/api/submissions/{row['id']}"
        with patch.object(api,'run_academic_review',side_effect=lambda submission,previous,**kwargs:
                          run_academic_review(submission,model,previous=previous,**kwargs)):
            result = self.client.post(path+'/audit?revision=1',headers=self.key)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([schema for schema,_ in calls],[Batch,Batch,Critique])
        self.assertTrue(all(attachments == calls[0][1] for _,attachments in calls))
        self.assertIn('repair_visual_response_format',[entry['tool'] for entry in result.json()['audit']['agent']['trace']])
        first,second = result.json()['audit']['question_findings']
        self.assertEqual(first['checks'][-2]['label'],'Question wording')
        self.assertEqual(first['checks'][-1]['status'],'Supported')
        self.assertIn('Leaf values 3 and 5',first['checks'][-1]['reason'])
        self.assertEqual(second['checks'][-1]['status'],'Needs review')
        self.assertIn('could not link',second['checks'][-1]['reason'])
        preview = f"/api/documents/{paper['id']}/figures/embedded/1"
        image = self.client.get(preview,headers=self.key)
        self.assertEqual(image.content,calls[0][1][0][1])
        self.assertEqual(self.client.get(preview,headers=self.other).status_code,404)
        exported = self.client.get(path+'/report.pdf?revision=1',headers=self.key)
        with pdfplumber.open(BytesIO(exported.content)) as pdf:
            text = ' '.join(' '.join(page.extract_text().split()) for page in pdf.pages[2:])
            self.assertIn('Figure assessment - Supported',text)
            self.assertIn('Leaf values 3 and 5',text)
            self.assertIn('could not link a viewable figure',text)

    def test_matching_pdf_caption_links_the_referenced_page(self):
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        from app.paper_figures import visual_sources

        pdf = BytesIO()
        canvas = Canvas(pdf)
        canvas.drawString(60,740,'1) Use Figure 2 to trace the game tree. 10 CO1 PO1 L3')
        canvas.showPage()
        canvas.drawString(60,740,'Figure 2. Game tree.')
        canvas.save()
        response = self.client.post('/api/documents',headers=self.key,
            files={'file':('tree.pdf',pdf.getvalue(),'application/pdf')})
        self.assertEqual(response.status_code,201,response.text)
        paper = response.json()
        draft = Submission.model_validate({'sets':[{'label':'A','document_ids':[paper['id']],'questions':paper['questions']}]})
        sources = visual_sources(api.repo,self.key['X-Workspace-Key'],draft)
        self.assertEqual([source.index for source in sources['A/1']],[2])
        preview = self.client.get(f"/api/documents/{paper['id']}/figures/page/2",headers=self.key)
        self.assertEqual(preview.status_code,200)
        self.assertTrue(preview.content.startswith(b'\xff\xd8'))

    def test_word_figures_after_last_question_follow_their_shared_caption_line(self):
        from io import BytesIO
        from docx import Document
        from PIL import Image
        from app.paper_figures import visual_sources

        def diagram(color):
            image = BytesIO()
            Image.new('RGB',(80,70),color).save(image,'PNG')
            image.seek(0)
            return image

        word = Document()
        word.add_paragraph().add_run().add_picture(diagram('black'))
        table = word.add_table(rows=5,cols=3)
        for row,number,text in zip(table.rows,('4','5','6','8'),
                                  ('Trace this case.','Use fig 1.','Use Fig. 2.','Explain the method.')):
            cells = row.cells
            cells[0].text, cells[1].text, cells[2].text = number,text,'10'
        table.cell(0,1).add_paragraph().add_run().add_picture(diagram('green'))
        figures = table.cell(4,1)
        figures.paragraphs[0].add_run().add_picture(diagram('red'))
        figures.paragraphs[0].add_run().add_picture(diagram('blue'))
        figures.add_paragraph('Fig 1                                     Fig 2')
        original = BytesIO()
        word.save(original)
        upload = self.client.post('/api/documents',headers=self.key,
            files={'file':('captioned.docx',original.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        self.assertEqual(upload.status_code,201,upload.text)
        paper = upload.json()
        draft = Submission.model_validate({'sets':[{'label':'A','document_ids':[paper['id']],
            'questions':paper['questions'],'extraction_warnings':paper['warnings']}]})
        key = self.key['X-Workspace-Key']
        by_question = visual_sources(api.repo,key,draft)
        self.assertEqual(by_question['A/4'][0].index,1)
        for number,index,caption,channel in (('5',2,'Figure 1',0),('6',3,'Figure 2',2)):
            source, = by_question[f'A/{number}']
            self.assertEqual(source.index,index)
            self.assertEqual(source.public()['label'],caption)
            response = self.client.get(f"/api/documents/{paper['id']}/figures/embedded/{index}",headers=self.key)
            self.assertEqual(response.status_code,200,response.text)
            with Image.open(BytesIO(response.content)) as rendered:
                self.assertGreater(rendered.getpixel((40,35))[channel],240)
        self.assertNotIn('A/8',by_question)

        row = self.create(draft.model_dump(mode='json'))
        audit = api.audit_submission(draft)
        audit.agent = {'status':'COMPLETE','engine_version':api.REVIEW_ENGINE_VERSION,
                       'figure_sources':{'A/4':[by_question['A/4'][0].public()],'A/5':[],'A/6':[]},
                       'reviews':[{'set_label':'A','q_no':number,'verification_status':'AGREED'}
                                  for number in ('4','5','6','8')]}
        api.repo.save_audit(key,row['id'],1,audit.model_dump(mode='json'))
        with patch.object(api,'run_academic_review',return_value={'status':'PARTIAL'}) as review:
            response = self.client.post(f"/api/submissions/{row['id']}/audit?revision=1",headers=self.key)
            self.assertEqual(response.status_code,200,response.text)
            kept = review.call_args.kwargs['previous']['reviews']
            self.assertEqual([item['q_no'] for item in kept],['4','8'])

    def test_pdf_recovers_two_side_by_side_captions_from_original_page(self):
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        from app.paper_figures import visual_sources

        pdf = BytesIO()
        canvas = Canvas(pdf)
        canvas.drawString(60,740,'1) Use Fig 1 to trace search. 10 CO1 PO1 L3')
        canvas.drawString(60,720,'2) Find a route using Figure 2. 10 CO1 PO1 L3')
        canvas.showPage()
        canvas.drawString(60,160,'Fig 1')
        canvas.drawString(330,160,'Fig 2')
        canvas.save()
        uploaded = self.client.post('/api/documents',headers=self.key,
            files={'file':('side-by-side.pdf',pdf.getvalue(),'application/pdf')})
        self.assertEqual(uploaded.status_code,201,uploaded.text)
        paper = uploaded.json()
        key = self.key['X-Workspace-Key']
        draft = Submission.model_validate({'sets':[{'label':'A','document_ids':[paper['id']],'questions':paper['questions']}]})
        source = api.repo.document(key,paper['id'])
        source['pages'][1]['text'] = 'Two diagrams at the end of the paper.'
        with patch.object(api.repo,'document',return_value=source):
            linked = visual_sources(api.repo,key,draft)
        self.assertEqual([figure.index for figure in linked['A/1']],[2])
        self.assertEqual([figure.public()['label'] for figure in linked['A/2']],['Figure 2 on page 2'])

    def test_saved_partial_audit_explains_pass_mismatch_and_missing_review_in_api_and_pdf(self):
        from io import BytesIO
        import pdfplumber

        row = self.create({
            'profile': {'outcomes': {'CO1': 'Apply stack operations.'}, 'co_po': {'CO1': {'PO1': 3}}},
            'sets': [{'label': 'A', 'questions': [
                {'q_no': '1', 'text': 'Trace one stack pop.', 'marks': 10, 'stated_level': 3, 'co': ['CO1'], 'po': ['PO1']},
                {'q_no': '2', 'text': 'Trace stack operations and identify the last item.', 'marks': 10, 'stated_level': 4, 'co': ['CO1'], 'po': ['PO3']},
                {'q_no': '3', 'text': 'Explain last-in, first-out.', 'marks': 10, 'stated_level': 2},
            ]}],
        })
        path = f"/api/submissions/{row['id']}"
        audit = api.audit_submission(Submission.model_validate(row['submission']))
        review = {
            'set_label': 'A', 'predicted_level': 3, 'syllabus_status': 'IN_SYLLABUS',
            'syllabus_explanation': 'The task applies the stack method in Module 1.',
            'citations': [{'section': 'Module 1', 'quote': 'Stack operations'}],
            'framing_issues': [], 'confidence': 'HIGH', 'verification_status': 'AGREED',
            'framing_explanation': 'The question specifies the operation and the expected result.',
        }
        audit.agent = {
            'status': 'PARTIAL', 'summary': 'AI cited unsupported evidence for A/3.',
            'reviews': [
                {**review,'q_no':'1','bloom_explanation':'Tracing the given stack is a routine application.'},
                {**review,'q_no':'2','bloom_explanation':'This task executes a standard stack procedure.',
                 'framing_issues':['The initial stack contents are missing.'],
                 'framing_suggestion':'Reduce the marks to match the task.',
                 'suggested_rewrite':'Given a stack with items A and B, trace two pop operations.'},
            ],
        }
        api.repo.save_audit(self.key['X-Workspace-Key'],row['id'],1,audit.model_dump(mode='json'))
        response = self.client.get(path,headers=self.key)
        self.assertEqual(response.status_code,200,response.text)
        first, second, third = response.json()['audit']['question_findings']
        self.assertEqual(first['checks'][0]['status'],'Supported')
        self.assertIn('routine application',first['checks'][0]['reason'])
        self.assertIn('from L4 to L3',second['checks'][0]['suggestion'])
        self.assertIn('PO3 falls outside',second['checks'][2]['reason'])
        self.assertIn('The initial stack contents are missing',second['checks'][4]['reason'])
        self.assertIn('Keep the full question at 10 marks',second['checks'][4]['suggestion'])
        self.assertEqual(third['checks'][0]['status'],'Incomplete')
        self.assertIn('unsupported evidence for A/3',third['checks'][0]['reason'])
        report = self.client.get(path+'/report.pdf?revision=1',headers=self.key)
        self.assertEqual(report.status_code,200)
        with pdfplumber.open(BytesIO(report.content)) as pdf:
            self.assertGreater(len(pdf.pages),2)
            text = ' '.join(' '.join(page.extract_text().split()) for page in pdf.pages[2:])
            for phrase in ('Set A - Question 1','Set A - Question 2','Set A - Question 3',
                           'routine application','from L4 to L3','PO3 falls outside',
                           'Keep the full question at 10 marks','unsupported evidence for A/3'):
                self.assertIn(phrase,text)

    def test_two_set_intake_faculty_review_and_departmental_draft(self):
        syllabus = self.client.post('/api/documents', headers=self.key, data={'role':'syllabus'},
            files={'file':('syllabus.txt', b'Course Code: TEST123\nStacks and queues.', 'text/plain')})
        self.assertEqual(syllabus.status_code, 201, syllabus.text)
        source = syllabus.json()
        payload = Submission().model_dump(mode='json')
        payload['profile'].update(course_code='TEST123', material_kind='notes',
            coverage_confirmed=True, course_evidence_verified=True, rules_confirmed=True,
            syllabus_document_ids=[source['id']],
            material_coverage={source['id']:{'module':1,'mode':'range','start_page':1,'end_page':1,
                'start_topic':'Stacks','end_topic':'Stacks and queues'}},
            syllabus={f"{source['id']}:page {p['page']}":p['text'] for p in source['pages']},
            outcomes={'CO1':'Use stacks and queues.'}, co_po={'CO1':{'PO1':3}})
        marks = [('1',10,1),('2',10,2),('3 a',4,2),('3 b',6,3),('4',10,3),
                ('5',10,3),('6',10,4),('7',10,4),('8 a',2,3),('8 b',8,5)]
        for label in ('A','B'):
            text = '\n'.join(f'{qid}) Evaluate stack exercise {label}/{qid}. {value} CO1 PO1 L{level}'
                for qid, value, level in marks)
            upload = self.client.post('/api/documents', headers=self.key,
                files={'file':(f'set-{label}.txt', text.encode(), 'text/plain')})
            self.assertEqual(upload.status_code, 201, upload.text)
            paper = upload.json()
            self.assertEqual(len(paper['questions']), 10)
            payload['sets'].append({'label':label, 'document_ids':[paper['id']], 'questions':paper['questions'],
                'metadata':{'course_code':'TEST123', 'course_name':'Synthetic course', 'semester':'5',
                    'date':'22/11/2026', 'academic_year':'2026-27', 'ia_test_no':'1', 'duration':'90 min', 'max_marks':50}})

        row = self.create(payload)
        url = '/api/submissions/' + row['id']
        unreviewed = self.client.post(url+'/audit?revision=1&enable_agent=false', headers=self.key).json()
        self.assertEqual(unreviewed['audit']['status'], 'BLOCKED')
        for paper in payload['sets']:
            paper['faculty_checks'] = dict.fromkeys(('syllabus','assessment','outcomes','format'), 'confirmed')
            for question in paper['questions']:
                question.update(extraction_confirmed=True, reviewed_level=question['stated_level'])
        saved = self.client.put(url, headers=self.key, json={'expected_revision':1,'submission':payload})
        self.assertEqual(saved.status_code, 200, saved.text)
        from app.academic_review import Batch, Critique, run_academic_review

        def model_response(schema, prompt):
            if schema is Batch:
                return Batch(reviews=[{
                    'set_label':paper['label'], 'q_no':q['q_no'], 'predicted_level':q['stated_level'],
                    'bloom_explanation':'Synthetic faculty-reviewed fixture.', 'syllabus_status':'IN_SYLLABUS',
                    'syllabus_explanation':'The fixture covers stacks and queues.',
                    'citations':[{'section':next(iter(payload['profile']['syllabus'])), 'quote':'Stacks and queues.'}],
                    'framing_issues':[], 'suggested_rewrite':None, 'confidence':'HIGH',
                } for paper in payload['sets'] for q in paper['questions']])
            self.assertIs(schema, Critique)
            return Critique(decisions=[{'set_label':paper['label'], 'q_no':q['q_no'], 'accepted':True,
                'feedback':'Accepted synthetic fixture.'} for paper in payload['sets'] for q in paper['questions']])

        with patch.object(api, 'run_academic_review', side_effect=lambda submission, previous:
                          run_academic_review(submission, call=model_response, previous=previous)):
            result = self.client.post(url+'/audit?revision=2&enable_agent=true', headers=self.key)
        self.assertEqual(result.status_code, 200, result.text)
        audit = result.json()['audit']
        self.assertEqual(audit['status'], 'READY_FOR_FACULTY_REVIEW', audit)
        self.assertFalse(audit['final_approval'])
        self.assertEqual(audit['blockers'], [])
        self.assertEqual(audit['agent']['status'], 'COMPLETE')
        self.assertEqual(len(audit['agent']['reviews']), 20)
        for paper in audit['sets']:
            self.assertEqual(paper['reviewed_blooms'], {'L1-L2':'30', 'L3-L4':'60', 'L5-L6':'10'})
            self.assertEqual(len(paper['paths']), 8)
            self.assertTrue(all(path['marks']=='50' for path in paper['paths']))
        report = self.client.get(url+'/report.pdf?revision=2', headers=self.key)
        self.assertEqual(report.status_code, 200, report.text if not report.is_success else '')
        self.assertTrue(report.content.startswith(b'%PDF'))

        single = self.create({**payload, 'sets':payload['sets'][:1]})
        single_url = '/api/submissions/' + single['id']
        single_result = self.client.post(single_url+'/audit?revision=1&enable_agent=false',headers=self.key).json()['audit']
        self.assertEqual(single_result['status'],'READY_FOR_FACULTY_REVIEW')
        report = self.client.get(single_url+'/report.pdf?revision=1',headers=self.key)
        self.assertEqual(report.status_code,200)
        import pdfplumber
        from io import BytesIO
        with pdfplumber.open(BytesIO(report.content)) as pdf:
            self.assertIn('Optional set not submitted',pdf.pages[1].extract_text())

        payload['sets'][0]['questions'][0]['reviewed_level'] = 4
        saved = self.client.put(url, headers=self.key, json={'expected_revision':2,'submission':payload})
        self.assertEqual(saved.status_code, 200, saved.text)
        audit = self.client.post(url+'/audit?revision=3&enable_agent=false', headers=self.key).json()['audit']
        self.assertEqual(audit['status'], 'NEEDS_REVISION')
        blooms = next(criterion for criterion in audit['sets'][0]['criteria'] if criterion['key']=='blooms')
        self.assertEqual(blooms['findings'][-1]['code'], 'BLOOM_LABEL_MISMATCH')


if __name__=='__main__':unittest.main()
