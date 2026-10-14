"""Acceptance request budget tested with a synthetic model; never sends HTTP."""
from pathlib import Path
import tempfile
import unittest
from thesislab.store import Store
from thesislab.model_acceptance import BoundedAcceptanceModel
from thesislab.domain import ContractError
from thesislab.live_providers import ModelHTTP,LiveHTTP,MODEL_ENDPOINTS

class MetadataFixture:
    def __init__(self):self.calls=0
    def json(self,system,payload):self.calls+=1;return {'fixture':True}
    def request_metadata(self):return {'request_sent':True,'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},'provider':'fixture_simulated_receipt_not_real_http'}

class AcceptanceBudgetTests(unittest.TestCase):
    def test_model_proxy_exception_is_exact_endpoint_and_benchmark_range_only(self):
        transport=ModelHTTP();url=MODEL_ENDPOINTS['deepseek']
        self.assertTrue(transport.address_allowed(url,'198.18.0.7'))
        self.assertFalse(LiveHTTP().address_allowed(url,'198.18.0.7'))
        for address in ('127.0.0.1','10.0.0.1','192.168.1.1','169.254.169.254','::1'):
            self.assertFalse(transport.address_allowed(url,address))
        for other in (url+'?key=x',url+'/other','https://evil.invalid/chat/completions'):
            with self.assertRaisesRegex(ContractError,'fixed_model_endpoint_required'):
                transport.request(other)
    def test_persisted_fourteen_attempt_limit_and_token_accounting(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'budget.sqlite';store=Store(path);fixture=MetadataFixture()
            model=BoundedAcceptanceModel(fixture,store.engine,limit=14)
            for _ in range(14):model.json('研究助手的 Understand',{})
            self.assertEqual(model.totals()['reserved_attempts'],14)
            self.assertEqual(model.totals()['known_token_usage']['total_tokens'],210)
            self.assertEqual(model.totals()['actual_requests_sent'],14)  # Simulated receipts only.
            with self.assertRaises(ContractError):model.json('你是 Plan 节点',{})
            store.close();store=Store(path)
            try:
                restored=BoundedAcceptanceModel(fixture,store.engine,limit=14)
                with self.assertRaises(ContractError):restored.json('你是 Plan 节点',{})
                self.assertEqual(fixture.calls,14)
            finally:store.close()
    def test_no_authorization_expansion_to_execute_followup_or_deep_research(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'budget.sqlite');fixture=MetadataFixture();model=BoundedAcceptanceModel(fixture,store.engine)
            try:
                for prompt in ('执行Deep Research','追问','补查决策'):
                    with self.assertRaises(ContractError):model.json(prompt,{})
                self.assertEqual(model.totals()['reserved_attempts'],0)
                self.assertEqual(fixture.calls,0)
            finally:store.close()
    def test_missing_usage_is_unknown_not_fabricated_token_count(self):
        class NoUsage(MetadataFixture):
            def request_metadata(self):return {'request_sent':None,'usage':None}
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'budget.sqlite');model=BoundedAcceptanceModel(NoUsage(),store.engine)
            try:
                model.json('你是 Plan 节点',{})
                self.assertEqual(model.totals()['requests_without_token_usage'],1)
                self.assertEqual(model.totals()['uncertain_transmissions'],1)
            finally:store.close()

    def test_known_pre_send_failure_releases_capacity_but_does_not_reset_audit(self):
        class PreSend(MetadataFixture):
            def request_metadata(self):return {'request_sent':False,'usage':None}
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'budget.sqlite');fixture=PreSend();model=BoundedAcceptanceModel(fixture,store.engine,limit=1)
            try:
                model.json('你是 Plan 节点',{});model.json('你是 Plan 节点',{})
                self.assertEqual(model.totals()['actual_requests_sent'],0)
                self.assertEqual(model.totals()['reserved_attempts'],2)
                self.assertEqual(model.totals()['known_pre_send_failures'],2)
            finally:store.close()
