"""M4 mock protocol tests and explicitly project-local REAL historical regression."""
from dataclasses import replace
from datetime import date
import hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from thesislab.cli import PROJECT_ROOT
from thesislab.domain import ContractError,encode
from thesislab.financial_tools import FinancialRequest,FinancialTools,IFinDMCPBoundary,ToolState
from thesislab.fuyao import HistoricalSnapshot,FuyaoHistoricalProvider,FuyaoLiveBoundary,income_parameters,income_wire_contract,BASE,PATH
from thesislab.store import Store
from thesislab.workspace import Workspace,financial_design
from thesislab.orchestrator import Orchestrator

class FinancialContractTests(unittest.TestCase):
    def request(self,**kwargs):return FinancialRequest('000000.SH',('operating_income',),**kwargs)
    def mock(self,*,code=0,value=None):
        row={'thscode':'000000.SH','period':'quarterly','fiscal_year':2025,'fiscal_period':'Q1','currency':'CNY','period_end_ms':1743350400000,'report_date_ms':1745942400000,'operating_income':value}
        body=json.dumps({'code':code,'data':{'item':[row]}}).encode()
        return HistoricalSnapshot(body,hashlib.sha256(body).hexdigest(),'2026-10-14T00:00:00+00:00',BASE+PATH,'mock-artifact',(),(),())
    def test_exact_get_header_name_no_credentials(self):
        wire=income_wire_contract(self.request())
        self.assertEqual(wire['method'],'GET');self.assertEqual(wire['authentication_header_name'],'X-api-key')
        self.assertIn('thscode=000000.SH&period=quarterly&limit=6',wire['url'])
        self.assertFalse(wire['credentials_included'])
    def test_query_modes_bounds_and_full_symbol(self):
        for req in (self.request(limit=0),self.request(limit=21),self.request(limit=True),self.request(start_ms=1),self.request(limit=None,start_ms=2,end_ms=1),replace(self.request(),entity='000000')):
            with self.subTest(req=req),self.assertRaises(ContractError):income_parameters(req)
        query=income_parameters(self.request(limit=None,start_ms=1735660800000,end_ms=1751212800000))
        self.assertNotIn('limit',query)
    def test_distinct_unconnected_unauthorized_unsupported_and_failure(self):
        tools=FinancialTools({'fuyao':FuyaoLiveBoundary(),'ifind_mcp':IFinDMCPBoundary()})
        self.assertEqual(tools.fetch(self.request()).state,ToolState.UNAUTHORIZED)
        self.assertEqual(tools.fetch(replace(self.request(),provider='ifind_mcp')).state,ToolState.NOT_CONNECTED)
        self.assertEqual(tools.fetch(replace(self.request(),provider='unknown')).state,ToolState.UNSUPPORTED)
        class Broken:
            def fetch(self,request):raise RuntimeError('must not echo private supplier detail')
        result=FinancialTools({'fuyao':Broken()}).fetch(self.request());self.assertEqual(result.state,ToolState.CALL_FAILED);self.assertEqual(result.reason,'RuntimeError')
    def test_null_is_missing_zero_is_value_mock_stays_mock(self):
        missing=FuyaoHistoricalProvider(self.mock()).fetch(self.request())
        zero=FuyaoHistoricalProvider(self.mock(value=0)).fetch(self.request())
        self.assertEqual(missing.state,ToolState.FIELD_MISSING);self.assertEqual(zero.records[0].value,'0')
        self.assertEqual(zero.mode,'synthetic_mock');self.assertEqual(zero.records[0].verification,'partial');self.assertIsNone(zero.records[0].start)
    def test_business_code_and_truncated_body(self):
        self.assertEqual(FuyaoHistoricalProvider(self.mock(code=2003)).fetch(self.request()).state,ToolState.UNAUTHORIZED)
        bad=replace(self.mock(),body=b'{',sha256=hashlib.sha256(b'{').hexdigest())
        self.assertEqual(FuyaoHistoricalProvider(bad).fetch(self.request()).state,ToolState.CALL_FAILED)
    def test_partial_scope_and_unmatched_company_not_fabricated(self):
        provider=FuyaoHistoricalProvider(self.mock(value=123))
        self.assertEqual(provider.fetch(replace(self.request(),consolidation='parent')).state,ToolState.UNSUPPORTED)
        self.assertEqual(provider.fetch(replace(self.request(),entity='111111.SH')).state,ToolState.DATA_MISSING)
        self.assertEqual(provider.fetch(replace(self.request(),metrics=('non_recurring_profit',))).state,ToolState.FIELD_MISSING)
    def test_safe_serialization_and_tampered_snapshot(self):
        result=FuyaoHistoricalProvider(self.mock(value=123)).fetch(self.request())
        self.assertNotIn('123',encode(result.audit_summary()))
        bad=replace(self.mock(value=123),body=b'altered')
        self.assertEqual(FuyaoHistoricalProvider(bad).fetch(self.request()).state,ToolState.CALL_FAILED)


class RealFinancialAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=PROJECT_ROOT/'.local/m3-http-test.sqlite'
        if not source.exists():raise unittest.SkipTest('Approved project-local history missing')
        cls.snapshot=HistoricalSnapshot.from_database(source)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'m4.sqlite');self.ws=Workspace(self.store)
        self.provider=FuyaoHistoricalProvider(self.snapshot)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def request(self):return FinancialRequest('600519.SH',('operating_income','operating_costs'),tuple(date(y,m,d) for y in (2025,2026) for m,d in ((3,31),(6,30))))
    def test_real_eight_fields_official_pdf_admission_dates_and_reopen(self):
        with patch('socket.socket.connect',side_effect=AssertionError('M4 offline only')):
            result=self.provider.fetch(self.request());ids=self.provider.admit(result,self.store)
        self.assertEqual(result.mode,'real_historical_response');self.assertEqual(result.state,ToolState.AVAILABLE);self.assertEqual(len(ids),8)
        self.assertEqual(result.external_requests,0)
        for datum in result.records:
            self.assertEqual(datum.basis,'ytd');self.assertEqual(datum.unit,'yuan');self.assertEqual(datum.verification,'verified')
            trace=self.store.trace(datum.issuer_evidence_id);self.assertIsNotNone(trace['evidence']['locator']['page']);self.assertEqual(trace['crosschecks'][0]['provider_field']['evidence']['locator']['json_pointer'],datum.raw_pointer)
            date_proof=json.loads(trace['source']['disclosure_locator']);self.store.artifact(date_proof['artifact_id'])
        self.store.close();self.store=Store(Path(self.tmp.name)/'m4.sqlite')
        from thesislab.schema import ConflictRecord
        from sqlalchemy import select
        with self.store.sessions() as session:conflicts=list(session.scalars(select(ConflictRecord.id)))
        self.assertEqual(len(conflicts),4);self.assertTrue(all(self.store.conflict_state(i)['state']=='unresolved' for i in conflicts))
    def test_unverified_returned_net_profit_and_eps_never_admitted(self):
        r=self.provider.fetch(replace(self.request(),metrics=('net_profit','basic_eps')))
        self.assertEqual(len(r.records),8);self.assertTrue(all(d.verification=='partial' for d in r.records))
        self.assertTrue(all(d.unit=='yuan_per_share' for d in r.records if d.metric=='basic_eps'))
        self.assertEqual(self.provider.admit(r,self.store),[])
    def test_orchestrator_compiles_primary_financial_requests_calculates_and_runs_m2(self):
        scopes={}
        for item in self.snapshot.evidence:
            if item['origin']=='calculation' and item['scope']['metric'] in ('operating_income_yoy','gross_margin_change') and item['scope']['basis']=='ytd':
                from thesislab.store import evidence_from_dict
                e=evidence_from_dict(item);scopes[(e.scope.end,e.scope.metric)]=e.scope
        descriptors=[('metric-'+str(i),'已定义期间收入或毛利率同比改善。',scope) for i,scope in enumerate(scopes.values())]
        s=self.ws.create('已定义期间收入增长且毛利率改善。');s=self.ws.edit(s['id'],s['version'],financial_design(s['statement'],descriptors))
        s=self.ws.confirm(s['id'],s['version'],reviewer='historical-regression',notes='Previously audited scope, test only.',accepted_suggestions=[],meaning_reviewed=True)
        o=Orchestrator(self.ws,financial_tools=FinancialTools({'fuyao':self.provider,'ifind_mcp':IFinDMCPBoundary()}))
        with patch('socket.socket.connect',side_effect=AssertionError('M4 offline only')):
            s=o.plan_financial_requests(s['id'],s['version'],entity='600519.SH',report_ends=())
            self.assertEqual(s['financial_plan']['primary_providers'],['fuyao','ifind_mcp'])
            self.assertEqual(len(s['financial_plan']['requests']),len(s['design']['tasks']))
            s=o.acquire_financial(s['id'],s['version']);s=o.calculate_financial(s['id'],s['version']);s=self.ws.run(s['id'],s['version'],as_of='2026-10-14')
        self.assertEqual(self.ws.engine.get(s['run_id'])['conclusion']['state'],'opposes')
        self.assertTrue(s['financial_plan']['calculation_ids'])
        self.assertTrue(all(r['external_requests']==0 for r in s['financial_plan']['results']))
