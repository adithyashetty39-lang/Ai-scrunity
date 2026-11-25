import { useEffect, useRef, useState } from 'react';
import './flyby.css';
import { BloomDistributionPreview } from './BloomDistributionPreview';
import { BloomReplacement } from './BloomReplacement';
import { MaterialCoverage, type SourceCoverage } from './MaterialCoverage';
import { ReviewWaitingPanel, type ReviewJobPhase } from './ReviewWaitingPanel';
import { ThemeToggle } from './ThemeToggle';
import { facultyDecisionId, missingCoverageField, nextReviewTarget, outcomeFieldId, questionFieldId,
  type ReviewStage, type ReviewTarget } from './reviewNavigation';

type FacultyBloomAction = 'accepted'|'overridden'|'deferred';
type FacultyBloomDecision = {action:FacultyBloomAction;suggested_level:number|null;note:string};
type FacultyBloomInput = {action:FacultyBloomAction;override_level:number|null;note:string};
type Question = { q_no:string; text:string; marks:string|number|null; co:string[]; po:string[]; stated_level:number|null; reviewed_level:number|null; faculty_bloom_decision?:FacultyBloomDecision|null; evidence:{document_id:string;page:number;quote:string}[]; extraction_confirmed:boolean };
const facultyChecks = {
  syllabus: 'Questions fall within the confirmed coverage',
  assessment: 'Printed instructions and alternatives follow the assessment plan',
  outcomes: 'Question content matches the CO and PO mapping',
  format: 'Layout and tables match the approved question-paper template',
} as const;
type FacultyCriterion = keyof typeof facultyChecks;
type FacultyDecision = 'confirmed'|'needs_revision';
type Paper = {label:'A'|'B'; metadata:Record<string,any>;questions:Question[];document_ids:string[];extraction_warnings?:string[];faculty_checks?:Partial<Record<FacultyCriterion,FacultyDecision>>};
type Submission = {schema_version:2;title:string;cloud_consent?:boolean;cloud_provider_id?:string|null;ai_mode?:'local'|'google'|'cloud';profile:Record<string,any>;sets:Paper[]};
type CloudConfig = {provider:string;label:string;model:string;destination:string;id:string;vision:boolean;configured:boolean};
type RecordData = {id:string;revision:number;submission:Submission;audit:any};
type SetBloomFinding = {label:'A'|'B';criteria:{key:string;findings:{code:string}[]}[]};
type FigureSource = {document_id:string;kind:'embedded'|'page';index:number;label:string};
type QuestionFinding = {
  set_label:'A'|'B'; q_no:string; text:string; printed_level:string; suggested_level:string; faculty_level:string;
  marks:string; co:string; po:string; checks:{label:string;status:string;reason:string;suggestion:string}[];
  citations:{source:string;quote:string;document_id:string|null}[]; rewrite:string|null;
  figure_sources?:FigureSource[];
  faculty_bloom_decision?:FacultyBloomDecision&{label:string};
  verification_status:'AGREED'|'PENDING'|'DISAGREEMENT'|null; confidence:string|null; verification_feedback:string|null;
};
type PendingUpload = {file:File;kind:'syllabus'|'mapping'|'A'|'B';module?:number};
let keyPromise:Promise<string>|null=null;
async function workspaceKey(accessCode?:string):Promise<string>{
  const fromLink=new URLSearchParams(window.location.hash.slice(1)).get('access');
  const code=accessCode??fromLink;
  const existing=localStorage.getItem('scrutiny-key');
  if(existing&&!code)return existing;
  if(!keyPromise)keyPromise=(async()=>{
    if(existing&&fromLink&&accessCode===undefined){
      const session=await fetch('/api/submissions',{headers:{'X-Workspace-Key':existing}});
      if(session.ok){
        window.history.replaceState(null,'',window.location.pathname+window.location.search);
        return existing;
      }
      if(session.status!==401)throw new Error('The workspace is temporarily unavailable. Reload to retry.');
    }
    const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_code:code??''})});
    if(!response.ok)throw new Error(response.status===401?'Open the presentation access link or enter its access code.':'The workspace is unavailable. Reload to retry.');
    const {workspace_key}=await response.json();
    if(existing)localStorage.removeItem('scrutiny-current');
    localStorage.setItem('scrutiny-key',workspace_key);
    if(fromLink)window.history.replaceState(null,'',window.location.pathname+window.location.search);
    return workspace_key;
  })().finally(()=>{keyPromise=null;});
  return keyPromise;
}
async function request(path:string,options:RequestInit={}){
  const key=await workspaceKey();
  let res:Response;
  try{res=await fetch('/api'+path,{...options,headers:{'X-Workspace-Key':key,...options.headers}});}
  catch{throw new Error('Could not reach the scrutiny app. Check your connection and try again.');}
  if(!res.ok){
    const data=await res.json().catch(()=>null);
    if(typeof data?.detail==='string'&&data.detail.trim())throw new Error(data.detail);
    if(res.status===413)throw new Error('This file is too large. Choose a file up to 15 MB.');
    const details=Array.isArray(data?.detail)?data.detail.map((item:{msg?:string})=>item.msg).filter(Boolean).join(' '):'';
    throw new Error(details||`The scrutiny app could not complete this request (HTTP ${res.status}). Try again.`);
  }
  return res;
}

function FigurePreview({source}:{source:FigureSource}){
  const [open,setOpen]=useState(false),[url,setUrl]=useState(''),[error,setError]=useState('');
  const {document_id,kind,index,label}=source;
  useEffect(()=>{
    if(!open)return;
    const controller=new AbortController();
    let imageUrl='';
    setUrl('');setError('');
    void request(`/documents/${document_id}/figures/${kind}/${index}`,{signal:controller.signal})
      .then(response=>response.blob())
      .then(blob=>{
        if(controller.signal.aborted)return;
        imageUrl=URL.createObjectURL(blob);
        setUrl(imageUrl);
      })
      .catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:String(reason));});
    return ()=>{controller.abort();if(imageUrl)URL.revokeObjectURL(imageUrl);};
  },[open,document_id,kind,index]);
  return <figure className="figure-preview">
    <button className="secondary" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>
      {open?'Hide':'Preview'} {label.toLowerCase()}
    </button>
    {open&&(url?<img src={url} alt={`${label} from the original question paper`}/>
      :error?<p role="alert">{error}</p>:<p role="status">Loading the original visual…</p>)}
  </figure>;
}
const emptyPaper=(label:'A'|'B'):Paper=>({label,metadata:{},questions:[],document_ids:[]});
const blankQuestion=():Question=>({q_no:'1',text:'',marks:null,co:[],po:[],stated_level:null,reviewed_level:null,evidence:[],extraction_confirmed:false});

function sourcePages(profile:Submission['profile'], id:string){
  const prefix=`${id}:page `;
  return Object.entries<string>(profile.syllabus)
    .filter(([section])=>section.startsWith(prefix))
    .map(([section,text])=>({number:Number(section.slice(prefix.length)),text}))
    .filter(page=>Number.isInteger(page.number)&&page.number>0)
    .sort((a,b)=>a.number-b.number);
}

function FacultyBloomReview({question,busy,onSave,decisionId}:{question:QuestionFinding;busy:boolean;onSave:(input:FacultyBloomInput)=>void;decisionId:string}){
  const saved=question.faculty_bloom_decision;
  const hasSuggestion=question.suggested_level!=='Unresolved';
  const [action,setAction]=useState<FacultyBloomAction|''>(saved?.action??'');
  const [override,setOverride]=useState(saved?.action==='overridden'?question.faculty_level.slice(1):'');
  const [note,setNote]=useState(saved?.note??'');
  const canSave=!!action&&(action!=='accepted'||hasSuggestion)&&(action!=='overridden'||!!override);
  return <form className="faculty-bloom" onSubmit={event=>{
    event.preventDefault();
    if(!canSave||busy||!action)return;
    onSave({action,override_level:action==='overridden'?Number(override):null,note});
  }}>
    <h4>Faculty Bloom’s decision</h4>
    {saved&&<p className="faculty-bloom-status">{saved.label}</p>}
    <div className="faculty-bloom-fields">
      <label>Decision<select id={decisionId} value={action} disabled={busy} onChange={event=>setAction(event.target.value as FacultyBloomAction|'')}>
        <option value="">Choose a decision</option>
        <option value="accepted" disabled={!hasSuggestion}>{hasSuggestion?`Accept AI suggestion (${question.suggested_level})`:'Accept AI suggestion (unavailable)'}</option>
        <option value="overridden">Override the level</option>
        <option value="deferred">Defer for later</option>
      </select></label>
      {action==='overridden'&&<label>Override level<select value={override} disabled={busy} required onChange={event=>setOverride(event.target.value)}>
        <option value="">Choose a level</option>
        {[1,2,3,4,5,6].map(level=><option key={level} value={level}>L{level}</option>)}
      </select></label>}
      <label>Faculty note (optional)<input value={note} disabled={busy} maxLength={500} onChange={event=>setNote(event.target.value)}/></label>
      <button className="secondary" disabled={busy||!canSave}>Save decision</button>
    </div>
  </form>;
}

function coverageSelections(profile:Submission['profile']):Record<string,SourceCoverage>{
  const selections:Record<string,SourceCoverage>={};
  for(const id of profile.syllabus_document_ids as string[]){
    const pages=sourcePages(profile,id);
    selections[id]=profile.material_coverage?.[id]??{module:null,mode:profile.coverage_mode==='all_uploaded'?'entire':'range',
      start_page:pages.length===1?pages[0].number:null,end_page:pages.length===1?pages[0].number:null,
      start_topic:profile.coverage_start??'',end_topic:profile.coverage_end??''};
  }
  return selections;
}

export default function App(){
  const [draft,setDraft]=useState<Submission|null>(null),[record,setRecord]=useState<RecordData|null>(null);
  const [tab,setTab]=useState<ReviewStage>('papers'),[activeSet,setActiveSet]=useState<'A'|'B'>('A');
  const [reviewJump,setReviewJump]=useState<ReviewTarget|null>(null);
  const previousTab=useRef(tab);
  const workspaceRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(reviewJump){
      const element=document.getElementById(reviewJump.id);
      const details=element?.closest('details');
      if(details)details.open=true;
      const destination=element??workspaceRef.current;
      destination?.focus({preventScroll:true});
      destination?.scrollIntoView({block:'center'});
      previousTab.current=tab;
      setReviewJump(null);
      return;
    }
    if(previousTab.current===tab)return;
    previousTab.current=tab;
    const workspace=workspaceRef.current;
    if(!workspace)return;
    workspace.focus({preventScroll:true});
    if(workspace.getBoundingClientRect().top<0)workspace.scrollIntoView({block:'start'});
  },[tab,reviewJump]);
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[dirty,setDirty]=useState(false);
  const [reviewPhase,setReviewPhase]=useState<ReviewJobPhase>('preparing');
  const [source,setSource]=useState<{id:string;text:string;warnings:string[]}|null>(null);
  const [pendingUpload,setPendingUpload]=useState<PendingUpload|null>(null);
  const [moduleNumber,setModuleNumber]=useState(1);
  const [accessCode,setAccessCode]=useState('');
  const [aiConfig,setAIConfig]=useState<{cloud:CloudConfig|null;error:string|null;hosted?:boolean}>({cloud:null,error:null});
  async function loadAIConfig(){
    try{setAIConfig(await(await request('/ai/config')).json());}
    catch(e){setAIConfig(state=>({...state,cloud:null,error:e instanceof Error?e.message:String(e)}));}
  }
  useEffect(()=>{void loadAIConfig();},[]);
  const cloud=aiConfig.cloud;
  const cloudSelected=!!draft?.ai_mode&&draft.ai_mode!=='local';
  const cloudAllowed=!!(draft?.cloud_consent&&cloud?.configured&&(draft.ai_mode==='google'?cloud.provider==='gemini':draft.cloud_provider_id===cloud.id));
  const [savedDrafts,setSavedDrafts]=useState<{id:string;title:string}[]>([]);
  useEffect(()=>{(async()=>{try{
    await workspaceKey();
    const saved=localStorage.getItem('scrutiny-current');
    if(saved){const result=await request('/submissions/'+saved);const row=await result.json();setRecord(row);setDraft(row.submission);}
    else{const data=await(await request('/profiles/starter')).json();setDraft(data.submission);}
  }catch(e){setError(e instanceof Error?e.message:String(e));
    try{const data=await(await request('/profiles/starter')).json();setDraft(data.submission);}catch{/* Show the session or server error. */}
  }})();},[]);
  useEffect(()=>{request('/submissions').then(r=>r.json()).then(setSavedDrafts).catch(()=>{});},[record?.id,record?.revision]);
  function change(fn:(d:Submission)=>void){setDraft(current=>{if(!current)return current;const copy=structuredClone(current);fn(copy);return copy;});setDirty(true);}
  function changePaper(fn:(p:Paper)=>void, invalidateChecks=true){
    change(d=>{
      let p=d.sets.find(s=>s.label===activeSet);
      if(!p){p=emptyPaper(activeSet);d.sets.push(p);}
      fn(p);
      if(invalidateChecks)p.faculty_checks={};
    });
  }
  function editQuestion(index:number,fields:Partial<Question>){
    changePaper(p=>{Object.assign(p.questions[index],fields,{extraction_confirmed:false,reviewed_level:null,faculty_bloom_decision:null});});
  }
  function profileField(name:string,value:any){
    change(d=>{
      d.profile[name]=value;
      if(['coverage_start','coverage_end','coverage_mode','material_kind'].includes(name))d.profile.coverage_confirmed=false;
      for(const p of d.sets){
        if(name==='rules_confirmed')delete p.faculty_checks?.assessment;
        else delete p.faculty_checks?.syllabus;
      }
    });
  }
  async function operation(label:string,fn:()=>Promise<void>){setBusy(label);setError('');setNotice('');try{await fn();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy('');}}
  async function persist():Promise<RecordData>{
    if(!draft)throw new Error('Workspace is loading.');
    if(record&&!dirty)return record;
    const res=await request(record?'/submissions/'+record.id:'/submissions',{method:record?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(record?{expected_revision:record.revision,submission:draft}:draft)});
    const row=await res.json();setRecord(row);setDirty(false);localStorage.setItem('scrutiny-current',row.id);return row;
  }
  function chooseUpload(selection:PendingUpload){
    setPendingUpload(selection);
    if(!cloudSelected||cloudAllowed)void upload(selection);
    else {setError('');setNotice('');}
  }
  async function upload({file,kind,module}:PendingUpload){
    if(busy||(cloudSelected&&!cloudAllowed))return;
    const isPaper=kind==='A'||kind==='B';
    if(isPaper&&draft?.sets.some(p=>p.label===kind&&(p.document_ids.length||p.questions.length))&&!window.confirm(`Replace the existing Set ${kind} paper with ${file.name}? If Set A changes course, the old course’s syllabus and mapping will be cleared from this draft. Saved revisions remain available.`))return;
    await operation('Reading '+file.name,async()=>{
      const fd=new FormData();fd.append('file',file);fd.append('role',kind==='syllabus'?(draft?.profile.material_kind||'syllabus'):kind==='mapping'?'mapping':'paper');fd.append('allow_cloud',cloudAllowed?'true':'false');fd.append('ai_mode',draft?.ai_mode||'local');if(draft?.cloud_provider_id)fd.append('cloud_provider_id',draft.cloud_provider_id);
      if(kind==='syllabus'&&draft?.profile.material_kind!=='notes'){
        for(const id of draft?.profile.syllabus_document_ids??[])fd.append('attached_syllabus_ids',id);
      }
      const data=await(await request('/documents',{method:'POST',body:fd})).json();
      const priorCourse=String(draft?.sets.find(p=>p.label==='A')?.metadata.course_code||draft?.profile.course_code||'').trim().toUpperCase();
      const uploadedCourse=String(data.metadata.course_code||'').trim().toUpperCase();
      const courseChanged=!!(priorCourse&&uploadedCourse&&priorCourse!==uploadedCourse);
      if(courseChanged&&kind==='mapping'){
        const confirmed=window.confirm(`The image reader detected ${uploadedCourse}. Your paper is for ${priorCourse}. Check the original image and continue only if the mapping belongs to ${priorCourse}. Use this mapping?`);
        if(!confirmed)return;
      }else if(courseChanged&&kind!=='A'){
        throw new Error(`This file is for ${uploadedCourse}. The Set A course is ${priorCourse}. Upload material for the same course.`);
      }
      if(kind==='mapping'){
        const existing=draft?.profile.co_po||{};
        const conflicts=Object.entries(data.co_po||{}).some(([co,mapping])=>Object.entries(existing[co]||{}).some(
          ([po,strength])=>(mapping as Record<string,number>)[po]!==strength));
        if(conflicts&&!window.confirm('This image changes strengths in existing CO rows. Replace those rows with the values read from this image?'))return;
      }
      setSource({id:data.id,text:data.pages.map((p:any)=>`Page ${p.page}\n${p.text}`).join('\n\n'),warnings:data.warnings});
      change(d=>{
        if(kind==='syllabus'){
          d.profile.material_coverage={...coverageSelections(d.profile),[data.id]:{filename:file.name,module:module??null,mode:module?'entire':'range'}};
          d.profile.syllabus_document_ids.push(data.id);d.profile.source_documents.push(data.id);
          data.pages.forEach((p:any)=>{d.profile.syllabus[data.id+':page '+p.page]=p.text;});
          d.profile.course_evidence_verified=false;d.profile.coverage_confirmed=false;
          if(data.metadata.course_code)d.profile.course_code=data.metadata.course_code;
          if(data.metadata.course_name)d.profile.course_name=data.metadata.course_name;
          d.profile.outcomes={...data.outcomes,...d.profile.outcomes};
          d.profile.co_po={...data.co_po,...d.profile.co_po};
          for(const p of d.sets){delete p.faculty_checks?.syllabus;delete p.faculty_checks?.outcomes;}
        }else if(kind==='mapping'){
          d.profile.mapping_document_ids=[...(d.profile.mapping_document_ids||[]),data.id];
          for(const [co,statement] of Object.entries(data.outcomes||{})){
            if(!d.profile.outcomes[co]?.trim())d.profile.outcomes[co]=statement;
          }
          for(const [co,mapping] of Object.entries(data.co_po||{})){
            d.profile.co_po[co]=mapping;
          }
          for(const p of d.sets)delete p.faculty_checks?.outcomes;
        }else{
          let paper=d.sets.find(s=>s.label===kind);if(!paper){paper=emptyPaper(kind);d.sets.push(paper);}
          paper.document_ids=[data.id];paper.extraction_warnings=data.warnings;paper.questions=data.questions;paper.metadata=data.metadata;
          paper.faculty_checks={};
          if(kind==='A'){
            if(courseChanged){
              d.profile.course_code=uploadedCourse;
              d.profile.course_name=data.metadata.course_name||'';
              d.profile.syllabus_document_ids=[];
              d.profile.mapping_document_ids=[];
              d.profile.source_documents=[];
              d.profile.syllabus={};
              d.profile.material_coverage={};
              d.profile.outcomes={};
              d.profile.co_po={};
              d.profile.coverage_confirmed=false;
              d.profile.course_evidence_verified=false;
              for(const other of d.sets)other.faculty_checks={};
            }
            if(!d.profile.course_code)d.profile.course_code=data.metadata.course_code||'';
            if(!d.profile.course_name)d.profile.course_name=data.metadata.course_name||'';
          }
        }
      });
      if(isPaper)setActiveSet(kind);
      if(module)setModuleNumber(module+1);
      setPendingUpload(null);
      if(kind==='mapping'){
        const count=Object.values(data.co_po||{}).reduce<number>((total,row)=>total+Object.keys(row as object).length,0);
        setNotice(count?`Imported ${count} CO–PO strengths. Compare them with the original image below.`:'Course outcome statements imported. The reader found no usable CO–PO strengths. Check the image or enter them manually.');
      }else{
        setNotice(kind==='syllabus'?'Source added. Select its coverage below.':courseChanged?'New course detected. Check the paper, then add the mapping and syllabus for this course.':`Set ${kind} paper loaded. Review the extracted questions and printed labels below.`);
      }
    });
  }
  function updateCoverage(id:string, selection:SourceCoverage){
    change(d=>{
      d.profile.material_coverage={...coverageSelections(d.profile),[id]:selection};
      d.profile.coverage_confirmed=false;
      for(const p of d.sets)delete p.faculty_checks?.syllabus;
    });
  }
  function removeCoverageSource(id:string){
    change(d=>{
      d.profile.syllabus_document_ids=d.profile.syllabus_document_ids.filter((doc:string)=>doc!==id);
      d.profile.source_documents=d.profile.source_documents.filter((doc:string)=>doc!==id);
      if(d.profile.material_coverage)delete d.profile.material_coverage[id];
      for(const key of Object.keys(d.profile.syllabus))if(key.startsWith(`${id}:page `))delete d.profile.syllabus[key];
      d.profile.coverage_confirmed=false;
      d.profile.course_evidence_verified=false;
      for(const p of d.sets)delete p.faculty_checks?.syllabus;
    });
  }
  function editOutcome(co:string,statement:string){
    change(d=>{
      d.profile.outcomes[co]=statement;
      for(const p of d.sets)delete p.faculty_checks?.outcomes;
    });
  }
  function editStrength(co:string,po:string,strength:number){
    change(d=>{
      d.profile.co_po[co]??={};
      if(strength)d.profile.co_po[co][po]=strength;
      else delete d.profile.co_po[co][po];
      for(const p of d.sets)delete p.faculty_checks?.outcomes;
    });
  }
  function addOutcome(){
    let n=1;
    while(outcomeIds.includes(`CO${n}`))n++;
    editOutcome(`CO${n}`,'');
  }
  function confirmCoverage(confirmed:boolean){
    change(d=>{
      d.profile.material_coverage=coverageSelections(d.profile);
      d.profile.coverage_confirmed=confirmed;
      for(const p of d.sets)delete p.faculty_checks?.syllabus;
    });
  }
  async function original(id:string){await operation('Opening source',async()=>{const blob=await(await request('/documents/'+id+'/original')).blob();const url=URL.createObjectURL(blob);window.open(url,'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(url),60000);});}
  async function run(){
    if(busy)return;
    setReviewPhase('preparing');
    setTab('results');
    await operation('Evaluating each question…',async()=>{
      const row=await persist();
      const job=`/submissions/${row.id}/review-job?revision=${row.revision}`;
      const started=await(await request(job,{method:'POST'})).json();
      setReviewPhase(started.status==='running'?'running':'queued');
      let result:RecordData;
      for(;;){
        const state=await(await request(job)).json();
        if(state.status==='finished'){result=state.record;break;}
        if(state.status!=='queued'&&state.status!=='running')throw new Error('The review stopped before saving a result. Run evaluation again to continue.');
        setReviewPhase(state.status);
        await new Promise(resolve=>setTimeout(resolve,1500));
      }
      setRecord(result);
      if(result.audit?.agent?.status==='COVERAGE_REQUIRED'){
        setTab('syllabus');
        setError(result.audit.agent.summary);
      }
    });
  }
  async function download(){await operation('Preparing draft report',async()=>{if(!record||dirty)throw new Error('Save and run scrutiny for your current changes first.');const blob=await(await request(`/submissions/${record.id}/report.pdf?revision=${record.revision}`)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`Scrutiny-r${record.revision}-DRAFT.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);});}
  async function saveFacultyBloom(question:QuestionFinding,input:FacultyBloomInput){
    if(!record||dirty||busy)return;
    await operation('Saving faculty decision',async()=>{
      const response=await request(`/submissions/${record.id}/faculty-bloom`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...input,expected_revision:record.revision,set_label:question.set_label,q_no:question.q_no,
          expected_suggested_level:question.suggested_level==='Unresolved'?null:Number(question.suggested_level.slice(1))}),
      });
      const updated:RecordData=await response.json();
      setRecord(updated);
      setDraft(updated.submission);
      setNotice(`Faculty decision saved for Set ${question.set_label}, Question ${question.q_no}.`);
    });
  }
  if(!draft)return <main className="loading">
    <div className="access-panel">
      <div className="brand"><span className="brand-mark" aria-hidden="true"/>Scrutiny desk</div>
      <h1>Open your workspace</h1>
      {error?<form onSubmit={e=>{e.preventDefault();void operation('Opening workspace',async()=>{await workspaceKey(accessCode.trim());window.location.reload();});}}>
        <p role="alert">{error}</p>
        <label>Presentation access code<input type="password" autoComplete="off" value={accessCode} onChange={e=>setAccessCode(e.target.value)}/></label>
        <button disabled={!!busy||!accessCode.trim()}>Open workspace</button>
      </form>:<p role="status">Opening your scrutiny workspace…</p>}
    </div>
  </main>;
  const paper=draft.sets.find(s=>s.label===activeSet)||emptyPaper(activeSet),profile=draft.profile;
  const duplicates=draft.sets.flatMap(p=>{const seen=new Set<string>(),repeated=new Set<string>();p.questions.forEach(q=>{if(seen.has(q.q_no))repeated.add(q.q_no);seen.add(q.q_no);});return [...repeated].map(q=>`${p.label}/Q${q}`);});
  const canContinue=!!draft.sets.find(p=>p.label==='A')?.questions.length&&!duplicates.length;
  const uploadDisabled=!!busy;
  const uploadDestination=pendingUpload?.kind==='mapping'?'CO–PO mapping':pendingUpload?.kind==='syllabus'?
    (pendingUpload.module?`Module ${pendingUpload.module}`:'syllabus'):`Set ${pendingUpload?.kind}`;
  const notes=profile.material_kind==='notes';
  const selections=coverageSelections(profile);
  const selectedCoverage=Object.values(selections);
  const coverageEntered=selectedCoverage.length>0&&selectedCoverage.every(selection=>!missingCoverageField(selection,notes));
  const outcomeIds=[...new Set([...Object.keys(profile.outcomes),...Object.keys(profile.co_po),...draft.sets.flatMap(p=>p.questions.flatMap(q=>q.co))])]
    .sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const reviewing=busy==='Evaluating each question…';
  const audit=!dirty&&!reviewing?record?.audit:null;
  const questionFindings:QuestionFinding[]=audit?.question_findings??[];
  const blockers=(audit?.blockers??[]).filter((item:string)=>item!=='Set B is mandatory and has not been supplied.');
  const coverageFailure:string=audit?.agent?.status==='COVERAGE_REQUIRED'?audit.agent.summary:'';
  const showContinueReview=!!pendingUpload||draft.sets.some(set=>set.questions.length||set.document_ids.length);
  const nextTask=showContinueReview?nextReviewTarget({
    papers:draft.sets, canContinue, pendingKind:pendingUpload?.kind,
    cloud:!cloudSelected||cloudAllowed?'ready':cloud?.configured?'consent':'unavailable',
    outcomes:profile.outcomes, coPo:profile.co_po, rulesConfirmed:profile.rules_confirmed,
    selections:selectedCoverage, notes, uploadModule:moduleNumber, coverageConfirmed:profile.coverage_confirmed,
    coverageFailure, hasAudit:!!audit, findings:questionFindings, blockerCount:blockers.length,
  }):null;
  function continueReview(target:ReviewTarget){
    if(target.set)setActiveSet(target.set);
    setTab(target.stage);
    setReviewJump(target);
  }
  const stages = [
    {id:'papers', label:'Question paper', disabled:!!busy},
    {id:'mapping', label:'CO–PO mapping', disabled:!!busy||!canContinue},
    {id:'syllabus', label:'Syllabus & coverage', disabled:!!busy||!canContinue},
    {id:'results', label:'Findings & report', disabled:!record?.audit&&!reviewing},
  ] as const;
  const uploadControls=(cloudSelected||pendingUpload)&&<div className="upload-controls">
    {cloudSelected&&(cloud?.configured?
      <label className="check"><input id="review-cloud-consent" type="checkbox" disabled={!!busy} checked={cloudAllowed}
        onChange={e=>change(d=>{d.ai_mode='cloud';d.cloud_consent=e.target.checked;d.cloud_provider_id=e.target.checked?cloud.id:null;})}/>
        I permit sending the selected files and review context to {cloud.destination} ({cloud.model}) for this scrutiny.
      </label>:<p>{aiConfig.error||'The cloud processing configuration is still loading.'}{aiConfig.error&&
        <button className="text-button" disabled={!!busy} onClick={()=>operation('Checking AI settings',loadAIConfig)}>Retry AI settings</button>}</p>)}
    {pendingUpload&&!busy&&<div className="pending-upload">
      <p><strong>{pendingUpload.file.name}</strong> · {uploadDestination}
        {cloudSelected&&!cloudAllowed&&<span>Confirm cloud processing above to read this file.</span>}</p>
      <button id="review-upload-read" disabled={cloudSelected&&!cloudAllowed} onClick={()=>void upload(pendingUpload)}>Upload and read</button>
      <button className="secondary" onClick={()=>setPendingUpload(null)}>Clear selection</button>
    </div>}
  </div>;
  return <div className="app">
    <a className="skip-link" href="#review-workspace">Skip to review workspace</a>
    <header className="site-header">
      <div className="wrap header-inner">
        <div className="brand"><span className="brand-mark" aria-hidden="true"/>Scrutiny desk</div>
        <div className="header-actions">
          <ThemeToggle/>
          <span className="mode"><span className="lock-mark" aria-hidden="true"/><span className="mode-text">Private draft workspace</span></span>
        </div>
      </div>
    </header>
    <main className="wrap">
      <div className="heading" data-enter><div><p className="eyebrow">CIE review</p><h1>Question paper scrutiny</h1><p>Check each question against the course outcomes and topics taught.</p></div><button className="secondary new-scrutiny" disabled={!!busy} onClick={()=>operation('Creating draft',async()=>{const data=await(await request('/profiles/starter')).json();setDraft(data.submission);setRecord(null);setDirty(true);localStorage.removeItem('scrutiny-current');setSource(null);setPendingUpload(null);setActiveSet('A');setTab('papers');})}><span aria-hidden="true">+</span> New scrutiny</button></div>
      <div className="app-frame">
        <aside className="workflow">
          <p className="workflow-label">Review stages</p>
          <nav aria-label="Review stages">
            {stages.map(({id,label,disabled},index)=><button key={id} disabled={disabled} aria-current={tab===id?'step':undefined} onClick={()=>setTab(id)}>
              <span className="step-number" aria-hidden="true">0{index+1}</span>{label}
            </button>)}
          </nav>
          {nextTask&&<div className="continue-review">
            <p id="next-review-action">{reviewing?'Evaluation is running.':nextTask.reason}</p>
            <button type="button" className="continue-review-button" aria-describedby="next-review-action"
              disabled={!!busy} onClick={()=>continueReview(nextTask)}>Continue review <span aria-hidden="true">→</span></button>
          </div>}
        </aside>
        <div className="stage-workspace" id="review-workspace" ref={workspaceRef} tabIndex={-1}>
          <div className="workspace-bar draft-bar">
            <label className="draft-title">Draft title<input aria-label="Scrutiny title" className="title-input" value={draft.title} disabled={!!busy} onChange={e=>change(d=>{d.title=e.target.value;})}/></label>
            <div className="save-actions">
              <span className="draft-status" role="status">{dirty?'Unsaved changes':record?`Saved · revision ${record.revision}`:'New draft'}</span>
              <button className="secondary" disabled={!!busy} onClick={()=>operation('Saving draft',async()=>{await persist();setNotice('Draft saved.');})}>Save draft</button>
            </div>
          </div>
      {error&&!(tab==='syllabus'&&error===coverageFailure)&&<div role="alert" className="alert error">{error}</div>}{notice&&<div role="status" className="alert">{notice}</div>}
      {busy&&!reviewing&&<div role="status" className="alert">{busy}…</div>}
      <details className="quick-start"><summary id="review-processing">Processing and saved scrutinies</summary>
        <div className="metadata-grid"><label>Processing method<select value={cloudSelected?'cloud':'local'} disabled={!!busy} onChange={e=>change(d=>{d.ai_mode=e.target.value as 'local'|'cloud';d.cloud_consent=false;d.cloud_provider_id=null;})}><option value="local" disabled={aiConfig.hosted}>{aiConfig.hosted?"Local AI unavailable on this host":"Local AI (experimental) — files stay on this computer"}</option><option value="cloud" disabled={!cloud?.configured}>{cloud?cloud.label+' — '+cloud.model:'Cloud AI unavailable'}</option></select></label><label>Saved scrutiny<select value={record?.id||''} disabled={!!busy} onChange={e=>{const id=e.target.value;if(id)operation('Opening draft',async()=>{if((dirty||pendingUpload)&&!window.confirm('Open the saved scrutiny and discard unsaved changes?'))return;const row=await(await request('/submissions/'+id)).json();setRecord(row);setDraft(row.submission);setDirty(false);setPendingUpload(null);setSource(null);setActiveSet('A');setTab('papers');localStorage.setItem('scrutiny-current',id);});}}><option value="">Current new draft</option>{savedDrafts.map(d=><option key={d.id} value={d.id}>{d.title}</option>)}</select></label></div>
        {cloud&&<p>Cloud service: {cloud.label} · {cloud.model||'model missing'} · {cloud.destination} · {cloud.vision?'Image input enabled':'Text only'} {!cloud.configured&&'· API key or model missing'} <button disabled={!!busy||!cloud.configured} onClick={()=>operation('Checking AI connection',async()=>{const data=await(await request('/ai/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider_id:cloud.id})})).json();setNotice(data.message);})}>Check AI connection</button></p>}
        {!cloudSelected&&aiConfig.error&&<p>{aiConfig.error}</p>}
      </details>
      {tab==='papers'&&<section className="panel"><div className="panel-title"><div><h2>Your question papers</h2><p>Check the extracted questions, marks, CO/PO labels and printed Bloom’s levels.</p></div><div className="segmented">{(['A','B'] as const).map(label=><button aria-pressed={activeSet===label} className={activeSet===label?'selected':''} key={label} onClick={()=>setActiveSet(label)}>Set {label}{label==='B'?' (optional)':''}<span>{draft.sets.find(s=>s.label===label)?.questions.length||0} parts</span></button>)}</div></div>
        <label className="upload"><span className="upload-icon" aria-hidden="true">↑</span><span className="upload-copy"><b>Choose Set {activeSet} paper</b><span id="paper-formats">PDF, DOCX, TXT, PNG or JPEG · up to 15 MB</span></span><input id="review-paper-file" aria-label={`Choose Set ${activeSet} paper`} aria-describedby="paper-formats" disabled={uploadDisabled} type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)chooseUpload({file,kind:activeSet});}}/></label>
        {uploadControls}
        {activeSet==='B'&&(paper.questions.length>0||paper.document_ids.length>0)&&<button id="review-optional-set" className="text-button" disabled={!!busy} onClick={()=>{
          change(d=>{d.sets=d.sets.filter(p=>p.label!=='B');});
          setActiveSet('A');
        }}>Remove optional Set B from this draft</button>}
        {!!paper.document_ids.length&&<div className="source-links">{paper.document_ids.map((id,i)=><button className="text-button" key={id} onClick={()=>original(id)}>View source {i+1} ↗</button>)}</div>}
        <div className="metadata-grid">{[['course_code','Course code'],['course_name','Course name'],['semester','Semester'],['date','Paper date'],['academic_year','Academic year'],['ia_test_no','CIE / IA number'],['duration','Duration'],['max_marks','Maximum scoring marks']].map(([key,label])=><label key={key}>{label}<input value={paper.metadata[key]??''} onChange={e=>changePaper(p=>{p.metadata[key]=key==='max_marks'?(e.target.value?Number(e.target.value):null):e.target.value;})}/></label>)}</div>
        {paper.extraction_warnings?.map((warning:string,i:number)=><div className="alert" key={i}>{warning}</div>)}
        <BloomDistributionPreview setLabel={activeSet} questions={paper.questions}
          offeredMarks={profile.offered_marks} bloomTargets={profile.bloom_targets}/>
        <div className="subheading"><div className="question-heading"><h3>Extracted questions</h3><span>{paper.questions.length} parts</span></div><button id="review-add-question" className="secondary" onClick={()=>changePaper(p=>p.questions.push(blankQuestion()))}>Add a question</button></div>
        {!paper.questions.length&&<div className="empty">Upload the paper to extract proposals, or add questions manually. Missing values will stay unresolved.</div>}
        {paper.questions.map((q,i)=><article className="question" key={i}>
          <div className="question-top"><label>Question<select id={questionFieldId(i,'number')} value={q.q_no} onChange={e=>editQuestion(i,{q_no:e.target.value})}>{Array.from({length:8},(_,n)=>n+1).flatMap(n=>['','a','b'].map(part=><option key={n+part} value={n+part}>{n+part}</option>))}</select></label><label>Marks<input id={questionFieldId(i,'marks')} type="number" min="0.5" max="10" step="0.5" value={q.marks??''} placeholder="Unknown" onChange={e=>editQuestion(i,{marks:e.target.value||null})}/></label><label>CO<input id={questionFieldId(i,'co')} placeholder="CO1" value={q.co.join(', ')} onChange={e=>changePaper(p=>{p.questions[i].co=e.target.value.toUpperCase().split(',').map(x=>x.trim()).filter(Boolean);p.questions[i].extraction_confirmed=false;})}/></label><label>PO<input id={questionFieldId(i,'po')} placeholder="PO1, PO11" value={q.po.join(', ')} onChange={e=>changePaper(p=>{p.questions[i].po=e.target.value.toUpperCase().split(',').map(x=>x.trim()).filter(Boolean);p.questions[i].extraction_confirmed=false;})}/></label><label>Printed Bloom’s<select id={questionFieldId(i,'bloom')} value={q.stated_level??''} onChange={e=>changePaper(p=>{p.questions[i].stated_level=e.target.value?Number(e.target.value):null;p.questions[i].extraction_confirmed=false;})}><option value="">Unknown</option>{[1,2,3,4,5,6].map(n=><option key={n} value={n}>L{n}</option>)}</select></label><button className="remove" aria-label={`Remove question ${q.q_no}`} onClick={()=>changePaper(p=>{p.questions.splice(i,1);})}>Remove</button></div>
          <label className="sr-only" htmlFor={questionFieldId(i,'text')}>Question {q.q_no} text</label><textarea id={questionFieldId(i,'text')} rows={3} value={q.text} onChange={e=>editQuestion(i,{text:e.target.value})}/>
          <label className="check"><input type="checkbox" checked={q.extraction_confirmed} onChange={e=>changePaper(p=>{p.questions[i].extraction_confirmed=e.target.checked;},false)}/>I checked the text, marks and labels against the source.</label>
          <details><summary>Faculty decision after AI review (optional)</summary><label>Faculty-reviewed Bloom’s level
            <select disabled={!!busy} value={q.reviewed_level??''} onChange={e=>changePaper(p=>{
              p.questions[i].reviewed_level=e.target.value?Number(e.target.value):null;
              p.questions[i].faculty_bloom_decision=null;
            },false)}>
              <option value="">Awaiting faculty review</option>
              {[1,2,3,4,5,6].map(n=><option key={n} value={n}>L{n}</option>)}
            </select>
          </label></details>
          {q.evidence.length>0&&<details><summary>Source excerpt · page {q.evidence[0].page}</summary><pre>{q.evidence.map(e=>e.quote).join('\n')}</pre></details>}
        </article>)}
        {!!paper.questions.length&&<details className="coverage">
          <summary>Faculty checks for Set {activeSet}</summary>
          <div className="metadata-grid">{(Object.keys(facultyChecks) as FacultyCriterion[]).map(key=><label key={key}>
            {facultyChecks[key]}
            <select disabled={!!busy} value={paper.faculty_checks?.[key]??''} onChange={e=>{
              const value=e.target.value as FacultyDecision|'';
              changePaper(p=>{
                p.faculty_checks??={};
                if(value)p.faculty_checks[key]=value;
                else delete p.faculty_checks[key];
              },false);
            }}>
              <option value="">Awaiting faculty review</option><option value="confirmed">Confirmed</option><option value="needs_revision">Needs revision</option>
            </select>
          </label>)}</div>
        </details>}
        {!!duplicates.length&&<p role="alert">Resolve repeated question numbers before continuing: {duplicates.join(', ')}.</p>}
        <div className="workspace-bar"><button disabled={!!busy||!canContinue} onClick={()=>setTab('mapping')}>Next: CO–PO mapping</button></div>
      </section>}
      {tab==='mapping'&&<section className="panel">
        <h2>Course details and CO–PO mapping</h2>
        <p>Upload a clear photo of the course outcomes or matrix to fill the fields, or enter the values below. Check the detected values against the original.</p>
        <label className="upload"><span className="upload-icon" aria-hidden="true">↑</span><span className="upload-copy"><b>Upload CO–PO mapping photo</b><span id="mapping-formats">PNG, JPEG, or a PDF with the mapping table</span></span>
          <input aria-label="Upload CO–PO mapping photo" aria-describedby="mapping-formats" type="file" accept=".png,.jpg,.jpeg,.pdf" disabled={uploadDisabled} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)chooseUpload({file,kind:'mapping'});}}/>
        </label>
        {uploadControls}
        {(profile.mapping_document_ids||[]).map((id:string,i:number)=><button key={id} className="text-button" onClick={()=>original(id)}>View mapping source {i+1}</button>)}
        <div className="metadata-grid">
          <label>Course code<input value={profile.course_code} onChange={e=>profileField('course_code',e.target.value)}/></label>
          <label>Course name<input value={profile.course_name} onChange={e=>profileField('course_name',e.target.value)}/></label>
        </div>
        <div className="outcome-list">
          {outcomeIds.map(co=><div className="question outcome" key={co}>
            <label>{co} statement<textarea id={outcomeFieldId(co,'statement')} value={profile.outcomes[co]??''} onChange={e=>editOutcome(co,e.target.value)}/></label>
            <div className="po-grid review-jump-target" id={outcomeFieldId(co,'strengths')} role="group" aria-label={`${co} PO strengths`} tabIndex={-1}>{Array.from({length:12},(_,i)=>`PO${i+1}`).map(po=><label key={po}>{po}
              <select aria-label={`${co} ${po} strength`} value={profile.co_po[co]?.[po]??''} onChange={e=>editStrength(co,po,Number(e.target.value))}>
                <option value="">—</option><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option>
              </select>
            </label>)}</div>
          </div>)}
        </div>
        <button className="secondary" onClick={addOutcome}>Add course outcome</button>
        <details className="coverage"><summary>Examination pattern</summary>
          <p>80 printed marks, 50 attempted. Q1 and Q2 are compulsory, with one question from each pair Q3/4, Q5/6 and Q7/8. Bloom’s targets are 30%, 60% and 10% across the 80 printed marks.</p>
          <label className="check"><input id="review-rules" type="checkbox" checked={profile.rules_confirmed} onChange={e=>profileField('rules_confirmed',e.target.checked)}/>I confirm these examination rules.</label>
        </details>
        <div className="workspace-bar"><button className="secondary" onClick={()=>setTab('papers')}>Back</button>
          <button disabled={!!busy} onClick={()=>setTab('syllabus')}>Next: syllabus & coverage</button></div>
      </section>}
      {tab==='syllabus'&&<section className="panel">
        <h2>Syllabus and covered topics</h2>
        {coverageFailure&&<div id="review-coverage-feedback" className="alert error review-jump-target" role="alert" tabIndex={-1}>{coverageFailure}</div>}
        <div className="metadata-grid material-fields"><label>Material type<select value={profile.material_kind} disabled={!!busy||!!profile.syllabus_document_ids.length} onChange={e=>profileField('material_kind',e.target.value)}>
          <option value="syllabus">Syllabus sheet</option><option value="notes">Module documents</option>
        </select></label>
        {notes&&<label>Number of the module to upload
          <input id="review-module-upload-number" aria-label="Module number to upload" type="number" min="1" step="1" value={moduleNumber||''}
            onChange={e=>setModuleNumber(Number(e.target.value)||0)}/>
        </label>}</div>
        <label className="upload"><span className="upload-icon" aria-hidden="true">↑</span><span className="upload-copy"><b>{notes?'Add module file':'Upload syllabus sheet'}</b><span id="syllabus-formats">PDF, DOCX, TXT, PNG or JPEG</span></span>
          <input id="review-syllabus-file" aria-label={notes?'Add module file':'Upload syllabus sheet'} aria-describedby="syllabus-formats" type="file" disabled={uploadDisabled||(notes&&(!Number.isInteger(moduleNumber)||moduleNumber<1))} accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
            onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)chooseUpload({file,kind:'syllabus',module:notes?moduleNumber:undefined});}}/>
        </label>
        {uploadControls}
        {profile.syllabus_document_ids.map((id:string,i:number)=>{
          const selection=selections[id];
          return <MaterialCoverage key={id} label={notes?`Module ${selection.module??'?'}`+(selection.filename?` · ${selection.filename}`:''):(selection.filename||`Syllabus source ${i+1}`)}
            index={i} notes={notes} selection={selection} pages={sourcePages(profile,id)} onOpen={()=>original(id)}
            onRemove={()=>removeCoverageSource(id)} onChange={value=>updateCoverage(id,value)}/>;
        })}
        <label className="check"><input type="checkbox" checked={profile.course_evidence_verified} onChange={e=>profileField('course_evidence_verified',e.target.checked)}/>I checked the extracted material against the original.</label>
        <label className="check"><input id="review-coverage-confirm" type="checkbox" disabled={!coverageEntered} checked={profile.coverage_confirmed&&coverageEntered}
          onChange={e=>confirmCoverage(e.target.checked)}/>I confirm this coverage for the exam.</label>
        {!coverageEntered&&<p>Upload the source, then choose the entire file or enter both pages and both topic phrases for each range.</p>}
        <div className="workspace-bar"><button className="secondary" onClick={()=>setTab('mapping')}>Back</button>
          <button id="review-evaluate" disabled={!!busy||!canContinue||!coverageEntered||!profile.coverage_confirmed||(cloudSelected&&!cloudAllowed)} onClick={run}>{busy||'Evaluate question paper'}</button>
        </div>
      </section>}
      {tab==='results'&&<section className="panel"><div className="panel-title"><h2>Scrutiny findings</h2><button id="review-download" className="secondary" disabled={!!busy||!audit} onClick={download}>Download draft PDF</button></div>
        {uploadControls}
        <div className="sr-only" role="status">{audit?'Scrutiny findings are ready.':''}</div>
        {reviewing?<ReviewWaitingPanel phase={reviewPhase}/>:!audit?<div className="empty" role="status">{dirty?'Your paper has changed. Save and run scrutiny to refresh the findings.':'Run scrutiny to see findings for this revision.'}</div>:<>
          <div className="verdict"><b>{audit.agent.status==='COMPLETE'?'Academic review complete':'Academic review'}</b><span>Revision {record?.revision} · {audit.status==='READY_FOR_FACULTY_REVIEW'?'Draft ready for departmental sign-off':'Draft report checks below'}</span></div>
          <details><summary id="review-report-checks">Draft report checks · {blockers.length} items require attention</summary><ul>{blockers.map((b:string,i:number)=><li key={i}>{b}</li>)}</ul></details>
          <details><summary>Structure, marks, and overall Bloom’s distribution</summary>{audit.sets.map((s:any)=><div key={s.label} className="set-results"><h3>Set {s.label} <span>{s.offered_marks??'?'} offered marks</span></h3><div className="criterion-grid">{s.criteria.map((c:any)=><details key={c.key} className="criterion"><summary><span className={'status '+c.status}>{c.status.replace(/_/g,' ')}</span>{c.label}</summary><ul>{c.findings.map((f:any,i:number)=><li key={i}>{f.message}</li>)}</ul></details>)}</div><details><summary>All eight valid answer paths</summary><table><thead><tr><th>Full questions answered</th><th>Total marks</th></tr></thead><tbody>{s.paths.map((p:any,i:number)=><tr key={i}><td>{p.questions.join(' + ')}</td><td>{p.marks??'Unknown'}</td></tr>)}</tbody></table></details><p className="distribution">Declared Bloom’s: {s.declared_blooms?Object.entries(s.declared_blooms).map(([k,v])=>`${k}: ${Number(v).toFixed(1)}%`).join(' · '):'unresolved labels or marks'}</p><p className="distribution">Faculty-reviewed Bloom’s: {s.reviewed_blooms?Object.entries(s.reviewed_blooms).map(([k,v])=>`${k}: ${Number(v).toFixed(1)}%`).join(' · '):'record a faculty Bloom’s decision for each question below'}</p></div>)}</details>
          {record&&audit.sets.filter((set:SetBloomFinding)=>set.criteria.some(c=>c.key==='blooms'&&c.findings.some(f=>f.code==='BLOOM_DISTRIBUTION')))
            .map((set:SetBloomFinding)=><BloomReplacement key={`${record.id}/${record.revision}/${set.label}`}
              recordId={record.id} revision={record.revision} setLabel={set.label} request={request} disabled={!!busy}/>)}
          <div className="agent-box">
            <h3>Question-by-question academic review</h3>
            <p>{audit.agent.summary||audit.agent.status.replace(/_/g,' ')}</p>
            {questionFindings.map((question,index)=><article className="academic-question" key={`${record?.id}/${question.set_label}/${question.q_no}/${index}`}>
                <h3>Set {question.set_label} · Question {question.q_no}</h3>
                <p>{question.text}</p>
                <div className="review-tags">
                  <span>Printed Bloom’s: {question.printed_level}</span>
                  <span>Suggested Bloom’s: {question.suggested_level}</span>
                  <span>Faculty-reviewed: {question.faculty_level}</span>
                  <span>{question.marks} marks</span>
                  <span>{question.co} · {question.po}</span>
                  {question.verification_status&&<span>{question.verification_status==='AGREED'?'Verifier agrees':question.verification_status==='PENDING'?'Verification pending':'Verifier disagrees'}</span>}
                </div>
                {!!question.figure_sources?.length&&<div className="figure-sources">
                  {question.figure_sources.map(source=><FigurePreview key={`${source.document_id}/${source.kind}/${source.index}`} source={source}/>)}
                </div>}
                <div className="question-checks">{question.checks.map(item=><section key={item.label}>
                  <h4>{item.label} <span className="finding-status" data-status={item.status}>{item.status}</span></h4>
                  <p className="finding-reason"><b>Why</b> {item.reason}</p>
                  <p><b>Suggestion</b> {item.suggestion}</p>
                </section>)}</div>
                <FacultyBloomReview question={question} decisionId={facultyDecisionId(index)} busy={!!busy} onSave={input=>void saveFacultyBloom(question,input)}/>
                {question.rewrite&&<blockquote><b>Suggested wording</b><p>{question.rewrite}</p></blockquote>}
                {question.citations.map((citation,i)=><details key={i}><summary>Evidence · {citation.source}</summary><q>{citation.quote}</q>
                  {citation.document_id&&<button className="text-button" onClick={()=>original(citation.document_id!)}>View original</button>}</details>)}
                {question.confidence&&<p className="review-confidence">AI confidence: {question.confidence} · {question.verification_feedback}</p>}
              </article>)}
            <details><summary>Agent activity</summary><ol>{audit.agent.trace?.map((entry:any,i:number)=><li key={i}>{entry.tool.replace(/_/g,' ')} {entry.status||''}</li>)}</ol></details>
            <div className="workspace-bar"><button className="secondary" onClick={()=>setTab('syllabus')}>Back to coverage</button>
              {audit.agent.status!=='COMPLETE'&&<button disabled={!!busy} onClick={run}>Retry evaluation</button>}
            </div>
          </div>
        </>}
      </section>}
      {source&&<details className="source-panel"><summary>Latest uploaded source and extraction notes</summary><ul>{source.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul><pre>{source.text}</pre></details>}
        </div>
      </div>
      <footer>Departmental reviewers make the final academic decisions and sign the report.
        <span className="flyby-credit">Flyby adapts the <a href="https://animalanimator.github.io/african-elephant-rig-blender/">African Elephant Bull model by Animal Animator</a> under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</span>
      </footer>
    </main>
  </div>;
}






