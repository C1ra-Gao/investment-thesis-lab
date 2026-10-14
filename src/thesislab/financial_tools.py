"""Provider-neutral financial requests. Acquisition, origin and verification stay separate."""
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol
from uuid import uuid4
from .domain import ContractError, require_text


class ToolState(StrEnum):
    AVAILABLE='available'
    UNAUTHORIZED='unauthorized'
    NOT_CONNECTED='not_connected'
    FIELD_MISSING='field_missing'
    DATA_MISSING='data_missing'
    CALL_FAILED='call_failed'
    UNSUPPORTED='unsupported'


@dataclass(frozen=True)
class FinancialRequest:
    entity:str
    metrics:tuple[str,...]
    report_ends:tuple[date,...]=()
    provider:str='fuyao'
    operation:str='income_statement'
    period:str='quarterly'
    limit:int|None=6
    start_ms:int|None=None
    end_ms:int|None=None
    consolidation:str='consolidated'
    request_id:str=field(default_factory=lambda:'financial-'+uuid4().hex)

    def __post_init__(self):
        require_text(self.entity,'financial_entity')
        if not isinstance(self.metrics,tuple) or not self.metrics or any(not isinstance(m,str) or not m.strip() for m in self.metrics):
            raise ContractError('financial_metrics_required')
        if not isinstance(self.report_ends,tuple) or any(type(d) is not date for d in self.report_ends):
            raise ContractError('invalid_financial_report_dates')
        if len(set(self.metrics))!=len(self.metrics):raise ContractError('duplicate_financial_metric')

    @classmethod
    def from_dict(cls,value):
        d=dict(value);d['metrics']=tuple(d['metrics']);d['report_ends']=tuple(date.fromisoformat(x) for x in d.get('report_ends',()))
        return cls(**d)


@dataclass(frozen=True)
class FinancialDatum:
    entity:str
    metric:str
    raw_pointer:str
    report_end:date
    value:str|None
    currency:str
    unit:str
    provider_report_date:date
    period_label:str
    start:date|None=None
    basis:str='unknown'
    consolidation:str='consolidated'
    verification:str='partial'
    evidence_id:str|None=None
    issuer_evidence_id:str|None=None
    issuer_disclosure_date:date|None=None
    reason:str='provider_return_not_independently_verified'


@dataclass(frozen=True)
class FinancialResult:
    request:FinancialRequest
    state:ToolState
    mode:str
    reason:str
    records:tuple[FinancialDatum,...]=()
    issues:tuple[dict,...]=()
    source_url:str|None=None
    raw_sha256:str|None=None
    original_acquired_at:str|None=None
    adapted_at:str|None=None
    historical_parameters:dict|None=None
    external_requests:int=0

    def audit_summary(self):
        # Actual amounts and supplier bodies remain private evidence, not audit prose.
        return {'request':self.request,'state':self.state,'mode':self.mode,'reason':self.reason,
            'field_count':len(self.records),'issues':self.issues,'source_url':self.source_url,
            'raw_sha256':self.raw_sha256,'original_acquired_at':self.original_acquired_at,
            'adapted_at':self.adapted_at,'historical_parameters':self.historical_parameters,
            'evidence_ids':[r.evidence_id for r in self.records if r.evidence_id],
            'issuer_evidence_ids':[r.issuer_evidence_id for r in self.records if r.issuer_evidence_id],
            'external_requests':self.external_requests}


class FinancialProvider(Protocol):
    def fetch(self,request:FinancialRequest)->FinancialResult:...


class IFinDMCPBoundary:
    """Independent connection boundary. No invented MCP URL, tools or capability list."""
    def fetch(self,request):
        return FinancialResult(request,ToolState.NOT_CONNECTED,'disabled','ifind_tool_schema_and_account_permission_unverified')


class FinancialTools:
    def __init__(self,providers):self.providers=dict(providers)
    def fetch(self,request):
        provider=self.providers.get(request.provider)
        if provider is None:return FinancialResult(request,ToolState.UNSUPPORTED,'disabled','provider_adapter_not_registered')
        try:return provider.fetch(request)
        except Exception as exc:
            # No raw exceptions from suppliers or credential sources enter audit/UI.
            return FinancialResult(request,ToolState.CALL_FAILED,'disabled',type(exc).__name__)

    def admit(self,result,store):
        provider=self.providers.get(result.request.provider)
        if not hasattr(provider,'admit'):return []
        return provider.admit(result,store)
