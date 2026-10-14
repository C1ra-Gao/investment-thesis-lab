"""Small, immutable contracts. Evidence quality and claim direction are separate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from typing import Any
from urllib.parse import urlparse


class ContractError(ValueError):
    pass


class Basis(StrEnum):
    YTD = "ytd"
    SINGLE = "single_period"
    UNKNOWN = "unknown"


class Direction(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NOT_DETERMINED = "not_determined"


class Verification(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    UNVERIFIABLE = "unverifiable"


def encode(value: Any) -> str:
    def default(obj: Any) -> Any:
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(type(obj).__name__)
    return json.dumps(value, default=default, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def identifier(prefix: str, payload: Any) -> str:
    return prefix + ":" + hashlib.sha256(encode(payload).encode()).hexdigest()


def amount(value: str | int | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (float, bool)):
        raise ContractError("binary_float_or_boolean_not_allowed")
    try:
        result = Decimal(value)
    except Exception as exc:
        raise ContractError("invalid_decimal") from exc
    if not result.is_finite():
        raise ContractError("non_finite_decimal")
    return result


def require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("missing_" + field)


@dataclass(frozen=True)
class Scope:
    entity: str
    metric: str
    start: date
    end: date
    currency: str
    unit: str
    consolidation: str
    basis: Basis
    accounting: str = "statutory"
    value_kind: str = "actual"

    def __post_init__(self) -> None:
        for field in ("entity", "metric", "currency", "unit", "consolidation",
                      "accounting", "value_kind"):
            require_text(getattr(self, field), field)
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ContractError("invalid_period")
        if not isinstance(self.basis, Basis):
            raise ContractError("invalid_basis")
        if self.consolidation not in ("consolidated", "parent", "unknown"):
            raise ContractError("invalid_consolidation")
        if self.value_kind not in ("actual", "forecast", "unknown"):
            raise ContractError("invalid_value_kind")


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    kind: str
    rights: str = "internal_validation_only_public_rights_unverified"
    disclosed_on: date | None = None
    disclosure_locator: str | None = None

    def __post_init__(self) -> None:
        for field in ("id", "name", "kind", "rights"):
            require_text(getattr(self, field), field)
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ContractError("invalid_source_url")
        if self.disclosed_on and not self.disclosure_locator:
            raise ContractError("disclosure_date_requires_locator")


@dataclass(frozen=True)
class Locator:
    artifact_id: str
    json_pointer: str | None = None
    page: int | None = None
    table: str | None = None
    row: str | None = None
    column: str | None = None

    def __post_init__(self) -> None:
        require_text(self.artifact_id, "artifact_id")
        if (self.json_pointer is not None) == (self.page is not None):
            raise ContractError("locator_needs_exactly_one_channel")
        if self.json_pointer is not None:
            if not self.json_pointer.startswith("/"):
                raise ContractError("invalid_json_pointer")
        else:
            if type(self.page) is not int or self.page < 1:
                raise ContractError("invalid_pdf_page")
            for field in ("table", "row", "column"):
                require_text(getattr(self, field), field)


@dataclass(frozen=True)
class Evidence:
    id: str
    scope: Scope
    value: Decimal | None
    verification: Verification
    origin: str
    locator: Locator | None = None
    provider_report_date: date | None = None
    issuer_disclosure_date: date | None = None
    reported_period_label: str | None = None
    raw_lexeme: str | None = None
    limitation: str | None = None

    def __post_init__(self) -> None:
        require_text(self.id, "evidence_id")
        if self.value is not None and (not isinstance(self.value, Decimal) or not self.value.is_finite()):
            raise ContractError("value_must_be_finite_decimal")
        if not isinstance(self.verification, Verification):
            raise ContractError("invalid_verification")
        if self.origin not in ("provider", "issuer", "calculation", "synthetic_test"):
            raise ContractError("invalid_origin")
        if self.origin in ("provider", "issuer") and self.locator is None:
            raise ContractError("raw_evidence_requires_locator")
        if self.value is None and self.verification == Verification.VERIFIED:
            raise ContractError("missing_value_cannot_be_verified")


@dataclass(frozen=True)
class Calculation:
    id: str
    operation: str
    formula: str
    inputs: tuple[str, ...]
    result: Evidence
    version: str = "decimal32-v1"

    def __post_init__(self) -> None:
        if not self.inputs or self.result.origin != "calculation":
            raise ContractError("invalid_calculation_lineage")


@dataclass(frozen=True)
class Conflict:
    id: str
    kind: str
    left_id: str
    right_id: str
    field: str
    details: dict[str, Any]
    material: bool = True


@dataclass(frozen=True)
class Assessment:
    subclaim_id: str
    evidence_id: str
    direction: Direction
    verification: Verification
    reason: str

    def __post_init__(self) -> None:
        require_text(self.reason, "assessment_reason")
        if not isinstance(self.direction, Direction) or not isinstance(self.verification, Verification):
            raise ContractError("invalid_assessment_enum")
        if self.verification != Verification.VERIFIED and self.direction != Direction.NOT_DETERMINED:
            raise ContractError("unverified_evidence_cannot_support_or_oppose")


@dataclass(frozen=True)
class Subclaim:
    id: str
    statement: str
    kind: str = "fact"

    def __post_init__(self) -> None:
        require_text(self.id, "subclaim_id")
        require_text(self.statement, "statement")
        if self.statement.rstrip().endswith(("?", "？")):
            raise ContractError("subclaim_must_be_statement_not_task_question")
        if self.kind not in ("fact", "causal", "forecast", "attribution", "assumption"):
            raise ContractError("invalid_claim_kind")


@dataclass(frozen=True)
class ClaimRelation:
    from_id: str
    to_id: str
    kind: str


@dataclass(frozen=True)
class ThesisRevision:
    id: str
    thesis_id: str
    statement: str
    subclaims: tuple[Subclaim, ...]
    relations: tuple[ClaimRelation, ...] = ()
    parent_id: str | None = None

    def __post_init__(self) -> None:
        require_text(self.statement, "statement")
        ids = [c.id for c in self.subclaims]
        if not ids or len(ids) != len(set(ids)):
            raise ContractError("empty_or_duplicate_subclaims")
        nodes = set(ids)
        graph: dict[str, list[str]] = {i: [] for i in ids}
        for edge in self.relations:
            if edge.from_id not in nodes or edge.to_id not in nodes:
                raise ContractError("unknown_relation_endpoint")
            if edge.kind not in ("necessary_for", "and", "or", "mechanism", "alternative", "comparison"):
                raise ContractError("invalid_relation_kind")
            if edge.kind not in ("alternative", "comparison"):
                graph[edge.from_id].append(edge.to_id)
        visiting, done = set(), set()
        def visit(node: str) -> None:
            if node in visiting:
                raise ContractError("cyclic_logical_dependencies")
            if node in done:
                return
            visiting.add(node)
            for child in graph[node]:
                visit(child)
            visiting.remove(node)
            done.add(node)
        for node in nodes:
            visit(node)


def evidence_from_dict(data: dict[str, Any]) -> Evidence:
    s = data["scope"].copy()
    s["start"], s["end"] = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
    s["basis"] = Basis(s["basis"])
    values = data.copy()
    values["scope"] = Scope(**s)
    values["value"] = amount(values["value"])
    values["verification"] = Verification(values["verification"])
    values["locator"] = Locator(**values["locator"]) if values["locator"] else None
    for field in ("provider_report_date", "issuer_disclosure_date"):
        values[field] = date.fromisoformat(values[field]) if values[field] else None
    return Evidence(**values)
