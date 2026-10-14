from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest

from thesislab.domain import Basis, ContractError
from thesislab.conflicts import detect
from tests.helpers import fact


class ConflictTests(unittest.TestCase):
    def test_equal_numbers_no_numeric_conflict(self):
        self.assertEqual(detect(fact("a"), fact("b")), ())

    def test_equal_values_can_have_date_conflict(self):
        a = replace(fact("a"), provider_report_date=date(2026, 4, 25))
        b = replace(fact("b"), issuer_disclosure_date=date(2025, 4, 30))
        conflicts = detect(a, b)
        self.assertEqual([c.kind for c in conflicts], ["date_mismatch"])
        self.assertFalse(conflicts[0].material)
        self.assertEqual(conflicts[0].details["provider_field_meaning"], "UNVERIFIED")

    def test_scope_mismatch_not_numeric_contradiction(self):
        for changes in ({"basis": Basis.SINGLE}, {"consolidation": "parent"}, {"value_kind": "forecast"},
                        {"currency": "USD"}, {"end_month": 6}, {"unit": "million_yuan"}):
            with self.subTest(changes=changes):
                self.assertEqual([c.kind for c in detect(fact("a"), fact("b", "200", **changes))],
                                 ["scope_mismatch"])

    def test_unknown_scope_not_numeric_contradiction(self):
        self.assertEqual(detect(fact("a", basis=Basis.UNKNOWN), fact("b", "200", basis=Basis.UNKNOWN))[0].kind,
                         "scope_unverified")

    def test_same_scope_numeric_conflict(self):
        self.assertEqual(detect(fact("a", "100"), fact("b", "101"))[0].kind, "numeric_mismatch")

    def test_tolerance_is_explicit_and_nonnegative(self):
        self.assertEqual(detect(fact("a", "100"), fact("b", "100.01"), tolerance=Decimal("0.01")), ())
        with self.assertRaises(ContractError):
            detect(fact("a"), fact("b"), tolerance=Decimal("-1"))

    def test_missing_is_not_a_numeric_conflict(self):
        self.assertEqual(detect(fact("a", value=None), fact("b")), ())

    def test_different_metric_is_not_compared(self):
        with self.assertRaises(ContractError):
            detect(fact("a"), fact("b", metric="operating_costs"))
