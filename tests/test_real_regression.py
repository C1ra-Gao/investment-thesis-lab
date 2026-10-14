"""Private fixtures are optional unless REQUIRE_REAL_REGRESSION=1 is set."""

from dataclasses import replace
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from thesislab.domain import ContractError
from thesislab.store import Store
from thesislab.regression import verify_phase3, MissingMaterial


class RealRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("THESISLAB_PHASE3_ROOT")
        if not root:
            if os.environ.get("REQUIRE_REAL_REGRESSION") == "1":
                raise RuntimeError("THESISLAB_PHASE3_ROOT required")
            raise unittest.SkipTest("Private Phase 3 material not configured; synthetic suite only")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "private.sqlite"
        cls.store = Store(cls.path)
        try:
            with patch("socket.socket.connect", side_effect=AssertionError("network_forbidden_in_regression")):
                cls.result = verify_phase3(Path(root), cls.store)
        except Exception:
            cls.store.close()
            cls.tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.tmp.cleanup()

    def test_eight_values_four_original_pdfs_and_no_requests(self):
        self.assertEqual(self.result["source_fields_matched"], 8)
        self.assertEqual(self.result["official_reports"], 4)
        self.assertEqual(self.result["financial_requests"], 0)
        self.assertEqual(self.result["keychain_reads"], 0)
        self.assertTrue(all(pair["value_match"] for pair in self.result["pairs"]))

    def test_all_calculations_match_private_audited_baseline(self):
        self.assertEqual([s["period"] for s in self.result["calculations"]], ["Q1", "H1", "Q2-single"])
        self.assertEqual(len(self.result["calculations"]), 3)

    def test_date_conflicts_not_hidden_by_equal_values(self):
        self.assertEqual(self.result["conflict_count"], 4)
        self.assertEqual(self.result["unresolved_conflicts"], 4)

    def test_initial_source_chain_contains_pdf_page_and_input_formula(self):
        trace = self.result["trace"]
        self.assertEqual(trace["calculation"]["operation"], "margin_delta")
        self.assertEqual(trace["inputs"][0]["calculation"]["operation"], "gross_margin")
        leaf = trace["inputs"][0]["inputs"][0]
        self.assertIsNotNone(leaf["evidence"]["locator"]["page"])
        self.assertEqual(leaf["source"]["kind"], "issuer_report")
        provider = leaf["crosschecks"][0]["provider_field"]
        self.assertTrue(provider["evidence"]["locator"]["json_pointer"].startswith("/data/item/"))
        self.assertEqual(provider["source"]["kind"], "provider_cache")
        self.assertEqual(len(trace["subclaim_associations"]), 1)

    def test_crosscheck_cannot_link_another_report_period(self):
        with self.assertRaises(ContractError):
            self.store.put_crosscheck(self.result["pairs"][0]["provider_evidence"],
                                      self.result["pairs"][2]["official_evidence"])

    def test_original_values_cannot_be_changed_by_operator(self):
        pair = self.result["pairs"][0]
        item = self.store.evidence(pair["provider_evidence"])
        with self.assertRaises(ContractError):self.store.put_evidence(replace(item, value=item.value + 1))
        self.assertEqual(self.store.evidence(item.id).value, item.value)

    def test_pdf_scope_checked_against_actual_caption(self):
        pair = self.result["pairs"][0]
        item = self.store.evidence(pair["official_evidence"])
        for changes in ({"unit": "million_yuan"}, {"consolidation": "parent"}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.store.put_evidence(replace(item, id="invalid-scope", scope=replace(item.scope, **changes)))

    def test_issuer_disclosure_date_cannot_be_relabelled(self):
        from datetime import timedelta
        item = self.store.evidence(self.result["pairs"][0]["official_evidence"])
        with self.assertRaises(ContractError):
            self.store.put_evidence(replace(item, id="invalid-date",
                                            issuer_disclosure_date=item.issuer_disclosure_date + timedelta(days=1)))

    def test_wrong_pdf_column_does_not_verify_the_original_value(self):
        item = self.store.evidence(self.result["pairs"][0]["official_evidence"])
        for column in ("column_not_in_report", str(item.scope.end.year - 1) + "年第一季度"):
            with self.subTest(column=column), self.assertRaises(ContractError):
                self.store.put_evidence(replace(item, id="invalid-column",
                                                locator=replace(item.locator, column=column)))

    def test_new_connection_restores_unresolved_field_decisions(self):
        reopened = Store(self.path)
        try:
            task = reopened.restore(self.result["task_id"])
            self.assertEqual(len(task["conflicts"]), 4)
            self.assertTrue(all(c["state"] == "unresolved" for c in task["conflicts"]))
            self.assertTrue(all("original_disclosure_date" in c["adopted_fields"] for c in task["conflicts"]))
            directions = [a["direction"] for a in task["assessments"]]
            self.assertEqual(directions.count("supports"), 2)
            self.assertEqual(directions.count("opposes"), 2)
        finally:reopened.close()

    def test_missing_material_fails_instead_of_using_synthetic_data(self):
        with tempfile.TemporaryDirectory() as missing:
            with self.assertRaises(MissingMaterial):verify_phase3(Path(missing), self.store)
