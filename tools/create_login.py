"""Create/update a private password-hash file; secrets never enter command args."""
import getpass
import json
import os
from pathlib import Path
from thesislab.deploy_gateway import password_hash

user=input('Login user: ').strip()
if not user or len(user)>80:raise SystemExit('Invalid user')
password=getpass.getpass('Password (12+ characters): ')
if len(password)<12:raise SystemExit('Password too short')
if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords differ')
path=Path('.private/users.json');path.parent.mkdir(exist_ok=True,mode=0o700)
users=json.loads(path.read_text()) if path.exists() else {}
users[user]=password_hash(password)
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:json.dump(users,f)
print('Private password hashes saved; no plaintext password retained.')
