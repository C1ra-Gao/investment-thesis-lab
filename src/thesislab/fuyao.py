"""Fuyao income contract and offline historical adapter. No transport or credential loader."""
from dataclasses import dataclass,field
from datetime import datetime,date
from decimal import Decimal
import hashlib
import json
import re
import sqlite3
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .financial_tools import FinancialResult,FinancialDatum,ToolState
from .domain import ContractError,amount,encode,Source
from .store import now,evidence_from_dict
from .conflicts import detect

BASE='https://fuyao.aicubes.cn'
PATH='/api/a-share/financials/income-statements'
AUTH_HEADER='X-api-key'
INCOME_FIELDS=('operating_income','operating_costs','operating_expenses','sales_fee','manage_fee',
    'research_and_development_expenses','operating_profit','interest_expenses','profit_total',
    'income_tax_expense','net_profit','parent_holder_net_profit','basic_eps')

def income_parameters(request):
    """2026-10-13 official snapshot contract; caller explicitly selects query mode."""
    if request.operation!='income_statement':raise ContractError('income_operation_required')
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',request.entity):raise ContractError('full_single_a_share_thscode_required')
    if request.period not in ('annual','quarterly'):raise ContractError('invalid_income_period')
    ranged=request.start_ms is not None or request.end_ms is not None
    if ranged:
        if request.limit is not None or type(request.start_ms) is not int or type(request.end_ms) is not int:
            raise ContractError('income_range_requires_start_end_and_no_limit')
        if request.start_ms>request.end_ms:raise ContractError('income_range_not_ordered')
        start=datetime.fromtimestamp(request.start_ms/1000,ZoneInfo('Asia/Shanghai'))
        end=datetime.fromtimestamp(request.end_ms/1000,ZoneInfo('Asia/Shanghai'))
        try:anniversary=start.replace(year=start.year+10)
        except ValueError:anniversary=start.replace(year=start.year+10,day=28)
        if end>anniversary:raise ContractError('income_window_exceeds_ten_years')
        query={'start':request.start_ms,'end':request.end_ms}
    else:
        if type(request.limit) is not int or not 1<=request.limit<=20:raise ContractError('income_limit_outside_1_20')
        query={'limit':request.limit}
    return {'thscode':request.entity,'period':request.period,**query}

def income_wire_contract(request):
    return {'method':'GET','url':BASE+PATH+'?'+urlencode(income_parameters(request)),
        'authentication_header_name':AUTH_HEADER,'credentials_included':False,
        'contract_source':'phase3_official_document_snapshot_2026-10-13','billing':'UNVERIFIED'}


class FuyaoLiveBoundary:
    def fetch(self,request):
        return FinancialResult(request,ToolState.UNAUTHORIZED,'disabled','live_financial_calls_not_authorized_no_credential_read')


@dataclass(frozen=True)
class HistoricalSnapshot:
    body:bytes=field(repr=False)
    sha256:str
    acquired_at:str
    source_url:str
    artifact_id:str
    sources:tuple[dict,...]=field(repr=False)
    artifacts:tuple[dict,...]=field(repr=False)
    evidence:tuple[dict,...]=field(repr=False)
    receipt:dict|None=field(default=None,repr=False)
    input_kind:str='synthetic_mock'

    @classmethod
    def from_database(cls,path,*,receipt=None):
        # Read-only project-local approved snapshot, never open/migrate its Store.
        with sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True) as c:
            sources=tuple(json.loads(r[0]) for r in c.execute('SELECT payload FROM sources'))
            c.row_factory=sqlite3.Row
            artifacts=tuple(dict(r) for r in c.execute('SELECT * FROM artifacts'))
            evidence=tuple(json.loads(r[0]) for r in c.execute('SELECT payload FROM evidence'))
        candidates=[a for a in artifacts if any(s['id']==a['source_id'] and s['kind']=='provider_cache' and s['url']==BASE+PATH for s in sources)]
        if len(candidates)!=1:raise ContractError('unique_fuyao_historical_snapshot_required')
        a=candidates[0]
        if hashlib.sha256(a['body']).hexdigest()!=a['sha256']:raise ContractError('historical_response_integrity_failure')
        return cls(a['body'],a['sha256'],a['acquired_at'],BASE+PATH,a['id'],sources,artifacts,evidence,receipt,'real_historical_response')


class FuyaoHistoricalProvider:
    def __init__(self,snapshot):self.snapshot=snapshot
    def fetch(self,request):
        snap=self.snapshot
        def result(state,reason,records=(),issues=()):
            return FinancialResult(request,state,snap.input_kind,reason,tuple(records),tuple(issues),
                snap.source_url,snap.sha256,snap.acquired_at,now(),snap.receipt.get('parameters') if snap.receipt else None)
        if request.operation!='income_statement':return result(ToolState.UNSUPPORTED,'operation_not_implemented_by_income_adapter')
        if request.consolidation!='consolidated':return result(ToolState.UNSUPPORTED,'income_endpoint_has_no_parent_statement_selector')
        try:query=income_parameters(request)
        except (ValueError,TypeError,OverflowError,OSError):return result(ToolState.CALL_FAILED,'invalid_income_request')
        if hashlib.sha256(snap.body).hexdigest()!=snap.sha256:return result(ToolState.CALL_FAILED,'historical_response_integrity_failure')
        if snap.receipt and (snap.receipt.get('body_complete') is not True or snap.receipt.get('http_status')!=200 or snap.receipt.get('response_sha256')!=snap.sha256):
            return result(ToolState.CALL_FAILED,'historical_receipt_not_complete_or_mismatched')
        try:raw=json.loads(snap.body,parse_float=Decimal)
        except (ValueError,UnicodeError):return result(ToolState.CALL_FAILED,'historical_response_not_complete_json')
        code=raw.get('code')
        if code in (2001,2003):return result(ToolState.UNAUTHORIZED,'historical_authentication_or_permission_denied')
        if code in (3001,3002):return result(ToolState.DATA_MISSING,'historical_provider_no_data')
        if code==3004:return result(ToolState.UNSUPPORTED,'historical_provider_type_not_supported')
        if code!=0:return result(ToolState.CALL_FAILED,'historical_provider_business_error')
        rows=raw.get('data',{}).get('item')
        if not isinstance(rows,list):return result(ToolState.CALL_FAILED,'income_response_schema_invalid')
        selected=[]
        for index,row in enumerate(rows):
            if not isinstance(row,dict):return result(ToolState.CALL_FAILED,'income_row_schema_invalid')
            if row.get('thscode')!=request.entity or row.get('period')!=request.period:continue
            try:
                end=datetime.fromtimestamp(row['period_end_ms']/1000,ZoneInfo('Asia/Shanghai')).date()
                reported=datetime.fromtimestamp(row['report_date_ms']/1000,ZoneInfo('Asia/Shanghai')).date()
                if type(row['period_end_ms']) is not int or type(row['report_date_ms']) is not int:raise ValueError()
            except (KeyError,TypeError,ValueError,OverflowError,OSError):return result(ToolState.CALL_FAILED,'income_date_metadata_invalid')
            if request.start_ms is not None and not request.start_ms<=row['period_end_ms']<=request.end_ms:continue
            selected.append((index,row,end,reported))
        selected.sort(key=lambda x:x[2],reverse=True)
        if request.limit is not None:selected=selected[:request.limit]
        if request.report_ends:selected=[x for x in selected if x[2] in request.report_ends]
        if not selected:return result(ToolState.DATA_MISSING,'no_matching_period_in_historical_snapshot')
        records=[];issues=[]
        if request.report_ends:
            for missing in sorted(set(request.report_ends)-{x[2] for x in selected}):issues.append({'state':'data_missing','report_end':missing.isoformat()})
        for index,row,end,reported in selected:
            for metric in request.metrics:
                pointer=f'/data/item/{index}/{metric}';value=row.get(metric)
                if metric not in INCOME_FIELDS or value is None:
                    issues.append({'state':'field_missing','metric':metric,'report_end':end.isoformat(),'reason':'not_in_income_contract' if metric not in INCOME_FIELDS else 'absent_or_null'})
                    continue
                try:
                    if isinstance(value,str):raise ContractError('income_numeric_field_is_string')
                    numeric=amount(value)
                except ContractError:return result(ToolState.CALL_FAILED,'income_numeric_field_invalid')
                proof=next((e for e in snap.evidence if e['origin']=='provider' and e.get('locator',{}).get('artifact_id')==snap.artifact_id and e['locator'].get('json_pointer')==pointer and e['value']==str(numeric)),None)
                official=None
                if proof:
                    official=next((e for e in snap.evidence if e['origin']=='issuer' and e['scope']==proof['scope'] and e['value']==proof['value']),None)
                verified=proof is not None and official is not None
                records.append(FinancialDatum(request.entity,metric,pointer,end,str(numeric),row.get('currency','unknown'),
                    'yuan_per_share' if metric=='basic_eps' else 'yuan',reported,row.get('fiscal_period','unknown'),
                    date.fromisoformat(proof['scope']['start']) if verified else None,proof['scope']['basis'] if verified else 'unknown',
                    'consolidated','verified' if verified else 'partial',proof['id'] if verified else None,
                    official['id'] if verified else None,date.fromisoformat(official['issuer_disclosure_date']) if verified else None,
                    'previous_official_cell_crosscheck_requires_revalidation_on_admission' if verified else 'flow_basis_and_original_report_unverified'))
        state=ToolState.FIELD_MISSING if any(x['state']=='field_missing' for x in issues) else ToolState.DATA_MISSING if issues else ToolState.AVAILABLE
        return result(state,'historical_local_projection_not_new_api_response',records,issues)

    def admit(self,result,store):
        """Recheck original bytes/locations in M1 before reusing historical trust."""
        snap=self.snapshot
        if result.raw_sha256!=snap.sha256 or result.mode!='real_historical_response':raise ContractError('historical_admission_source_mismatch')
        ids={r.evidence_id for r in result.records if r.evidence_id}|{r.issuer_evidence_id for r in result.records if r.issuer_evidence_id}
        payloads=[e for e in snap.evidence if e['id'] in ids]
        artifact_ids={e['locator']['artifact_id'] for e in payloads}
        # Disclosure-date locators must retain their original index artifact too.
        for source in snap.sources:
            if source['id'] in {a['source_id'] for a in snap.artifacts if a['id'] in artifact_ids} and source.get('disclosure_locator'):
                proof=json.loads(source['disclosure_locator'])
                index=next(a for a in snap.artifacts if a['id']==proof['artifact_id'])
                from .regression import _check_index
                _check_index(index['body'],source['url'],source['disclosed_on'])
                artifact_ids.add(index['id'])
        artifacts=[a for a in snap.artifacts if a['id'] in artifact_ids]
        for source in snap.sources:
            if source['id'] in {a['source_id'] for a in artifacts}:
                d=dict(source)
                if d.get('disclosed_on'):d['disclosed_on']=date.fromisoformat(d['disclosed_on'])
                store.put_source(Source(**d))
        for a in artifacts:
            if hashlib.sha256(a['body']).hexdigest()!=a['sha256']:raise ContractError('historical_artifact_integrity_failure')
            store.put_artifact(a['source_id'],a['body'],a['media_type'],a['acquired_at'],a['local_reference'])
        for e in payloads:store.put_evidence(evidence_from_dict(e))
        for r in result.records:
            if r.evidence_id and r.issuer_evidence_id:
                store.put_crosscheck(r.evidence_id,r.issuer_evidence_id)
                for conflict in detect(store.evidence(r.evidence_id),store.evidence(r.issuer_evidence_id)):store.put_conflict(conflict)
        return [r.evidence_id for r in result.records if r.evidence_id]
