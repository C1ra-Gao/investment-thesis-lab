"""Safe metadata-only config check. No network, secret values or expanded Compose output."""
from pathlib import Path
import json
import os
import re
from thesislab.live_providers import ProviderSettings

names=('THESISLAB_LLM_PROVIDER','THESISLAB_LLM_MODEL','THESISLAB_LLM_API_KEY',
       'THESISLAB_FINANCIAL_PROVIDER','THESISLAB_FINANCIAL_API_KEY')
settings=ProviderSettings.from_environment()
public=settings.public();private=settings.snapshot()
def safe(value):
    if any(private[k] and private[k] in value for k in ('model_key','financial_key')):return '[redacted]'
    return value
declared=set()
path=Path('.env.example')
if path.exists():
    declared=set(re.findall(r'^([A-Z][A-Z0-9_]*)=',path.read_text(),re.M))
print(json.dumps({'provider':safe(public['provider']),'model':safe(public['model']),
    'model_key_configured':public['model_configured'],'financial_provider':public['financial_provider'],
    'financial_key_configured':public['financial_configured'],
    'backend_environment_names':list(names),'example_names_match':all(n in declared for n in names) if declared else None,
    'process_override_names_only':[n for n in names if n in os.environ],
    'network_requests':0,'secret_values_returned':False},ensure_ascii=False,indent=2))
