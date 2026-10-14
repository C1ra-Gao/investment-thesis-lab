"""Differences are classified before any numeric contradiction is alleged."""

from decimal import Decimal
from .domain import Conflict, Evidence, ContractError, identifier, amount


def detect(left: Evidence, right: Evidence, *, tolerance: Decimal = Decimal("0")) -> tuple[Conflict, ...]:
    tolerance = amount(tolerance)
    if tolerance is None or tolerance < 0:
        raise ContractError("invalid_tolerance")
    if left.id == right.id:
        return ()
    if (left.scope.entity, left.scope.metric) != (right.scope.entity, right.scope.metric):
        raise ContractError("unrelated_fields")
    dimensions = ("start", "end", "currency", "unit", "consolidation", "basis", "accounting", "value_kind")
    differences = {f: {"left": str(getattr(left.scope, f)), "right": str(getattr(right.scope, f))}
                   for f in dimensions if getattr(left.scope, f) != getattr(right.scope, f)}
    results = []
    def add(kind, field, details, material=True):
        payload = {"left": left.id, "right": right.id, "kind": kind, "field": field, "details": details}
        results.append(Conflict(identifier("conflict", payload), kind, left.id, right.id, field, details, material))
    if differences:
        add("scope_mismatch", "scope", differences)
        return tuple(results)
    unknown = [f for f in ("currency", "unit", "consolidation", "basis", "accounting", "value_kind")
               if str(getattr(left.scope, f)) == "unknown"]
    if unknown:
        add("scope_unverified", "scope", {"unknown_dimensions": unknown})
        return tuple(results)
    if left.value is not None and right.value is not None and abs(left.value - right.value) > tolerance:
        add("numeric_mismatch", "value", {"left": str(left.value), "right": str(right.value),
                                         "tolerance": str(tolerance)})
    provider = left.provider_report_date or right.provider_report_date
    issuer = left.issuer_disclosure_date or right.issuer_disclosure_date
    if provider and issuer and provider != issuer:
        add("date_mismatch", "original_disclosure_date",
            {"provider_report_date": provider.isoformat(), "issuer_disclosure_date": issuer.isoformat(),
             "provider_field_meaning": "UNVERIFIED", "blocks": "historical_time_use_not_matched_values"},
            material=False)
    return tuple(results)
