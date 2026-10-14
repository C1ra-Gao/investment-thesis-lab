"""Explicit live acquisitions; no historical response fallback or credential logging."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import threading
import time
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from .domain import ContractError, Source, Scope, Evidence, Locator, Basis, Verification, identifier
from .store import now
from .online_transport import _PinnedHTTPS
from .fuyao import income_wire_contract, FuyaoHistoricalProvider, HistoricalSnapshot
from .financial_tools import FinancialRequest

MODEL_ENDPOINTS = {
    'deepseek': 'https://api.deepseek.com/chat/completions',
    'openai': 'https://api.openai.com/v1/chat/completions',
    'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
}
MODEL_DEFAULTS = {'deepseek':'deepseek-chat','openai':'gpt-4.1-mini','qwen':'qwen-plus'}
SEC_TAGS = {
    'operating_income': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'),
    'operating_costs': ('CostOfRevenue', 'CostOfGoodsAndServicesSold'),
    'net_profit': ('NetIncomeLoss',),
    'operating_profit': ('OperatingIncomeLoss',),
    'operating_cash_flow': ('NetCashProvidedByUsedInOperatingActivities',),
}


class LiveHTTP:
    """Public-global DNS pinning, TLS verification, no redirects/retries, bounded bodies."""
    def __init__(self):
        self.lock = threading.Lock()
        self.last = 0.0

    def request(self, url, *, headers=None, body=None, max_bytes=20_000_000):
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443) or p.fragment:
            raise ContractError('https_url_required')
        if any(x in p.query.lower() for x in ('token=', 'api_key', 'apikey', 'password', 'signature=')):
            raise ContractError('credential_query_forbidden')
        addresses = {x[4][0] for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
            raise ContractError('private_network_source_forbidden')
        # Less than 2 req/sec per process, including SEC's documented fair access.
        with self.lock:
            time.sleep(max(0, .6 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
        c = _PinnedHTTPS(p.hostname, sorted(addresses)[0], 60)
        try:
            c.request('POST' if body is not None else 'GET', p.path + ('?' + p.query if p.query else ''), body=body,
                      headers={'Accept-Encoding':'identity', **(headers or {})})
            r = c.getresponse()
            data = r.read(max_bytes + 1)
            if len(data)>max_bytes: raise ContractError('response_too_large')
            if r.getheader('Content-Length') and int(r.getheader('Content-Length')) != len(data):
                raise ContractError('incomplete_response')
            if r.status != 200: raise ContractError('upstream_http_'+str(r.status))
            return data
        except ContractError: raise
        except Exception as exc: raise ContractError('transport_'+type(exc).__name__) from None
        finally: c.close()


class ProviderSettings:
    """Server-only environment configuration; user consent is separate from keys."""
    def __init__(self):
        self.lock = threading.RLock()
        self.values = {'provider':'deepseek','model':'deepseek-chat','model_key':'','financial_key':'',
                       'financial_provider':'fuyao','sec_contact':'','public_enabled':False,'public_allowed':True}

    @classmethod
    def from_environment(cls, path='.env', *, environ=None):
        from .environment import read_environment,boolean
        env=read_environment(path,environ=environ);settings=cls()
        provider=env.get('THESISLAB_LLM_PROVIDER','deepseek')
        if provider not in MODEL_ENDPOINTS:raise ContractError('unsupported_environment_model_provider')
        financial_provider=env.get('THESISLAB_FINANCIAL_PROVIDER','fuyao')
        if financial_provider not in ('fuyao','none'):raise ContractError('unsupported_environment_financial_provider')
        settings.configure({'provider':provider,'model':env.get('THESISLAB_LLM_MODEL') or MODEL_DEFAULTS[provider],
            'model_key':env.get('THESISLAB_LLM_API_KEY',''),'financial_key':env.get('THESISLAB_FINANCIAL_API_KEY',''),
            'sec_contact':env.get('THESISLAB_SEC_CONTACT','')})
        settings.values.update(financial_provider=financial_provider,
            public_allowed=boolean(env.get('THESISLAB_ALLOW_PUBLIC_DISCLOSURES'),False))
        return settings

    def consent(self, enabled):
        if type(enabled) is not bool:raise ContractError('invalid_public_consent')
        with self.lock:
            if enabled and not self.values['public_allowed']:raise ContractError('public_disclosures_disabled_in_env')
            self.values['public_enabled']=enabled
            return self.public()

    def configure(self, body):
        with self.lock:
            provider=body.get('provider',self.values['provider'])
            if provider not in MODEL_ENDPOINTS: raise ContractError('unsupported_model_provider')
            for k in ('model_key','financial_key','sec_contact','model'):
                value=body.get(k)
                if value is not None and (not isinstance(value,str) or len(value)>512 or '\n' in value or '\r' in value):
                    raise ContractError('invalid_setting')
            if provider != self.values['provider']:
                self.values['model_key']=''
                self.values['model']=MODEL_DEFAULTS[provider]
            self.values['provider']=provider
            for k in ('model','model_key','financial_key','sec_contact'):
                if body.get(k): self.values[k]=body[k].strip()
            if body.get('clear_keys') is True:
                self.values['model_key']=''; self.values['financial_key']=''
            if 'public_enabled' in body:
                if type(body['public_enabled']) is not bool: raise ContractError('invalid_public_permission')
                self.values['public_enabled']=body['public_enabled']
            return self.public()

    def public(self):
        with self.lock:
            return {k:v for k,v in self.values.items() if not k.endswith('_key') and k!='sec_contact'} | {
                'model_configured':bool(self.values['model_key']),
                'financial_configured':bool(self.values['financial_key']),
                'sec_contact_configured':bool(self.values['sec_contact']),
                'configuration_source':'server_environment', 'providers':list(MODEL_ENDPOINTS),
                'connection_status':'configured_not_tested' if self.values['model_key'] else 'not_configured'}

    def snapshot(self):
        with self.lock: return dict(self.values)


class ChatModel:
    def __init__(self, settings, http): self.settings=settings; self.http=http
    def json(self, system, payload):
        s=self.settings.snapshot()
        if not s['model_key']: raise ContractError('configure_model_key_first')
        body=json.dumps({'model':s['model'],'messages':[{'role':'system','content':system},
             {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
             'response_format':{'type':'json_object'},'temperature':0,'max_tokens':5000},ensure_ascii=False).encode()
        raw=self.http.request(MODEL_ENDPOINTS[s['provider']],headers={
             'Authorization':'Bearer '+s['model_key'],'Content-Type':'application/json'},body=body,max_bytes=500_000)
        try:
            result=json.loads(raw)['choices'][0]['message']['content']
            def unique(pairs):
                d={}
                for k,v in pairs:
                    if k in d: raise ValueError('duplicate_key')
                    d[k]=v
                return d
            d=json.loads(result,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(d,dict): raise ValueError()
            # Never retain provider completions containing a configured credential.
            text=json.dumps(d)
            if any(s[k] and s[k] in text for k in ('model_key','financial_key')): raise ValueError()
            return d
        except (KeyError,ValueError,TypeError,IndexError): raise ContractError('invalid_model_json') from None


class LiveFinancial:
    def __init__(self, settings, http, store): self.settings=settings; self.http=http; self.store=store
    def fetch(self, entity, metrics):
        settings=self.settings.snapshot();key=settings['financial_key']
        if settings['financial_provider']!='fuyao':raise ContractError('financial_provider_disabled_in_env')
        if not key: raise ContractError('authorized_financial_key_required')
        request=FinancialRequest(entity,tuple(metrics),limit=20)
        wire=income_wire_contract(request)
        body=self.http.request(wire['url'],headers={'X-api-key':key,'Accept':'application/json'})
        acquired=now(); sha=hashlib.sha256(body).hexdigest()
        # Reuse M4's exact schema parser, explicitly reclassify a NEW acquisition.
        snapshot=HistoricalSnapshot(body,sha,acquired,wire['url'],'',(),(),(),input_kind='live_fuyao')
        result=FuyaoHistoricalProvider(snapshot).fetch(request)
        if not result.records: raise ContractError('fuyao_'+result.reason)
        source=Source(identifier('live-fuyao',{'url':wire['url'],'at':acquired}),'同花顺扶摇实时查询',wire['url'],
                      'provider_cache',rights='user_authorized_private_research_no_redistribution')
        self.store.put_source(source)
        artifact=self.store.put_artifact(source.id,body,'application/json',acquired)
        ids=[]
        for record in result.records:
            scope=Scope(entity,record.metric,record.report_end,record.report_end,record.currency,record.unit,
                        'consolidated',Basis.UNKNOWN)
            evidence=Evidence(identifier('live-fuyao-field',{'artifact':artifact,'pointer':record.raw_pointer}),
                      scope,Decimal(record.value),Verification.PARTIAL,'provider',Locator(artifact,json_pointer=record.raw_pointer),
                      provider_report_date=record.provider_report_date,reported_period_label=record.period_label,
                      limitation='Live API value/metadata checked; flow basis requires original report crosscheck.')
            self.store.put_evidence(evidence); ids.append(evidence.id)
        return {'evidence_ids':ids,'source_url':wire['url'],'acquired_at':acquired,'issues':list(result.issues),
                'mode':'live_fuyao','scope_warning':'unknown_flow_basis_not_admitted_to_calculations'}


def validate_sec_field(raw, pointer, scope, disclosed):
    """Raw CompanyFacts metadata admission, shared with Store validation."""
    parts=pointer.split('/')[1:]
    if len(parts)!=7 or parts[:2]!=['facts','us-gaap'] or parts[3:5]!=['units','USD'] or parts[-1]!='val':
        raise ContractError('invalid_sec_locator')
    tag=parts[2]
    if tag not in SEC_TAGS.get(scope.metric,()): raise ContractError('sec_metric_tag_mismatch')
    row=raw['facts']['us-gaap'][tag]['units']['USD'][int(parts[5])]
    if type(row.get('val')) not in (int, float, Decimal) or not Decimal(str(row['val'])).is_finite():
        raise ContractError('sec_numeric_field_invalid')
    if (scope.entity!='CIK'+str(raw['cik']).zfill(10) or scope.start.isoformat()!=row.get('start')
        or scope.end.isoformat()!=row.get('end') or disclosed.isoformat()!=row.get('filed')
        or scope.currency!='USD' or scope.unit!='usd' or scope.accounting!='US_GAAP'
        or scope.consolidation!='consolidated' or row.get('form') not in ('10-K','10-Q')
        or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',row.get('accn',''))):
        raise ContractError('sec_metadata_mismatch')
    days=(scope.end-scope.start).days+1
    if scope.basis!=Basis.YTD or not 330<=days<=380:
        raise ContractError('sec_mvp_requires_annual_flow')


class SECFinancial:
    def __init__(self,settings,http,store): self.settings=settings; self.http=http; self.store=store
    def fetch(self,entity,metrics,year):
        s=self.settings.snapshot()
        if not s['public_enabled']: raise ContractError('public_retrieval_not_enabled')
        if not s['sec_contact'] or '@' not in s['sec_contact']: raise ContractError('sec_contact_email_required')
        if not re.fullmatch(r'CIK\d{10}',entity): raise ContractError('sec_cik_required')
        url='https://data.sec.gov/api/xbrl/companyfacts/'+entity+'.json'
        body=self.http.request(url,headers={'User-Agent':'ThesisLab/1.0 '+s['sec_contact'],'Accept':'application/json'})
        raw=json.loads(body,parse_float=Decimal)
        if str(raw.get('cik')).zfill(10)!=entity[3:]: raise ContractError('sec_company_mismatch')
        acquired=now(); ids=[]; gaps=[]; filings=set()
        for metric in metrics:
            count=0
            for tag in SEC_TAGS.get(metric,()):
                rows=raw.get('facts',{}).get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[])
                for index,row in enumerate(rows):
                    if row.get('form') not in ('10-K','10-Q') or not row.get('start'): continue
                    start=date.fromisoformat(row['start']); end=date.fromisoformat(row['end'])
                    if end.year not in (year,year-1) or not 330<=(end-start).days+1<=380: continue
                    filed=date.fromisoformat(row['filed'])
                    pointer=f'/facts/us-gaap/{tag}/units/USD/{index}/val'
                    scope=Scope(entity,metric,start,end,'USD','usd','consolidated',Basis.YTD,accounting='US_GAAP')
                    validate_sec_field(raw,pointer,scope,filed)
                    source=Source(identifier('sec-facts-source',{'url':url,'at':acquired,'filed':row['filed']}),
                        str(raw.get('entityName',entity))+' SEC CompanyFacts',url,'sec_xbrl',
                        rights='public_SEC_companyfacts_private_research',disclosed_on=filed,disclosure_locator=pointer.rsplit('/',1)[0]+'/filed')
                    self.store.put_source(source)
                    artifact=self.store.put_artifact(source.id,body,'application/json',acquired)
                    evidence=Evidence(identifier('sec-field',{'artifact':artifact,'pointer':pointer}),scope,
                        Decimal(str(row['val'])),Verification.VERIFIED,'issuer',Locator(artifact,json_pointer=pointer),
                        issuer_disclosure_date=filed,limitation='SEC entity-wide US-GAAP XBRL; all filing vintages retained, not independent audit.')
                    self.store.put_evidence(evidence);ids.append(evidence.id); count+=1
                    filings.add('https://www.sec.gov/Archives/edgar/data/'+str(int(entity[3:]))+'/'+row['accn'].replace('-','')+'/'+row['accn']+'-index.html')
            if not count:gaps.append({'metric':metric,'reason':'annual_us_gaap_tag_missing'})
        return {'evidence_ids':ids,'source_url':url,'acquired_at':acquired,'issues':gaps,
                'original_filings':sorted(filings),'mode':'live_sec_xbrl'}
