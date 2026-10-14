from dataclasses import replace
from datetime import date
from decimal import Decimal, getcontext
import unittest

from thesislab.domain import Basis, Verification
from thesislab.finance import yoy, gross_margin, cumulative_to_single, margin_delta, CalculationError
from tests.helpers import fact


class FinanceTests(unittest.TestCase):
    def test_yoy_positive_growth(self):
        result = yoy(fact("current", "120", year=2026), fact("prior", "100", year=2025))
        self.assertEqual(result.result.value, Decimal("20"))
        self.assertEqual(result.inputs, ("current", "prior"))

    def test_margin_correct_cost_field(self):
        result = gross_margin(fact("income", "100"), fact("cost", "20", metric="operating_costs"))
        self.assertEqual(result.result.value, Decimal("80"))
        self.assertEqual(result.result.scope.unit, "percent")

    def test_margin_rejects_operating_total_expenses(self):
        with self.assertRaises(CalculationError):
            gross_margin(fact(), fact("expense", "20", metric="operating_expenses"))

    def test_scope_guards_for_margin(self):
        for changes in ({"consolidation": "parent"}, {"currency": "USD"}, {"unit": "million_yuan"},
                        {"basis": Basis.SINGLE}, {"accounting": "adjusted"}, {"value_kind": "forecast"}):
            with self.subTest(changes=changes), self.assertRaises(CalculationError):
                gross_margin(fact(), fact("cost", "20", metric="operating_costs", **changes))

    def test_missing_and_unverified_are_not_zero(self):
        for item in (fact(value=None), replace(fact(), verification=Verification.PARTIAL)):
            with self.subTest(item=item), self.assertRaises(CalculationError):
                gross_margin(item, fact("cost", "20", metric="operating_costs"))

    def test_unknown_scope_rejected(self):
        for changes in ({"basis": Basis.UNKNOWN}, {"consolidation": "unknown"}, {"unit": "unknown"},
                        {"currency": "unknown"}, {"value_kind": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(CalculationError):
                yoy(fact("a", "100", year=2026, **changes), fact("b", "80", **changes))

    def test_nonpositive_denominators(self):
        for value in ("0", "-1"):
            with self.subTest(value=value), self.assertRaises(CalculationError):
                yoy(fact("a", "120", year=2026), fact("b", value))
            with self.subTest(value=value), self.assertRaises(CalculationError):
                gross_margin(fact(value=value), fact("cost", "20", metric="operating_costs"))

    def test_period_alignment_required_for_yoy(self):
        with self.assertRaises(CalculationError):
            yoy(fact("a", "120", year=2026, end_month=6), fact("b", "100", end_month=3))
        with self.assertRaises(CalculationError):
            yoy(fact("a", "120", year=2027), fact("b", "100", year=2025))

    def test_cumulative_subtracts_values_not_ratios(self):
        result = cumulative_to_single(fact("h1", "250", end_month=6), fact("q1", "100"))
        self.assertEqual(result.result.value, Decimal("150"))
        self.assertEqual(result.result.scope.start, date(2025, 4, 1))
        self.assertEqual(result.result.scope.basis, Basis.SINGLE)
        with self.assertRaises(CalculationError):
            cumulative_to_single(fact("m1", "90", metric="gross_margin", end_month=6),
                                 fact("m2", "80", metric="gross_margin"))

    def test_difference_must_be_one_quarter(self):
        with self.assertRaises(CalculationError):
            cumulative_to_single(fact("annual", "400", end_month=12), fact("q1", "100"))
        with self.assertRaises(CalculationError):
            cumulative_to_single(fact("h1", "250", end_month=6), fact("other", "100", year=2024))

    def test_single_cannot_be_subtracted_as_ytd(self):
        with self.assertRaises(CalculationError):
            cumulative_to_single(fact("a", "200", end_month=6, basis=Basis.SINGLE),
                                 fact("b", "100", basis=Basis.SINGLE))

    def test_margin_delta_is_percentage_points(self):
        a = gross_margin(fact("a", "100", year=2026), fact("ac", "30", metric="operating_costs", year=2026))
        b = gross_margin(fact("b", "100"), fact("bc", "20", metric="operating_costs"))
        delta = margin_delta(a.result, b.result)
        self.assertEqual(delta.result.value, Decimal("-10"))
        self.assertEqual(delta.result.scope.unit, "percentage_points")

    def test_global_decimal_context_does_not_change_results(self):
        context = getcontext()
        old = context.prec
        try:
            context.prec = 5
            short = gross_margin(fact("a", "3"), fact("c", "1", metric="operating_costs"))
            context.prec = 50
            long = gross_margin(fact("a", "3"), fact("c", "1", metric="operating_costs"))
            self.assertEqual(short, long)
        finally:
            context.prec = old
