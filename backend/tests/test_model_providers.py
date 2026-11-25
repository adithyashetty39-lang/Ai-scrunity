"""Offline protocol, consent, and failure checks; no private papers or live keys."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from pydantic import BaseModel,ConfigDict
from app import academic_review
from app.ai_config import authorize,ConsentRequired,get_config,public_config
from app.domain import Submission,PaperSet,Question
from app.model_client import generate,ModelUnavailable

RealClient=httpx.Client


class Answer(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    ok:bool


def environment(provider='openai',**extra):
    return {'SCRUTINY_AI_PROVIDER':provider,'SCRUTINY_AI_KEY':'synthetic-secret',
            'SCRUTINY_AI_MODEL':'synthetic-model','SCRUTINY_AI_VISION':'true',**extra}


class ProviderTests(unittest.TestCase):
    def invoke(self,env,reply,attachments=(),status=200,schema=Answer):
        requests=[]
        def handler(request):
            requests.append(request)
            if isinstance(reply,str):return httpx.Response(status,text=reply,headers={'content-type':'text/event-stream'})
            return httpx.Response(status,json=reply)
        def client(**kwargs):return RealClient(transport=httpx.MockTransport(handler),**kwargs)
        with patch.dict(os.environ,env,clear=True),patch('app.model_client.httpx.Client',side_effect=client):
            value=generate(schema,'Synthetic test only.',attachments,provider='cloud')
        return value,requests

    def test_openai_chat_protocol_and_image(self):
        result,requests=self.invoke(environment(),{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]},[('image/png',b'synthetic image')])
        self.assertTrue(result.ok);self.assertEqual(len(requests),1)
        req=requests[0];body=json.loads(req.content)
        self.assertEqual(str(req.url),'https://api.openai.com/v1/chat/completions')
        self.assertEqual(req.headers['authorization'],'Bearer synthetic-secret')
        self.assertIn('max_completion_tokens',body)
        self.assertEqual(body['response_format']['type'],'json_schema')
        self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_compatible_endpoint_and_json_modes(self):
        for mode in ('json','schema','prompt'):
            with self.subTest(mode=mode):
                env=environment('openai_compatible',SCRUTINY_AI_BASE_URL='https://example.invalid/api/v1/',SCRUTINY_AI_JSON_MODE=mode)
                _,requests=self.invoke(env,{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]})
                body=json.loads(requests[0].content)
                self.assertEqual(str(requests[0].url),'https://example.invalid/api/v1/chat/completions')
                self.assertIn('max_tokens',body)
                self.assertEqual('response_format' in body,mode!='prompt')

    def test_reasoning_models_have_room_for_verifier_json(self):
        from app.academic_review import Batch,Critique
        env=environment('openai_compatible',SCRUTINY_AI_BASE_URL='https://coarena.ai/api/v1')
        for schema,content,limit in ((Batch,'{"reviews":[]}',8192),(Critique,'{"decisions":[]}',8192)):
            with self.subTest(schema=schema.__name__):
                _,requests=self.invoke(env,{'choices':[{'finish_reason':'stop','message':{'content':content}}]},schema=schema)
                self.assertEqual(json.loads(requests[0].content)['max_tokens'],limit)
        with self.assertRaisesRegex(ModelUnavailable,'output-token limit'):
            self.invoke(env,{'choices':[{'finish_reason':'length','message':{'content':''}}]})

    def test_anthropic_protocol_and_image(self):
        result,requests=self.invoke(environment('anthropic'),{'stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}]},[('image/jpeg',b'synthetic')])
        self.assertTrue(result.ok);req=requests[0];body=json.loads(req.content)
        self.assertEqual(str(req.url),'https://api.anthropic.com/v1/messages')
        self.assertEqual(req.headers['x-api-key'],'synthetic-secret')
        self.assertEqual(req.headers['anthropic-version'],'2023-06-01')
        self.assertEqual(body['messages'][0]['content'][1]['source']['media_type'],'image/jpeg')

    def test_gemini_legacy_key_and_stream(self):
        event={'candidates':[{'content':{'parts':[{'text':'{"ok":true}'}]},'finishReason':'STOP'}]}
        env={'SCRUTINY_AI_PROVIDER':'gemini','GEMINI_API_KEY':'legacy-secret','GEMINI_MODEL':'gemini-3-test'}
        result,requests=self.invoke(env,'data: '+json.dumps(event)+'\n\n')
        self.assertTrue(result.ok);self.assertEqual(requests[0].headers['x-goog-api-key'],'legacy-secret')
        self.assertEqual(json.loads(requests[0].content)['generationConfig']['thinkingConfig']['thinkingLevel'],'LOW')

    def test_pdf_pages_are_sent_as_images(self):
        from reportlab.pdfgen.canvas import Canvas
        pdf=BytesIO();canvas=Canvas(pdf);canvas.drawString(50,700,'Synthetic page');canvas.showPage();canvas.save()
        _,requests=self.invoke(environment(),{'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]},[('application/pdf',pdf.getvalue())])
        url=json.loads(requests[0].content)['messages'][1]['content'][1]['image_url']['url']
        self.assertTrue(base64.b64decode(url.split(',')[1]).startswith(b'\x89PNG'))

    def test_text_only_blocks_attachment_before_network(self):
        with patch.dict(os.environ,environment(SCRUTINY_AI_VISION='false'),clear=True),patch('app.model_client.httpx.Client') as client:
            with self.assertRaisesRegex(ModelUnavailable,'text-only'):generate(Answer,'test',[('image/png',b'test')])
            client.assert_not_called()

    def test_provider_image_limit_blocks_entire_request(self):
        env=environment('openai_compatible',SCRUTINY_AI_BASE_URL='https://coarena.ai/api/v1',
                        SCRUTINY_AI_MODEL='deepseek-v4-1-flash-1017',SCRUTINY_AI_MAX_IMAGES='8')
        with patch.dict(os.environ,env,clear=True),patch('app.model_client.httpx.Client') as client:
            with self.assertRaisesRegex(ModelUnavailable,'up to 8'):
                generate(Answer,'Synthetic test',[('image/png',b'synthetic')]*9)
            client.assert_not_called()
        for invalid in ('0','11','not-a-number'):
            with patch.dict(os.environ,{**env,'SCRUTINY_AI_MAX_IMAGES':invalid},clear=True):
                with self.assertRaisesRegex(ModelUnavailable,'integer from 1 to 10'):get_config()

    def test_refused_truncated_and_invalid_results_remain_unresolved(self):
        responses=[{'choices':[{'finish_reason':'length','message':{'content':'{"ok":true}'}}]},
                   {'choices':[{'finish_reason':'stop','message':{'refusal':'No','content':'{"ok":true}'}}]},
                   {'choices':[{'finish_reason':'stop','message':{'content':'{"invented":true}'}}]},
                   {'choices':[{'finish_reason':'stop','message':{'content':'not JSON'}}]}]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(ModelUnavailable):self.invoke(environment(),response)
        with self.assertRaises(ModelUnavailable):self.invoke(environment('anthropic'),{'stop_reason':'max_tokens','content':[{'type':'text','text':'{"ok":true}'}]})

    def test_http_errors_are_sanitized_and_never_fall_back(self):
        for status in (401,403,404,429,503):
            count=[]
            def handler(request):
                count.append(request)
                return httpx.Response(status,json={'error':'synthetic-secret PRIVATE SOURCE'})
            with patch.dict(os.environ,environment(),clear=True),patch('app.model_client.httpx.Client',side_effect=lambda **kw:RealClient(transport=httpx.MockTransport(handler),**kw)):
                with self.assertRaises(ModelUnavailable) as error:generate(Answer,'PRIVATE SOURCE')
                self.assertIn(str(status),str(error.exception))
                self.assertNotIn('synthetic-secret',str(error.exception));self.assertNotIn('PRIVATE SOURCE',str(error.exception))
                self.assertEqual(len(count),1)

    def test_public_configuration_and_key_rotation(self):
        with patch.dict(os.environ,environment(),clear=True):
            config=get_config();public=public_config()
            self.assertNotIn('synthetic-secret',json.dumps(public));self.assertNotIn('synthetic-secret',repr(config))
            self.assertTrue(public['cloud']['configured'])
            with patch.dict(os.environ,{'SCRUTINY_AI_KEY':'replacement-key'}):self.assertEqual(get_config().id,config.id)
            with patch.dict(os.environ,{'SCRUTINY_AI_MODEL':'another-model'}):self.assertNotEqual(get_config().id,config.id)

    def test_destination_permission_required_and_old_google_permission_is_scoped(self):
        with patch.dict(os.environ,environment(),clear=True):
            config=get_config()
            with self.assertRaises(ConsentRequired):authorize('cloud',False,config.id)
            with self.assertRaises(ConsentRequired):authorize('cloud',True,'old-destination')
            with self.assertRaises(ConsentRequired):authorize('google',True)
            self.assertEqual(authorize('cloud',True,config.id).provider,'openai')
            with patch.dict(os.environ,{'SCRUTINY_AI_PROVIDER':'anthropic'}):
                with self.assertRaises(ConsentRequired):authorize('cloud',True,config.id)

    def test_malformed_endpoints_and_missing_keys_do_not_send_requests(self):
        for endpoint in ('http://example.invalid/v1','https://key@example.invalid/v1','https://example.invalid/v1?api_key=secret','https://example.invalid:bad/v1'):
            with patch.dict(os.environ,environment('openai_compatible',SCRUTINY_AI_BASE_URL=endpoint),clear=True):
                with self.assertRaises(ModelUnavailable):get_config()
        with patch.dict(os.environ,{'SCRUTINY_AI_PROVIDER':'openai','SCRUTINY_AI_MODEL':'test'},clear=True),patch('app.model_client.httpx.Client') as client:
            with self.assertRaisesRegex(ModelUnavailable,'missing'):generate(Answer,'test')
            client.assert_not_called()

    def test_model_change_cannot_reuse_old_model_reviews(self):
        data=Submission(ai_mode='cloud',cloud_consent=True,sets=[PaperSet(label='A',questions=[Question(q_no='1',text='Synthetic')])])
        with patch.dict(os.environ,environment(),clear=True):
            data.cloud_provider_id=get_config().id
            previous={'model_config_id':'old-model','reviews':[{'q_no':'1'}]}
            with patch.object(academic_review,'_run_academic_review',return_value={'status':'UNAVAILABLE'}) as run:
                result=academic_review.run_academic_review(data,previous=previous)
                self.assertIsNone(run.call_args.args[3]);self.assertEqual(result['model_config_id'],get_config().id)
            previous['model_config_id']=get_config().id
            with patch.object(academic_review,'_run_academic_review',return_value={'status':'COMPLETE'}) as run:
                academic_review.run_academic_review(data,previous=previous)
                self.assertIs(run.call_args.args[3],previous)


if __name__=='__main__':unittest.main()
