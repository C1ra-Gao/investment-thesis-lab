"""WSGI deployment boundary: authenticated single-user databases behind HTTPS.

The existing loopback application remains private behind this gateway. Production
configuration is loaded only by create_app; offline tests inject synthetic users.
"""
import base64
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
import json
from pathlib import Path
import secrets
from threading import Thread,RLock
from time import time
from urllib.parse import parse_qs

from .cli import private_output
from .store import Store
from .workspace import Workspace
from .web_server import make_server

LOGIN=b'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ThesisLab Login</title><h1>ThesisLab Research Workspace</h1><p>Private research. Sign in with your assigned account.</p><form method="post" action="/login"><label>User <input name="user" maxlength="80" autocomplete="username" required></label><label>Password <input type="password" name="password" maxlength="256" autocomplete="current-password" required></label><button>Sign in</button></form></html>'''

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),300000).hex()

class Gateway:
    def __init__(self,users,signing_key,origin,*,workspace_factory=None):
        if not origin.startswith('https://') or len(signing_key)<32:raise ValueError('https_origin_and_strong_session_secret_required')
        self.users=users;self.key=signing_key.encode();self.origin=origin.rstrip('/');self.services={};self.lock=RLock();self.failures={}
        self.factory=workspace_factory or self._factory
    def _factory(self,user):
        # New empty per-user database, never seeded with internal supplier materials.
        identity=hashlib.sha256(user.encode()).hexdigest()
        store=Store(private_output('.local/tenants/'+identity+'.sqlite'));ws=Workspace(store);ws.owner=identity
        return ws
    def token(self,user):
        payload=base64.urlsafe_b64encode(json.dumps({'user':user,'expires':int(time())+3600}).encode()).decode()
        return payload+'.'+hmac.new(self.key,payload.encode(),'sha256').hexdigest()
    def principal(self,cookie):
        try:
            c=SimpleCookie();c.load(cookie);value=c['thesislab_login'].value;p,sig=value.split('.')
            if not hmac.compare_digest(sig,hmac.new(self.key,p.encode(),'sha256').hexdigest()):return None
            d=json.loads(base64.urlsafe_b64decode(p))
            return d['user'] if d['expires']>time() and d['user'] in self.users else None
        except (ValueError,KeyError,TypeError):return None
    def response(self,start,status,body,extra=()):
        start(status,[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),*extra]);return [body]
    def __call__(self,e,start):
        path=e.get('PATH_INFO','/');method=e.get('REQUEST_METHOD','GET')
        if method=='POST' and e.get('HTTP_ORIGIN')!=self.origin:return self.response(start,'403 Forbidden',b'Origin denied')
        if path=='/login':
            if method=='GET':return self.response(start,'200 OK',LOGIN)
            if method!='POST':return self.response(start,'405 Method Not Allowed',b'Method denied')
            try:
                length=int(e.get('CONTENT_LENGTH','0'))
                if not 0<length<=2048:raise ValueError()
                form=parse_qs(e['wsgi.input'].read(length).decode());user=form.get('user',[''])[0];password=form.get('password',[''])[0]
            except (ValueError,UnicodeError):return self.response(start,'400 Bad Request',b'Invalid login')
            remote=e.get('REMOTE_ADDR','unknown');key=(remote,user);attempts,deadline=self.failures.get(key,(0,time()+300))
            if deadline<time():attempts=0;deadline=time()+300
            if attempts>=5:return self.response(start,'429 Too Many Requests',b'Wait before retrying')
            stored=self.users.get(user,'synthetic-placeholder$'+'0'*64);salt=stored.split('$')[0]
            good=hmac.compare_digest(password_hash(password,salt),stored)
            if not good or user not in self.users:
                self.failures[key]=(attempts+1,deadline);return self.response(start,'401 Unauthorized',b'Invalid credentials')
            return self.response(start,'303 See Other',b'',(('Location','/research'),('Set-Cookie','thesislab_login='+self.token(user)+'; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=3600')))
        user=self.principal(e.get('HTTP_COOKIE',''))
        if user is None:return self.response(start,'303 See Other',b'',(('Location','/login'),))
        if method not in ('GET','POST'):return self.response(start,'405 Method Not Allowed',b'Method denied')
        try:length=int(e.get('CONTENT_LENGTH') or '0')
        except ValueError:return self.response(start,'400 Bad Request',b'Invalid size')
        if not 0<=length<=512000:return self.response(start,'413 Payload Too Large',b'Request too large')
        with self.lock:
            if user not in self.services:
                ws=self.factory(user);server=make_server(ws);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);c.request('GET','/');r=c.getresponse();r.read();cookie=r.getheader('Set-Cookie').split(';')[0];c.close()
                self.services[user]=(server,thread,ws,cookie)
            server,thread,ws,cookie=self.services[user]
        c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=120)
        headers={'Cookie':cookie,'Origin':'http://127.0.0.1:'+str(server.server_port)}
        for src,dst in (('CONTENT_TYPE','Content-Type'),('HTTP_X_THESISLAB_CSRF','X-ThesisLab-CSRF')):
            if e.get(src):headers[dst]=e[src]
        body=e['wsgi.input'].read(length) if length else None
        try:
            c.request(method,path,body=body,headers=headers);r=c.getresponse();data=r.read()
            response_headers=[(k,v) for k,v in r.getheaders() if k.lower() not in ('set-cookie','server','date','connection','transfer-encoding')]
            start(str(r.status)+' '+r.reason,response_headers);return [data]
        finally:c.close()
    def close(self):
        for server,thread,ws,cookie in self.services.values():server.shutdown();server.server_close();thread.join();ws.store.close()

def create_app():
    import os
    # Hosting operator provisions secrets; this factory is not invoked by local
    # development or automated tests, and never returns config through HTTP.
    origin=os.environ['THESISLAB_PUBLIC_ORIGIN'];key=os.environ['THESISLAB_SESSION_SIGNING_KEY']
    path=private_output(os.environ.get('THESISLAB_USERS_FILE','.private/users.json'))
    return Gateway(json.loads(path.read_text()),key,origin)
