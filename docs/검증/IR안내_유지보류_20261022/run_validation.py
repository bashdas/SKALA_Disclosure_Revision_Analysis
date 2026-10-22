import asyncio, copy, json, sys, hashlib, os
from pathlib import Path
from uuid import uuid4
import unicodedata
P=next(d for d in Path('/Users/parkkunmin/Documents/SKALA/학습/1_진행중').iterdir() if unicodedata.normalize('NFC',d.name).startswith('10.22'))/'실습 및 과제/SKALA_LangGraph_Disclosure_Revision_Analysis'
scope={"__name__":"recorded_validation"}
exec((P/'docs/검증/공시영향분석_20261022/run_validation.py').read_text().rsplit('asyncio.run(main())',1)[0],scope)
RecordedHarness,Ledger,AnalysisGraph,InMemorySaver,search_documents=[scope[k] for k in ['RecordedHarness','Ledger','AnalysisGraph','InMemorySaver','search_documents']]
A=P/'docs/검증/IR안내_유지보류_20261022';fixed=json.loads((A/'inputs.json').read_text());dump=scope['dump']
async def main():
 dump(A/'conditions.json',{'model':os.environ.get('OPENAI_MODEL'),'real_model':True,'tools':'captured actual filing, memo version and initial RAG response; local search replay; local report persistence','source_task':fixed['before']['request']['analysis_task_id'],'input_sha256':hashlib.sha256((A/'inputs.json').read_bytes()).hexdigest(),'temperature':'omitted, API default','seed':'omitted','budgets':'production defaults unchanged'})
 for n in range(1,4):
  d=A/f'run-{n}';d.mkdir(exist_ok=True)
  t=str(uuid4());l=Ledger('/tmp/disclosure-web-validation/ir-decision-'+t+'.sqlite');l.begin(t,'fixed')
  h=RecordedHarness(t,l,directory=d)
  class Tools:
   def __init__(self):self.calls=[]
   async def call(self,name,args):
    self.calls.append({'name':name,'args':args});dump(d/'tools.json',self.calls)
    if name=='disclosure_get_document':return copy.deepcopy(fixed['filing'])
    if name=='business_get_memo':return copy.deepcopy(fixed['memo'])
    if name=='ensure_analysis_index':return {'indexed':True}
    if name=='search_evidence':
     if args['query']=='공시 사실과 기존 메모의 수치, 전망 및 가정':return copy.deepcopy(fixed['rag'])
     docs=fixed['filing']['documents']+[fixed['memo']]+fixed['rag']['documents']
     return {'documents':copy.deepcopy(docs),'sources':search_documents(docs,args['query'],args.get('top_k',5))}
    if name=='business_save_report':return {'status':'COMPLETED','report_id':'local-validation'}
    return {'error':'FIXED_REPLAY_EXTERNAL_UNAVAILABLE'}
  state={'request':{**fixed['before']['request'],'analysis_task_id':t,'thread_id':t},'scope':'fixed-ir-validation','warnings':[],'results':{}}
  try:
   r=await AnalysisGraph(h,Tools(),InMemorySaver()).graph.ainvoke(state,{'configurable':{'thread_id':t}})
   dump(d/'state.json',r);(d/'report.md').write_text(r['report']['content'])
   print(n,'selected',[x['perspective_type']for x in r.get('base',{}).get('selected',[])],'decision',r['report']['report_json'].get('memo_review'),'proposals',len(r['report']['report_json']['base']['proposals']),flush=True)
  except Exception as e:dump(d/'failure.json',{'error':type(e).__name__});print(n,type(e).__name__,flush=True)
  finally:dump(d/'events.json',l.events(t));await h.close();l.db.close()
asyncio.run(main())
