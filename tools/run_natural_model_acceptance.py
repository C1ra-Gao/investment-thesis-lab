"""Run only after human says configuration complete and authorizes starting.

At most 14 actual or uncertain LLM transmissions, persisted across restart. No financial execution.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thesislab.agent_runtime import AgentRuntime
from thesislab.live_providers import ProviderSettings,ChatModel,ModelHTTP
from thesislab.model_acceptance import BoundedAcceptanceModel
from thesislab.store import Store

CASES=[
 ('profitability','微软2025年净利润同比增长。'),
 ('valuation','微软估值回落，但2025年基本面没有恶化。'),
 ('comparison','比较微软与苹果2025年的盈利质量，微软的经营现金流与净利润比更高。'),
 ('supply_chain','2025年新能源汽车产业链利润向电池企业转移。'),
 ('macro','美联储降息将提升银行盈利。'),
 ('exploratory','龙头盈利改善是否可持续？'),
]
p=argparse.ArgumentParser()
p.add_argument('--start-authorized',action='store_true',required=True)
p.add_argument('--limit',type=int,default=14)
p.add_argument('--reviewed-scopes',action='store_true',help='Plan existing six cases with explicit acceptance-only scope assumptions')
args=p.parse_args()
settings=ProviderSettings.from_environment()
if not settings.public()['model_configured']:raise SystemExit('Model key not configured; no request sent.')
store=Store('.local/natural-live-acceptance.sqlite');model=BoundedAcceptanceModel(ChatModel(settings,ModelHTTP()),store.engine,limit=args.limit)
runtime=AgentRuntime(store,settings=settings,model=model)
def await_task(id):
    for _ in range(900):
        s=runtime.get(id)
        if s['status']!='running':return s
        time.sleep(.2)
    raise RuntimeError('Model task timeout; check persistent state before any retry.')
results=[]
try:
    previous={'cases':[next(x for x in runtime.list(full=True) if x['statement']==statement and x.get('understanding')) for _,statement in CASES]} if args.reviewed_scopes else None
    for index,(expected,statement) in enumerate(CASES):
        totals=model.totals()
        if totals['actual_requests_sent']+totals['uncertain_transmissions']+totals['pending_or_interrupted_reservations']>=args.limit:break
        if args.reviewed_scopes:
            s=runtime.get(previous['cases'][index]['id'])
            intent=s['understanding']
            scope=[
                '验收假设：微软FY2025对FY2024，US-GAAP合并净利润。',
                '验收假设：微软FY2025对FY2024收入、净利润与经营现金流；估值变化仍须验证，缺少行情数据标为无法验证。',
                '验收假设：各自FY2025，US-GAAP；财年结束日不同必须说明，无法证明同观察窗口则不排名。',
                '验收假设：中国动力电池制造与整车环节，2025对2024，利润份额变化；无聚合数据时无法验证，不以单公司增长替代。',
                '验收假设：美国银行业，2024至2025降息窗口，净利润和净息差；因果与宏观工具缺失必须说明。',
                '验收假设：微软FY2025对FY2024净利润，未来两年持续性单独待验证。',
            ][index]
            intent['assumptions'].append(scope)
            if expected=='exploratory':
                intent['entities']=[{'id':'e1','name':'微软','kind':'company'}]
                intent['time_range']={'label':'FY2025对FY2024及未来两年','year':2025,'period':'annual'}
            answers={c['id']:scope for c in intent['clarifications']}
            intent['clarifications']=[]
            s=runtime.edit(s['id'],{'version':s['version'],'answers':answers,'understanding':intent})
        else:
            s=runtime.create({'statement':statement})
        runtime.launch(s['id'],{'version':s['version'],'action':'launch'});s=await_task(s['id'])
        # Do not automatically answer unanticipated clarifications or launch Execute.
        results.append({'id':s['id'],'expected_type':expected,'status':s['status'],'stage':s['stage'],
            'understanding':s['understanding'],'plan':s['plan'],'error':s['error']})
        if s['status']=='failed' and not args.reviewed_scopes:break
finally:
    result={'mode':'actual_llm_understand_plan_only','financial_requests':0,'deep_research_executed':False,
            'totals':model.totals(),'cases':results}
    Path('.local/natural-live-acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'totals':model.totals(),'case_states':[{k:r[k] for k in ('expected_type','status','stage','error')} for r in results]},ensure_ascii=False))
    for thread in list(runtime.workers.values()):thread.join(5)
    store.close()
if any(r['status']=='failed' for r in results):raise SystemExit(1)
