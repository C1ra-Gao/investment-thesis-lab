"""Append-only M2 snapshots, confirmations, runs and change-condition checks."""

from datetime import date
import json
from time import perf_counter
from sqlalchemy import Column, Integer, String, Text, ForeignKey, MetaData, Table, select

from .domain import ContractError, encode, identifier, require_text
from .schema import ConflictRecord, CalculationRecord
from .store import now
from .research import validate_draft, compare_predicate, ancestors, revision_impact


metadata = MetaData()
records = Table("research_records", metadata,
                Column("id", String, primary_key=True), Column("kind", String, nullable=False),
                Column("thesis_id", String, nullable=False, index=True),
                Column("parent_id", String, ForeignKey("research_records.id")),
                Column("payload", Text, nullable=False))
versions = Table("research_schema_history", metadata,
                 Column("version", Integer, primary_key=True), Column("recorded_at", String, nullable=False))


def upgrade_research(engine):
    """Additive v1 -> v2 migration. M1 schema_version=1 remains immutable history.

    PRAGMA user_version is the current version. M1 artifacts are not rewritten.
    SQLAlchemy SQLite transactional DDL is explicitly wrapped in BEGIN IMMEDIATE.
    """
    with engine.connect() as c:
        c.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            version = c.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version not in (1, 2):raise ContractError("unsupported_research_schema")
            if version == 1:
                metadata.create_all(c)
                c.execute(versions.insert().values(version=2, recorded_at=now()))
                for table in metadata.tables:
                    for op in ("UPDATE", "DELETE"):
                        c.exec_driver_sql(f'CREATE TRIGGER "immutable_{table}_{op.lower()}" BEFORE {op} ON "{table}" '
                                          "BEGIN SELECT RAISE(ABORT, 'append_only_record'); END")
                c.exec_driver_sql("PRAGMA user_version=2")
            else:
                if c.execute(select(versions.c.version)).scalar_one() != 2:
                    raise ContractError("research_schema_history_mismatch")
            c.commit()
        except Exception:
            c.rollback()
            raise


class ResearchEngine:
    def __init__(self, store):
        self.store = store
        upgrade_research(store.engine)

    def get(self, object_id, kind=None):
        with self.store.engine.connect() as c:
            row = c.execute(select(records).where(records.c.id == object_id)).mappings().first()
        if not row:raise KeyError(object_id)
        if kind and row["kind"] != kind:raise ContractError("wrong_research_record_kind")
        return json.loads(row["payload"])

    def _save(self, kind, thesis_id, payload, parent_id=None):
        require_text(thesis_id, "thesis_id")
        object_id = identifier(kind, {"thesis_id": thesis_id, "parent_id": parent_id, "payload": payload})
        with self.store.sessions.begin() as session:
            if session.execute(select(records.c.id).where(records.c.id == object_id)).first():return object_id
            session.execute(records.insert().values(id=object_id, kind=kind, thesis_id=thesis_id,
                                                    parent_id=parent_id, payload=encode(payload)))
            self.store._audit(session, "research_" + kind + "_saved", object_id,
                              actor=payload.get("reviewer", "local_operator"))
        return object_id

    def draft(self, thesis_id, data, *, origin="manual", parent_id=None, reason=None):
        if origin not in ("manual", "model_candidate", "synthetic_test"):
            raise ContractError("unknown_draft_origin")
        data = validate_draft(data)
        impact = None
        if parent_id:
            parent = self.get(parent_id, "confirmation")
            if parent["thesis_id"] != thesis_id:raise ContractError("revision_cannot_switch_thesis")
            require_text(reason, "revision_reason")
            impact = revision_impact(self.get(parent["draft_id"], "draft")["design"], data)
        return self._save("draft", thesis_id, {"thesis_id": thesis_id, "design": data, "origin": origin,
                                              "parent_confirmation": parent_id, "reason": reason,
                                              "impact": impact, "created_at": now()}, parent_id)

    def confirm(self, draft_id, *, reviewer, meaning_reviewed, accepted_suggestions, budget):
        require_text(reviewer, "reviewer")
        if meaning_reviewed is not True:raise ContractError("explicit_meaning_review_required")
        draft = self.get(draft_id, "draft")
        design = draft["design"]
        if any(q["critical"] and not q["answer"] for q in design["clarifications"]):
            raise ContractError("critical_ambiguity_unresolved")
        suggestions = {c["id"] for c in design["claims"] if c["origin"] == "suggestion"}
        if set(accepted_suggestions) != suggestions:
            raise ContractError("suggestions_require_acceptance_or_revised_draft")
        # Offline M2 executes only existing local evidence, never APIs or models.
        if budget != {"llm_calls": 0, "financial_calls": 0} or any(type(v) is not int for v in budget.values()):
            raise ContractError("M2_offline_budget_must_be_zero")
        return self._save("confirmation", draft["thesis_id"], {
            "thesis_id": draft["thesis_id"], "draft_id": draft_id, "reviewer": reviewer,
            "meaning_reviewed": True, "accepted_suggestions": sorted(suggestions),
            "budget": budget, "confirmed_at": now()}, draft_id)

    def _design(self, confirmation_id):
        confirmed = self.get(confirmation_id, "confirmation")
        return confirmed, self.get(confirmed["draft_id"], "draft")["design"]

    def _lineage_ids(self, evidence_id):
        ids = {evidence_id}
        with self.store.sessions() as session:
            row = session.scalar(select(CalculationRecord).where(CalculationRecord.result_id == evidence_id))
            inputs = json.loads(row.payload)["inputs"] if row else []
        for i in inputs:ids |= self._lineage_ids(i)
        return ids

    def _conflicts(self, evidence_id):
        ids = self._lineage_ids(evidence_id)
        with self.store.sessions() as session:
            candidates = list(session.scalars(select(ConflictRecord).where(
                ConflictRecord.left_id.in_(ids) | ConflictRecord.right_id.in_(ids))))
        return [self.store.conflict_state(c.id) for c in candidates]

    def evaluate(self, confirmation_id, bindings, *, reviewer, as_of):
        """Bindings map EvidenceTasks to existing M1 evidence; no retrieval.

        Numeric rules run here; nonnumeric relations need explicit human review.
        New facts/forecast outcomes cannot be supplied as model-only strings.
        """
        require_text(reviewer, "reviewer")
        started = perf_counter()
        as_of_date = date.fromisoformat(as_of)
        confirmed, design = self._design(confirmation_id)
        tasks = {t["id"]: t for t in design["tasks"]}
        nodes = {c["id"]: c for c in design["claims"]}
        task_results, observations = [], {i: [] for i in nodes}
        if not isinstance(bindings, dict) or not set(bindings) <= tasks.keys():
            raise ContractError("unknown_task_binding")
        for task_id, t in tasks.items():
            binding = bindings.get(task_id)
            base = {"task_id": task_id, "claim_id": t["claim_id"], "purpose": t["purpose"]}
            if binding is None:
                task_results.append({**base, "state": "evidence_missing", "capability": t["capability"]})
                continue
            if not isinstance(binding, dict) or set(binding) - {"evidence_id", "direction", "reason", "human_verified"}:
                raise ContractError("invalid_evidence_binding")
            e = self.store.evidence(binding["evidence_id"])
            conflicts = self._conflicts(e.id)
            blocked = [c["conflict"]["id"] for c in conflicts if c["state"] == "unresolved" and c["conflict"]["material"]]
            lineage = self._lineage_ids(e.id)
            for c in conflicts:
                if c["state"] == "resolved" and c["conflict"]["material"]:
                    chosen = c["reviews"][-1]["selected_evidence_id"]
                    rejected = {c["conflict"]["left_id"], c["conflict"]["right_id"]} - {chosen}
                    if rejected & lineage:blocked.append("review_rejected_input_recalculate:" + c["conflict"]["id"])
            dates = []
            for i in self._lineage_ids(e.id):
                leaf = self.store.evidence(i)
                if leaf.issuer_disclosure_date:dates.append(leaf.issuer_disclosure_date)
                elif leaf.origin == "provider":
                    blocked.append("provider_disclosure_time_unverified:" + i)
            temporal = (e.scope.end > as_of_date or any(d > as_of_date for d in dates))
            direction, reason = "unverifiable", "unverified_or_missing_evidence"
            claim = nodes[t["claim_id"]]
            if claim["kind"] == "forecast":
                horizon = claim["qualifiers"].get("forecast_end")
                temporal = temporal or horizon is None or date.fromisoformat(horizon) > as_of_date
            if blocked:reason = "unresolved_material_conflict_or_time_semantics"
            elif temporal:reason = "not_available_within_as_of"
            elif e.verification.value == "verified" and e.value is not None:
                if "predicate" in claim:
                    result = compare_predicate(e, claim["predicate"])
                    direction = "unverifiable" if result is None else "supports" if result else "opposes"
                    reason = "unknown_scope_or_forecast_value" if result is None else "confirmed_decimal_predicate"
                else:
                    if binding.get("human_verified") is not True or binding.get("direction") not in ("supports", "opposes", "unverifiable"):
                        raise ContractError("nonnumeric_assessment_requires_explicit_human_review")
                    require_text(binding.get("reason"), "human_assessment_reason")
                    direction, reason = binding["direction"], binding["reason"]
                    if claim["kind"] in ("causal", "attribution") and claim["qualifiers"].get("identification_gap") and direction == "supports":
                        direction, reason = "unverifiable", "causal_or_attribution_identification_gap"
            observation = {**base, "evidence_id": e.id, "direction": direction, "reason": reason,
                           "quality": e.verification.value, "origin": e.origin,
                           "blocking_conflicts": blocked,
                           "conflicts": conflicts, "lineage_ids": sorted(self._lineage_ids(e.id)),
                           "reviewer": reviewer}
            # Rival-discrimination observations do not vote on the original claim.
            if t["purpose"] != "discriminate":observations[t["claim_id"]].append(observation)
            task_results.append({**observation, "state": "evaluated"})
        results = {}
        def solve(i):
            if i in results:return results[i]
            node = nodes[i]
            children = [r["from_id"] for r in design["relations"]
                        if r["to_id"] == i and r["kind"] == node["rule"]]
            obs = observations[i]
            directions = {o["direction"] for o in obs}
            dependencies = sorted({j for o in obs for j in o["lineage_ids"]})
            reason = "no_admissible_evidence"
            state = "unverifiable"
            if node["rule"] != "atomic":
                child_results = [solve(j) for j in children]
                states = [r["state"] for r in child_results]
                dependencies = sorted({j for r in child_results for j in r["evidence_dependencies"]})
                if node["rule"] == "and":
                    state = "opposes" if "opposes" in states else "supports" if all(s == "supports" for s in states) else "unverifiable"
                else:
                    state = "supports" if "supports" in states else "opposes" if all(s == "opposes" for s in states) else "unverifiable"
                reason = "logical_" + node["rule"]
            elif any(o["blocking_conflicts"] for o in obs):
                reason = "unresolved_material_conflict_or_rejected_input"
            elif {"supports", "opposes"} <= directions:
                reason = "unresolved_assessment_disagreement"
            elif "supports" in directions:state, reason = "supports", "admissible_support"
            elif "opposes" in directions:state, reason = "opposes", "admissible_counterevidence"
            # Necessary premises can refute but can never prove a causal mechanism.
            necessities = [solve(r["from_id"]) for r in design["relations"]
                           if r["to_id"] == i and r["kind"] == "necessary_for"]
            dependencies = sorted(set(dependencies) | {j for r in necessities for j in r["evidence_dependencies"]})
            if any(r["state"] == "opposes" for r in necessities):state, reason = "opposes", "necessary_premise_refuted"
            elif necessities and any(r["state"] != "supports" for r in necessities) and state == "supports":
                state, reason = "unverifiable", "necessary_premise_unverified"
            results[i] = {"state": state, "reason": reason, "evidence_dependencies": dependencies,
                          "observations": obs, "children": children}
            return results[i]
        for i in nodes:solve(i)
        payload = {"thesis_id": confirmed["thesis_id"], "confirmation_id": confirmation_id,
                   "reviewer": reviewer, "as_of": as_of, "created_at": now(), "claims": results,
                   "conclusion": results[design["root_id"]], "tasks": task_results,
                   "condition_ids": [c["id"] for c in design["conditions"]],
                   "usage": {"llm_calls": 0, "financial_calls": 0, "tokens": None, "cost": None},
                   "input_mode": "existing_local_evidence", "validity": "current_run_snapshot"}
        payload["evidence_origins"] = sorted({r["origin"] for r in task_results if "origin" in r})
        payload["research_status"] = "partial" if any(
            t["state"] == "evidence_missing" or t.get("direction") == "unverifiable" for t in task_results) else "evaluated"
        payload["limitations"] = {
            "condition_gaps": {c["id"]: c["condition_gap"] for c in design["claims"] if c["condition_gap"]},
            "missing_task_ids": [t["task_id"] for t in task_results if t["state"] == "evidence_missing"],
            "semantic_equivalence": "human_reviewed_not_machine_proven",
            "historical_point_in_time": "not_supported"}
        payload["usage"].update({"model": None, "model_status": "not_called",
                                 "duration_ms": round((perf_counter() - started) * 1000, 3),
                                 "tool_retries": 0, "external_tool_failures": 0,
                                 "local_evidence_bindings": len(bindings)})
        return self._save("run", confirmed["thesis_id"], payload, confirmation_id)

    def check_condition(self, confirmation_id, condition_id, *, reviewer, observed_on,
                        evidence_id=None, event_occurred=None, reason=None):
        require_text(reviewer, "reviewer")
        confirmed, design = self._design(confirmation_id)
        condition = next((c for c in design["conditions"] if c["id"] == condition_id), None)
        if condition is None:raise ContractError("unknown_condition")
        day = date.fromisoformat(observed_on)
        if not date.fromisoformat(condition["start"]) <= day <= date.fromisoformat(condition["end"]):
            raise ContractError("observation_outside_condition_window")
        triggered = None
        if condition["mode"] == "threshold":
            if evidence_id:
                e = self.store.evidence(evidence_id)
                if e.scope.end > day:raise ContractError("future_evidence_condition")
                for i in self._lineage_ids(e.id):
                    leaf = self.store.evidence(i)
                    if leaf.issuer_disclosure_date and leaf.issuer_disclosure_date > day:
                        raise ContractError("undisclosed_evidence_condition")
                    if leaf.origin == "provider" and not leaf.issuer_disclosure_date:
                        raise ContractError("provider_time_semantics_unverified")
                if any(c["state"] == "unresolved" and c["conflict"]["material"] for c in self._conflicts(e.id)):
                    raise ContractError("unresolved_condition_evidence_conflict")
                triggered = compare_predicate(e, condition["predicate"])
        elif event_occurred is not None:
            if type(event_occurred) is not bool or not evidence_id:
                raise ContractError("manual_event_requires_evidence_and_boolean")
            e = self.store.evidence(evidence_id)
            require_text(reason, "manual_event_review_reason")
            if e.scope.end > day:raise ContractError("future_evidence_condition")
            for i in self._lineage_ids(e.id):
                leaf = self.store.evidence(i)
                if leaf.issuer_disclosure_date and leaf.issuer_disclosure_date > day:
                    raise ContractError("undisclosed_evidence_condition")
                if leaf.origin == "provider" and not leaf.issuer_disclosure_date:
                    raise ContractError("provider_time_semantics_unverified")
            if any(c["state"] == "unresolved" and c["conflict"]["material"] for c in self._conflicts(e.id)):
                raise ContractError("unresolved_condition_evidence_conflict")
            if e.verification.value == "verified" and e.value is not None:triggered = event_occurred
        effects = {"falsify": "falsification_proposed", "weaken": "weakening_proposed", "revalidate": "needs_revalidation"}
        payload = {"thesis_id": confirmed["thesis_id"], "confirmation_id": confirmation_id,
                   "condition_id": condition_id, "reviewer": reviewer, "observed_on": observed_on,
                   "evidence_id": evidence_id, "reason": reason, "triggered": triggered,
                   "check_state": "unknown" if triggered is None else "triggered" if triggered else "not_triggered",
                   "effect": effects[condition["kind"]] if triggered else "no_confirmed_change",
                   "affected_claims": ancestors(design, condition["claim_ids"]) if triggered else [],
                   "old_conclusions_modified": False, "recorded_at": now()}
        return self._save("condition_check", confirmed["thesis_id"], payload, confirmation_id)

    def history(self, thesis_id):
        with self.store.engine.connect() as c:
            return [{"id": r["id"], "kind": r["kind"], "parent_id": r["parent_id"],
                     "payload": json.loads(r["payload"])} for r in c.execute(
                         select(records).where(records.c.thesis_id == thesis_id)).mappings()]
