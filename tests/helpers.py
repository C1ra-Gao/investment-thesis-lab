"""All fixtures here are invented unit-test data, not financial observations."""

from datetime import date
from decimal import Decimal
from dataclasses import replace
from thesislab.domain import Scope, Evidence, Verification, Basis


def fact(id="synthetic-income", value="100", metric="operating_income", year=2025,
         end_month=3, basis=Basis.YTD, **scope_changes):
    end_day = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
    scope = Scope("SYNTHETIC:ENTITY", metric, date(year, 1, 1), date(year, end_month, end_day),
                  "CNY", "yuan", "consolidated", basis)
    scope = replace(scope, **scope_changes)
    return Evidence(id, scope, Decimal(value) if value is not None else None,
                    Verification.VERIFIED if value is not None else Verification.UNVERIFIABLE,
                    "synthetic_test")
