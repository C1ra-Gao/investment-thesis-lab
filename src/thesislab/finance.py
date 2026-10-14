"""Whitelisted Decimal calculations with scope guards and immutable lineage."""

from dataclasses import replace
from datetime import timedelta, date
from decimal import localcontext, Decimal, ROUND_HALF_EVEN
import calendar

from .domain import Basis, Evidence, Calculation, Verification, ContractError, identifier


class CalculationError(ContractError):
    pass


def _usable(*items: Evidence) -> None:
    for item in items:
        if item.value is None:
            raise CalculationError("missing_input")
        if item.verification != Verification.VERIFIED:
            raise CalculationError("input_not_verified")
        if (item.scope.basis == Basis.UNKNOWN or item.scope.consolidation == "unknown"
                or item.scope.accounting == "unknown" or item.scope.value_kind != "actual"
                or item.scope.currency == "unknown" or item.scope.unit == "unknown"):
            raise CalculationError("scope_unknown_or_non_actual")


def _same(a: Evidence, b: Evidence, *, metric: bool = True, period: bool = True) -> None:
    fields = ["entity", "currency", "unit", "consolidation", "accounting", "value_kind", "basis"]
    if metric:
        fields.append("metric")
    if period:
        fields.extend(["start", "end"])
    mismatch = [f for f in fields if getattr(a.scope, f) != getattr(b.scope, f)]
    if mismatch:
        raise CalculationError("scope_mismatch:" + ",".join(mismatch))


def _year_pair(a: Evidence, b: Evidence) -> None:
    _same(a, b, period=False)
    for field in ("start", "end"):
        current, previous = getattr(a.scope, field), getattr(b.scope, field)
        if current.year != previous.year + 1 or current.month != previous.month:
            raise CalculationError("not_aligned_prior_year_period")
        # End-of-month dates remain aligned across leap years.
        if current.day != previous.day and not (
            current.day == calendar.monthrange(current.year, current.month)[1]
            and previous.day == calendar.monthrange(previous.year, previous.month)[1]
        ):
            raise CalculationError("not_aligned_prior_year_period")


def _result(operation: str, formula: str, inputs: tuple[Evidence, ...], value: Decimal,
            scope) -> Calculation:
    payload = {"operation": operation, "version": "decimal32-v1", "inputs": [i.id for i in inputs],
               "formula": formula, "value": str(value), "scope": scope}
    cid = identifier("calculation", payload)
    result = Evidence(cid + ":result", scope, value, Verification.VERIFIED, "calculation",
                      limitation="Computed from verified inputs; not independent assurance of issuer facts.")
    return Calculation(cid, operation, formula, tuple(i.id for i in inputs), result)


def yoy(current: Evidence, prior: Evidence) -> Calculation:
    _usable(current, prior)
    _year_pair(current, prior)
    if prior.value <= 0:
        raise CalculationError("non_positive_prior_denominator")
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 32, ROUND_HALF_EVEN
        value = (current.value / prior.value - 1) * 100
    scope = replace(current.scope, metric=current.scope.metric + "_yoy", unit="percent")
    return _result("yoy", "(current/prior-1)*100", (current, prior), value, scope)


def gross_margin(revenue: Evidence, costs: Evidence) -> Calculation:
    _usable(revenue, costs)
    _same(revenue, costs, metric=False)
    if revenue.scope.metric != "operating_income" or costs.scope.metric != "operating_costs":
        raise CalculationError("wrong_gross_margin_fields")
    if revenue.scope.unit != "yuan" or revenue.value <= 0:
        raise CalculationError("invalid_revenue_denominator_or_unit")
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 32, ROUND_HALF_EVEN
        value = (revenue.value - costs.value) / revenue.value * 100
    scope = replace(revenue.scope, metric="gross_margin", unit="percent")
    return _result("gross_margin", "(operating_income-operating_costs)/operating_income*100",
                   (revenue, costs), value, scope)


def margin_delta(current: Evidence, prior: Evidence) -> Calculation:
    _usable(current, prior)
    _year_pair(current, prior)
    if current.scope.metric != "gross_margin" or current.scope.unit != "percent":
        raise CalculationError("not_gross_margin_percent")
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 32, ROUND_HALF_EVEN
        value = current.value - prior.value
    scope = replace(current.scope, metric="gross_margin_change", unit="percentage_points")
    return _result("margin_delta", "current_gross_margin-prior_gross_margin", (current, prior), value, scope)


def cumulative_to_single(later: Evidence, earlier: Evidence) -> Calculation:
    _usable(later, earlier)
    _same(later, earlier, period=False)
    if later.scope.basis != Basis.YTD or later.scope.start != earlier.scope.start:
        raise CalculationError("not_same_cumulative_origin")
    if later.scope.metric not in ("operating_income", "operating_costs"):
        raise CalculationError("not_additive_flow")
    a, b = later.scope.end, earlier.scope.end
    if b.month not in (3, 6, 9) or b.day != calendar.monthrange(b.year, b.month)[1]:
        raise CalculationError("not_quarter_end")
    expected = date(b.year, b.month + 3, calendar.monthrange(b.year, b.month + 3)[1])
    if a != expected:
        raise CalculationError("difference_not_one_quarter")
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 32, ROUND_HALF_EVEN
        value = later.value - earlier.value
    scope = replace(later.scope, start=b + timedelta(days=1), basis=Basis.SINGLE)
    return _result("cumulative_to_single", "later_ytd-earlier_ytd", (later, earlier), value, scope)
