"""Personal, source-linked scrutiny workspace. No global latest report."""
import secrets
import hmac
from hashlib import sha256
import os
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.agent_workflow import run_agent
from app.academic_review import REVIEW_ENGINE_VERSION, run_academic_review
from app.document_reader import read_mapping_text, read_with_vision
from app.model_client import ModelUnavailable,generate
from app.ai_config import authorize,public_config,configured_provider
from app.bloom_replacements import STRATEGY, covered_sources, replacement_plan, suggest_replacement
from app.domain import Audit, FacultyBloomAction, FacultyBloomDecision, Model, Submission
from app.draft_report import export_draft
from app.fixtures import blank_submission
from app.intake import MAX_BYTES, check_file, parse_outcome_statements, parse_proposals, read_document
from app.mapping_reader import read_mapping_image
from app.paper_figures import FigureSource, PDF_RENDER_LOCK, visual_sources
from app.question_findings import question_reviews
from app.repository import Conflict, Repository
from app.validation import audit_submission

app = FastAPI(title='Personal CIE Scrutiny', version='2.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],
    allow_methods=['GET','POST','PUT'], allow_headers=['Content-Type','X-Workspace-Key'])
repo = Repository()
review_jobs = {}
job_lock = Lock()
review_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='scrutiny')
replacement_jobs = {}
replacement_lock = Lock()
replacement_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bloom-replacement')


def hosted():
    return os.environ.get('SCRUTINY_HOSTED') == '1'


def session_signature(nonce, secret):
    return hmac.new(secret.encode(), b'scrutiny-session:'+nonce.encode(),sha256).hexdigest()


def owner(x_workspace_key: Annotated[str, Header(min_length=32, max_length=160)]):
    if hosted():
        secret = os.environ.get('SCRUTINY_ACCESS_TOKEN','')
        nonce, separator, signature = x_workspace_key.partition('.')
        if not secret or not separator or len(nonce)!=43 or not hmac.compare_digest(signature.encode(),session_signature(nonce,secret).encode()):
            raise HTTPException(401,'Open the presentation access link to start a session.')
    return x_workspace_key


Owner = Annotated[str, Depends(owner)]


class SaveRequest(Model):
    expected_revision: int = Field(ge=1)
    submission: Submission


class FacultyBloomRequest(Model):
    expected_revision: int = Field(ge=1)
    set_label: Literal['A','B']
    q_no: str = Field(pattern=r'^[1-8][ab]?$')
    action: FacultyBloomAction
    override_level: int | None = Field(default=None, ge=1, le=6)
    expected_suggested_level: int | None = Field(default=None, ge=1, le=6)
    note: str = Field(default='', max_length=500)

class ReplacementRequest(Model):
    revision: int = Field(ge=1)
    set_label: Literal['A','B']
    q_no: str = Field(pattern=r'^[1-8][ab]?$')
    target_level: int = Field(ge=1, le=6)
    strategy: STRATEGY


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse(status_code=404, content={'detail':'Submission, revision, or source not found.'})


@app.exception_handler(Conflict)
async def conflict(request, exc):
    return JSONResponse(status_code=409, content={'detail':str(exc)})


@app.exception_handler(ModelUnavailable)
async def unavailable(request,exc):
    return JSONResponse(status_code=503,content={'detail':str(exc)})


@app.exception_handler(ValueError)
async def invalid_source(request,exc):
    return JSONResponse(status_code=422,content={'detail':str(exc)})


@app.get('/api/health')
def health():
    return {'ok':True, 'version':3, 'mode':'personal-draft', 'official_approval_enabled':False,
            'ai_provider':configured_provider(),'cloud_consent_required':True,'hosted':hosted()}


@app.get('/api/ai/config')
def ai_configuration():
    return {**public_config(),'hosted':hosted()}


class ConnectionCheck(Model):
    provider_id:str=Field(min_length=1,max_length=64)


class ConnectionProbe(Model):
    ok:bool


@app.post('/api/ai/check')
def check_ai(payload:ConnectionCheck,key:Owner):
    config=authorize('cloud',True,payload.provider_id)
    result=generate(ConnectionProbe,'Connection test only. Return the JSON object {"ok":true}.',provider='cloud')
    if not result.ok:raise ModelUnavailable('The provider did not pass the connection check.')
    return {'ok':True,'provider':config.public(),
            'message':'AI connection succeeded using synthetic text only. This does not validate scan reading or academic accuracy.'}


class SessionRequest(Model):
    access_code: str = Field(default='',max_length=512)


@app.post('/api/session')
def session(payload:SessionRequest|None=None):
    nonce = secrets.token_urlsafe(32)
    if hosted():
        secret = os.environ.get('SCRUTINY_ACCESS_TOKEN','')
        if not secret or not payload or not hmac.compare_digest(payload.access_code.encode(),secret.encode()):
            raise HTTPException(401,'Open the presentation access link or enter its access code.')
        nonce += '.' + session_signature(nonce,secret)
    return JSONResponse({'workspace_key':nonce,'mode':'personal-draft'},headers={'Cache-Control':'no-store'})


@app.get('/api/profiles/starter')
def profile():
    draft = blank_submission()
    if hosted():draft.ai_mode = 'cloud'
    return {'submission':draft,
        'note':'Upload your own course paper and syllabus or notes. No example course is preselected.'}


def validate_sources(key, payload):
    profile = payload.profile
    attached_pages = {}
    for doc_id in profile.mapping_document_ids:
        repo.document(key, doc_id)
    for doc_id in profile.syllabus_document_ids:
        source = repo.document(key, doc_id)
        if profile.material_coverage:
            attached_pages.update({f"{doc_id}:page {page['page']}":page['text'] for page in source['pages']})
    if profile.material_coverage and profile.syllabus != attached_pages:
        raise HTTPException(422, 'Coverage must use the complete saved page text from the uploaded files.')
    if set(profile.material_coverage) - set(profile.syllabus_document_ids):
        raise HTTPException(422, 'Choose coverage only for attached syllabus or module files.')
    for paper in payload.sets:
        for doc_id in paper.document_ids:
            repo.document(key, doc_id)
        for question in paper.questions:
            for evidence in question.evidence:
                source = repo.document(key, evidence.document_id)
                page = next((p for p in source['pages'] if p['page']==evidence.page), None)
                if evidence.document_id not in paper.document_ids or page is None or evidence.quote not in page['text']:
                    raise HTTPException(422, f'{paper.label}/{question.q_no}: evidence must quote its attached source page exactly.')


@app.post('/api/submissions', status_code=201)
def create(payload: Submission, key: Owner):
    validate_sources(key, payload)
    return repo.create(key, payload)


@app.get('/api/submissions/{rid}')
def get(rid: str, key: Owner, revision: int | None = None):
    if revision is not None and revision < 1:
        raise HTTPException(422,'Revision must be positive.')
    return with_question_findings(repo.get(key, rid, revision))


def with_question_findings(row):
    if row['audit'] is not None:
        submission = Submission.model_validate(row['submission'])
        audit = Audit.model_validate(row['audit'])
        row['audit']['question_findings'] = question_reviews(submission, audit)
    return row


@app.get('/api/submissions')
def list_drafts(key:Owner):
    return repo.list_drafts(key)


@app.put('/api/submissions/{rid}')
def save(rid: str, payload: SaveRequest, key: Owner):
    repo.get(key, rid)
    validate_sources(key, payload.submission)
    return repo.update(key, rid, payload.expected_revision, payload.submission)


@app.post('/api/submissions/{rid}/faculty-bloom')
def record_faculty_bloom(rid: str, payload: FacultyBloomRequest, key: Owner):
    row = repo.get(key,rid)
    if row['revision'] != payload.expected_revision:
        raise Conflict('This draft has changed. Reload before saving the faculty decision.')
    if row['audit'] is None:
        raise HTTPException(409,'Run evaluation for this revision to open its Findings.')
    submission = Submission.model_validate(row['submission'])
    matches = [question for paper in submission.sets if paper.label == payload.set_label
               for question in paper.questions if question.q_no == payload.q_no]
    if len(matches) != 1:
        raise HTTPException(422,'Choose a question with a unique number in this set.')
    previous_audit = Audit.model_validate(row['audit'])
    review = next((item for item in previous_audit.agent.get('reviews',[])
                   if item['set_label'] == payload.set_label and item['q_no'] == payload.q_no),{})
    suggested = review.get('predicted_level')
    if suggested != payload.expected_suggested_level:
        raise Conflict('The AI suggestion has changed. Reload Findings before saving the decision.')
    if payload.action == 'accepted' and suggested is None:
        raise HTTPException(422,'This question has no AI Bloom’s suggestion to accept.')
    if (payload.action == 'overridden') != (payload.override_level is not None):
        raise HTTPException(422,'Choose an override level only when overriding the suggestion.')
    reviewed = suggested if payload.action == 'accepted' else payload.override_level
    decision = FacultyBloomDecision(action=payload.action,suggested_level=suggested,note=payload.note.strip())
    question = matches[0]
    if question.faculty_bloom_decision == decision and question.reviewed_level == reviewed:
        return with_question_findings(row)
    question.reviewed_level = reviewed
    question.faculty_bloom_decision = decision
    audit = audit_submission(submission)
    audit.agent = previous_audit.agent
    saved = repo.update(key,rid,payload.expected_revision,submission,
                        audit=audit.model_dump(mode='json'),expected_audit=row['audit'])
    return with_question_findings(saved)


def replacement_revision(key, rid, revision, set_label):
    row = repo.get(key, rid)
    if row['revision'] != revision or row['audit'] is None:
        raise Conflict('Open Findings for the current evaluated revision to plan a replacement.')
    submission = Submission.model_validate(row['submission'])
    paper = next((item for item in submission.sets if item.label == set_label), None)
    if paper is None or not paper.questions:
        raise ValueError('Choose a set with questions.')
    return submission, paper, row['audit']


@app.get('/api/submissions/{rid}/bloom-replacements')
def plan_bloom_replacement(rid: str, key: Owner, revision: int, set_label: Literal['A','B']):
    submission, paper, _ = replacement_revision(key, rid, revision, set_label)
    return replacement_plan(paper, submission.profile)


def check_replacement_revision(key, rid, payload, submission, paper, question, sources, preferred):
    replacement_revision(key, rid, payload.revision, payload.set_label)
    return suggest_replacement(submission, paper, question, payload.target_level, payload.strategy, sources, preferred)


@app.post('/api/submissions/{rid}/bloom-replacements', status_code=202)
def start_bloom_replacement(rid: str, payload: ReplacementRequest, key: Owner):
    submission, paper, audit = replacement_revision(key, rid, payload.revision, payload.set_label)
    plan = replacement_plan(paper, submission.profile)
    if not any(item['q_no'] == payload.q_no and payload.target_level in item['levels'] for item in plan['options']):
        raise ValueError('Choose a question and level that improve the printed Bloom’s distribution.')
    authorize(submission.ai_mode, submission.cloud_consent, submission.cloud_provider_id)
    sources = covered_sources(submission, paper, lambda doc_id: repo.document(key, doc_id))
    question = next(q for q in paper.questions if q.q_no == payload.q_no)
    preferred = {
        citation['section']
        for review in audit.get('agent', {}).get('reviews', [])
        if review.get('set_label') == paper.label and review.get('q_no') == question.q_no
        and review.get('verification_status') == 'AGREED'
        for citation in review.get('citations', [])
    }
    now = monotonic()
    with replacement_lock:
        for job_id, (_, _, started, future) in list(replacement_jobs.items()):
            if future.done() and (started < now - 900 or len(replacement_jobs) >= 40):
                replacement_jobs.pop(job_id)
        for job_id, (draft_id, requested, _, future) in replacement_jobs.items():
            if draft_id == rid and requested == payload and (not future.done() or future.exception() is None):
                return {'job_id': job_id}
            if draft_id == rid and not future.done():
                raise HTTPException(429, 'Wait for the current replacement check for this paper to finish.')
        if sum(not task[-1].done() for task in replacement_jobs.values()) >= 3:
            raise HTTPException(429, 'The replacement queue is full. Try again shortly.')
        job_id = uuid.uuid4().hex
        future = replacement_worker.submit(check_replacement_revision, key, rid, payload, submission, paper,
                                           question, sources, preferred)
        replacement_jobs[job_id] = (rid, payload, now, future)
    return {'job_id': job_id}


@app.get('/api/submissions/{rid}/bloom-replacements/{job_id}')
def bloom_replacement_result(rid: str, job_id: str, key: Owner):
    row = repo.get(key, rid)
    with replacement_lock:
        task = replacement_jobs.get(job_id)
    if task is None or task[0] != rid:
        raise HTTPException(404, 'The replacement check expired. Request it again.')
    _, payload, _, future = task
    if row['revision'] != payload.revision:
        raise Conflict('The paper changed while the replacement was checked. Plan against the current revision.')
    if not future.done():
        return {'status': 'checking'}
    return {'status': 'ready', 'suggestion': future.result()}


@app.post('/api/submissions/{rid}/audit')
def scrutinize(rid: str, key: Owner, revision: int, enable_agent: bool = True):
    if hosted():
        raise HTTPException(409,'Start a review job to evaluate this draft on the hosted app.')
    return run_revision_review(rid,key,revision,enable_agent)


def run_revision_review(rid, key, revision, enable_agent=True):
    row = repo.get(key, rid, revision)
    submission = Submission.model_validate(row['submission'])
    audit = audit_submission(submission)
    try:
        if enable_agent:
            previous = (row.get('audit') or {}).get('agent') or {}
            if previous.get('engine_version') != REVIEW_ENGINE_VERSION:
                previous = None
            figures = visual_sources(repo, key, submission)
            figure_sources = {qid:[source.public() for source in sources] for qid,sources in figures.items()}
            if previous:
                saved_sources = previous.get('figure_sources',{})
                changed = {qid for qid in figure_sources.keys() | saved_sources.keys()
                           if figure_sources.get(qid,[]) != saved_sources.get(qid,[])}
                if changed:
                    previous = {**previous,'reviews':[
                        review for review in previous.get('reviews',[])
                        if f"{review['set_label']}/{review['q_no']}" not in changed
                    ]}
            figure_args = {'figures':figures} if figures else {}
            audit.agent = run_academic_review(submission, previous=previous, **figure_args)
            if figures:
                audit.agent['figure_sources'] = figure_sources
            audit.agent['engine_version'] = REVIEW_ENGINE_VERSION
        else:
            audit.agent = {'status':'NOT_REQUESTED','model_used':False,'trace':[],'reviews':[]}
    except ValueError:
        audit.agent = {'status':'CONFIGURATION_ERROR','model_used':False,'trace':[],'proposals':[]}
    repo.save_audit(key, rid, revision, audit.model_dump(mode='json'))
    return with_question_findings(repo.get(key, rid, revision))


def review_in_background(rid, key, revision):
    with job_lock:review_jobs[(rid,revision)] = 'running'
    try:
        run_revision_review(rid,key,revision)
    except Exception:
        with job_lock:review_jobs[(rid,revision)] = 'failed'
    else:
        with job_lock:review_jobs.pop((rid,revision),None)


@app.post('/api/submissions/{rid}/review-job', status_code=202)
def start_review_job(rid:str, key:Owner, revision:int):
    repo.get(key,rid,revision)
    job = (rid,revision)
    with job_lock:
        if review_jobs.get(job) in ('queued','running'):
            return {'status':review_jobs[job]}
        if sum(state in ('queued','running') for state in review_jobs.values()) >= 4:
            raise HTTPException(429,'The review queue is full. Retry when a review finishes.')
        review_jobs[job] = 'queued'
        review_workers.submit(review_in_background,rid,key,revision)
    return {'status':'queued'}


@app.get('/api/submissions/{rid}/review-job')
def review_job_status(rid:str, key:Owner, revision:int):
    with job_lock:
        status = review_jobs.get((rid,revision))
    row = repo.get(key,rid,revision)
    if status:
        return {'status':status}
    return {'status':'finished','record':with_question_findings(row)} if row['audit'] is not None else {'status':'interrupted'}


@app.post('/api/documents', status_code=201)
async def upload(key: Owner, file: UploadFile = File(), role:str=Form(default='paper'),allow_cloud:bool=Form(default=False),ai_mode:str=Form(default='local'),cloud_provider_id:str|None=Form(default=None),attached_syllabus_ids:list[str]=Form(default=[])):
    if role not in ('paper','syllabus','notes','mapping'):
        raise HTTPException(422,'Document role must be paper, syllabus, notes, or mapping.')
    content = await file.read(MAX_BYTES+1)
    suffix = Path(file.filename or '').suffix.lower()
    try:
        check_file(content, suffix)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if role == 'syllabus' and attached_syllabus_ids:
        digest = sha256(content).hexdigest()
        if any(repo.document(key,doc_id)['sha256']==digest for doc_id in attached_syllabus_ids):
            raise HTTPException(409,'This syllabus file is already attached. Edit its coverage below.')
    doc_id = uuid.uuid4().hex
    directory = repo.root/'documents'
    directory.mkdir(parents=True,exist_ok=True)
    path = directory/(doc_id+suffix)
    path.write_bytes(content)
    try:
        pages,metadata,questions,outcomes,matrix,warnings=await run_in_threadpool(process_document,path,doc_id,role,allow_cloud,ai_mode,cloud_provider_id)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422,str(exc) if isinstance(exc,(ModelUnavailable,ValueError)) else f'Document processing failed ({type(exc).__name__}). The upload was not accepted.')
    text = '\n'.join(p['text'] for p in pages)
    repo.save_document(key,doc_id,Path(file.filename or 'document').name,suffix,content,text,pages)
    return {'id':doc_id,'metadata':metadata,'questions':questions,'pages':pages,
        'outcomes':outcomes,'co_po':matrix,'warnings':warnings,'status':'SOURCE_REVIEW_REQUIRED'}


def process_document(path,doc_id,role,allow_cloud,ai_mode='local',cloud_provider_id=None):
    visual=path.suffix.lower() in ('.pdf','.png','.jpg','.jpeg')
    if ai_mode not in ('local','google','cloud'):raise ValueError('Choose local or configured cloud processing.')
    if ai_mode!='local':authorize(ai_mode,allow_cloud,cloud_provider_id)
    if role == 'mapping' and path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
        try:
            extracted = read_mapping_image(path, doc_id)
        except (OSError, RuntimeError, ValueError):
            extracted = None
        if extracted is not None:
            return extracted
    long_material=False
    if role!='paper' and path.suffix.lower()=='.pdf':
        import pypdfium2 as pdfium
        with PDF_RENDER_LOCK, pdfium.PdfDocument(str(path)) as pdf:long_material=len(pdf)>8
    if role in ('syllabus','notes') and path.suffix.lower()=='.pdf' and not long_material:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            if pdf.pages and all(not page.images for page in pdf.pages):
                pages = [{'page':number, 'text':page.extract_text() or '', 'method':'pdf_text'}
                         for number,page in enumerate(pdf.pages,1)]
                if all(page['text'].strip() for page in pages):
                    metadata,_,_=parse_proposals(pages,doc_id)
                    return pages,metadata,[],parse_outcome_statements(pages),{},[]
    if visual and ai_mode!='local' and allow_cloud and not long_material:
        return read_with_vision(path,doc_id,role,provider=ai_mode)
    if role == 'mapping' and visual and ai_mode == 'local' and not long_material:
        return read_with_vision(path,doc_id,role,provider='local')
    pages,warnings=read_document(path)
    metadata,questions,issues=parse_proposals(pages,doc_id)
    if role in ('syllabus', 'notes'):
        return pages, metadata, [], parse_outcome_statements(pages), {}, warnings
    if role == 'mapping':
        outcomes, matrix, mapping_warnings = read_mapping_text(pages, ai_mode)
        return pages, metadata, [], outcomes, matrix, warnings + mapping_warnings
    if role=='paper' and not questions:
        if visual and ai_mode=='local':
            return read_with_vision(path,doc_id,role,provider='local')
        raise ValueError('Text was read, but no question structure could be extracted. No zero-question paper was accepted.')
    return pages,metadata,questions,{}, {},warnings+issues


@app.post('/api/submissions/{rid}/prepare')
def prepare_existing(rid:str,key:Owner):
    """Recover earlier failed scans as a new revision; retain original snapshots."""
    row=repo.get(key,rid)
    payload=Submission.model_validate(row['submission'])
    changed=False
    def recover(old_id,role):
        doc=repo.document(key,old_id)
        old_path=repo.root/'documents'/(old_id+doc['suffix'])
        new_id=uuid.uuid4().hex
        pages,metadata,questions,outcomes,matrix,warnings=process_document(old_path,new_id,role,payload.cloud_consent,payload.ai_mode,payload.cloud_provider_id)
        new_path=repo.root/'documents'/(new_id+doc['suffix'])
        content=old_path.read_bytes();new_path.write_bytes(content)
        repo.save_document(key,new_id,doc['name'],doc['suffix'],content,'\n'.join(p['text'] for p in pages),pages)
        return new_id,pages,metadata,questions,outcomes,matrix,warnings
    for paper in payload.sets:
        if not paper.questions and paper.document_ids:
            for old_id in list(paper.document_ids):
                new_id,pages,metadata,questions,_,_,warnings=recover(old_id,'paper')
                paper.document_ids[paper.document_ids.index(old_id)]=new_id
                paper.metadata=metadata;paper.questions.extend(questions);paper.extraction_warnings.extend(warnings);changed=True
    if not any(text.strip() for text in payload.profile.syllabus.values()) and payload.profile.syllabus_document_ids:
        payload.profile.syllabus={}
        for old_id in list(payload.profile.syllabus_document_ids):
            new_id,pages,metadata,_,outcomes,matrix,_=recover(old_id,payload.profile.material_kind)
            payload.profile.syllabus_document_ids[payload.profile.syllabus_document_ids.index(old_id)]=new_id
            payload.profile.syllabus.update({new_id+':page '+str(p['page']):p['text'] for p in pages})
            payload.profile.outcomes.update(outcomes);payload.profile.co_po.update(matrix);changed=True
    return repo.update(key,rid,row['revision'],payload) if changed else row


@app.get('/api/documents/{doc_id}')
def document(doc_id: str,key: Owner):
    return repo.document(key,doc_id)


@app.get('/api/documents/{doc_id}/original')
def original(doc_id: str,key: Owner):
    doc=repo.document(key,doc_id)
    return FileResponse(repo.root/'documents'/(doc_id+doc['suffix']),filename=doc['name'],headers={'Cache-Control':'no-store'})


@app.get('/api/documents/{doc_id}/figures/{kind}/{index}')
def figure_preview(doc_id: str, kind: Literal['embedded','page'], index: int, key: Owner):
    doc = repo.document(key,doc_id)
    if index < 1 or (kind == 'embedded' and doc['suffix'] != '.docx'):
        raise HTTPException(404,'The linked figure was not found.')
    source = FigureSource(doc_id,repo.root/'documents'/(doc_id+doc['suffix']),kind,index)
    try:
        image = source.jpeg()
    except (OSError,ValueError,RuntimeError):
        raise HTTPException(422,'The linked figure could not be displayed. Open the original paper to inspect it.') from None
    return Response(content=image,media_type='image/jpeg',headers={'Cache-Control':'no-store'})


@app.get('/api/submissions/{rid}/report.pdf')
def report(rid: str,key: Owner,revision: int):
    row=repo.get(key,rid,revision)
    if row['audit'] is None:
        raise HTTPException(409,'Run scrutiny on this exact revision before exporting its draft.')
    path=export_draft(Submission.model_validate(row['submission']),Audit.model_validate(row['audit']),rid,revision)
    return FileResponse(path,filename=f'Scrutiny-{rid[:12]}-r{revision}-DRAFT.pdf',media_type='application/pdf',headers={'Cache-Control':'no-store'})


@app.post('/api/submissions/{rid}/finalize')
def finalize(rid: str,key: Owner):
    repo.get(key,rid)
    raise HTTPException(409,'This build generates scrutiny drafts. Resolve academic findings and obtain departmental signatures before examination use.')


@app.get('/api/report.pdf')
@app.post('/api/scrutiny')
def legacy():
    raise HTTPException(410,'Use the revision-scoped workspace. Global latest-report exports have been retired.')


dist=Path(__file__).resolve().parents[2]/'frontend'/'dist'
if dist.exists():
    app.mount('/',StaticFiles(directory=dist,html=True),name='ui')
