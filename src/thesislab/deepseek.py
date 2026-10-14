"""CandidateProvider adapter. JSON validity, M2 validity and meaning stay separate."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from threading import Lock
from time import perf_counter

from .domain import ContractError, require_text
from .research import validate_draft
from .deepseek_prompt import SYSTEM_PROMPT, PROMPT_VERSION
from .deepseek_transport import HTTPSDeepSeekTransport


class DeepSeekFailure(ContractError):
    """Only controlled codes, never provider messages or raw response bodies."""


def strict_json(text):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:raise ValueError("duplicate_json_key")
            result[k] = v
        return result
    def reject(value):raise ValueError("non_finite_json_number")
    return json.loads(text, object_pairs_hook=unique, parse_constant=reject)


@dataclass
class CallBudget:
    max_requests: int = 18
    max_output_tokens: int = 12000
    authorized: bool = False
    used: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    on_consume: object = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= 100:
            raise DeepSeekFailure("invalid_request_budget")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 393216:
            raise DeepSeekFailure("invalid_output_budget")
        if type(self.authorized) is not bool:raise DeepSeekFailure("invalid_authorization")

    def consume(self):
        with self._lock:
            if not self.authorized:raise DeepSeekFailure("explicit_model_budget_authorization_required")
            if self.used >= self.max_requests:raise DeepSeekFailure("model_request_budget_exhausted")
            self.used += 1  # Failed/uncertain attempts consume a slot; never auto-retry.
            if self.on_consume is not None:self.on_consume(self.used)
            return self.used


def safe_usage(raw):
    raw = raw if isinstance(raw, dict) else {}
    fields = ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    return {k: raw.get(k) if type(raw.get(k)) is int and raw[k] >= 0 else None for k in fields}


def safe_identifier(value):
    # Model/id metadata is not allowed to act as a log-exfiltration channel.
    if isinstance(value, str) and 0 < len(value) <= 120 and all(c.isascii() and (c.isalnum() or c in "-_./:") for c in value):
        return value
    return None


class DeepSeekCandidateProvider:
    def __init__(self, budget: CallBudget, *, transport=None, timeout=90, system_prompt=SYSTEM_PROMPT,
                 prompt_version=PROMPT_VERSION, character_map=False):
        if type(timeout) is not int or not 1 <= timeout <= 120:raise DeepSeekFailure("invalid_timeout")
        self.budget, self.timeout = budget, timeout
        self.transport = transport if transport is not None else HTTPSDeepSeekTransport()
        self.system_prompt, self.prompt_version = system_prompt, prompt_version
        self.character_map = character_map
        self.attempts = []
        self._busy = Lock()
        self.halted = False
        self.last_content = None  # Quarantined model text, not financial evidence.

    def candidate(self, statement: str) -> dict:
        require_text(statement, "statement")
        if len(statement) > 2000 or statement.rstrip().endswith(("?", "？")):
            raise DeepSeekFailure("invalid_declarative_input")
        if not self._busy.acquire(blocking=False):raise DeepSeekFailure("parallel_model_calls_forbidden")
        attempt = None
        try:
            if self.halted:raise DeepSeekFailure("model_session_halted")
            self.last_content = None
            number = self.budget.consume()
            started = perf_counter()
            attempt = {"request_number": number, "started_at": datetime.now(timezone.utc).isoformat(),
                       "requested_model": "deepseek-flash", "returned_model": None,
                       "prompt_version": self.prompt_version, "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
                       "system_prompt_sha256": hashlib.sha256(self.system_prompt.encode()).hexdigest(),
                       "max_output_tokens": self.budget.max_output_tokens, "thinking": "disabled",
                       "http_status": None, "response_complete": False, "received_bytes": 0,
                       "json_pass": None, "m2_schema_pass": None, "error_type": None,
                       "usage": safe_usage(None), "actual_fee": None,
                       "semantic_review": "pending_human_review", "input_kind": "user_statement_only",
                       "automatic_retries": 0, "duration_ms": None}
            self.attempts.append(attempt)
            input_packet = {"investment_thesis": statement}
            if self.character_map:
                input_packet.update(unicode_length=len(statement), unicode_index=[{"index": i, "character": c} for i, c in enumerate(statement)])
            attempt["input_packet_version"] = "unicode-map-v2" if self.character_map else "statement-only-v1"
            payload = {"model": "deepseek-flash", "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(input_packet, ensure_ascii=False)}],
                "response_format": {"type": "json_object"}, "stream": False,
                "max_tokens": self.budget.max_output_tokens, "thinking": {"type": "disabled"}, "temperature": 0}
            wire = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            attempt["request_body_bytes"] = len(wire)
            try:
                response = self.transport.send(wire, timeout=self.timeout)
            except Exception:
                raise DeepSeekFailure("transport_exception") from None
            attempt.update(http_status=response.status, response_complete=response.complete,
                           received_bytes=response.received_bytes)
            attempt["transport_error_type"] = safe_identifier(response.error_type)
            if response.error_type or not response.complete:
                self.halted = True  # Uncertain transport result must not be auto-replayed.
                raise DeepSeekFailure("transport_failed_or_incomplete")
            if response.status != 200:
                self.halted = True
                codes = {401: "authentication_denied", 402: "insufficient_balance", 403: "permission_denied",
                         429: "rate_limited", 400: "invalid_request", 422: "invalid_parameters"}
                raise DeepSeekFailure(codes.get(response.status, "http_error"))
            try:
                envelope = strict_json(response.body.decode("utf-8"))
                if not isinstance(envelope, dict):raise ValueError()
            except (ValueError, UnicodeError, RecursionError):
                raise DeepSeekFailure("invalid_response_envelope") from None
            attempt["returned_model"] = safe_identifier(envelope.get("model"))
            attempt["completion_id"] = safe_identifier(envelope.get("id"))
            attempt["system_fingerprint"] = safe_identifier(envelope.get("system_fingerprint"))
            attempt["provider_created"] = envelope.get("created") if type(envelope.get("created")) is int else None
            attempt["usage"] = safe_usage(envelope.get("usage"))
            try:
                if len(envelope["choices"]) != 1:raise ValueError()
                choice = envelope["choices"][0]
                attempt["finish_reason"] = safe_identifier(choice["finish_reason"])
                content = choice["message"]["content"]
                if choice["message"].get("tool_calls"):raise ValueError()
                if not isinstance(content, str) or not content.strip():raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise DeepSeekFailure("invalid_or_empty_completion") from None
            self.last_content = content
            try:
                data = strict_json(content)
                attempt["json_pass"] = True
            except (ValueError, RecursionError):
                attempt["json_pass"] = False
                raise DeepSeekFailure("candidate_json_invalid") from None
            if choice["finish_reason"] != "stop":
                raise DeepSeekFailure("completion_not_finished")
            if not isinstance(data, dict):
                attempt["m2_schema_pass"] = False
                raise DeepSeekFailure("candidate_json_not_object")
            try:
                valid = validate_draft(data)
                if valid["statement"] != statement:raise ContractError("provider_changed_original_statement")
            except (ContractError, TypeError, ValueError, KeyError, AttributeError, RecursionError) as exc:
                attempt["m2_schema_pass"] = False
                attempt["contract_error_type"] = type(exc).__name__
                attempt["contract_error_code"] = str(exc) if isinstance(exc, ContractError) and str(exc).replace("_", "").isalpha() and str(exc).isascii() else None
                raise DeepSeekFailure("candidate_m2_contract_invalid") from None
            attempt["m2_schema_pass"] = True
            # Financial facts stay outside this adapter. Caller may persist only
            # a model_candidate draft; user confirmation and M1 evidence follow.
            return valid
        except DeepSeekFailure as exc:
            if attempt is not None:attempt["error_type"] = str(exc)
            raise
        finally:
            if attempt is not None:attempt["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            self._busy.release()
