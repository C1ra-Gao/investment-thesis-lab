"""Real public-source smoke, separate from all fixture tests. No model or paid API."""
import argparse
import json
from thesislab.store import Store
from thesislab.agent_runtime import AgentRuntime
from thesislab.live_providers import ProviderSettings

p=argparse.ArgumentParser()
p.add_argument('--public-consent',action='store_true',required=True)
p.add_argument('--year',type=int,default=2025)
p.add_argument('--period',choices=['H1','Q1','annual'],default='H1')
args=p.parse_args()
settings=ProviderSettings();settings.configure({'public_enabled':args.public_consent})
store=Store('.local/live-public-smoke.sqlite')
runtime=AgentRuntime(store,settings=settings)
s=runtime.create({'statement':'真实公开来源连接和原始字段核验，不代表模型研究验收','entity':'600519.SH','year':args.year,'period':args.period})
result={'mode':'actual_live_public_query','model_called':False,'paid_financial_api_called':False}
try:
    index=runtime.tool(s,{'tool':'issuer_index'});result['index']=index
    s['discovered_documents']=index['documents'];result['documents']=[]
    for d in index['documents'][:1]:result['documents'].append(runtime.tool(s,{'tool':'issuer_pdf',**d}))
    result['status']='passed' if result['documents'] and result['documents'][0]['evidence_ids'] else 'no_verified_financial_fields'
except Exception as exc:result.update(status='failed',error=runtime.error(exc))
finally:
    from pathlib import Path
    Path('.local/live-public-smoke-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'status':result['status'],'error':result.get('error'),'model_called':False,'financial_fields':sum(len(d.get('evidence_ids',[])) for d in result.get('documents',[]))},ensure_ascii=False))
    store.close()
if result['status']!='passed':raise SystemExit(1)
