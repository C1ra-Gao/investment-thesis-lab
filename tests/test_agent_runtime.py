"""Explicit synthetic model/HTTP fixtures. These tests never call a live provider."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
import unittest

from thesislab.store import Store
from thesislab.agent_runtime import AgentRuntime, validate_plan
from thesislab.live_providers import ProviderSettings, SECFinancial
from thesislab.domain import ContractError, Evidence, Scope, Basis, Locator, Verification, Source


def plan(year=2025,metric='operating_income_yoy',threshold='0',kind='numeric'):
    return {'scope':'年度合并收入同比，非因果归因', 'clarifications':[], 'questions':[
        {'id':'q1','statement':'年度收入同比增长','kind':kind,'metric':metric,'operator':'gt','threshold':threshold,
         'year':year,'period':'annual','tool':'sec_facts','condition':'下一份同口径披露使收入同比不再大于零'}]}


class FixtureModel:
    def __init__(self,response=None):self.response=response or plan();self.requests=[]
    def json(self,system,payload):
        self.requests.append(payload)
        if 'additional_queries' in system:return {'reason':'缺少其他合法来源，保留无法验证','additional_queries':[]}
        if 'needs_new_research' in system:return {'answer':'当前只有收入证据，不能证明因果归因。','evidence_ids':payload['allowed_evidence_ids'][:1],'needs_new_research':True}
        return deepcopy(self.response)


def sec_body(current=120,prior=100,entity=320193,conflict=False):
    rows=[{'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-01','form':'10-K','accn':'0000320193-26-000001','val':current},
          {'start':'2024-01-01','end':'2024-12-31','filed':'2025-02-01','form':'10-K','accn':'0000320193-25-000001','val':prior}]
    if conflict:rows.append({**rows[0],'val':130,'filed':'2026-03-01','accn':'0000320193-26-000002'})
    return json.dumps({'cik':entity,'entityName':'SYNTHETIC FIXTURE COMPANY','facts':{'us-gaap':{
        'RevenueFromContractWithCustomerExcludingAssessedTax':{'units':{'USD':rows}}}}}).encode()


class FixtureHTTP:
    def __init__(self,body=None,error=None):self.body=body or sec_body();self.error=error;self.requests=[]
    def request(self,url,**kwargs):
        self.requests.append((url,kwargs))
        if self.error:raise ContractError(self.error)
        return self.body


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'agent.sqlite';self.store=Store(self.path)
        self.settings=ProviderSettings();self.settings.configure({'model_key':'SYNTHETIC_SECRET_DO_NOT_EXPORT',
            'public_enabled':True,'sec_contact':'fixture@example.invalid'})
        self.model=FixtureModel();self.http=FixtureHTTP()
        self.agent=AgentRuntime(self.store,settings=self.settings,model=self.model,http=self.http)

    def tearDown(self):
        for thread in list(self.agent.workers.values()):thread.join(5)
        self.store.close();self.temp.cleanup()

    def create(self,**kwargs):return self.agent.create({'statement':'年度收入同比增长','entity':'CIK0000320193','year':2025,'period':'annual',**kwargs})
    def wait(self,id):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            s=self.agent.get(id)
            if s['status']!='running':return s
            time.sleep(.02)
        self.fail('background worker timeout')
    def research(self,**kwargs):
        s=self.create(**kwargs);self.agent.launch(s['id'],{'version':s['version'],'action':'launch'});s=self.wait(s['id'])
        self.assertEqual(s['stage'],'Plan',s.get('error'))
        self.agent.launch(s['id'],{'version':s['version'],'action':'execute'});return self.wait(s['id'])

    def test_end_to_end_deterministic_lineage_followup_restore(self):
        s=self.research();self.assertEqual(s['status'],'completed',s['error']);self.assertEqual(s['report']['conclusion'],'support')
        a=s['assessments'][0];self.assertEqual(a['value'],'20.0')
        e=self.agent.evidence(a['evidence_ids'][0]);self.assertEqual(e['fact_type'],'calculation')
        self.assertIn('source',e['lineage']['inputs'][0]);self.assertTrue(e['lineage']['inputs'][0]['source']['url'].startswith('https://data.sec.gov'))
        s=self.agent.followup(s['id'],{'version':s['version'],'question':'是否足以说明因果？'})
        self.assertEqual(s['followups'][0]['type'],'model_inference_not_new_verified_fact')
        self.assertNotIn('SYNTHETIC_SECRET_DO_NOT_EXPORT',json.dumps(s))
        store=Store(self.path)
        try:
            recovered=AgentRuntime(store);self.assertEqual(recovered.get(s['id'])['report'],s['report'])
            self.assertFalse(recovered.settings.public()['model_configured'])
        finally:store.close()

    def test_negative_evidence_refutes(self):
        self.http.body=sec_body(current=80)
        s=self.research();self.assertEqual(s['report']['conclusion'],'refute');self.assertEqual(Decimal(s['assessments'][0]['value']),Decimal('-20'))

    def test_missing_and_failure_never_become_fake_numbers(self):
        self.http.error='upstream_http_403'
        s=self.research();self.assertEqual(s['report']['conclusion'],'unverifiable')
        self.assertEqual(s['evidence_ids'],[]);self.assertEqual(next(c for c in s['calls'] if c['tool']=='sec_facts')['error'],'upstream_http_403')
        self.assertEqual(len(self.http.requests),1)

    def test_conflicting_vintages_preserved_and_blocked(self):
        self.http.body=sec_body(conflict=True)
        s=self.research();self.assertEqual(s['report']['conclusion'],'unverifiable')
        self.assertTrue(any(c['kind']=='numeric_mismatch' for c in s['conflicts']))
        self.assertEqual(len([i for i in s['evidence_ids'] if self.store.evidence(i).origin=='issuer']),3)

    def test_critical_ambiguity_requires_answer(self):
        self.model.response=plan();self.model.response['clarifications']=[{'id':'scope','question':'盈利改善指净利润还是毛利率？','required':True}]
        s=self.create();self.agent.launch(s['id'],{'version':s['version'],'action':'launch'});s=self.wait(s['id'])
        self.assertEqual(s['status'],'awaiting_clarification')
        with self.assertRaises(ContractError):self.agent.launch(s['id'],{'version':s['version'],'action':'execute'})
        s=self.agent.edit(s['id'],{'version':s['version'],'answers':{'scope':'收入增长'}})
        self.agent.launch(s['id'],{'version':s['version'],'action':'launch'});s=self.wait(s['id']);self.assertEqual(s['stage'],'Plan')

    def test_model_cannot_invent_unapproved_metrics_or_scope(self):
        s=self.create()
        for override in ({'metric':'magic_score'},{'year':2024},{'threshold':'NaN'}):
            p=plan();p['questions'][0].update(override)
            with self.assertRaises(ContractError):validate_plan(p,s)

    def test_company_comparison_checks_scope_and_revision_preserves_parent(self):
        left=self.research();self.http.body=sec_body(current=140,entity=789019)
        right=self.research(entity='CIK0000789019')
        comparison=self.agent.compare(left['id'],right['id']);self.assertTrue(comparison['rows'][0]['comparable'])
        child=self.create(parent_id=left['id'],statement='新命题')
        self.assertEqual(child['parent_id'],left['id']);self.assertEqual(self.agent.get(left['id'])['report'],left['report'])

    def test_restart_marks_uncertain_call_and_resume_does_not_replay(self):
        s=self.create();s.update(status='running',stage='Execute',jobs=[{'id':'j','tool':'sec_facts','status':'running','metrics':['operating_income']}])
        s['plan']=plan();s['calls']=[{'id':'c','tool':'sec_facts','status':'running'}];self.agent.save(s,'synthetic_crash')
        recovered=AgentRuntime(self.store,settings=self.settings,model=self.model,http=self.http)
        s=recovered.get(s['id']);self.assertEqual(s['calls'][0]['status'],'interrupted')
        recovered.launch(s['id'],{'version':s['version'],'action':'resume'})
        for t in list(recovered.workers.values()):t.join(5)
        s=recovered.get(s['id']);self.assertEqual(s['report']['conclusion'],'unverifiable');self.assertEqual(self.http.requests,[])

    def test_raw_sec_metadata_and_locator_not_trusted_on_model_word(self):
        body=sec_body(entity=789019);self.http.body=body
        with self.assertRaisesRegex(ContractError,'sec_company_mismatch'):self.agent.sec.fetch('CIK0000320193',['operating_income'],2025)
        raw=json.loads(sec_body());raw['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax']['units']['USD'][0]['val']='120'
        self.http.body=json.dumps(raw).encode()
        with self.assertRaises(ContractError):self.agent.sec.fetch('CIK0000320193',['operating_income'],2025)

    def test_settings_never_echo_secrets(self):
        d=self.settings.configure({'financial_key':'PRIVATE_FINANCE_KEY'})
        self.assertTrue(d['financial_configured']);self.assertNotIn('PRIVATE_FINANCE_KEY',json.dumps(d))
        self.settings.configure({'provider':'qwen'});self.assertFalse(self.settings.public()['model_configured'])


if __name__=='__main__':unittest.main()
