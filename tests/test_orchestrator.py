"""V1 roles use admitted M1/M2 core; these fixtures are explicitly synthetic."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.orchestrator import Orchestrator
from thesislab.domain import ContractError
from tests.research_helpers import design

class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"v1.sqlite"
        self.store=Store(self.path);self.ws=Workspace(self.store);self.o=Orchestrator(self.ws)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def task(self):
        d=design();s=self.ws.create(d["statement"]);s=self.ws.edit(s["id"],s["version"],d)
        return self.ws.confirm(s["id"],s["version"],reviewer="synthetic-test",notes="Synthetic semantic review",meaning_reviewed=True,accepted_suggestions=[])
    def finish(self,s):
        s=self.o.start(s["id"],s["version"],"2026-10-14")
        while s["orchestration"]["status"]=="running":s=self.o.step(s["id"],s["version"])
        return s
    def test_unconfirmed_cannot_start(self):
        s=self.ws.create("未经确认的主张。")
        with self.assertRaises(ContractError):self.o.start(s["id"],s["version"],"2026-10-14")
    def test_missing_evidence_remains_unknown_and_reported(self):
        s=self.finish(self.task())
        self.assertEqual(s["orchestration"]["status"],"completed")
        self.assertEqual(s["report"]["conclusion"]["state"],"unverifiable")
        self.assertEqual(s["orchestration"]["steps"][0]["status"],"completed_with_gaps")
        self.assertEqual(s["orchestration"]["model_calls"],0)
        self.assertEqual(s["orchestration"]["financial_calls"],0)
    def test_pause_reopen_resume_no_reexecution(self):
        s=self.task();s=self.o.start(s["id"],s["version"],"2026-10-14");s=self.o.step(s["id"],s["version"])
        s=self.o.control(s["id"],s["version"],"pause")
        with self.assertRaises(ContractError):self.o.step(s["id"],s["version"])
        self.store.close();self.store=Store(self.path);self.ws=Workspace(self.store);self.o=Orchestrator(self.ws)
        s=self.o.control(s["id"],s["version"],"resume");s=self.o.step(s["id"],s["version"])
        self.assertEqual(s["orchestration"]["steps"][0]["attempts"],1)
        self.assertEqual(s["orchestration"]["steps"][1]["attempts"],1)
    def test_edit_invalidates_execution_and_comparison_flags_old_conclusion(self):
        s=self.finish(self.task());old=s["version"];run=s["run_id"]
        d=deepcopy(s["design"]);d["claims"][1]["predicate"]["threshold"]="9"
        s=self.ws.edit(s["id"],s["version"],d)
        self.assertEqual(s["orchestration"]["status"],"needs_review")
        with self.assertRaises(ContractError):self.o.step(s["id"],s["version"])
        c=self.o.compare_versions(s["id"],old,s["version"])
        self.assertTrue(c["claim_graph_changed"]);self.assertTrue(c["right"]["conclusion_is_historical"])
        self.assertEqual(c["right"]["run_id"],run)
    def test_tool_failure_halts_no_auto_retry(self):
        s=self.task();s=self.o.start(s["id"],s["version"],"2026-10-14")
        from unittest.mock import patch
        with patch.object(self.ws,"catalog",side_effect=RuntimeError("private message must not escape")):
            s=self.o.step(s["id"],s["version"])
        self.assertEqual(s["orchestration"]["status"],"failed")
        self.assertEqual(s["orchestration"]["steps"][0]["error"],"RuntimeError")
        with self.assertRaises(ContractError):self.o.step(s["id"],s["version"])
    def test_crashed_running_step_not_silently_replayed(self):
        s=self.task();s=self.o.start(s["id"],s["version"],"2026-10-14")
        s["orchestration"]["steps"][0]["status"]="running"
        s=self.ws.save(s,s["version"],"synthetic_crash_checkpoint");s=self.o.step(s["id"],s["version"])
        self.assertEqual(s["orchestration"]["status"],"failed")
        self.assertEqual(s["orchestration"]["steps"][0]["error"],"interrupted_step_outcome_requires_manual_review")
