from dataclasses import replace, FrozenInstanceError
from datetime import date
from decimal import Decimal
import json
import unittest

from thesislab.domain import (amount, ContractError, Locator, Source, ThesisRevision,
                             Subclaim, ClaimRelation, Assessment, Direction, Verification,
                             encode, evidence_from_dict)
from tests.helpers import fact


class DomainTests(unittest.TestCase):
    def test_decimal_preserves_text_and_missing(self):
        self.assertEqual(str(amount("1.2300")), "1.2300")
        self.assertIsNone(amount(None))

    def test_rejects_float_boolean_and_nonfinite(self):
        for value in (0.1, True, "NaN", "Infinity", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                amount(value)

    def test_evidence_immutable_in_memory(self):
        with self.assertRaises(FrozenInstanceError):
            fact().value = Decimal("0")

    def test_evidence_roundtrip_keeps_decimal_and_dates(self):
        item = fact(value="1.2300")
        self.assertEqual(item, evidence_from_dict(json.loads(encode(item))))

    def test_missing_cannot_be_verified(self):
        with self.assertRaises(ContractError):
            replace(fact(value=None), verification=Verification.VERIFIED)

    def test_locator_requires_one_channel(self):
        for kwargs in ({}, {"json_pointer": "/v", "page": 1}, {"page": 0}, {"json_pointer": "v"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ContractError):
                Locator("synthetic-artifact", **kwargs)

    def test_pdf_locator_requires_row_and_column(self):
        with self.assertRaises(ContractError):
            Locator("synthetic-artifact", page=1, table="合并利润表")

    def test_source_disclosure_requires_provenance(self):
        with self.assertRaises(ContractError):
            Source("s", "synthetic", "https://example.invalid", "synthetic_test", disclosed_on=date(2025, 1, 1))

    def test_source_rejects_credentials_and_non_https(self):
        for url in ("http://example.invalid", "https://username:placeholder@example.invalid"):
            with self.subTest(url=url), self.assertRaises(ContractError):
                Source("s", "synthetic", url, "synthetic_test")

    def test_subclaim_is_not_task_question(self):
        with self.assertRaises(ContractError):
            Subclaim("c", "查一下收入？")

    def test_revision_rejects_missing_duplicate_or_foreign_nodes(self):
        a = Subclaim("a", "收入增长。")
        for claims, edges in (((), ()), ((a, a), ()), ((a,), (ClaimRelation("a", "b", "and"),))):
            with self.subTest(claims=claims), self.assertRaises(ContractError):
                ThesisRevision("r", "t", "收入增长。", claims, edges)

    def test_revision_rejects_dependency_cycle(self):
        a, b = Subclaim("a", "收入增长。"), Subclaim("b", "改善持续。")
        with self.assertRaises(ContractError):
            ThesisRevision("r", "t", "收入增长。", (a, b),
                           (ClaimRelation("a", "b", "and"), ClaimRelation("b", "a", "necessary_for")))

    def test_alternative_links_are_not_dependency_cycles(self):
        a, b = Subclaim("a", "机制A可能成立。", "assumption"), Subclaim("b", "机制B可能成立。", "assumption")
        revision = ThesisRevision("r", "t", "解释待核验。", (a, b),
                                 (ClaimRelation("a", "b", "alternative"), ClaimRelation("b", "a", "alternative")))
        self.assertEqual(len(revision.relations), 2)

    def test_quality_does_not_become_direction(self):
        with self.assertRaises(ContractError):
            Assessment("c", "e", Direction.SUPPORTS, Verification.PARTIAL, "locator pending")
        self.assertEqual(Assessment("c", "e", Direction.NOT_DETERMINED, Verification.UNVERIFIABLE,
                                    "missing input").direction, Direction.NOT_DETERMINED)
