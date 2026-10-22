import asyncio, copy, json, sys, time
from pathlib import Path
from uuid import uuid4
import unicodedata
P=next(d for d in Path('/Users/parkkunmin/Documents/SKALA/학습/1_진행중').iterdir() if unicodedata.normalize('NFC',d.name).startswith('10.22'))/'실습 및 과제/SKALA_LangGraph_Disclosure_Revision_Analysis'
scope={"__name__":"recorded_validation"}
exec((P/'docs/검증/공시영향분석_20261022/run_validation.py').read_text().rsplit('asyncio.run(main())',1)[0],scope)
RecordedHarness,Ledger,AnalysisGraph,InMemorySaver,search_documents=[scope[k] for k in ['RecordedHarness','Ledger','AnalysisGraph','InMemorySaver','search_documents']]
A=P/'docs/검증/신규정정분석_20261022'
fixed=scope['fixed'];dump=scope['dump']
originals=json.loads(Path('/tmp/disclosure-web-validation/case-originals.json').read_text())
row=next(x for x in originals if x['filing']['company_name']=='삼성중공업')
new_filing={"documents":[{"document_id":"opendart:"+row['filing']['receipt_no']+":"+row['version']['content_hash'],"text":row['version']['raw_content'],"url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+row['filing']['receipt_no'],"published_at":row['filing']['filed_at'][:10]}],"changes":[],"complete_correction_table":False,"metadata_status":"FOUND","report_name":row['filing']['title']}
async def main():
 for kind in ['NEW','CORRECTION']:
  for n in range(1,3):
   d=A/kind/f'run-{n}';d.mkdir(parents=True,exist_ok=True)
   filing=copy.deepcopy(new_filing if kind=='NEW' else fixed['filing']);memo=copy.deepcopy(fixed['memo'])
   task=str(uuid4());l=Ledger('/tmp/disclosure-web-validation/newtype-'+task+'.sqlite');l.begin(task,'fixed')
   h=RecordedHarness(task,l,directory=d)
   class Tools:
    def __init__(self):self.calls=[]
    async def call(self,name,args):
     self.calls.append({'name':name,'args':args});dump(d/'tools.json',self.calls)
     if name=='disclosure_get_document':return copy.deepcopy(filing)
     if name=='business_get_memo':return copy.deepcopy(memo)
     if name=='ensure_analysis_index':return {'indexed':True}
     if name=='search_evidence':
      docs=filing['documents']+[memo]
      return {'documents':copy.deepcopy(docs),'sources':search_documents(docs,args['query'],args.get('top_k',5))}
     if name=='business_save_report':return {'status':'COMPLETED','report_id':'local-validation'}
     return {'error':'FIXED_REPLAY_EXTERNAL_UNAVAILABLE'}
   receipt=row['filing']['receipt_no'] if kind=='NEW' else '20260203800709'
   state={'request':{'analysis_task_id':task,'memo_id':'aa58e157-b7b1-4270-8c9f-efe30aabed8c','base_memo_version':1,'disclosure_receipt_no':receipt,'company_name_snapshot':'삼성중공업','corp_code':'00126478','thread_id':task,'disclosure_type':kind},'scope':'fixed-type-validation','warnings':[],'results':{}}
   dump(d/'inputs.json',{'request':state['request'],'filing':filing,'memo':memo})
   try:
    r=await AnalysisGraph(h,Tools(),InMemorySaver()).graph.ainvoke(state,{'configurable':{'thread_id':task}})
    dump(d/'state.json',r);(d/'report.md').write_text(r['report']['content'])
    print(kind,n,'type',r['filing']['analysis_type'],'perspectives',{k:v['status'] for k,v in r['results'].items()},'proposals',[x['impact_type']for x in r['report']['report_json']['base']['proposals']],flush=True)
   except Exception as e:dump(d/'failure.json',{'error':type(e).__name__});print(kind,n,type(e).__name__,flush=True)
   finally:
    dump(d/'events.json',l.events(task));await h.close();l.db.close()
asyncio.run(main())
