"""Append-only local repository with effective-field review projections."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from .domain import (Evidence, Calculation, Conflict, Source, ThesisRevision, Assessment, ContractError,
                     encode, identifier, evidence_from_dict, require_text)
from .schema import (SourceRecord, ArtifactRecord, EvidenceRecord, CalculationRecord,
                     CalculationInput, ConflictRecord, ReviewRecord, RevisionRecord,
                     CheckpointRecord, AuditRecord, AssessmentRecord, CrosscheckRecord)
from .migrations import upgrade
from .locators import json_value, pdf_value, verify_pdf_scope


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        if str(path) == ":memory:":
            url = "sqlite+pysqlite:///:memory:"
        else:
            path = Path(path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            url = "sqlite+pysqlite:///" + str(path)
        self.engine = create_engine(url)
        @event.listens_for(self.engine, "connect")
        def constraints(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
        upgrade(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _audit(session, action: str, object_id: str, actor: str = "local_operator", **details) -> None:
        session.add(AuditRecord(payload=encode({"action": action, "object_id": object_id,
                                              "actor": actor, "recorded_at": now(), **details})))

    def _payload(self, model, object_id: str) -> dict:
        with self.sessions() as session:
            row = session.get(model, object_id)
            if row is None:
                raise KeyError(object_id)
            return json.loads(row.payload)

    def put_source(self, source: Source) -> str:
        with self.sessions.begin() as session:
            old = session.get(SourceRecord, source.id)
            if old:
                if old.payload != encode(source):
                    raise ContractError("immutable_source_collision")
                return source.id
            session.add(SourceRecord(id=source.id, payload=encode(source)))
            self._audit(session, "source_added", source.id)
        return source.id

    def put_artifact(self, source_id: str, body: bytes, media_type: str, acquired_at: str,
                     local_reference: str = "") -> str:
        if not isinstance(body, bytes) or not body:
            raise ContractError("empty_or_non_bytes_artifact")
        dt = datetime.fromisoformat(acquired_at)
        if dt.tzinfo is None:
            raise ContractError("acquisition_time_requires_timezone")
        sha = hashlib.sha256(body).hexdigest()
        artifact_id = identifier("artifact", {"source_id": source_id, "sha256": sha})
        with self.sessions.begin() as session:
            if not session.get(SourceRecord, source_id):
                raise ContractError("unknown_source")
            existing = session.get(ArtifactRecord, artifact_id)
            if existing:
                if existing.body != body or existing.acquired_at != acquired_at:
                    raise ContractError("immutable_artifact_collision_or_new_acquisition")
                return artifact_id
            session.add(ArtifactRecord(id=artifact_id, source_id=source_id, body=body,
                                       sha256=sha, media_type=media_type, acquired_at=acquired_at,
                                       local_reference=local_reference))
            self._audit(session, "artifact_added", artifact_id, sha256=sha)
        return artifact_id

    def artifact(self, artifact_id: str) -> dict:
        with self.sessions() as session:
            row = session.get(ArtifactRecord, artifact_id)
            if row is None:
                raise KeyError(artifact_id)
            if hashlib.sha256(row.body).hexdigest() != row.sha256:
                raise ContractError("stored_artifact_integrity_failure")
            return {"id": row.id, "source_id": row.source_id, "body": row.body,
                    "sha256": row.sha256, "media_type": row.media_type,
                    "acquired_at": row.acquired_at, "local_reference": row.local_reference}

    @staticmethod
    def _insert_evidence(session, item: Evidence) -> None:
        old = session.get(EvidenceRecord, item.id)
        if old:
            if old.payload != encode(item):
                raise ContractError("immutable_evidence_collision")
            return
        session.add(EvidenceRecord(id=item.id, payload=encode(item),
                                   artifact_id=item.locator.artifact_id if item.locator else None))
        session.flush()

    def put_evidence(self, item: Evidence) -> None:
        if item.origin == "calculation":
            raise ContractError("use_put_calculation_for_derived_evidence")
        if item.locator:
            artifact = self.artifact(item.locator.artifact_id)
            source = self._payload(SourceRecord, artifact["source_id"])
            if item.origin == "synthetic_test" and source["kind"] != "synthetic_test":
                raise ContractError("synthetic_input_requires_synthetic_source")
            if source['kind'] == 'sec_xbrl' and item.locator.json_pointer:
                cursor = json.loads(artifact['body'], parse_float=Decimal)
                for part in item.locator.json_pointer.split('/')[1:]:
                    cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
                from .domain import amount
                expected = amount(cursor)
            else:
                expected = (json_value(artifact["body"], item.locator.json_pointer)
                            if item.locator.json_pointer else pdf_value(artifact["body"], item.locator))
            if item.value != expected:
                raise ContractError("evidence_value_does_not_match_raw_locator")
            if item.origin == "issuer":
                if (source["kind"] not in ("issuer_report", "sec_xbrl") or item.issuer_disclosure_date is None
                        or source["disclosed_on"] != item.issuer_disclosure_date.isoformat()):
                    raise ContractError("issuer_date_does_not_match_source_metadata")
                if source['kind'] == 'sec_xbrl':
                    from .live_providers import validate_sec_field
                    if not source['url'].startswith('https://data.sec.gov/api/xbrl/companyfacts/CIK'):
                        raise ContractError('invalid_sec_source_url')
                    validate_sec_field(json.loads(artifact['body']), item.locator.json_pointer,
                                       item.scope, item.issuer_disclosure_date)
                elif item.locator.page is None:
                    raise ContractError("M1_issuer_financial_field_requires_pdf_locator")
                else:
                    verify_pdf_scope(artifact["body"], item.locator, item.scope)
            elif item.origin == "provider":
                if source["kind"] != "provider_cache" or not item.locator.json_pointer:
                    raise ContractError("provider_field_requires_cached_json_source")
                raw = json.loads(artifact["body"], parse_float=Decimal)
                cursor = raw
                parts = item.locator.json_pointer.split("/")[1:]
                for part in parts[:-1]:
                    part = part.replace("~1", "/").replace("~0", "~")
                    cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
                if not isinstance(cursor, dict):
                    raise ContractError("provider_financial_metadata_missing")
                end = datetime.fromtimestamp(cursor["period_end_ms"] / 1000, ZoneInfo("Asia/Shanghai")).date()
                reported = datetime.fromtimestamp(cursor["report_date_ms"] / 1000, ZoneInfo("Asia/Shanghai")).date()
                if (item.scope.entity != cursor["thscode"] or item.scope.currency != cursor["currency"]
                        or item.scope.end != end or item.provider_report_date != reported
                        or item.scope.metric != parts[-1]):
                    raise ContractError("provider_metadata_does_not_match_normalized_field")
        elif item.origin != "synthetic_test":
            raise ContractError("raw_evidence_requires_locator")
        with self.sessions.begin() as session:
            if session.get(EvidenceRecord, item.id):
                self._insert_evidence(session, item)
                return
            self._insert_evidence(session, item)
            self._audit(session, "evidence_added", item.id)

    def evidence(self, evidence_id: str) -> Evidence:
        return evidence_from_dict(self._payload(EvidenceRecord, evidence_id))

    def put_crosscheck(self, provider_id: str, issuer_id: str) -> str:
        provider, issuer = self.evidence(provider_id), self.evidence(issuer_id)
        if (provider.origin != "provider" or issuer.origin != "issuer"
                or provider.value is None or provider.value != issuer.value
                or provider.scope != issuer.scope
                or provider.verification.value != "verified" or issuer.verification.value != "verified"):
            raise ContractError("crosscheck_requires_matching_verified_provider_and_issuer_fields")
        payload = {"provider_id": provider_id, "issuer_id": issuer_id,
                   "method": "local_json_pointer_and_official_pdf_cell_equal_same_scope", "version": "m1-v1",
                   "value_match": True, "date_semantics_resolved": False}
        object_id = identifier("crosscheck", payload)
        with self.sessions.begin() as session:
            if session.get(CrosscheckRecord, object_id):
                return object_id
            session.add(CrosscheckRecord(id=object_id, provider_id=provider_id, issuer_id=issuer_id,
                                          payload=encode(payload)))
            self._audit(session, "crosscheck_saved", object_id)
        return object_id

    def put_calculation(self, calculation: Calculation) -> None:
        from .finance import yoy, fiscal_yoy, gross_margin, margin_delta, cumulative_to_single, cash_conversion
        operations = {"yoy": yoy, "fiscal_yoy": fiscal_yoy, "gross_margin": gross_margin, "margin_delta": margin_delta,
                      "cumulative_to_single": cumulative_to_single, "cash_conversion": cash_conversion}
        fn = operations.get(calculation.operation)
        if fn is None or len(calculation.inputs) != 2:
            raise ContractError("unknown_operation_or_input_count")
        recomputed = fn(*(self.evidence(i) for i in calculation.inputs))
        if encode(recomputed) != encode(calculation):
            raise ContractError("calculation_does_not_match_recomputed_inputs")
        with self.sessions.begin() as session:
            old = session.get(CalculationRecord, calculation.id)
            if old:
                if old.payload != encode(calculation):
                    raise ContractError("immutable_calculation_collision")
                return
            self._insert_evidence(session, calculation.result)
            session.add(CalculationRecord(id=calculation.id, result_id=calculation.result.id,
                                         payload=encode(calculation)))
            session.flush()
            for position, evidence_id in enumerate(calculation.inputs):
                session.add(CalculationInput(calculation_id=calculation.id, position=position,
                                             evidence_id=evidence_id))
            self._audit(session, "calculation_added", calculation.id)

    def put_conflict(self, conflict: Conflict) -> None:
        from .conflicts import detect
        tolerance = Decimal(conflict.details.get("tolerance", "0"))
        candidates = detect(self.evidence(conflict.left_id), self.evidence(conflict.right_id),
                            tolerance=tolerance)
        if not any(encode(c) == encode(conflict) for c in candidates):
            raise ContractError("conflict_does_not_match_evidence")
        with self.sessions.begin() as session:
            old = session.get(ConflictRecord, conflict.id)
            if old:
                if old.payload != encode(conflict):
                    raise ContractError("immutable_conflict_collision")
                return
            session.add(ConflictRecord(id=conflict.id, left_id=conflict.left_id,
                                        right_id=conflict.right_id, payload=encode(conflict)))
            self._audit(session, "conflict_detected", conflict.id)

    def review(self, conflict_id: str, *, reviewer: str, reason: str,
               selected_evidence_id: str | None = None, field: str | None = None,
               keep_unresolved: bool = True) -> int:
        require_text(reviewer, "reviewer")
        require_text(reason, "reason")
        conflict = self._payload(ConflictRecord, conflict_id)
        adopted = None
        if selected_evidence_id is None:
            if field is not None or not keep_unresolved:
                raise ContractError("unresolved_review_cannot_adopt_field")
        else:
            if selected_evidence_id not in (conflict["left_id"], conflict["right_id"]):
                raise ContractError("selected_evidence_not_in_conflict")
            if field != conflict["field"]:
                raise ContractError("review_must_target_conflicting_field")
            evidence = self.evidence(selected_evidence_id)
            if field == "original_disclosure_date":
                if evidence.issuer_disclosure_date is None:
                    raise ContractError("selected_evidence_has_no_issuer_date")
                adopted = evidence.issuer_disclosure_date.isoformat()
                if not keep_unresolved:
                    raise ContractError("adopting_issuer_date_does_not_resolve_provider_semantics")
            elif field == "value":
                adopted = str(evidence.value) if evidence.value is not None else None
            elif field == "scope":
                adopted = asdict(evidence.scope)
            else:
                raise ContractError("unsupported_review_field")
        payload = {"reviewer": reviewer, "reason": reason, "recorded_at": now(),
                   "field": field, "selected_evidence_id": selected_evidence_id,
                   "adopted_value": adopted, "keep_unresolved": keep_unresolved,
                   "residual": "provider_date_semantics_UNVERIFIED" if conflict["kind"] == "date_mismatch" else None}
        with self.sessions.begin() as session:
            row = ReviewRecord(conflict_id=conflict_id, selected_evidence_id=selected_evidence_id,
                               payload=encode(payload))
            session.add(row)
            session.flush()
            self._audit(session, "field_review_recorded", conflict_id, actor=reviewer,
                        review_sequence=row.sequence)
            return row.sequence

    def conflict_state(self, conflict_id: str) -> dict:
        conflict = self._payload(ConflictRecord, conflict_id)
        with self.sessions() as session:
            reviews = [json.loads(r.payload) for r in session.scalars(
                select(ReviewRecord).where(ReviewRecord.conflict_id == conflict_id)
                .order_by(ReviewRecord.sequence))]
        adopted = {r["field"]: r for r in reviews if r["field"] is not None}
        return {"conflict": conflict, "state": "unresolved" if not reviews or reviews[-1]["keep_unresolved"]
                else "resolved", "adopted_fields": adopted, "reviews": reviews}

    def put_revision(self, revision: ThesisRevision) -> None:
        with self.sessions.begin() as session:
            if revision.parent_id:
                parent = session.get(RevisionRecord, revision.parent_id)
                if parent is None or parent.thesis_id != revision.thesis_id:
                    raise ContractError("invalid_parent_revision")
            old = session.get(RevisionRecord, revision.id)
            if old:
                if old.payload != encode(revision):
                    raise ContractError("immutable_revision_collision")
                return
            session.add(RevisionRecord(id=revision.id, thesis_id=revision.thesis_id,
                                       parent_id=revision.parent_id, payload=encode(revision)))
            self._audit(session, "revision_saved", revision.id)

    def checkpoint(self, task_id: str, revision_id: str, *, state: str,
                   evidence_ids: list[str], conflict_ids: list[str]) -> int:
        require_text(task_id, "task_id")
        if state not in ("draft", "awaiting_review", "partial", "complete", "failed"):
            raise ContractError("invalid_checkpoint_state")
        for i in evidence_ids:
            self.evidence(i)
        for i in conflict_ids:
            self._payload(ConflictRecord, i)
        with self.sessions.begin() as session:
            if not session.get(RevisionRecord, revision_id):
                raise ContractError("unknown_revision")
            latest = session.scalar(select(CheckpointRecord).where(CheckpointRecord.task_id == task_id)
                                    .order_by(CheckpointRecord.sequence.desc()).limit(1))
            if latest:
                previous = session.get(RevisionRecord, latest.revision_id)
                current = session.get(RevisionRecord, revision_id)
                if previous.thesis_id != current.thesis_id:
                    raise ContractError("task_cannot_switch_thesis")
            payload = {"state": state, "evidence_ids": evidence_ids, "conflict_ids": conflict_ids,
                       "saved_at": now()}
            row = CheckpointRecord(task_id=task_id, revision_id=revision_id, payload=encode(payload))
            session.add(row)
            session.flush()
            self._audit(session, "checkpoint_saved", task_id, checkpoint_sequence=row.sequence)
            return row.sequence

    def put_assessment(self, revision_id: str, assessment: Assessment) -> str:
        revision = self._payload(RevisionRecord, revision_id)
        if assessment.subclaim_id not in {c["id"] for c in revision["subclaims"]}:
            raise ContractError("unknown_subclaim_in_revision")
        if assessment.verification != self.evidence(assessment.evidence_id).verification:
            raise ContractError("assessment_cannot_upgrade_evidence_quality")
        object_id = identifier("assessment", {"revision": revision_id, "assessment": assessment})
        with self.sessions.begin() as session:
            if session.get(AssessmentRecord, object_id):
                return object_id
            session.add(AssessmentRecord(id=object_id, revision_id=revision_id,
                                          evidence_id=assessment.evidence_id, payload=encode(assessment)))
            self._audit(session, "assessment_saved", object_id)
        return object_id

    def restore(self, task_id: str) -> dict:
        with self.sessions() as session:
            row = session.scalar(select(CheckpointRecord).where(CheckpointRecord.task_id == task_id)
                                 .order_by(CheckpointRecord.sequence.desc()).limit(1))
            if row is None:
                raise KeyError(task_id)
            payload = json.loads(row.payload)
            revision_id, sequence = row.revision_id, row.sequence
        return {"task_id": task_id, "checkpoint_sequence": sequence,
                "revision": self._payload(RevisionRecord, revision_id), **payload,
                "conflicts": [self.conflict_state(i) for i in payload["conflict_ids"]],
                "assessments": self.assessments(revision_id)}

    def assessments(self, revision_id: str) -> list[dict]:
        with self.sessions() as session:
            return [json.loads(r.payload) for r in session.scalars(
                select(AssessmentRecord).where(AssessmentRecord.revision_id == revision_id))]

    def audit(self) -> list[dict]:
        with self.sessions() as session:
            return [json.loads(r.payload) for r in session.scalars(select(AuditRecord).order_by(AuditRecord.sequence))]

    def trace(self, evidence_id: str) -> dict[str, Any]:
        visited = set()
        def walk(item_id: str) -> dict:
            if item_id in visited:
                return {"evidence_id": item_id, "shared_dependency": True}
            visited.add(item_id)
            evidence = self.evidence(item_id)
            node = {"evidence": json.loads(encode(evidence))}
            if evidence.locator:
                artifact = self.artifact(evidence.locator.artifact_id)
                node["artifact"] = {k: v for k, v in artifact.items() if k != "body"}
                node["source"] = self._payload(SourceRecord, artifact["source_id"])
                if evidence.origin == "issuer":
                    with self.sessions() as session:
                        checks = [json.loads(r.payload) for r in session.scalars(
                            select(CrosscheckRecord).where(CrosscheckRecord.issuer_id == item_id))]
                    node["crosschecks"] = [{"verification": check, "provider_field": walk(check["provider_id"])}
                                           for check in checks]
            else:
                with self.sessions() as session:
                    record = session.scalar(select(CalculationRecord).where(CalculationRecord.result_id == item_id))
                    if record is None:
                        if evidence.origin != "synthetic_test":
                            raise ContractError("derived_evidence_has_no_calculation")
                        return node
                    calc = json.loads(record.payload)
                node["calculation"] = {k: v for k, v in calc.items() if k != "result"}
                node["inputs"] = [walk(i) for i in calc["inputs"]]
            return node
        result = walk(evidence_id)
        with self.sessions() as session:
            associations = [(r.revision_id, json.loads(r.payload)) for r in session.scalars(
                select(AssessmentRecord).where(AssessmentRecord.evidence_id == evidence_id))]
        result["subclaim_associations"] = []
        for revision_id, assessment in associations:
            revision = self._payload(RevisionRecord, revision_id)
            claim = next(c for c in revision["subclaims"] if c["id"] == assessment["subclaim_id"])
            result["subclaim_associations"].append({"revision_id": revision_id, "subclaim": claim,
                                                   "assessment": assessment})
        return result
