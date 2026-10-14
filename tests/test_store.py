from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import json
import tempfile
import unittest

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from thesislab.store import Store
from thesislab.domain import (Source, Locator, ContractError, Subclaim, ThesisRevision,
                             Assessment, Direction, Verification)
from thesislab.finance import gross_margin
from thesislab.conflicts import detect
from tests.helpers import fact


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "synthetic.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def seed_dates(self):
        a = replace(fact("provider"), provider_report_date=date(2026, 4, 25))
        b = replace(fact("issuer"), issuer_disclosure_date=date(2025, 4, 30))
        self.store.put_evidence(a)
        self.store.put_evidence(b)
        conflict = detect(a, b)[0]
        self.store.put_conflict(conflict)
        return a, b, conflict

    def test_raw_json_locator_verified_against_bytes(self):
        source = Source("synthetic", "synthetic test", "https://example.invalid/test", "synthetic_test")
        self.store.put_source(source)
        body = b'{"code":0,"data":{"value":"100.00"}}'
        artifact = self.store.put_artifact(source.id, body, "application/json", "2025-01-01T00:00:00+00:00")
        item = replace(fact(value="100.00"), locator=Locator(artifact, json_pointer="/data/value"))
        self.store.put_evidence(item)
        self.assertEqual(self.store.artifact(artifact)["body"], body)
        self.assertEqual(self.store.trace(item.id)["evidence"]["value"], "100.00")
        with self.assertRaises(ContractError):
            self.store.put_evidence(replace(item, id="forged", value=Decimal("200")))

    def test_null_field_survives_without_zero(self):
        self.store.put_evidence(fact(value=None))
        self.assertIsNone(self.store.evidence("synthetic-income").value)

    def test_provider_metadata_cannot_be_silently_relabelled(self):
        # Explicitly invented provider-envelope fixture; no real financial numbers.
        source = Source("synthetic-provider", "Synthetic provider envelope", "https://example.invalid/fixture", "provider_cache")
        self.store.put_source(source)
        body = json.dumps({"code": 0, "data": {"item": [{"thscode": "SYNTHETIC:ENTITY", "currency": "CNY",
                           "period_end_ms": 1743350400000, "report_date_ms": 1745942400000,
                           "operating_income": "100"}]}}).encode()
        artifact = self.store.put_artifact(source.id, body, "application/json", "2025-05-01T00:00:00+00:00")
        item = replace(fact("synthetic-provider-field"), origin="provider", provider_report_date=date(2025, 4, 30),
                       locator=Locator(artifact, json_pointer="/data/item/0/operating_income"))
        self.store.put_evidence(item)
        for changes in ({"currency": "USD"}, {"entity": "SYNTHETIC:OTHER"}, {"metric": "operating_costs"}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.store.put_evidence(replace(item, id="bad", scope=replace(item.scope, **changes)))

    def test_append_only_update_delete_and_identity_collision(self):
        self.store.put_evidence(fact())
        for sql in ("UPDATE evidence SET payload='changed'", "DELETE FROM evidence"):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                with self.store.engine.begin() as connection:
                    connection.execute(text(sql))
        with self.assertRaises(ContractError):
            self.store.put_evidence(fact(value="200"))
        self.assertEqual(self.store.evidence("synthetic-income").value, Decimal("100"))

    def test_calculation_recomputed_and_lineage_persisted(self):
        income, cost = fact("income"), fact("cost", "20", metric="operating_costs")
        self.store.put_evidence(income)
        self.store.put_evidence(cost)
        calc = gross_margin(income, cost)
        self.store.put_calculation(calc)
        trace = self.store.trace(calc.result.id)
        self.assertEqual(trace["calculation"]["inputs"], ["income", "cost"])
        self.assertEqual(len(trace["inputs"]), 2)
        with self.assertRaises(ContractError):
            self.store.put_calculation(replace(calc, result=replace(calc.result, value=Decimal("99"))))

    def test_derived_evidence_cannot_bypass_calculation(self):
        calc = gross_margin(fact(), fact("cost", "20", metric="operating_costs"))
        with self.assertRaises(ContractError):
            self.store.put_evidence(calc.result)

    def test_field_review_does_not_overwrite_raw_and_stays_unresolved(self):
        a, b, c = self.seed_dates()
        before = self.store.evidence(a.id)
        self.store.review(c.id, reviewer="synthetic-reviewer", reason="issuer-index decision",
                          selected_evidence_id=b.id, field="original_disclosure_date")
        state = self.store.conflict_state(c.id)
        self.assertEqual(state["state"], "unresolved")
        self.assertEqual(state["adopted_fields"]["original_disclosure_date"]["adopted_value"], "2025-04-30")
        self.assertEqual(self.store.evidence(a.id), before)
        self.assertEqual(len(state["reviews"]), 1)
        with self.assertRaises(ContractError):
            self.store.review(c.id, reviewer="synthetic", reason="not enough",
                              selected_evidence_id=b.id, field="original_disclosure_date", keep_unresolved=False)

    def test_review_rejects_wrong_field_foreign_evidence_and_empty_reason(self):
        _, b, c = self.seed_dates()
        for kwargs in ({"field": "value", "selected_evidence_id": b.id},
                       {"field": "original_disclosure_date", "selected_evidence_id": "unrelated"},
                       {"reason": ""}):
            values = {"reviewer": "synthetic", "reason": "reason", **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ContractError):
                self.store.review(c.id, **values)

    def test_numeric_review_effective_value_separate_from_both_originals(self):
        a, b = fact("a", "100"), fact("b", "101")
        for item in (a, b):self.store.put_evidence(item)
        c = detect(a, b)[0]
        self.store.put_conflict(c)
        self.store.review(c.id, reviewer="synthetic", reason="selected synthetic source", selected_evidence_id=b.id,
                          field="value", keep_unresolved=False)
        self.assertEqual(self.store.conflict_state(c.id)["state"], "resolved")
        self.assertEqual(self.store.evidence(a.id).value, Decimal("100"))
        self.assertEqual(self.store.evidence(b.id).value, Decimal("101"))

    def test_reopen_restore_revision_evidence_and_unresolved_review(self):
        a, b, c = self.seed_dates()
        revision = ThesisRevision("r1", "thesis", "收入增长。", (Subclaim("claim", "收入增长。"),))
        self.store.put_revision(revision)
        self.store.review(c.id, reviewer="synthetic", reason="keep unresolved")
        self.store.checkpoint("task", revision.id, state="awaiting_review", evidence_ids=[a.id, b.id], conflict_ids=[c.id])
        self.store.close()
        self.store = Store(self.path)
        result = self.store.restore("task")
        self.assertEqual(result["state"], "awaiting_review")
        self.assertEqual(result["revision"]["id"], "r1")
        self.assertEqual(result["conflicts"][0]["state"], "unresolved")
        self.assertEqual(len(result["conflicts"][0]["reviews"]), 1)

    def test_revision_parent_validation_and_no_overwrite(self):
        r = ThesisRevision("r1", "t", "收入增长。", (Subclaim("c", "收入增长。"),))
        self.store.put_revision(r)
        self.store.put_revision(replace(r, id="r2", parent_id=r.id))
        with self.assertRaises(ContractError):self.store.put_revision(replace(r, statement="利润增长。"))
        with self.assertRaises(ContractError):self.store.put_revision(replace(r, id="bad", thesis_id="other", parent_id=r.id))

    def test_assessment_cannot_upgrade_or_attach_unknown_subclaim(self):
        r = ThesisRevision("r", "t", "收入增长。", (Subclaim("c", "收入增长。"),))
        self.store.put_revision(r)
        self.store.put_evidence(fact("partial", value=None))
        bad = Assessment("c", "partial", Direction.SUPPORTS, Verification.VERIFIED, "not permitted")
        with self.assertRaises(ContractError):self.store.put_assessment(r.id, bad)
        self.store.put_evidence(fact("verified"))
        unknown = Assessment("other", "verified", Direction.SUPPORTS, Verification.VERIFIED, "unknown node")
        with self.assertRaises(ContractError):self.store.put_assessment(r.id, unknown)

    def test_migration_repeat_and_foreign_keys(self):
        with self.store.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA user_version").scalar_one(), 1)
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.audit(), [])

    def test_audit_records_are_append_only(self):
        self.store.put_evidence(fact())
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as connection:connection.execute(text("DELETE FROM audit_events"))
        self.assertEqual(self.store.audit()[0]["action"], "evidence_added")

    def test_tampered_conflict_rejected(self):
        _, _, c = self.seed_dates()
        with self.assertRaises(ContractError):
            self.store.put_conflict(replace(c, details={"invented": True}))
