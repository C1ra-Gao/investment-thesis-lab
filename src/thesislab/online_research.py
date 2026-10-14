"""Task-driven issuer research; raw disclosures precede facts and human-approved rules."""
from copy import deepcopy
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin
import calendar
import io
import re
from uuid import uuid4

from .domain import Source, Scope, Basis, Evidence, Locator, Verification, ContractError, encode, identifier
from .locators import pdf_value,verify_pdf_scope
from .finance import gross_margin,yoy,margin_delta
from .conflicts import detect
from .store import now
from .orchestrator import Orchestrator
from .workspace import RevisionConflict

ISSUERS={'600519.SH':{'name':'贵州茅台','index':'https://www.moutaichina.com/mtgf/tzzgx/cwbg/index.html','hosts':['www.moutaichina.com']}}
METRICS={'operating_income':('其中：营业收入','营业收入'),
         'operating_costs':('其中：营业成本','营业成本'),
         'net_profit':('四、净利润','四、净利润（净亏损以“－”号填列）','五、净利润','五、净利润（净亏损以“－”号填列）'),
         'operating_profit':('三、营业利润','三、营业利润（亏损以“－”号填列）'),
         'parent_holder_net_profit':('归属于母公司所有者的净利润','归属于母公司股东的净利润'),
         'investment_income':('投资收益（损失以“－”号填列）',)}
normalize=lambda s:re.sub(r'\s+','',s or '')


class DisclosureIndex(HTMLParser):
    def __init__(self,base):super().__init__();self.base=base;self.entries=[];self.item=None;self.anchor=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='li':self.item={'text':[],'links':[],'date_text':[]}
        if self.item is not None and tag=='a':self.anchor={'url':urljoin(self.base,a.get('href','')),'title':a.get('title',''),'text':[]}
        if self.item is not None and tag=='span':self.in_date=True
    def handle_data(self,data):
        if self.item is not None:
            self.item['text'].append(data)
            if getattr(self,'in_date',False):self.item['date_text'].append(data)
        if self.anchor is not None:self.anchor['text'].append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor is not None and self.item is not None:
            self.anchor['title']=self.anchor['title'] or ''.join(self.anchor['text']).strip();self.item['links'].append(self.anchor);self.anchor=None
        if tag=='span':self.in_date=False
        if tag=='li' and self.item is not None:
            day=''.join(self.item['date_text']).strip()
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
                for a in self.item['links']:
                    if a['url'].split('?')[0].lower().endswith('.pdf'):
                        self.entries.append({'title':a['title'],'url':a['url'],'disclosed_on':day,'date_locator':'li span: '+day,'index_context':''.join(self.item['text']).strip()})
            self.item=None;self.in_date=False


def extract_financial_fields(store,body,artifact_id,*,entity,disclosed_on):
    """Only unambiguous M1-supported CNY/yuan consolidated actual YTD cells admitted."""
    import pdfplumber
    admitted=[];gaps=[]
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        if len(pdf.pages)>250:raise ContractError('pdf_page_limit_exceeded')
        for page_number,page in enumerate(pdf.pages,1):
            text=normalize(page.extract_text())
            if '合并利润表' not in text:continue
            periods=re.findall(r'(\d{4})年(\d{1,2})[—－\-–至](\d{1,2})月',text)
            annual_years=re.findall(r'(\d{4})年度',text)
            if not periods and not annual_years:continue
            end_month=int(periods[0][2]) if periods else 12
            begin_month=int(periods[0][1]) if periods else 1
            if begin_month!=1:continue
            for table in page.extract_tables():
                header=next((r for r in table if r and normalize(r[0])=='项目'),None)
                if not header:continue
                for index,column in enumerate(header[1:],1):
                    m=re.match(r'(\d{4})年',normalize(column))
                    if not m:continue
                    year=int(m.group(1));start=date(year,1,1);end=date(year,end_month,calendar.monthrange(year,end_month)[1])
                    for row in table:
                        if not row:continue
                        for metric,aliases in METRICS.items():
                            if normalize(row[0]) not in map(normalize,aliases):continue
                            locator=Locator(artifact_id,page=page_number,table='合并利润表',row=row[0],column=column)
                            scope=Scope(entity,metric,start,end,'CNY','yuan','consolidated',Basis.YTD)
                            try:
                                verify_pdf_scope(body,locator,scope);value=pdf_value(body,locator)
                                e=Evidence(identifier('online-field',{'locator':locator,'scope':scope}),scope,value,Verification.VERIFIED,'issuer',locator,
                                    issuer_disclosure_date=date.fromisoformat(disclosed_on),raw_lexeme=row[index],
                                    limitation='Original PDF cell verified; current disclosure vintage, not historical PIT.')
                                store.put_evidence(e);admitted.append(e.id)
                            except (ContractError,ValueError) as exc:gaps.append({'metric':metric,'page':page_number,'reason':str(exc)})
    return {'evidence_ids':sorted(set(admitted)),'gaps':gaps}


def numeric_rule(claim):
    if claim['kind']!='fact' or claim['rule']!='atomic':return None
    text=claim['statement']
    if '收入' in text and any(x in text for x in ('增长','增加')):
        return ('operating_income_yoy','le' if '未增长' in text else 'gt')
    if '毛利率' in text:
        if '未改善' in text or '没有改善' in text:return ('gross_margin_change','le')
        if '下降' in text:return ('gross_margin_change','lt')
        if '改善' in text or '上升' in text:return ('gross_margin_change','gt')
    return None


class OnlineResearch:
    def __init__(self,workspace,transport):self.ws=workspace;self.transport=transport
    def checked(self,task_id,version):return Orchestrator(self.ws)._checked(task_id,version)
    def start(self,task_id,version,*,entity,year,period,as_of,consent):
        if consent is not True:raise ContractError('explicit_public_retrieval_consent_required')
        if entity not in ISSUERS:raise ContractError('issuer_source_not_configured')
        if type(year) is not int or not 2000<=year<=date.today().year or period not in ('H1','Q1'):
            raise ContractError('unsupported_research_period')
        date.fromisoformat(as_of)
        with self.ws.lock:
            s=self.checked(task_id,version)
            if s.get('online') and s['online']['status'] in ('running','paused','awaiting_rule_review'):
                raise ContractError('existing_online_execution_requires_resume_or_review')
            jobs=[{'id':'index','role':'Evidence Retrieval','tool':'issuer_index','depends_on':[],'status':'pending','attempts':0}]
            for t in s['design']['tasks']:
                jobs.append({'id':'task-'+t['id'],'task_id':t['id'],'claim_id':t['claim_id'],'purpose':t['purpose'],
                    'role':'Counter-Evidence' if t['purpose'] in ('refute','discriminate') else 'Evidence Retrieval',
                    'tool':'issuer_search','query':t['action']+' '+t['source_requirement'],'depends_on':['index'],'status':'pending','attempts':0})
            s['online']={'id':uuid4().hex,'status':'running','entity':entity,'year':year,'period':period,'as_of':as_of,
                'confirmation_id':s['confirmed_id'],'design_hash':encode(s['design']),'started_at':now(),
                'jobs':jobs,'documents':[],'evidence_ids':[],'proposed_rules':[],'gaps':[],
                'input_mode':'live_public_disclosures','model_mode':s['candidate_source']}
            return self.ws.save(s,version,'online_started')
    def control(self,task_id,version,action):
        with self.ws.lock:
            s=self.checked(task_id,version);o=s.get('online')
            if not o or o['status']!=('running' if action=='pause' else 'paused'):raise ContractError('online_control_state_invalid')
            o['status']='paused' if action=='pause' else 'running';return self.ws.save(s,version,'online_'+action)
    def step(self,task_id,version):
        with self.ws.lock:
            s=self.checked(task_id,version);o=s.get('online')
            if not o or o['status']!='running':raise ContractError('online_not_running')
            if o['confirmation_id']!=s['confirmed_id'] or o['design_hash']!=encode(s['design']):raise ContractError('online_plan_changed')
            if any(j['status']=='running' for j in o['jobs']):
                o['status']='failed';o['gaps'].append('interrupted_online_request_requires_review')
                return self.ws.save(s,version,'online_interrupted')
            done={j['id'] for j in o['jobs'] if j['status'] in ('completed','completed_with_gaps')}
            job=next((j for j in o['jobs'] if j['status']=='pending' and set(j['depends_on'])<=done),None)
            if job is None:return self._finalize(s)
            job.update(status='running',attempts=job['attempts']+1,started_at=now())
            s=self.ws.save(s,version,'online_tool_started');o=s['online'];job=next(j for j in o['jobs'] if j['id']==job['id'])
            try:
                if job['tool']=='issuer_index':
                    url=ISSUERS[o['entity']]['index'];r=self.transport.get(url)
                    if r.status!=200:raise ContractError('issuer_index_http_'+str(r.status))
                    parser=DisclosureIndex(r.url);parser.feed(r.body.decode('utf-8'))
                    source=Source(identifier('online-source',{'url':r.url,'at':r.acquired_at}),ISSUERS[o['entity']]['name']+'披露目录',r.url,'issuer_index')
                    self.ws.store.put_source(source);artifact=self.ws.store.put_artifact(source.id,r.body,'text/html',r.acquired_at)
                    o['index_artifact']=artifact;o['index_entries']=parser.entries
                    job['output']={'source_url':r.url,'acquired_at':r.acquired_at,'entry_count':len(parser.entries),'request_id':r.request_id,'artifact_id':artifact}
                elif job['tool']=='issuer_search':
                    title='半年度报告' if o['period']=='H1' else '第一季度报告'
                    found=[x for x in o['index_entries'] if title in x['title'] and '摘要' not in x['title'] and str(o['year']) in x['title']]
                    job['output']={'query':job['query'],'purpose':job['purpose'],'matches':found,
                        'index_artifact':o['index_artifact'],'cache_hit':True,'network_requests':0,
                        'limitation':'Issuer-index search only; no claim of web-wide search or identified causality.'}
                    if not found:
                        o['gaps'].append({'task_id':job['task_id'],'reason':'no_issuer_report_for_confirmed_period'})
                    for x in found[:1]:
                        if not any(d['url']==x['url'] for d in o['documents']):
                            d={**x,'id':'document-'+uuid4().hex};o['documents'].append(d)
                            o['jobs'].append({'id':d['id'],'role':'Evidence Verification','tool':'issuer_pdf',
                                'document_id':d['id'],'depends_on':[job['id']],'status':'pending','attempts':0})
                    if job['purpose']=='discriminate':
                        o['gaps'].append({'task_id':job['task_id'],'reason':'Attribution needs recurring/nonrecurring profit bridge; income growth alone is insufficient.'})
                else:
                    d=next(x for x in o['documents'] if x['id']==job['document_id']);r=self.transport.get(d['url'])
                    if r.status!=200:raise ContractError('issuer_pdf_http_'+str(r.status))
                    if not r.body.startswith(b'%PDF-'):raise ContractError('issuer_response_not_pdf')
                    source=Source(identifier('online-source',{'url':r.url,'at':r.acquired_at}),d['title'],r.url,'issuer_report',
                        disclosed_on=date.fromisoformat(d['disclosed_on']),disclosure_locator=o['index_artifact']+' '+d['date_locator'])
                    self.ws.store.put_source(source);artifact=self.ws.store.put_artifact(source.id,r.body,'application/pdf',r.acquired_at)
                    result=extract_financial_fields(self.ws.store,r.body,artifact,entity=o['entity'],disclosed_on=d['disclosed_on'])
                    o['evidence_ids']+=result['evidence_ids'];o['gaps']+=result['gaps'];d.update(artifact_id=artifact,acquired_at=r.acquired_at)
                    job['output']={'source_url':r.url,'request_id':r.request_id,**result,'disclosed_on':d['disclosed_on'],'artifact_id':artifact}
                job.update(status='completed_with_gaps' if job.get('output',{}).get('gaps') or job['tool']=='issuer_search' and not job['output']['matches'] else 'completed',finished_at=now())
                return self.ws.save(s,s['version'],'online_tool_finished')
            except Exception as exc:
                job.update(status='failed',finished_at=now(),error=str(exc) if isinstance(exc,ContractError) else type(exc).__name__)
                o['status']='failed';return self.ws.save(s,s['version'],'online_tool_failed')
    def _finalize(self,s):
        o=s['online'];raw=[self.ws.store.evidence(i) for i in set(o['evidence_ids'])]
        for i,left in enumerate(raw):
            for right in raw[i+1:]:
                if left.scope.entity==right.scope.entity and left.scope.metric==right.scope.metric and left.scope.start==right.scope.start and left.scope.end==right.scope.end:
                    for c in detect(left,right):self.ws.store.put_conflict(c)
        outputs={};month=6 if o['period']=='H1' else 3
        def find(year,metric):
            choices=[e for e in raw if e.scope.end.year==year and e.scope.end.month==month and e.scope.metric==metric]
            return choices[0] if len(choices)==1 else None
        a,b=find(o['year'],'operating_income'),find(o['year']-1,'operating_income')
        c,d=find(o['year'],'operating_costs'),find(o['year']-1,'operating_costs')
        if all(x is not None for x in (a,b,c,d)):
            ga,gb=gross_margin(a,c),gross_margin(b,d)
            for calc in (ga,gb):self.ws.store.put_calculation(calc)
            for metric,calc in (('operating_income_yoy',yoy(a,b)),('gross_margin_change',margin_delta(ga.result,gb.result))):
                self.ws.store.put_calculation(calc);outputs[metric]=calc.result.id
        else:o['gaps'].append('aligned_income_cost_prior_period_fields_missing')
        for claim in s['design']['claims']:
            rule=numeric_rule(claim)
            if rule and rule[0] in outputs:
                e=self.ws.store.evidence(outputs[rule[0]])
                o['proposed_rules'].append({'claim_id':claim['id'],'evidence_id':e.id,'predicate':{'scope':__import__('json').loads(encode(e.scope)),'operator':rule[1],'threshold':'0'},
                    'description':claim['statement']+'；按已取得同期间字段计算，比较零值。','origin':'deterministic_rule_proposal_requires_human_review'})
        o['derived_ids']=list(outputs.values());o['status']='awaiting_rule_review'
        return self.ws.save(s,s['version'],'online_evidence_ready_for_review')
    def accept_rules(self,task_id,version,*,accepted,notes):
        with self.ws.lock:
            s=self.checked(task_id,version);o=s.get('online')
            if not o or o['status']!='awaiting_rule_review' or accepted is not True:raise ContractError('numeric_rule_review_required')
            design=deepcopy(s['design']);bindings={}
            for rule in o['proposed_rules']:
                next(c for c in design['claims'] if c['id']==rule['claim_id'])['predicate']=rule['predicate']
                for t in design['tasks']:
                    if t['claim_id']==rule['claim_id']:bindings[t['id']]={'evidence_id':rule['evidence_id']}
            s=self.ws.edit(task_id,version,design,bindings,reason='User explicitly accepts source-linked deterministic rules')
            suggestions=[c['id'] for c in design['claims'] if c['origin']=='suggestion']
            s=self.ws.confirm(task_id,s['version'],reviewer=self.ws.owner,notes=notes,accepted_suggestions=suggestions,meaning_reviewed=True)
            s=self.ws.run(task_id,s['version'],as_of=o['as_of']);r=self.ws.engine.get(s['run_id'])
            o['status']='completed';o['finished_at']=now();s['online']=o
            s['report']={'statement':s['statement'],'run_id':s['run_id'],'confirmation_id':s['confirmed_id'],'created_at':now(),
                'mode':'online_verified_source_report','conclusion':r['conclusion'],'claims':r['claims'],'tasks':r['tasks'],
                'claim_statements':{c['id']:c['statement'] for c in design['claims']},'change_conditions':design['conditions'],
                'evidence_ids':r['conclusion']['evidence_dependencies'],'online_documents':o['documents'],
                'limitations':['公开发行人披露检索；不是全网搜索。','抽取范围有限；归因、因果及预测缺口不得用财务相关性补齐。',*o['gaps']],
                'conflict_ids':[x['conflict']['id'] for x in self.ws.conflicts() if {x['conflict']['left_id'],x['conflict']['right_id']}&set(o['evidence_ids'])]}
            return self.ws.save(s,s['version'],'online_report_generated')
