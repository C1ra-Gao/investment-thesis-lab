"""M2 candidate contracts and deterministic reasoning. No model or network calls.

Span/coverage checks constrain structure, not semantic equivalence. Human review
is mandatory; no heuristic parser claims to understand arbitrary investment text.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Protocol

from .domain import ContractError, ThesisRevision, Subclaim, ClaimRelation, encode, amount, require_text


OPS = {"gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
       "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
       "eq": lambda a, b: a == b}
SCOPE_FIELDS = {"entity", "metric", "start", "end", "currency", "unit", "consolidation",
                "basis", "accounting", "value_kind"}


def exact_keys(obj, required, optional=()):
    if not isinstance(obj, dict) or set(obj) - set(required) - set(optional) or set(required) - set(obj):
        raise ContractError("invalid_contract_fields")


def predicate(value):
    exact_keys(value, ("scope", "operator", "threshold"))
    exact_keys(value["scope"], SCOPE_FIELDS)
    from .domain import Scope, Basis
    fields = value["scope"].copy()
    fields["start"], fields["end"] = date.fromisoformat(fields["start"]), date.fromisoformat(fields["end"])
    fields["basis"] = Basis(fields["basis"])
    Scope(**fields)
    if value["operator"] not in OPS or amount(value["threshold"]) is None:
        raise ContractError("invalid_threshold_predicate")


def validate_draft(data):
    """Strict, vendor-neutral candidate input; returns a defensive copy."""
    exact_keys(data, ("statement", "root_id", "claims", "relations", "clarifications", "tasks", "conditions"))
    require_text(data["statement"], "thesis_statement")
    if data["statement"].rstrip().endswith(("?", "？")):
        raise ContractError("thesis_must_be_declarative")
    claims = data["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= 64:
        raise ContractError("invalid_claim_count")
    nodes = {}
    coverage = set()
    for c in claims:
        exact_keys(c, ("id", "statement", "kind", "origin", "spans", "qualifiers", "rule", "important",
                       "condition_gap"), ("predicate",))
        Subclaim(c["id"], c["statement"], c["kind"])
        if c["id"] in nodes or c["origin"] not in ("original", "suggestion"):
            raise ContractError("duplicate_claim_or_unknown_origin")
        if c["rule"] not in ("atomic", "and", "or") or type(c["important"]) is not bool:
            raise ContractError("invalid_claim_rule")
        if c["kind"] in ("causal", "forecast", "attribution") and c["rule"] != "atomic":
            raise ContractError("mechanism_requires_independent_verification")
        if not isinstance(c["qualifiers"], dict) or not isinstance(c["spans"], list):
            raise ContractError("invalid_semantic_annotations")
        if c["origin"] == "original" and not c["spans"]:
            raise ContractError("original_claim_requires_span")
        for span in c["spans"]:
            exact_keys(span, ("start", "end", "text"))
            a, b = span["start"], span["end"]
            if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(data["statement"]):
                raise ContractError("invalid_original_span")
            if data["statement"][a:b] != span["text"]:
                raise ContractError("span_does_not_match_original")
            if c["origin"] == "original":coverage.update(range(a, b))
        if "predicate" in c:
            predicate(c["predicate"])
            if c["rule"] != "atomic" or c["kind"] != "fact":
                raise ContractError("numeric_predicate_only_for_atomic_fact")
        nodes[c["id"]] = c
    # Every nonpunctuation character needs a source mapping. This does not prove
    # preservation of negation or causal meaning; confirmation covers semantics.
    if any(i not in coverage for i, char in enumerate(data["statement"]) if char.isalnum()):
        raise ContractError("unmapped_original_text")
    if data["root_id"] not in nodes or nodes[data["root_id"]]["origin"] != "original":
        raise ContractError("invalid_root")
    edges = []
    seen = set()
    for r in data["relations"]:
        exact_keys(r, ("from_id", "to_id", "kind"))
        key = (r["from_id"], r["to_id"], r["kind"])
        if key in seen:raise ContractError("duplicate_relation")
        seen.add(key)
        if r["kind"] in ("and", "or"):
            if r["to_id"] not in nodes or nodes[r["to_id"]]["rule"] != r["kind"]:
                raise ContractError("mixed_combination_rule")
        edges.append(ClaimRelation(**r))
    ThesisRevision("candidate", "candidate", data["statement"],
                   tuple(Subclaim(c["id"], c["statement"], c["kind"]) for c in claims), tuple(edges))
    for c in claims:
        children = [r for r in data["relations"] if r["to_id"] == c["id"] and r["kind"] == c["rule"]]
        if c["rule"] != "atomic" and not children:
            raise ContractError("empty_combination_node")
    for q in data["clarifications"]:
        exact_keys(q, ("id", "claim_ids", "field", "question", "critical", "answer"))
        require_text(q["id"], "clarification_id")
        require_text(q["field"], "clarification_field")
        require_text(q["question"], "clarification_question")
        if type(q["critical"]) is not bool or not q["claim_ids"] or not set(q["claim_ids"]) <= nodes.keys():
            raise ContractError("invalid_clarification")
        if q["answer"] is not None:require_text(q["answer"], "clarification_answer")
    task_ids = set()
    for t in data["tasks"]:
        exact_keys(t, ("id", "claim_id", "purpose", "action", "source_requirement", "capability", "acceptance"))
        if t["id"] in task_ids or t["claim_id"] not in nodes or t["purpose"] not in ("support", "refute", "discriminate"):
            raise ContractError("invalid_evidence_task")
        task_ids.add(t["id"])
        if t["capability"] not in ("local_verified", "unverified", "unavailable"):
            raise ContractError("invalid_capability")
        for f in ("id", "action", "source_requirement", "acceptance"):require_text(t[f], f)
    condition_ids = set()
    for c in data["conditions"]:
        exact_keys(c, ("id", "kind", "claim_ids", "observation", "start", "end", "source_requirement", "mode"),
                   ("predicate",))
        if c["id"] in condition_ids or c["kind"] not in ("falsify", "weaken", "revalidate"):
            raise ContractError("invalid_change_condition")
        condition_ids.add(c["id"])
        if not c["claim_ids"] or not set(c["claim_ids"]) <= nodes.keys():
            raise ContractError("invalid_condition_targets")
        for f in ("id", "observation", "source_requirement"):require_text(c[f], f)
        if date.fromisoformat(c["start"]) > date.fromisoformat(c["end"]):
            raise ContractError("invalid_condition_window")
        if c["mode"] == "threshold":
            predicate(c.get("predicate"))
        elif c["mode"] != "manual_event" or "predicate" in c:
            raise ContractError("invalid_condition_mode")
    for c in claims:
        if c["rule"] == "atomic" and c["origin"] == "original":
            purposes = {t["purpose"] for t in data["tasks"] if t["claim_id"] == c["id"]}
            if not {"support", "refute"} <= purposes:
                raise ContractError("missing_support_or_refutation_task")
        if c["kind"] in ("causal", "attribution") and not any(
                t["claim_id"] == c["id"] and t["purpose"] == "discriminate" for t in data["tasks"]):
            require_text(c["qualifiers"].get("identification_gap"), "identification_gap")
        if c["important"] and not any(c["id"] in x["claim_ids"] for x in data["conditions"]):
            require_text(c["condition_gap"], "condition_gap")
    return deepcopy(data)


class CandidateProvider(Protocol):
    """Injection boundary only; no bundled provider, credentials or HTTP client."""
    def candidate(self, statement: str) -> dict: ...


def request_candidate(statement: str, provider: CandidateProvider | None = None, *, authorized=False):
    if not authorized or provider is None:
        raise ContractError("model_calls_not_authorized_or_configured")
    result = validate_draft(provider.candidate(statement))
    if result["statement"] != statement:
        raise ContractError("provider_changed_original_statement")
    return result


def ancestors(data, ids):
    result = set(ids)
    while True:
        expanded = result | {r["to_id"] for r in data["relations"]
                             if r["from_id"] in result and r["kind"] not in ("alternative", "comparison")}
        if expanded == result:return sorted(result)
        result = expanded


def revision_impact(old, new):
    previous = {c["id"]: c for c in old["claims"]}
    current = {c["id"]: c for c in new["claims"]}
    changed = {i for i in previous.keys() | current.keys() if encode(previous.get(i)) != encode(current.get(i))}
    if encode(old["relations"]) != encode(new["relations"]):
        changed |= {r["to_id"] for r in old["relations"] + new["relations"]}
    if encode(old["conditions"]) != encode(new["conditions"]):
        changed |= {i for c in old["conditions"] + new["conditions"] for i in c["claim_ids"]}
    if old["statement"] != new["statement"]:changed.add(new["root_id"])
    affected = set(ancestors(old, changed)) | set(ancestors(new, changed))
    return {"changed_claims": sorted(changed), "needs_revalidation": sorted(affected),
            "unchanged_claims": sorted(current.keys() - affected),
            "raw_evidence_policy": "retain_originals_recheck_scope_time_and_reassess_new_revision",
            "assessment_reuse": False}


def compare_predicate(evidence, p):
    if evidence.verification.value != "verified" or evidence.value is None:
        return None
    if encode(evidence.scope) != encode(p["scope"]):
        raise ContractError("predicate_evidence_scope_mismatch")
    if (evidence.scope.value_kind != "actual" or evidence.scope.consolidation == "unknown"
            or evidence.scope.basis.value == "unknown" or evidence.scope.accounting == "unknown"
            or evidence.scope.currency == "unknown" or evidence.scope.unit == "unknown"):
        return None
    return OPS[p["operator"]](evidence.value, amount(p["threshold"]))
