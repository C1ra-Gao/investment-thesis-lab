from pathlib import Path
import tempfile
import unittest

from tools.audit_staged import findings
from thesislab.cli import private_output
from thesislab.domain import ContractError
from thesislab.locators import json_value


class SafetyTests(unittest.TestCase):
    def test_raw_response_database_and_pdf_not_allowlisted(self):
        for path in ("response.json", "data/file.pdf", ".local/store.sqlite", "private-data/input.json", ".env"):
            with self.subTest(path=path):self.assertTrue(findings(path, b"internal-only"))

    def test_only_safe_environment_template_allowed(self):
        self.assertEqual(findings(".env.example", b"THESISLAB_DATABASE=.local/store.sqlite\n"), [])

    def test_private_value_detected_without_echo(self):
        issues = findings("docs/example.md", b"synthetic number 9,876.54", {"9876.54"})
        self.assertIn("private_financial_value_present", issues)
        self.assertNotIn("9876.54", " ".join(issues))

    def test_runtime_network_imports_rejected(self):
        self.assertIn("network_credential_or_process_client_in_runtime", findings("src/unsafe.py", b"import requests\n"))

    def test_sensitive_output_cannot_land_in_tracked_paths(self):
        with self.assertRaises(ContractError):private_output("docs/unsafe-output.json")

    def test_local_output_is_allowed(self):
        self.assertTrue(private_output(".local/synthetic-output.json").name.endswith(".json"))

    def test_partial_or_error_json_is_not_a_financial_fact(self):
        with self.assertRaises(ContractError):json_value(b'{"code":2003,"data":null}', "/data/value")
        with self.assertRaises(ValueError):json_value(b'{"code":0,"data":', "/data/value")
