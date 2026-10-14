"""Isolated synthetic browser acceptance server. Never a production startup path."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thesislab.agent_runtime import AgentRuntime
from thesislab.live_providers import ProviderSettings
from thesislab.store import Store
from thesislab.workspace import Workspace
from thesislab.web_server import make_server
from tests.natural_fixtures import NaturalFixtureModel,NaturalFixtureHTTP

class FixtureSettings(ProviderSettings):
    def public(self):return {**super().public(),'acceptance_fixture_mode':True}

settings=FixtureSettings()
settings.configure({'model_key':'SYNTHETIC_BROWSER_FIXTURE','public_enabled':True,'sec_contact':'fixture@example.invalid'})
store=Store('.local/natural-browser-fixture.sqlite')
agent=AgentRuntime(store,settings=settings,model=NaturalFixtureModel(),http=NaturalFixtureHTTP())
server=make_server(Workspace(store),8768,agent=agent)
print('SYNTHETIC ACCEPTANCE ONLY — no real model/data HTTP: http://127.0.0.1:8768/research',flush=True)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close();store.close()
