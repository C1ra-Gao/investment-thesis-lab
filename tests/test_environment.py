"""Environment-only credentials and consent separation. All keys are fixtures."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest

from thesislab.environment import read_environment
from thesislab.live_providers import ProviderSettings
from thesislab.domain import ContractError
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.web_server import make_server
from thesislab.agent_runtime import AgentRuntime
from tests.test_agent_runtime import FixtureModel,FixtureHTTP


class EnvironmentTests(unittest.TestCase):
    def test_file_and_process_precedence_no_execution_or_interpolation(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'.env';path.write_text('THESISLAB_LLM_PROVIDER=qwen\nTHESISLAB_LLM_API_KEY="FIXTURE SECRET"\nLITERAL="$(echo danger)"\n')
            values=read_environment(path,environ={'THESISLAB_LLM_PROVIDER':'deepseek'})
            self.assertEqual(values['THESISLAB_LLM_PROVIDER'],'deepseek')
            self.assertEqual(values['LITERAL'],'$(echo danger)')
            self.assertEqual(values['THESISLAB_LLM_API_KEY'],'FIXTURE SECRET')

    def test_provider_switch_and_all_secrets_stay_server_side(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'.env';path.write_text('THESISLAB_LLM_PROVIDER=qwen\nTHESISLAB_LLM_MODEL=qwen-plus\nTHESISLAB_LLM_API_KEY=MODEL_FIXTURE_SECRET\nTHESISLAB_FINANCIAL_PROVIDER=fuyao\nTHESISLAB_FINANCIAL_API_KEY=FINANCE_FIXTURE_SECRET\nTHESISLAB_SEC_CONTACT=contact@example.invalid\nTHESISLAB_ALLOW_PUBLIC_DISCLOSURES=true\n')
            settings=ProviderSettings.from_environment(path,environ={})
            public=settings.public();self.assertEqual(public['provider'],'qwen')
            self.assertTrue(public['model_configured']);self.assertTrue(public['financial_configured'])
            self.assertFalse(public['public_enabled']);self.assertTrue(public['public_allowed'])
            for private in ('MODEL_FIXTURE_SECRET','FINANCE_FIXTURE_SECRET','contact@example.invalid'):
                self.assertNotIn(private,json.dumps(public))
            self.assertTrue(settings.consent(True)['public_enabled'])
            restarted=ProviderSettings.from_environment(path,environ={})
            self.assertFalse(restarted.public()['public_enabled']);self.assertTrue(restarted.public()['model_configured'])
            changed=ProviderSettings.from_environment(path,environ={'THESISLAB_LLM_PROVIDER':'openai','THESISLAB_LLM_MODEL':'fixture-model'})
            self.assertEqual(changed.public()['model'],'fixture-model')

    def test_permission_gate_independent_of_key_and_invalid_config_fails_closed(self):
        settings=ProviderSettings.from_environment('/nonexistent-test-env',environ={'THESISLAB_LLM_API_KEY':'FIXTURE'})
        with self.assertRaisesRegex(ContractError,'public_disclosures_disabled'):settings.consent(True)
        self.assertTrue(settings.public()['model_configured'])
        for env in ({'THESISLAB_LLM_PROVIDER':'unknown'},{'THESISLAB_FINANCIAL_PROVIDER':'unknown'},{'THESISLAB_ALLOW_PUBLIC_DISCLOSURES':'maybe'}):
            with self.assertRaises(ContractError):ProviderSettings.from_environment('/nonexistent-test-env',environ=env)


class AgentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'http.sqlite')
        self.settings=ProviderSettings.from_environment('/nonexistent-test-env',environ={
            'THESISLAB_LLM_API_KEY':'HTTP_FIXTURE_SECRET','THESISLAB_ALLOW_PUBLIC_DISCLOSURES':'true',
            'THESISLAB_SEC_CONTACT':'fixture@example.invalid'})
        self.agent=AgentRuntime(self.store,settings=self.settings,model=FixtureModel(),http=FixtureHTTP())
        self.server=make_server(Workspace(self.store),agent=self.agent)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_port
        c=HTTPConnection('127.0.0.1',self.port);c.request('GET','/research');r=c.getresponse();self.html=r.read().decode();self.cookie=r.getheader('Set-Cookie').split(';')[0];c.close()
        _,session=self.request('/api/session');self.csrf=session['csrf']

    def tearDown(self):
        for worker in list(self.agent.workers.values()):worker.join(8)
        self.server.shutdown();self.server.server_close();self.thread.join();self.store.close();self.temp.cleanup()

    def request(self,path,body=None):
        c=HTTPConnection('127.0.0.1',self.port,timeout=10)
        headers={'Cookie':self.cookie}
        if body is not None:headers.update({'Content-Type':'application/json','Origin':f'http://127.0.0.1:{self.port}','X-ThesisLab-CSRF':self.csrf})
        c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        r=c.getresponse();raw=r.read();status=r.status;c.close()
        try:return status,json.loads(raw)
        except ValueError:return status,raw.decode()

    def poll(self,id):
        for _ in range(100):
            status,s=self.request('/api/agent/tasks/'+id)
            if s['status']!='running':return s
            time.sleep(.02)
        self.fail('worker timed out')

    def test_environment_only_http_contract_and_no_key_fields(self):
        status,settings=self.request('/api/agent/settings');self.assertEqual(status,200)
        self.assertNotIn('HTTP_FIXTURE_SECRET',json.dumps(settings));self.assertNotIn('model_key',settings)
        self.assertEqual(self.request('/api/agent/settings',{'model_key':'UNTRUSTED_BROWSER_KEY'})[0],405)
        self.assertEqual(self.request('/api/agent/consent',{'enabled':True,'financial_key':'BAD'})[0],400)
        status,state=self.request('/api/agent/consent',{'enabled':True});self.assertEqual(status,200);self.assertTrue(state['public_enabled'])
        status,js=self.request('/research.js');self.assertEqual(status,200)
        self.assertNotIn('type="password"',js);self.assertNotIn('name="model_key"',js);self.assertNotIn('name="financial_key"',js)
        self.assertIn('/api/agent/consent',js)

    def test_full_http_background_flow_comparison_followup_export_reopen(self):
        self.request('/api/agent/consent',{'enabled':True})
        status,s=self.request('/api/agent/tasks',{'entity':'CIK0000320193','year':2025,'period':'annual','statement':'SYNTHETIC FIXTURE ONLY: annual revenue grew'})
        self.assertEqual(status,201);id=s['id']
        status,_=self.request(f'/api/agent/tasks/{id}/launch',{'version':s['version']});self.assertEqual(status,202)
        s=self.poll(id);self.assertEqual(s['stage'],'Plan')
        status,s=self.request(f'/api/agent/tasks/{id}/edit',{'version':s['version'],'plan':s['plan']});self.assertEqual(status,200)
        status,_=self.request(f'/api/agent/tasks/{id}/execute',{'version':s['version']});self.assertEqual(status,202)
        s=self.poll(id);self.assertEqual(s['report']['conclusion'],'support',s['error'])
        status,evidence=self.request(f'/api/agent/tasks/{id}/evidence');self.assertEqual(status,200);self.assertEqual(len(evidence),3)
        status,s=self.request(f'/api/agent/tasks/{id}/followup',{'version':s['version'],'question':'Why insufficient for causation?'})
        self.assertEqual(status,200);self.assertEqual(len(s['followups']),1)
        self.assertNotIn('HTTP_FIXTURE_SECRET',json.dumps({'task':s,'evidence':evidence}))
        status,restored=self.request(f'/api/agent/tasks/{id}');self.assertEqual(restored,s)
        status,child=self.request(f'/api/agent/tasks/{id}/revise',{'version':s['version'],'statement':'Revised synthetic thesis'})
        self.assertEqual(status,201);self.assertEqual(child['parent_id'],id)


if __name__=='__main__':unittest.main()
