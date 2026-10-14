"""Project-local admitted real corpus; no reads of external research directories."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from thesislab.cli import PROJECT_ROOT
from thesislab.locators import pdf_value,verify_pdf_scope,json_value
from thesislab.store import Store
from thesislab.workspace import Workspace


class ProjectCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=PROJECT_ROOT/".local/m3-http-test.sqlite"
        if not source.exists():raise unittest.SkipTest("Admitted project-local corpus not configured")
        cls.tmp=tempfile.TemporaryDirectory()
        cls.path=Path(cls.tmp.name)/"corpus.sqlite"
        a=sqlite3.connect("file:"+str(source)+"?mode=ro",uri=True);b=sqlite3.connect(cls.path)
        a.backup(b);a.close();b.close()
        cls.store=Store(cls.path);cls.ws=Workspace(cls.store,model_cache=PROJECT_ROOT/".local/deepseek-m25")
    @classmethod
    def tearDownClass(cls):cls.store.close();cls.tmp.cleanup()
    def test_eight_issuer_fields_revalidate_against_stored_pdf_bytes(self):
        issuer=[self.store.evidence(e["id"]) for e in self.ws.catalog() if e["origin"]=="issuer"]
        self.assertEqual(len(issuer),8);self.assertEqual(len({e.locator.artifact_id for e in issuer}),4)
        for e in issuer:
            raw=self.store.artifact(e.locator.artifact_id)["body"]
            self.assertEqual(pdf_value(raw,e.locator),e.value)
            verify_pdf_scope(raw,e.locator,e.scope)
    def test_eight_provider_fields_still_match_original_cached_json(self):
        provider=[self.store.evidence(e["id"]) for e in self.ws.catalog() if e["origin"]=="provider"]
        self.assertEqual(len(provider),8)
        for e in provider:
            raw=self.store.artifact(e.locator.artifact_id)["body"]
            self.assertEqual(json_value(raw,e.locator.json_pointer),e.value)
    def confirm(self,s):
        return self.ws.confirm(s["id"],s["version"],reviewer="project-local-regression-test",notes="Explicit test-design confirmation, not real user semantic approval.",accepted_suggestions=[],meaning_reviewed=True)
    def test_local_real_example_q2_and_revalidation_no_external_calls(self):
        with patch("socket.socket.connect",side_effect=AssertionError("no external calls")):
            s=self.confirm(self.ws.example());s=self.ws.run(s["id"],s["version"],as_of="2026-10-14")
            original=s["run_id"];self.assertEqual(self.ws.engine.get(original)["conclusion"]["state"],"opposes")
            entity=next(e["scope"]["entity"] for e in self.ws.catalog() if e["origin"]=="issuer")
            child=self.confirm(self.ws.single_plan(entity));child=self.ws.run(child["id"],child["version"],as_of="2026-10-14")
            self.assertEqual(self.ws.engine.get(child["run_id"])["conclusion"]["state"],"opposes")
            s=self.ws.run(s["id"],s["version"],as_of="2026-10-14")
            self.assertNotEqual(s["run_id"],original);self.assertEqual(self.ws.engine.get(original)["conclusion"]["state"],"opposes")
    def test_actual_deepseek_cache_pass_fail_preserved_and_user_confirmation_blocked(self):
        if not (PROJECT_ROOT/".local/deepseek-m25/ledger.json").exists():raise unittest.SkipTest("Actual model cache unavailable")
        good=self.ws.load_cached(4);bad=self.ws.load_cached(6)
        self.assertEqual(good["schema"]["status"],"passed");self.assertEqual(bad["schema"]["status"],"failed")
        self.assertEqual(good["semantic_review"],"pending")
        from thesislab.domain import ContractError
        with self.assertRaises(ContractError):self.ws.run(good["id"],good["version"],as_of="2026-10-14")
    def test_unresolved_dates_and_reopen_history_survive(self):
        self.assertEqual(len(self.ws.conflicts()),4)
        self.assertTrue(all(c["state"]=="unresolved" for c in self.ws.conflicts()))
        original=self.store.restore("internal-regression")
        reopened=Store(self.path)
        try:self.assertEqual(reopened.restore("internal-regression")["revision"],original["revision"])
        finally:reopened.close()
    def test_v1_real_orchestrated_evidence_report_is_reproducible(self):
        from thesislab.orchestrator import Orchestrator
        from unittest.mock import patch
        with patch('socket.socket.connect',side_effect=AssertionError('offline only')):
            s=self.confirm(self.ws.example());o=Orchestrator(self.ws)
            s=o.start(s['id'],s['version'],'2026-10-14')
            for i in range(5):s=o.step(s['id'],s['version'])
        self.assertEqual(s['orchestration']['status'],'completed')
        self.assertEqual(s['report']['conclusion']['state'],'opposes')
        self.assertEqual(s['orchestration']['steps'][2]['status'],'needs_review')
        self.assertTrue(s['orchestration']['steps'][0]['output']['matches'])
        self.assertTrue(s['orchestration']['steps'][1]['output']['matches'])
        self.assertEqual(s['report']['claim_statements'],{c['id']:c['statement'] for c in s['design']['claims']})
    def test_v1_cache_miss_never_becomes_fake_model_candidate(self):
        from thesislab.deepseek import DeepSeekCandidateProvider,CallBudget
        from unittest.mock import Mock
        transport=Mock();provider=DeepSeekCandidateProvider(CallBudget(1,4000,True),transport=transport)
        ws=Workspace(self.store,provider=provider,model_cache=PROJECT_ROOT/'.local/deepseek-m25',model_mode='real_model_cache_replay_only')
        s=ws.create('宁德时代盈利改善来自主营业务');s=ws.model_generate(s['id'],s['version'])
        transport.send.assert_not_called()
        self.assertEqual(s['candidate_source'],'manual_scaffold')
        self.assertEqual(s['model_receipt']['error_type'],'offline_cache_miss')
        self.assertIsNone(s['raw_candidate'])
