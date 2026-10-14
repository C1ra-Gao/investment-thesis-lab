"""Offline semantic/logic tests: authored graphs, not an LLM quality evaluation."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from thesislab.domain import ContractError, encode
from thesislab.store import Store
from thesislab.research import validate_draft, request_candidate, revision_impact
from thesislab.research_store import ResearchEngine
from thesislab.conflicts import detect
from thesislab.finance import gross_margin
from thesislab.cli import main, PROJECT_ROOT
from tests.helpers import fact
from tests.research_helpers import design, pred, node, condition


class CandidateTests(unittest.TestCase):
    def test_three_human_authored_semantic_graphs(self):
        for kind in ("state", "causal", "attribution"):
            with self.subTest(kind=kind):
                d = design(kind=kind)
                validated = validate_draft(d)
                self.assertEqual(validated["statement"], d["statement"])
                self.assertEqual(validated["claims"][2]["statement"], d["claims"][2]["statement"])
                self.assertNotEqual(validated["tasks"][0]["action"], validated["claims"][1]["statement"])
    def test_questions_rejected(self):
        d = design(); d["claims"][1]["statement"] = "估值下降了吗？"
        with self.assertRaises(ContractError):validate_draft(d)
    def test_span_mismatch_and_unmapped_qualifier_rejected(self):
        for mutation in ("bad_span", "unmapped"):
            d = design()
            if mutation == "bad_span":d["claims"][0]["spans"][0]["text"] = "changed"
            else:
                for c in d["claims"]:c["spans"] = [{"start": 0, "end": 2, "text": d["statement"][:2]}]
            with self.assertRaises(ContractError):validate_draft(d)
    def test_cycles_and_mixed_combination_rejected(self):
        d = design(); d["relations"].append({"from_id": "root", "to_id": "a", "kind": "necessary_for"})
        with self.assertRaises(ContractError):validate_draft(d)
        d = design(); d["relations"][0]["kind"] = "or"
        with self.assertRaises(ContractError):validate_draft(d)
    def test_causal_not_proven_by_numeric_premise(self):
        d = design(kind="causal"); d["claims"][2]["predicate"] = pred()
        with self.assertRaises(ContractError):validate_draft(d)
    def test_no_provider_invocation_without_authorization(self):
        class Forbidden:
            def candidate(self, statement):raise AssertionError("must_not_call")
        with self.assertRaises(ContractError):request_candidate("原主张。", Forbidden())
    def test_unknown_fields_and_missing_refutation_rejected(self):
        d = design(); d["unexpected"] = "candidate cannot inject executable code"
        with self.assertRaises(ContractError):validate_draft(d)
        d = design(); d["tasks"].pop()
        with self.assertRaises(ContractError):validate_draft(d)
    def test_invalid_condition_targets_rejected(self):
        d = condition(design());d["conditions"][0]["claim_ids"] = ["absent"]
        with self.assertRaises(ContractError):validate_draft(d)
    def test_forecast_is_retained_not_filtered(self):
        d = validate_draft(design(kind="causal"))
        self.assertEqual(d["claims"][2]["kind"], "forecast")
    def test_numeric_qualifier_change_requires_reassessment(self):
        old = design();new = deepcopy(old)
        new["claims"][1]["predicate"]["threshold"] = "20"
        impact = revision_impact(old, new)
        self.assertEqual(impact["needs_revalidation"], ["a", "root"])
        self.assertEqual(impact["unchanged_claims"], ["b"])
        self.assertFalse(impact["assessment_reuse"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "research.sqlite"
        self.store = Store(self.path)
        self.engine = ResearchEngine(self.store)
    def tearDown(self):
        self.store.close();self.tmp.cleanup()
    def confirm(self, data=None):
        d = self.engine.draft("synthetic-thesis", data or design(), origin="synthetic_test")
        return self.engine.confirm(d, reviewer="test-human", meaning_reviewed=True,
                                   accepted_suggestions=[], budget={"llm_calls": 0, "financial_calls": 0})
    def evaluate(self, confirmation, bindings):
        run = self.engine.evaluate(confirmation, bindings, reviewer="test-human", as_of="2026-10-14")
        return self.engine.get(run, "run")
    def test_confirmation_required(self):
        draft = self.engine.draft("t", design())
        with self.assertRaises(ContractError):self.evaluate(draft, {})
    def test_critical_ambiguity_blocks_confirmation_but_draft_saved(self):
        d = design();d["clarifications"] = [{"id": "q", "claim_ids": ["b"], "field": "fundamentals",
            "question": "基本面指标集合及未恶化阈值是什么？", "critical": True, "answer": None}]
        draft = self.engine.draft("t", d)
        self.assertEqual(self.engine.get(draft)["design"]["claims"][2]["statement"], d["claims"][2]["statement"])
        with self.assertRaises(ContractError):self.engine.confirm(draft, reviewer="human", meaning_reviewed=True,
                accepted_suggestions=[], budget={"llm_calls": 0, "financial_calls": 0})
    def test_explicit_semantics_review_and_zero_budget(self):
        draft = self.engine.draft("t", design())
        for reviewed, budget in ((False, {"llm_calls": 0, "financial_calls": 0}), (True, {"llm_calls": 1, "financial_calls": 0})):
            with self.assertRaises(ContractError):self.engine.confirm(draft, reviewer="human", meaning_reviewed=reviewed,
                    accepted_suggestions=[], budget=budget)
    def test_suggestions_need_acceptance(self):
        d = design();d["claims"].append(node("rival", "风险溢价也可解释估值变化。", d["statement"], origin="suggestion", kind="assumption"))
        draft = self.engine.draft("t", d)
        with self.assertRaises(ContractError):self.engine.confirm(draft, reviewer="human", meaning_reviewed=True,
            accepted_suggestions=[], budget={"llm_calls": 0, "financial_calls": 0})
        c = self.engine.confirm(draft, reviewer="human", meaning_reviewed=True, accepted_suggestions=["rival"],
            budget={"llm_calls": 0, "financial_calls": 0})
        self.assertEqual(self.engine.get(c)["accepted_suggestions"], ["rival"])
    def test_missing_tasks_unknown_not_failed_or_zero(self):
        run = self.evaluate(self.confirm(), {})
        self.assertEqual(run["conclusion"]["state"], "unverifiable")
        self.assertTrue(all(t["state"] == "evidence_missing" for t in run["tasks"]))
        self.assertIsNone(run["usage"]["tokens"])
    def test_and_counterexample_no_vote(self):
        c = self.confirm();self.store.put_evidence(fact("positive", "100"));self.store.put_evidence(fact("negative", "-1"))
        run = self.evaluate(c, {"a-support": {"evidence_id": "positive"}, "b-refute": {
            "evidence_id": "negative", "human_verified": True, "direction": "opposes", "reason": "Synthetic human semantics."}})
        self.assertEqual(run["claims"]["a"]["state"], "supports")
        self.assertEqual(run["conclusion"]["state"], "opposes")
    def test_or_support_and_unknown(self):
        d = design();d["claims"][0]["rule"] = "or"
        for r in d["relations"]:r["kind"] = "or"
        self.store.put_evidence(fact("p"))
        run = self.evaluate(self.confirm(d), {"a-support": {"evidence_id": "p"}})
        self.assertEqual(run["conclusion"]["state"], "supports")
    def test_causal_premise_and_attribution_insufficient(self):
        for kind in ("causal", "attribution"):
            self.store.put_evidence(fact("p"))
            run = self.evaluate(self.confirm(design(kind=kind)), {"a-support": {"evidence_id": "p"}})
            self.assertEqual(run["claims"]["b"]["state"], "unverifiable")
            self.assertEqual(run["conclusion"]["state"], "unverifiable")
    def test_necessary_premise_can_refute_causal(self):
        self.store.put_evidence(fact("n", "-1"))
        run = self.evaluate(self.confirm(design(kind="causal")), {"a-refute": {"evidence_id": "n"}})
        self.assertEqual(run["claims"]["b"]["reason"], "necessary_premise_refuted")
    def test_no_human_confirmation_cannot_promote_numeric_fact_to_attribution(self):
        self.store.put_evidence(fact("p"))
        with self.assertRaises(ContractError):self.evaluate(self.confirm(design(kind="attribution")),
            {"b-support": {"evidence_id": "p", "direction": "supports"}})
    def test_identification_gap_blocks_human_claim_of_attribution(self):
        self.store.put_evidence(fact("p"))
        run = self.evaluate(self.confirm(design(kind="attribution")), {"b-support": {"evidence_id": "p",
            "human_verified": True, "direction": "supports", "reason": "Income is not a contribution bridge."}})
        self.assertEqual(run["claims"]["b"]["state"], "unverifiable")
    def test_mechanism_has_separate_node_and_does_not_prove_forecast(self):
        d = design(kind="causal")
        self.assertEqual(next(c for c in d["claims"] if c["id"] == "m")["kind"], "causal")
        self.assertTrue(any(r["kind"] == "mechanism" for r in d["relations"]))
        run = self.evaluate(self.confirm(d), {})
        self.assertEqual(run["claims"]["m"]["state"], "unverifiable")
        self.assertEqual(run["claims"]["b"]["state"], "unverifiable")
    def test_scope_mismatch_rejected(self):
        self.store.put_evidence(fact("other", entity="SYNTHETIC:OTHER"))
        with self.assertRaises(ContractError):self.evaluate(self.confirm(), {"a-support": {"evidence_id": "other"}})
    def test_null_or_unverified_does_not_support(self):
        self.store.put_evidence(fact("missing", value=None))
        run = self.evaluate(self.confirm(), {"a-support": {"evidence_id": "missing"}})
        self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
    def test_future_disclosure_does_not_refute_or_support(self):
        self.store.put_evidence(replace(fact("future"), issuer_disclosure_date=date(2027, 1, 1)))
        run = self.evaluate(self.confirm(), {"a-support": {"evidence_id": "future"}})
        self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
    def test_unresolved_numeric_conflict_blocks_and_review_snapshot_immutable(self):
        a, b = fact("p", "100"), fact("q", "101")
        for e in (a, b):self.store.put_evidence(e)
        conflict = detect(a, b)[0];self.store.put_conflict(conflict)
        c = self.confirm()
        first = self.evaluate(c, {"a-support": {"evidence_id": "p"}})
        self.assertEqual(first["claims"]["a"]["state"], "unverifiable")
        self.store.review(conflict.id, reviewer="human", reason="synthetic source choice", field="value",
                          selected_evidence_id="p", keep_unresolved=False)
        second = self.evaluate(c, {"a-support": {"evidence_id": "p"}})
        self.assertEqual(second["claims"]["a"]["state"], "supports")
        self.assertEqual(first["claims"]["a"]["state"], "unverifiable")
    def test_opposite_admissible_assessments_remain_unresolved(self):
        self.store.put_evidence(fact("p"));self.store.put_evidence(fact("n", "-1"))
        run = self.evaluate(self.confirm(), {"a-support": {"evidence_id": "p"}, "a-refute": {"evidence_id": "n"}})
        self.assertEqual(run["claims"]["a"]["reason"], "unresolved_assessment_disagreement")
    def test_selected_other_value_blocks_rejected_input(self):
        a, b = fact("p", "100"), fact("q", "101")
        for e in (a, b):self.store.put_evidence(e)
        conflict = detect(a, b)[0];self.store.put_conflict(conflict)
        self.store.review(conflict.id, reviewer="human", reason="Prefer q", field="value", selected_evidence_id="q", keep_unresolved=False)
        run = self.evaluate(self.confirm(), {"a-support": {"evidence_id": "p"}})
        self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
        self.assertEqual(self.store.evidence("p").value, fact("p").value)
    def test_conflict_in_calculation_input_blocks_result(self):
        income, cost, alternate = fact("income"), fact("cost", "20", metric="operating_costs"), fact("alternate", "101")
        for e in (income, cost, alternate):self.store.put_evidence(e)
        calc = gross_margin(income, cost);self.store.put_calculation(calc)
        self.store.put_conflict(detect(income, alternate)[0])
        d = design();d["claims"][1]["predicate"] = pred(calc.result)
        run = self.evaluate(self.confirm(d), {"a-support": {"evidence_id": calc.result.id}})
        self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
        self.assertIn("income", run["conclusion"]["evidence_dependencies"])
    def test_unobserved_forecast_cannot_be_promoted_by_human_direction(self):
        self.store.put_evidence(fact("p"))
        run = self.evaluate(self.confirm(design(kind="causal")), {"b-support": {"evidence_id": "p",
            "direction": "supports", "human_verified": True, "reason": "Insufficient present numeric observation."}})
        self.assertEqual(run["claims"]["b"]["state"], "unverifiable")
    def test_unknown_scope_and_forecast_values_never_refute(self):
        for field in ({"consolidation": "unknown"}, {"value_kind": "forecast"}):
            e = fact("unknown-" + str(len(field)) + next(iter(field)), **field);self.store.put_evidence(e)
            d = design();d["claims"][1]["predicate"] = pred(e)
            run = self.evaluate(self.confirm(d), {"a-support": {"evidence_id": e.id}})
            self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
    def test_rival_discrimination_does_not_vote_on_claim(self):
        d = design();d["tasks"].append({**d["tasks"][0], "id": "rival-check", "purpose": "discriminate"})
        self.store.put_evidence(fact("p"))
        run = self.evaluate(self.confirm(d), {"rival-check": {"evidence_id": "p"}})
        self.assertEqual(run["claims"]["a"]["state"], "unverifiable")
    def test_revision_does_not_copy_assessments_or_modify_history(self):
        c = self.confirm();old = self.evaluate(c, {})
        d = design();d["claims"][1]["predicate"]["threshold"] = "20"
        draft = self.engine.draft("synthetic-thesis", d, parent_id=c, reason="Threshold revised.")
        self.assertEqual(self.engine.get(draft)["impact"]["needs_revalidation"], ["a", "root"])
        self.assertEqual(old["conclusion"]["state"], "unverifiable")
        with self.assertRaises(ContractError):self.engine.draft("other-thesis", d, parent_id=c, reason="bad")
    def test_revalidation_event_does_not_falsify(self):
        c = self.confirm(condition(design(), mode="manual_event"))
        self.store.put_evidence(fact("event"))
        check = self.engine.check_condition(c, "change-a", reviewer="human", observed_on="2026-10-14",
            evidence_id="event", event_occurred=True, reason="Synthetic event reviewed.")
        result = self.engine.get(check)
        self.assertEqual(result["effect"], "needs_revalidation")
        self.assertFalse(result["old_conclusions_modified"])
    def test_threshold_condition_unknown_false_true_and_kinds(self):
        for kind in ("falsify", "weaken", "revalidate"):
            c = self.confirm(condition(design(), kind=kind))
            self.store.put_evidence(fact("p"));self.store.put_evidence(fact("n", "-1"))
            for evidence_id, expected in ((None, "unknown"), ("p", "not_triggered"), ("n", "triggered")):
                check = self.engine.check_condition(c, "change-a", reviewer="human", observed_on="2026-10-14", evidence_id=evidence_id)
                self.assertEqual(self.engine.get(check)["check_state"], expected)
    def test_condition_window_and_future_data_rejected(self):
        c = self.confirm(condition(design()))
        with self.assertRaises(ContractError):self.engine.check_condition(c, "change-a", reviewer="human", observed_on="2027-01-01")
        self.store.put_evidence(replace(fact("future"), issuer_disclosure_date=date(2027, 1, 1)))
        with self.assertRaises(ContractError):self.engine.check_condition(c, "change-a", reviewer="human", observed_on="2026-10-14", evidence_id="future")
    def test_manual_event_missing_quality_remains_unknown(self):
        c = self.confirm(condition(design(), mode="manual_event"))
        self.store.put_evidence(fact("missing", value=None))
        check = self.engine.check_condition(c, "change-a", reviewer="human", observed_on="2026-10-14",
            evidence_id="missing", event_occurred=True, reason="Insufficient evidence.")
        self.assertEqual(self.engine.get(check)["check_state"], "unknown")
    def test_database_v1_to_v2_reopen_and_append_only(self):
        c = self.confirm();self.evaluate(c, {})
        with self.store.engine.connect() as db:
            self.assertEqual(db.exec_driver_sql("PRAGMA user_version").scalar_one(), 2)
            self.assertEqual(db.exec_driver_sql("SELECT version FROM schema_version").scalar_one(), 1)
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as db:db.execute(text("DELETE FROM research_records"))
        before = self.engine.history("synthetic-thesis")
        self.store.close();self.store = Store(self.path);self.engine = ResearchEngine(self.store)
        self.assertEqual(self.engine.history("synthetic-thesis"), before)
    def test_failed_additive_migration_rolls_back_without_touching_m1(self):
        from sqlalchemy import inspect
        from thesislab.research_store import metadata, upgrade_research
        other = Store(Path(self.tmp.name) / "v1.sqlite")
        try:
            other.put_evidence(fact("preserved"))
            create = metadata.create_all
            def failed(connection):
                create(connection)
                raise RuntimeError("synthetic_migration_failure")
            with patch.object(metadata, "create_all", side_effect=failed), self.assertRaises(RuntimeError):
                upgrade_research(other.engine)
            with other.engine.connect() as c:
                self.assertEqual(c.exec_driver_sql("PRAGMA user_version").scalar_one(), 1)
                self.assertNotIn("research_records", inspect(c).get_table_names())
            self.assertEqual(other.evidence("preserved"), fact("preserved"))
            ResearchEngine(other)
            self.assertEqual(other.evidence("preserved"), fact("preserved"))
        finally:other.close()
    def test_zero_network_calls_during_pipeline(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            self.evaluate(self.confirm(), {})


class CLITests(unittest.TestCase):
    def test_manual_candidate_confirm_evaluate_and_restore(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / ".local") as root:
            root = Path(root);draft = root / "draft.json";bindings = root / "bindings.json";db = root / "engine.sqlite"
            draft.write_text(json.dumps(design(), ensure_ascii=False));bindings.write_text("{}")
            def call(args):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):code = main(args + ["--db", str(db)])
                self.assertEqual(code, 0, out.getvalue())
                return out.getvalue()
            d = json.loads(call(["draft", "--input", str(draft), "--thesis", "synthetic", "--origin", "synthetic_test"]))["id"]
            c = json.loads(call(["confirm", "--draft", d, "--reviewer", "human", "--meaning-reviewed"]))["id"]
            r = json.loads(call(["evaluate", "--confirmation", c, "--bindings", str(bindings), "--reviewer", "human", "--as-of", "2026-10-14"]))["id"]
            output = root / "restored.json"
            call(["research-show", "--id", r, "--output", str(output)])
            self.assertEqual(json.loads(output.read_text())["conclusion"]["state"], "unverifiable")
