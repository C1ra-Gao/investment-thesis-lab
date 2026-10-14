"""M3 behavior and HTTP security; synthetic core + optional real fixture regression."""

from copy import deepcopy
from dataclasses import replace
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from thesislab.domain import ContractError, encode
from thesislab.store import Store
from thesislab.workspace import Workspace, RevisionConflict, manual_design
from thesislab.web_server import make_server
from tests.helpers import fact
from tests.research_helpers import design


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"web.sqlite"
        self.store=Store(self.path);self.ws=Workspace(self.store)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def confirmed(self):
        s=self.ws.create("合成主张。");s=self.ws.edit(s["id"],s["version"],design())
        return self.ws.confirm(s["id"],s["version"],reviewer="synthetic-human",notes="Synthetic review, not a real investment result.",accepted_suggestions=[],meaning_reviewed=True)
    def test_declarative_input_and_recovery(self):
        s=self.ws.create("某公司估值回落，但基本面未恶化。")
        self.assertEqual(s["candidate_source"],"manual_scaffold")
        with self.assertRaises(ContractError):self.ws.create("该买股票吗？")
        self.store.close();self.store=Store(self.path);self.ws=Workspace(self.store)
        self.assertEqual(self.ws.get(s["id"]),s)
    def test_confirmation_required(self):
        s=self.ws.create("主张。");
        with self.assertRaises(ContractError):self.ws.run(s["id"],s["version"],as_of="2026-10-14")
    def test_invalid_model_candidate_can_be_saved_but_not_confirmed(self):
        s=self.ws.create("主张。");d=manual_design("主张。");d["claims"][0]["spans"][0]["end"]=99
        s=self.ws.edit(s["id"],s["version"],d)
        self.assertEqual(s["schema"]["status"],"failed")
        with self.assertRaises(ContractError):self.ws.confirm(s["id"],s["version"],reviewer="human",notes="Reviewed",accepted_suggestions=[],meaning_reviewed=True)
    def test_edit_resets_semantic_review_and_preserves_old_run(self):
        s=self.confirmed();s=self.ws.run(s["id"],s["version"],as_of="2026-10-14")
        old=self.ws.engine.get(s["run_id"])
        d=deepcopy(s["design"]);d["claims"][1]["predicate"]["threshold"]="2"
        changed=self.ws.edit(s["id"],s["version"],d)
        self.assertEqual(changed["semantic_review"],"pending")
        with self.assertRaises(ContractError):self.ws.run(changed["id"],changed["version"],as_of="2026-10-14")
        self.assertEqual(self.ws.engine.get(s["run_id"]),old)
    def test_concurrent_save_reports_conflict(self):
        s=self.ws.create("主张。");self.ws.edit(s["id"],s["version"],s["design"])
        with self.assertRaises(RevisionConflict):self.ws.edit(s["id"],s["version"],s["design"])
    def test_explain_and_verify_are_distinct_and_persisted(self):
        s=self.confirmed();s=self.ws.run(s["id"],s["version"],as_of="2026-10-14")
        s=self.ws.followup(s["id"],s["version"],question="为什么？",mode="explain",topic="date")
        self.assertEqual(s["followups"][-1]["model_calls"],0)
        s=self.ws.followup(s["id"],s["version"],question="验证新字段",mode="verify",topic="other")
        self.assertEqual(s["followups"][-1]["status"],"source_gap")
        self.assertEqual(len(self.ws.get(s["id"])["followups"]),2)
    def test_compare_positive_scope_negative_period_and_missing_data(self):
        p=fact("p",year=2026);q=fact("q",year=2025);different=fact("different",year=2025,end_month=6)
        for e in(p,q,different):self.store.put_evidence(e)
        a=self.ws.create("左研究。");b=self.ws.create("右研究。")
        a=self.ws.edit(a["id"],a["version"],a["design"],{"root-support":{"evidence_id":"p"}})
        b=self.ws.edit(b["id"],b["version"],b["design"],{"root-support":{"evidence_id":"q"},"root-refute":{"evidence_id":"different"}})
        a=self.ws.compare(a["id"],a["version"],other_task_id=b["id"],left_id="p",right_id="q")
        self.assertEqual(a["comparisons"][-1]["status"],"comparable")
        a=self.ws.compare(a["id"],a["version"],other_task_id=b["id"],left_id="p",right_id="different")
        self.assertEqual(a["comparisons"][-1]["status"],"not_comparable")
        a=self.ws.compare(a["id"],a["version"],other_task_id=b["id"])
        self.assertEqual(a["comparisons"][-1]["reason"],"evidence_coverage_missing")
    def test_model_schema_success_never_confirms_semantics(self):
        from thesislab.deepseek import DeepSeekCandidateProvider,CallBudget
        from tests.test_deepseek import SyntheticTransport,reply
        d=design();self.ws.provider=DeepSeekCandidateProvider(CallBudget(1,4000,True),transport=SyntheticTransport(reply(d)))
        s=self.ws.create(d["statement"]);s=self.ws.model_generate(s["id"],s["version"])
        self.assertEqual(s["schema"]["status"],"passed")
        self.assertEqual(s["semantic_review"],"pending")
        self.assertIsNone(s["confirmed_id"])
        with self.assertRaises(ContractError):self.ws.run(s["id"],s["version"],as_of="2026-10-14")
    def test_schema3_append_only_and_m1_m2_compatible(self):
        self.ws.create("主张。");
        with self.store.engine.connect() as c:self.assertEqual(c.exec_driver_sql("PRAGMA user_version").scalar_one(),3)
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as c:c.execute(text("DELETE FROM web_events"))
        self.store.close();self.store=Store(self.path);self.ws=Workspace(self.store)
        self.assertEqual(len(self.ws.list()),1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/"http.sqlite");self.ws=Workspace(self.store)
        self.server=make_server(self.ws);self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_port;self.cookie=None;self.csrf=None
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.store.close();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        c=HTTPConnection("127.0.0.1",self.port,timeout=10)
        h={}
        if self.cookie:h["Cookie"]=self.cookie
        if body is not None:h.update({"Content-Type":"application/json","Origin":f"http://127.0.0.1:{self.port}","X-ThesisLab-CSRF":self.csrf or ""})
        if headers:h.update(headers)
        c.request("GET" if body is None else "POST",path,body=json.dumps(body) if body is not None else None,headers=h)
        r=c.getresponse();status=r.status;cookie=r.getheader("Set-Cookie");data=r.read();c.close()
        if cookie:self.cookie=cookie.split(";")[0]
        return status,data
    def login(self):
        self.assertEqual(self.request("/")[0],200)
        status,data=self.request("/api/session");self.csrf=json.loads(data)["csrf"]
    def test_full_http_flow_and_recovery(self):
        self.login();status,data=self.request("/api/tasks",{"statement":"陈述主张。"});self.assertEqual(status,200)
        s=json.loads(data)
        self.assertEqual(self.request(f"/api/tasks/{s['id']}/run",{"version":s["version"],"as_of":"2026-10-14"})[0],400)
        status,data=self.request(f"/api/tasks/{s['id']}/confirm",{"version":s["version"],"notes":"Synthetic HTTP test review","meaning_reviewed":True,"accepted_suggestions":[]});self.assertEqual(status,200);s=json.loads(data)
        status,data=self.request(f"/api/tasks/{s['id']}/run",{"version":s["version"],"as_of":"2026-10-14"});self.assertEqual(status,200);s=json.loads(data)
        run=json.loads(self.request("/api/runs/"+s["run_id"])[1]);self.assertEqual(run["conclusion"]["state"],"unverifiable")
        self.assertEqual(json.loads(self.request("/api/tasks/"+s["id"])[1])["run_id"],s["run_id"])
    def test_auth_host_origin_csrf_and_private_file_protection(self):
        self.assertEqual(self.request("/api/evidence")[0],401)
        self.assertEqual(self.request("/",headers={"Host":"evil.example"})[0],403)
        self.login()
        self.assertEqual(self.request("/api/tasks",{"statement":"陈述。"},headers={"Origin":"https://evil.example"})[0],403)
        self.assertEqual(self.request("/api/tasks",{"statement":"陈述。"},headers={"X-ThesisLab-CSRF":"wrong"})[0],403)
        for path in ("/.local/m3.sqlite","/../.env","/%2e%2e/README.md"):
            self.assertEqual(self.request(path)[0],404)
    def test_conflicting_version_is_409(self):
        self.login();s=json.loads(self.request("/api/tasks",{"statement":"陈述。"})[1])
        body={"version":s["version"],"design":s["design"]}
        self.assertEqual(self.request(f"/api/tasks/{s['id']}/save",body)[0],200)
        self.assertEqual(self.request(f"/api/tasks/{s['id']}/save",body)[0],409)
    def test_v1_http_orchestrator_and_version_comparison(self):
        self.login();s=json.loads(self.request('/api/tasks',{'statement':'合成HTTP流程主张。'})[1])
        path=f"/api/tasks/{s['id']}"
        self.assertEqual(self.request(path+'/orchestrate',{'version':s['version'],'as_of':'2026-10-14'})[0],400)
        s=json.loads(self.request(path+'/confirm',{'version':s['version'],'notes':'Synthetic HTTP audit','meaning_reviewed':True})[1]);old=s['version']
        s=json.loads(self.request(path+'/orchestrate',{'version':s['version'],'as_of':'2026-10-14'})[1])
        for i in range(5):
            status,data=self.request(path+'/agent-step',{'version':s['version']});self.assertEqual(status,200);s=json.loads(data)
        self.assertEqual(s['orchestration']['status'],'completed')
        self.assertEqual(s['report']['conclusion']['state'],'unverifiable')
        status,data=self.request(path+'/version-compare',{'version':s['version'],'left_version':old,'right_version':s['version']})
        self.assertEqual(status,200);self.assertIsNone(json.loads(data)['left']['conclusion'])
        self.assertEqual(self.request(path+'/agent-step',{'version':s['version']})[0],400)
    def test_static_frontend_has_no_external_assets_or_user_html_injection(self):
        self.login();status,html=self.request("/");self.assertEqual(status,200)
        self.assertNotIn(b"cdn.",html)
        js=self.request("/app.js")[1]
        self.assertNotIn(b"innerHTML",js)
        self.assertIn(b"textContent",js)


class RealWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=os.environ.get("THESISLAB_PHASE3_ROOT")
        if not root:raise unittest.SkipTest("Private Phase3 material not configured")
        cls.tmp=tempfile.TemporaryDirectory();cls.store=Store(Path(cls.tmp.name)/"real.sqlite")
        from thesislab.regression import verify_phase3
        cls.baseline=verify_phase3(Path(root).resolve(),cls.store);cls.ws=Workspace(cls.store)
    @classmethod
    def tearDownClass(cls):cls.store.close();cls.tmp.cleanup()
    def confirm(self,s):
        return self.ws.confirm(s["id"],s["version"],reviewer="real-regression-test-operator",notes="Human-authored real evidence design tested as a fixture, not model semantic approval.",accepted_suggestions=[],meaning_reviewed=True)
    def test_real_web_model_flow_manual_example_q2_and_history(self):
        with patch("socket.socket.connect",side_effect=AssertionError("no external calls")):
            original=self.confirm(self.ws.example());original=self.ws.run(original["id"],original["version"],as_of="2026-10-14")
            self.assertEqual(self.ws.engine.get(original["run_id"])["conclusion"]["state"],"opposes")
            entity=self.ws.catalog()[0]["scope"]["entity"]
            original=self.ws.followup(original["id"],original["version"],question="核验Q2单季",mode="verify",topic="q2",entity=entity)
            child=self.ws.get(original["followups"][-1]["child_task_id"])
            self.assertEqual(child["stage"],"draft")
            child=self.confirm(child);child=self.ws.run(child["id"],child["version"],as_of="2026-10-14")
            childrun=self.ws.engine.get(child["run_id"])
            self.assertTrue(all(c["state"]=="opposes" for c in childrun["claims"].values()))
            old_run=original["run_id"];original=self.ws.run(original["id"],original["version"],as_of="2026-10-14")
            self.assertEqual(len(original["run_ids"]),2)
            self.assertNotEqual(original["run_id"],old_run)
            self.assertEqual(self.ws.engine.get(old_run)["conclusion"]["state"],"opposes")
            left=next(o["evidence_id"] for o in self.ws.engine.get(original["run_id"])["tasks"] if "evidence_id" in o)
            right=next(o["evidence_id"] for o in childrun["tasks"] if "evidence_id" in o)
            original=self.ws.compare(original["id"],original["version"],other_task_id=child["id"],left_id=left,right_id=right)
            self.assertEqual(original["comparisons"][-1]["status"],"not_comparable")
            self.assertTrue(all(c["state"]=="unresolved" for c in self.ws.conflicts()))
