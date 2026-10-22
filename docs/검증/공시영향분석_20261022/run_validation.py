import asyncio, copy, hashlib, json, os, subprocess, sys, time, unicodedata
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT=Path('/Users/parkkunmin/Documents/SKALA')
P=next(d for d in (ROOT/'학습/1_진행중').iterdir() if unicodedata.normalize('NFC',d.name).startswith('10.22'))/'실습 및 과제/SKALA_LangGraph_Disclosure_Revision_Analysis'
A=P/'docs/검증/공시영향분석_20261022'
sys.path.insert(0,str(P/'ai'))
os.environ.update(PYTHONDONTWRITEBYTECODE='1',XDG_CACHE_HOME='/tmp/disclosure-web-validation/cache',TIKTOKEN_CACHE_DIR='/tmp/disclosure-web-validation/cache/tiktoken')
env=dict(x.split('=',1) for x in json.loads(subprocess.check_output(['docker','inspect','disclosure-web-ai-worker-1']))[0]['Config']['Env'])
for k in ('OPENAI_API_KEY','OPENAI_MODEL'):
 if k in env:os.environ[k]=env[k]
from openai import AsyncOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.graph import AnalysisGraph
from disclosure_ai.services.documents import search_documents

fixed=json.loads((A/'inputs.json').read_text())
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str))
class RecordedHarness(Harness):
 def __init__(self,*args,directory,**kwargs):
  super().__init__(*args,**kwargs);self.directory=directory;self.records=[];self.raw=[]
  self.real=AsyncOpenAI(max_retries=0)
  async def parse(**kw):
   row={k:(v.model_json_schema() if k=='response_format' else copy.deepcopy(v)) for k,v in kw.items()};self.raw.append(row)
   try:
    r=await self.real.chat.completions.parse(**kw);row['response']=r.model_dump(mode='json');return r
   except Exception as e:row['error']=type(e).__name__;raise
   finally:dump(self.directory/'api.json',self.raw)
  self.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
 async def model(self,role,context,schema,report=False):
  row={'role':role,'context':copy.deepcopy(context)};self.records.append(row)
  try:
   r=await super().model(role,context,schema,report);row['response']=r.model_dump();return r
  except Exception as e:row['error']=type(e).__name__;raise
  finally:dump(self.directory/'models.json',self.records)
 async def review_output(self,payload,**kwargs):
  dump(self.directory/'before_filter.json',payload)
  r=await super().review_output(payload,**kwargs);dump(self.directory/'after_filter.json',r);return r
 async def close(self):await self.real.close()
class CapturedTools:
 def __init__(self,directory):self.directory=directory;self.calls=[]
 async def call(self,name,args):
  self.calls.append({'name':name,'args':copy.deepcopy(args)});dump(self.directory/'tools.json',self.calls)
  if name=='disclosure_get_document':return copy.deepcopy(fixed['filing'])
  if name=='business_get_memo':return copy.deepcopy(fixed['memo'])
  if name=='ensure_analysis_index':return {'indexed':True}
  if name=='search_evidence':
   if args['query']=='정정 내용과 기존 메모의 계약 금액, 기간 및 위험':return copy.deepcopy(fixed['rag'])
   docs=fixed['filing']['documents']+[fixed['memo']]+fixed['rag']['documents']
   return {'documents':copy.deepcopy(docs),'sources':search_documents(docs,args['query'],args.get('top_k',5))}
  if name=='business_save_report':return {'status':'COMPLETED','report_id':'local-validation'}
  # 원격 서비스 응답을 한 번 확보하고 전후 실행에서 같은 응답을 사용합니다.
  clean={k:v for k,v in args.items() if k!='task_id'}
  key=hashlib.sha256(json.dumps([name,clean],sort_keys=True).encode()).hexdigest()
  q=A/'external'/f'{key}.json';q.parent.mkdir(exist_ok=True)
  if q.exists():return json.loads(q.read_text())
  script="import asyncio,json;from disclosure_ai.services.tools import Tools;print(json.dumps(asyncio.run(Tools('').call("+repr(name)+","+repr(clean)+")),ensure_ascii=False))"
  proc=await asyncio.create_subprocess_exec('docker','exec','disclosure-web-ai-worker-1','python','-B','-c',script,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
  out,err=await proc.communicate()
  value=json.loads(out) if proc.returncode==0 else {'error':'CAPTURE_FAILED'}
  dump(q,value);return value
async def main():
 phase=sys.argv[1]
 dump(A/f'{phase}-conditions.json',{'model':os.environ.get('OPENAI_MODEL','gpt-5.4-mini'),'temperature':'API default, omitted','seed':'omitted','input_sha256':hashlib.sha256((A/'inputs.json').read_bytes()).hexdigest(),'memo_version':1,'receipt':'20260203800709','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=P,text=True).strip(),'settings':'production Harness budgets and output limits unchanged','tools':'captured actual filing/memo/RAG, deterministic local search, shared captured external responses, local report persistence','real_model':True})
 for n in range(1,6):
  d=A/phase/f'run-{n}';d.mkdir(parents=True,exist_ok=True)
  task=str(uuid4());ledger=Ledger(str(Path('/tmp/disclosure-web-validation')/f'{phase}-{task}.sqlite'));ledger.begin(task,'fixed')
  h=RecordedHarness(task,ledger,directory=d);tools=CapturedTools(d)
  state={'request':{'analysis_task_id':task,'memo_id':'aa58e157-b7b1-4270-8c9f-efe30aabed8c','base_memo_version':1,'disclosure_receipt_no':'20260203800709','company_name_snapshot':'삼성중공업','corp_code':'00126478','thread_id':task},'scope':'fixed-validation','warnings':[],'results':{}}
  started=time.time()
  try:
   graph=AnalysisGraph(h,tools,InMemorySaver()).graph
   result=await graph.ainvoke(state,{'configurable':{'thread_id':task}})
   dump(d/'state.json',result)
   report=result.get('report') or result.get('output',{}).get('report')
   if report:dump(d/'report.json',report);(d/'report.md').write_text(report['content'])
  except Exception as e:dump(d/'failure.json',{'error':type(e).__name__})
  finally:
   dump(d/'events.json',ledger.events(task));dump(d/'usage.json',{k:ledger.row(task)[k] for k in ('turns','tokens','tools')});await h.close();ledger.db.close()
  print(phase,n,'seconds',round(time.time()-started,2),'model calls',len(h.raw),flush=True)
asyncio.run(main())
