"""Small non-executing .env reader; real process environment takes precedence."""
import os
from pathlib import Path
import re
import shlex
from .domain import ContractError

def read_environment(path='.env', *, environ=None):
    values={}
    path=Path(path)
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('export '):line=line[7:].strip()
            if '=' not in line:raise ContractError('invalid_env_assignment')
            name,value=line.split('=',1);name=name.strip()
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name):raise ContractError('invalid_env_name')
            try:
                parts=shlex.split(value,comments=True,posix=True)
                if len(parts)>1:raise ValueError()
                values[name]=parts[0] if parts else ''
            except ValueError:raise ContractError('invalid_env_value_use_quotes_for_spaces') from None
    values.update(dict(os.environ if environ is None else environ))
    return values

def boolean(value,default=False):
    if value is None:return default
    if value.lower() in ('true','1','yes'):return True
    if value.lower() in ('false','0','no',''):return False
    raise ContractError('invalid_boolean_environment_setting')
