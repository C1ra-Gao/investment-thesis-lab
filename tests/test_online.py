"""V2 offline protocol tests. Mock responses are explicitly synthetic, never real API evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.online_transport import NetworkLedger,PublicHTTPS,PublicResponse
from thesislab.online_research import DisclosureIndex,OnlineResearch,numeric_rule
from thesislab.domain import ContractError


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'online.sqlite');self.ws=Workspace(self.store)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def confirmed(self):
        s=self.ws.create('合成测试：收入增长。')
        return self.ws.confirm(s['id'],s['version'],reviewer='synthetic-reviewer',notes='Synthetic test',meaning_reviewed=True,accepted_suggestions=[])
    def test_durable_budget_failed_reservation_survives_reopen(self):
        a=NetworkLedger(self.store.engine,authorized=True,model_limit=1,public_limit=1)
        a.reserve('public','https://www.moutaichina.com/synthetic')
        b=NetworkLedger(self.store.engine,authorized=True,public_limit=1)
        with self.assertRaises(ContractError):b.reserve('public','second')
    def test_no_authorization_no_reservation(self):
        a=NetworkLedger(self.store.engine)
        with self.assertRaises(ContractError):a.reserve('model','synthetic')
        self.assertEqual(a.records(),[])
    def test_permission_denial_stops_all_new_requests(self):
        a=NetworkLedger(self.store.engine,authorized=True)
        token=a.reserve('public','synthetic');a.record('public','result',token,{'http_status':403})
        with self.assertRaises(ContractError):a.reserve('public','second')
    def test_ssrf_and_credential_urls_rejected_before_request(self):
        a=NetworkLedger(self.store.engine,authorized=True);p=PublicHTTPS(a,hosts=['www.moutaichina.com'])
        for url in ('http://www.moutaichina.com/','https://127.0.0.1/','https://www.moutaichina.com:444/','https://user:pass@www.moutaichina.com/','https://www.moutaichina.com/?token=synthetic'):
            with self.subTest(url=url),self.assertRaises(ContractError):p.validate(url)
        self.assertEqual(a.records(),[])
    def test_disclosure_date_is_visible_span_not_path_or_upload_metadata(self):
        p=DisclosureIndex('https://www.moutaichina.com/index.html')
        p.feed('<li><a href="/2026-08/17/report.pdf" title="合成2026年半年度报告">报告</a><span>2026-08-15</span></li>')
        self.assertEqual(p.entries[0]['disclosed_on'],'2026-08-15')
        q=DisclosureIndex('https://www.moutaichina.com/');q.feed('<li><a href="/2026-08-17/report.pdf">报告</a></li>');self.assertEqual(q.entries,[])
    def test_dynamic_jobs_follow_actual_plan_purposes_and_no_fact_from_html(self):
        s=self.confirmed();transport=Mock();transport.get.return_value=PublicResponse('https://www.moutaichina.com/index.html',200,b'<html>No synthetic matching document</html>','text/html','2026-10-14T00:00:00+00:00','synthetic-request')
        o=OnlineResearch(self.ws,transport);s=o.start(s['id'],s['version'],entity='600519.SH',year=2026,period='H1',as_of='2026-10-14',consent=True)
        self.assertEqual(len(s['online']['jobs']),1+len(s['design']['tasks']))
        while s['online']['status']=='running':s=o.step(s['id'],s['version'])
        self.assertEqual(s['online']['status'],'awaiting_rule_review');self.assertEqual(s['online']['evidence_ids'],[])
        self.assertEqual(transport.get.call_count,1)
        self.assertTrue(any(j.get('purpose')=='refute' for j in s['online']['jobs']))
        s=o.accept_rules(s['id'],s['version'],accepted=True,notes='Explicit synthetic no-data review')
        self.assertEqual(s['report']['conclusion']['state'],'unverifiable')
    def test_paused_online_task_rejects_execution(self):
        s=self.confirmed();o=OnlineResearch(self.ws,Mock());s=o.start(s['id'],s['version'],entity='600519.SH',year=2026,period='H1',as_of='2026-10-14',consent=True)
        s=o.control(s['id'],s['version'],'pause')
        with self.assertRaises(ContractError):o.step(s['id'],s['version'])
        s=o.control(s['id'],s['version'],'resume');self.assertEqual(s['online']['status'],'running')
    def test_negation_and_causal_claims_not_numeric_shortcuts(self):
        self.assertEqual(numeric_rule({'kind':'fact','rule':'atomic','statement':'毛利率未改善。'}),('gross_margin_change','le'))
        self.assertIsNone(numeric_rule({'kind':'attribution','rule':'atomic','statement':'盈利改善主要来自主营业务。'}))
        self.assertIsNone(numeric_rule({'kind':'forecast','rule':'atomic','statement':'收入将增长。'}))
