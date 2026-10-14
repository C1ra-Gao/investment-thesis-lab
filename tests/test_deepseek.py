"""Explicit synthetic HTTP/model fixtures; never evidence of real LLM quality."""

from copy import deepcopy
import contextlib
import io
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from thesislab.deepseek import CallBudget, DeepSeekCandidateProvider, DeepSeekFailure, strict_json
from thesislab.deepseek_transport import HTTPSDeepSeekTransport, TransportResponse, HOST, PATH, MAX_RESPONSE_BYTES
from thesislab.research import request_candidate
from thesislab.research_store import ResearchEngine
from thesislab.store import Store
from tests.research_helpers import design
from tools.audit_staged import findings
from thesislab.candidate_review import summarize, render_candidate, review_form
from tools.run_deepseek_validation import main as validation_main
from thesislab.cli import PROJECT_ROOT


class SyntheticTransport:
    def __init__(self, reply):self.reply, self.calls, self.requests = reply, 0, []
    def send(self, body, *, timeout):
        self.calls += 1
        self.requests.append(json.loads(body))
        return self.reply


def reply(data=None, *, content=None, finish="stop", model="synthetic-model-not-live", usage=None):
    if content is None:content = json.dumps(data or design(), ensure_ascii=False)
    envelope = {"id": "synthetic-completion", "model": model, "choices": [
        {"finish_reason": finish, "message": {"role": "assistant", "content": content}}],
        "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}
    body = json.dumps(envelope, ensure_ascii=False).encode()
    return TransportResponse(200, body, True, len(body))


class DeepSeekAdapterTests(unittest.TestCase):
    def provider(self, response=None, *, count=6):
        t = SyntheticTransport(response or reply())
        p = DeepSeekCandidateProvider(CallBudget(count, 4000, True), transport=t)
        return p, t

    def test_authorization_checked_before_transport_and_credentials(self):
        p = DeepSeekCandidateProvider(CallBudget(), transport=SyntheticTransport(reply()))
        with patch("os.environ.get", side_effect=AssertionError("no credential reads")), self.assertRaises(DeepSeekFailure):
            p.candidate(design()["statement"])
        self.assertEqual(p.transport.calls, 0)
        self.assertEqual(p.budget.used, 0)

    def test_m2_gate_also_blocks_unauthorized_provider(self):
        p, t = self.provider()
        with self.assertRaises(ValueError):request_candidate(design()["statement"], p)
        self.assertEqual(t.calls, 0)

    def test_three_authored_fixtures_pass_adapter_not_model_evaluation(self):
        with patch("socket.socket.connect", side_effect=AssertionError("no network")):
            for kind in ("state", "causal", "attribution"):
                d = design(kind=kind);p, t = self.provider(reply(d))
                self.assertEqual(request_candidate(d["statement"], p, authorized=True), d)
                self.assertTrue(p.attempts[0]["json_pass"])
                self.assertTrue(p.attempts[0]["m2_schema_pass"])
                self.assertEqual(t.calls, 1)

    def test_json_mode_nonstream_fixed_model_and_cap(self):
        p, t = self.provider();p.candidate(design()["statement"])
        body = t.requests[0]
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["max_tokens"], 4000)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertFalse(body["stream"])
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("tools", body)
        self.assertEqual(json.loads(body["messages"][1]["content"]), {"investment_thesis": design()["statement"]})

    def test_usage_is_actual_response_metadata_or_unknown_not_assumed_zero(self):
        p, _ = self.provider();p.candidate(design()["statement"])
        self.assertEqual(p.attempts[0]["usage"]["total_tokens"], 300)
        self.assertEqual(p.attempts[0]["returned_model"], "synthetic-model-not-live")
        self.assertIsNone(p.attempts[0]["actual_fee"])
        p, _ = self.provider(reply(usage={}));p.candidate(design()["statement"])
        self.assertTrue(all(v is None for v in p.attempts[0]["usage"].values()))

    def test_invalid_json_separate_from_schema(self):
        p, t = self.provider(reply(content="{incomplete"))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertFalse(p.attempts[0]["json_pass"])
        self.assertIsNone(p.attempts[0]["m2_schema_pass"])
        self.assertEqual(t.calls, 1)

    def test_valid_json_bad_contract_rejected_without_repair(self):
        p, t = self.provider(reply(content='{"claims": []}'))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertTrue(p.attempts[0]["json_pass"])
        self.assertFalse(p.attempts[0]["m2_schema_pass"])
        self.assertEqual(t.calls, 1)

    def test_original_statement_changed_rejected(self):
        d = design();p, _ = self.provider(reply(d))
        with self.assertRaises(DeepSeekFailure):p.candidate("另一家公司收入增长。")
        self.assertFalse(p.attempts[0]["m2_schema_pass"])

    def test_span_and_question_mutations_rejected(self):
        for mutation in ("span", "question"):
            d = design()
            if mutation == "span":d["claims"][1]["spans"][0]["text"] = "invented source"
            else:d["claims"][1]["statement"] = "基本面好吗？"
            p, t = self.provider(reply(d))
            with self.assertRaises(DeepSeekFailure):p.candidate(d["statement"])
            self.assertFalse(p.attempts[0]["m2_schema_pass"])
            self.assertEqual(t.calls, 1)

    def test_truncated_but_parseable_json_never_accepted(self):
        p, _ = self.provider(reply(finish="length"))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertTrue(p.attempts[0]["json_pass"])
        self.assertIsNone(p.attempts[0]["m2_schema_pass"])

    def test_duplicate_keys_nonfinite_and_markdown_rejected(self):
        for content in ('{"a": 1, "a": 2}', '{"a": NaN}', '```json\n{}\n```'):
            p, _ = self.provider(reply(content=content))
            with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
            self.assertFalse(p.attempts[0]["json_pass"])

    def test_http_denial_balance_and_rate_limit_halt_without_retry(self):
        for status in (401, 402, 403, 429, 500):
            p, t = self.provider(TransportResponse(status, b"do not log error content", True, 24))
            for _ in range(2):
                with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
            self.assertEqual(t.calls, 1)
            self.assertEqual(p.budget.used, 1)
            self.assertNotIn("do not log", json.dumps(p.attempts))

    def test_incomplete_response_halts_and_records_type(self):
        p, t = self.provider(TransportResponse(200, b"partial", False, 7, "IncompleteRead"))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertEqual(p.attempts[0]["transport_error_type"], "IncompleteRead")
        self.assertIsNone(p.attempts[0]["json_pass"])
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertEqual(t.calls, 1)

    def test_budget_counts_invalid_completions_and_does_not_retry(self):
        p, t = self.provider(reply(content="broken"), count=2)
        for _ in range(3):
            with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertEqual(t.calls, 2)
        self.assertEqual(p.budget.used, 2)

    def test_budget_is_finite_and_matches_model_output_limit(self):
        for args in ((101, 12000), (18, 393217), (True, 4000), (6, 0)):
            with self.assertRaises(DeepSeekFailure):CallBudget(*args)

    def test_parallel_calls_rejected_before_consuming_slot(self):
        p, t = self.provider();p._busy.acquire()
        try:
            with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        finally:p._busy.release()
        self.assertEqual(t.calls, 0)

    def test_model_draft_does_not_confirm_or_insert_evidence(self):
        p, _ = self.provider();candidate = p.candidate(design()["statement"])
        with tempfile.TemporaryDirectory() as root:
            s = Store(Path(root)/"synthetic.sqlite")
            try:
                engine = ResearchEngine(s);id = engine.draft("synthetic-model-import", candidate, origin="model_candidate")
                self.assertEqual(engine.get(id)["origin"], "model_candidate")
                self.assertEqual([r["kind"] for r in engine.history("synthetic-model-import")], ["draft"])
                with s.engine.connect() as c:self.assertEqual(c.exec_driver_sql("SELECT COUNT(*) FROM evidence").scalar_one(), 0)
            finally:s.close()

    def test_empty_or_malformed_envelope_rejected(self):
        for response in (reply(content=" "), TransportResponse(200, b"[]", True, 2),
                         TransportResponse(200, b"not JSON", True, 8)):
            p, _ = self.provider(response)
            with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])

    def test_only_transport_gets_narrow_audit_exception(self):
        content = b"import http.client\n"
        self.assertEqual(findings("src/thesislab/deepseek_transport.py", content), [])
        self.assertIn("network_credential_or_process_client_in_runtime", findings("src/thesislab/deepseek.py", content))
        self.assertIn("network_credential_or_process_client_in_runtime", findings("src/thesislab/deepseek_transport.py", b"import requests\n"))
        self.assertEqual(findings("src/thesislab/deepseek_keychain.py", b"import subprocess\n"), [])

    def test_parseable_array_is_json_success_but_not_m2(self):
        p, _ = self.provider(reply(content="[]"))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertTrue(p.attempts[0]["json_pass"])
        self.assertFalse(p.attempts[0]["m2_schema_pass"])

    def test_invalid_contract_records_controlled_failure_code(self):
        p, _ = self.provider(reply(content='{"claims": []}'))
        with self.assertRaises(DeepSeekFailure):p.candidate(design()["statement"])
        self.assertEqual(p.attempts[0]["contract_error_code"], "invalid_contract_fields")

    def test_human_review_not_automatically_passed(self):
        p, _ = self.provider();d = p.candidate(design()["statement"])
        form = review_form(d["statement"], p.attempts[0])
        self.assertEqual(form["overall"], "UNVERIFIED")
        self.assertTrue(all(v["status"] == "UNVERIFIED" for v in form["criteria"].values()))
        self.assertIn("未自动确认", render_candidate(d))
        self.assertIn("Research Plan", render_candidate(d))

    def test_summary_no_calls_is_unknown_rate_not_zero(self):
        self.assertIsNone(summarize([])["json_rate_all_attempts"])
        self.assertIsNone(summarize([])["schema_rate_all_attempts"])
        self.assertIsNone(summarize([])["actual_fee"])

    def test_persist_budget_before_transport(self):
        reserved = []
        budget = CallBudget(1, 4000, True, on_consume=lambda n: reserved.append(n))
        class RequiresReservation(SyntheticTransport):
            def send(inner, body, *, timeout):
                self.assertEqual(reserved, [1])
                return super().send(body, timeout=timeout)
        p = DeepSeekCandidateProvider(budget, transport=RequiresReservation(reply()))
        p.candidate(design()["statement"])

    def test_reservation_failure_prevents_transport(self):
        def failed(_):raise OSError("synthetic_persistence_failure")
        p = DeepSeekCandidateProvider(CallBudget(1, 4000, True, on_consume=failed), transport=SyntheticTransport(reply()))
        with self.assertRaises(OSError):p.candidate(design()["statement"])
        self.assertEqual(p.transport.calls, 0)


class RunnerTests(unittest.TestCase):
    def invoke(self, args):
        with contextlib.redirect_stdout(io.StringIO()):return validation_main(args)

    def test_no_authorization_means_no_key_read_or_network(self):
        import os
        get = os.environ.get
        def safe_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":raise AssertionError("no key read")
            return get(name, default)
        with patch("os.environ.get", side_effect=safe_get), \
             patch("socket.socket.connect", side_effect=AssertionError("no network")):
            self.assertEqual(self.invoke([]), 2)

    def test_persistent_budget_and_candidate_import_with_synthetic_transport(self):
        from thesislab.candidate_review import PUBLIC_CASES
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT/".local") as root:
            def fixture(body, *, timeout):
                statement = json.loads(json.loads(body)["messages"][1]["content"])["investment_thesis"]
                return reply(design(statement=statement))
            args = ["--authorize-budget", "--run-dir", root, "--max-requests", "2", "--cases", "state"]
            with patch("thesislab.deepseek_transport.HTTPSDeepSeekTransport.send", side_effect=fixture) as transport:
                self.assertEqual(self.invoke(args), 0)
                self.assertEqual(self.invoke(args), 0)
                self.assertEqual(self.invoke(args), 1)
                self.assertEqual(transport.call_count, 2)
            ledger = json.loads((Path(root)/"ledger.json").read_text())
            self.assertEqual(ledger["reserved_requests"], 2)
            self.assertTrue(all(a["m2_schema_pass"] for a in ledger["attempts"]))
            self.assertTrue((Path(root)/"attempt-1-state.candidate.json").exists())
            self.assertTrue((Path(root)/"attempt-2-state.review.md").exists())

    def test_unfinished_reserved_attempt_is_not_replayed(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT/".local") as root:
            path = Path(root)/"ledger.json"
            path.write_text(json.dumps({"max_requests": 6, "max_output_tokens": 4000, "reserved_requests": 1,
                                       "attempts": [{"request_number": 1, "state": "reserved"}], "halted": False}))
            with patch("thesislab.deepseek_transport.HTTPSDeepSeekTransport.send") as send:
                self.assertEqual(self.invoke(["--authorize-budget", "--run-dir", root, "--cases", "state"]), 1)
                send.assert_not_called()


class TransportTests(unittest.TestCase):
    def run_send(self, body=b"{}", *, status=200, length="2", encoding="identity", read_error=None):
        response = Mock(status=status)
        response.read.side_effect = read_error
        response.read.return_value = body
        response.getheader.side_effect = lambda k, default=None: {"Content-Length": length, "Content-Encoding": encoding}.get(k, default)
        connection = Mock();connection.getresponse.return_value = response
        with patch("thesislab.deepseek_transport.http.client.HTTPSConnection", return_value=connection) as constructor:
            result = HTTPSDeepSeekTransport(lambda: "synthetic-placeholder-never-a-real-key").send(b'{"model":"deepseek-flash"}', timeout=90)
        return result, constructor, connection

    def test_fixed_https_host_path_and_no_redirects(self):
        result, ctor, conn = self.run_send()
        self.assertTrue(result.complete)
        ctor.assert_called_once_with(HOST, timeout=90)
        self.assertEqual(conn.request.call_args.args[:2], ("POST", PATH))
        conn.close.assert_called_once()
        result, _, conn = self.run_send(status=302)
        self.assertEqual(result.body, b"")
        self.assertEqual(conn.request.call_count, 1)

    def test_missing_key_no_connection(self):
        with patch("thesislab.deepseek_transport.http.client.HTTPSConnection") as ctor:
            result = HTTPSDeepSeekTransport(lambda: None).send(b"{}", timeout=90)
        ctor.assert_not_called();self.assertEqual(result.error_type, "credential_missing")

    def test_length_mismatch_compression_and_large_body_rejected(self):
        for options in ({"length": "3"}, {"encoding": "gzip"}, {"body": b"x" * (MAX_RESPONSE_BYTES+1)}):
            result, _, conn = self.run_send(**options)
            self.assertFalse(result.complete)
            self.assertEqual(result.body, b"")
            conn.close.assert_called_once()

    def test_incomplete_read_does_not_return_partial_json(self):
        result, _, conn = self.run_send(read_error=http.client.IncompleteRead(b"partial", 10))
        self.assertEqual(result.error_type, "IncompleteRead")
        self.assertEqual(result.received_bytes, 7)
        self.assertEqual(result.body, b"")

    def test_error_body_and_credential_echo_are_never_returned(self):
        result, _, _ = self.run_send(body=b"synthetic-placeholder-never-a-real-key", length=None)
        self.assertEqual(result.error_type, "response_contains_credential")
        self.assertNotIn("synthetic-placeholder", repr(result))
        result, _, _ = self.run_send(body=b"sensitive server details", status=401, length=None)
        self.assertEqual(result.body, b"")

class KeychainTests(unittest.TestCase):
    def test_reads_only_authorized_service_and_current_user_with_no_key_argument(self):
        from thesislab.deepseek_keychain import read_authorized_key, SERVICE
        result = Mock(returncode=0, stdout=b"synthetic-placeholder\n", stderr=b"")
        with patch.dict("os.environ", {"USER": "synthetic-macos-account"}), \
             patch("thesislab.deepseek_keychain.subprocess.run", return_value=result) as run:
            self.assertEqual(read_authorized_key(), "synthetic-placeholder")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/security", "find-generic-password", "-s", SERVICE,
                                                "-a", "synthetic-macos-account", "-w"])
        self.assertNotIn("synthetic-placeholder", repr(run.call_args))
    def test_keychain_failure_never_exposes_raw_stderr(self):
        from thesislab.deepseek_keychain import read_authorized_key, KeychainAccessFailure
        result = Mock(returncode=44, stdout=b"", stderr=b"specified item could not be found; sensitive detail")
        with patch.dict("os.environ", {"USER": "synthetic"}), \
             patch("thesislab.deepseek_keychain.subprocess.run", return_value=result):
            with self.assertRaises(KeychainAccessFailure) as caught:read_authorized_key()
        self.assertEqual(str(caught.exception), "keychain_item_not_found")
    def test_access_dialog_timeout_pauses_before_any_http(self):
        from thesislab.deepseek_keychain import read_authorized_key
        import subprocess
        with patch.dict("os.environ", {"USER": "synthetic"}), \
             patch("thesislab.deepseek_keychain.subprocess.run", side_effect=subprocess.TimeoutExpired("security", 8)), \
             patch("thesislab.deepseek_transport.http.client.HTTPSConnection") as connect:
            result = HTTPSDeepSeekTransport(read_authorized_key).send(b"{}", timeout=90)
        self.assertEqual(result.error_type, "keychain_access_timeout_or_dialog_pause")
        connect.assert_not_called()

