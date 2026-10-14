"""Natural-language acceptance with declared fixtures; no real or paid API requests."""
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest
from thesislab.store import Store
from thesislab.agent_runtime import AgentRuntime
from thesislab.live_providers import ProviderSettings
from thesislab.research_intent import validate_natural_plan,validate_intent,question_capability
from thesislab.domain import ContractError
from tests.natural_fixtures import CASES,NaturalFixtureHTTP,NaturalFixtureModel,question

class NaturalResearchTests(unittest.TestCase):
    def test_live_observed_metric_semantic_mismatch_blocks_execution(self):
        intent={'entities':[{'id':'e1','name':'微软','kind':'company','symbol':'CIK0000789019'}]}
        q={'entity_ids':['e1'],'tool':'sec_facts','kind':'numeric','metric':'operating_income_yoy',
           'statement':'微软营业利润同比改善','year':2025,'period':'annual'}
        self.assertIn('计划主张与指标不一致',question_capability(q,intent,[]))
        q.update(metric='cash_conversion',statement='现金转换率不低于2024年')
        self.assertIn('跨年度',question_capability(q,intent,[]))
        q.update(metric='parent_holder_net_profit',statement='归母净利润同比增长')
        self.assertIn('未接入',question_capability(q,intent,[]))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'natural.sqlite';self.store=Store(self.path)
        self.settings=ProviderSettings();self.settings.configure({'model_key':'NATURAL_TEST_KEY','public_enabled':True,'sec_contact':'test@example.invalid'})
        self.model=NaturalFixtureModel();self.http=NaturalFixtureHTTP()
        self.r=AgentRuntime(self.store,model=self.model,http=self.http,settings=self.settings)
    def tearDown(self):
        for thread in list(self.r.workers.values()):thread.join(10)
        self.store.close();self.temp.cleanup()
    def wait(self,id):
        for _ in range(400):
            s=self.r.get(id)
            if s['status']!='running':return s
            time.sleep(.01)
        self.fail('worker timeout')
    def prepare(self,statement):
        s=self.r.create({'statement':statement});self.assertEqual(s['stage'],'Understand')
        self.assertIsNone(s['entity']);self.assertIsNone(s['year'])
        self.r.launch(s['id'],{'version':s['version'],'action':'launch'});return self.wait(s['id'])
    def execute(self,s):
        self.r.launch(s['id'],{'version':s['version'],'action':'execute'});s=self.wait(s['id'])
        self.assertEqual(s['status'],'completed',s.get('error'));return s
    def test_six_types_enter_understand_and_dynamic_plan_without_fixed_form(self):
        for type,statement in CASES:
            with self.subTest(type=type):
                s=self.prepare(statement)
                self.assertEqual(s['understanding']['thesis_type'],type,s['error'])
                if type=='exploratory':
                    self.assertEqual(s['stage'],'Clarify');self.assertIsNone(s['plan'])
                    with self.assertRaises(ContractError):self.r.launch(s['id'],{'version':s['version'],'action':'execute'})
                    s=self.r.edit(s['id'],{'version':s['version'],'answers':{'subject':'微软；只用2025年年度财务事实作背景，持续性单独待验证。'}})
                    self.r.launch(s['id'],{'version':s['version'],'action':'launch'});s=self.wait(s['id'])
                self.assertEqual(s['stage'],'Plan',s['error']);self.assertTrue(s['plan']['questions'])
                self.assertTrue(all(q['support_test'] and q['counter_test'] and q['source_requirement'] for q in s['plan']['questions']))
                s=self.execute(s)
                if type!='profitability':self.assertEqual(s['report']['conclusion'],'unverifiable')
                else:self.assertEqual(s['report']['conclusion'],'support')
                if type in ('macro','supply_chain'):
                    self.assertEqual(s['evidence_ids'],[])
                    self.assertTrue(all(j['tool']=='unavailable' for j in s['jobs']))
                    self.assertTrue(s['assessments'][0]['reason'])
    def test_two_company_tools_preserve_identity_and_cash_comparison(self):
        s=self.execute(self.prepare(CASES[2][1]));calls=[c for c in s['calls'] if c['tool']=='sec_facts']
        self.assertEqual({c['parameters']['entity'] for c in calls},{'CIK0000789019','CIK0000320193'})
        a=next(a for a in s['assessments'] if a['question_id']=='cash')
        self.assertEqual(a['comparison_values'],['150.0','100']);self.assertEqual(a['direction'],'support')
        self.assertEqual(len(a['evidence_ids']),2)
        for id in a['evidence_ids']:self.assertEqual(self.r.evidence(id)['fact_type'],'calculation')
        self.assertEqual(s['report']['conclusion'],'unverifiable')
    def test_add_delete_edit_questions_persists_and_executes_changed_plan(self):
        s=self.prepare(CASES[0][1]);p=deepcopy(s['plan']);p['questions'].append(question('risk','现金流净利润比大于零',['msft'],metric='cash_conversion'))
        p['questions'][0]['threshold']='100'
        s=self.r.edit(s['id'],{'version':s['version'],'plan':p});s=self.execute(s)
        self.assertEqual(next(a for a in s['assessments'] if a['question_id']=='profit')['direction'],'refute')
        self.assertEqual(len(s['assessments']),2)
        child=self.prepare(CASES[0][1]);p=deepcopy(child['plan']);p['questions']=[question('different','现金流净利润比大于零',['msft'],metric='cash_conversion')]
        child=self.r.edit(child['id'],{'version':child['version'],'plan':p});child=self.execute(child)
        self.assertEqual([a['question_id'] for a in child['assessments']],['different'])
    def test_unresolved_entity_does_not_use_model_guessed_identifier(self):
        value={'objective':'未知公司盈利','thesis_type':'profitability','entities':[{'id':'x','name':'不知名公司','kind':'company','symbol':'CIK0000789019'}],
            'time_range':{'label':'2025年度','year':2025,'period':'annual'},'assumptions':[],'research_axes':[],'clarifications':[]}
        intent=validate_intent(value,'不知名公司盈利',{});self.assertIsNone(intent['entities'][0]['symbol'])
        s={'understanding':intent,'documents':[]};p=validate_natural_plan({'scope':'未知主体','questions':[question('q','盈利提高',['x'])]},s)
        self.assertEqual(p['questions'][0]['execution_support'],'unavailable')
    def test_conflict_and_failure_keep_unverifiable_and_sources_not_fabricated(self):
        self.http.conflict=True;s=self.execute(self.prepare(CASES[0][1]));self.assertEqual(s['report']['conclusion'],'unverifiable');self.assertTrue(s['conflicts'])
        self.http.conflict=False;self.http.error='upstream_http_403'
        s=self.execute(self.prepare(CASES[0][1]));self.assertEqual(s['report']['conclusion'],'unverifiable');self.assertEqual(s['evidence_ids'],[])
        self.assertTrue(any(c.get('error')=='upstream_http_403' for c in s['calls']))
    def test_followup_in_plan_and_conclusion_and_restore_are_preserved(self):
        s=self.prepare(CASES[1][1]);s=self.r.followup(s['id'],{'version':s['version'],'question':'哪些资料缺失？'})
        self.assertEqual(s['followups'][0]['type'],'model_inference_not_new_verified_fact')
        s=self.execute(s);s=self.r.followup(s['id'],{'version':s['version'],'question':'为什么还不能判断估值？'})
        self.assertEqual(len(s['followups']),2)
        reopened=Store(self.path)
        try:
            r=AgentRuntime(reopened,settings=ProviderSettings());self.assertEqual(r.get(s['id'])['report'],s['report']);self.assertEqual(len(r.get(s['id'])['followups']),2)
        finally:reopened.close()
    def test_invalid_graph_and_cross_entity_references_fail_before_query(self):
        s=self.prepare(CASES[0][1])
        for mutate in ('entity','cycle','empty'):
            p=deepcopy(s['plan'])
            if mutate=='entity':p['questions'][0]['entity_ids']=['invented']
            if mutate=='cycle':p['questions'][0]['depends_on']=['profit']
            if mutate=='empty':p['questions']=[]
            with self.assertRaises(ContractError):validate_natural_plan(p,s)
        self.assertEqual(self.http.requests,[])

    def test_future_period_remains_in_plan_without_querying_fabricated_results(self):
        s=self.prepare(CASES[0][1]);p=deepcopy(s['plan']);p['questions'][0].update(year=2027,time_range='2027年度预测')
        s=self.r.edit(s['id'],{'version':s['version'],'plan':p})
        self.assertEqual(s['plan']['questions'][0]['execution_support'],'unavailable')
        s=self.execute(s);self.assertEqual(s['report']['conclusion'],'unverifiable');self.assertEqual(self.http.requests,[])

if __name__=='__main__':unittest.main()
