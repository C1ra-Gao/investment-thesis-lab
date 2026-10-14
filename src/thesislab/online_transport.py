"""Explicitly authorized, bounded public HTTPS; no credentials, proxy or automatic retry."""
from dataclasses import dataclass, field
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
from uuid import uuid4
import json

from .domain import ContractError, encode
from .store import now


class NetworkLedger:
    """Durable reservations count failed/uncertain calls across server restarts."""
    def __init__(self, engine, *, authorized=False, model_limit=2, public_limit=8):
        self.engine=engine;self.authorized=authorized;self.limits={"model":model_limit,"public":public_limit}
        with engine.begin() as c:
            c.exec_driver_sql('CREATE TABLE IF NOT EXISTS v2_network_ledger (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, phase TEXT NOT NULL, attempt TEXT NOT NULL, payload TEXT NOT NULL)')
            for op in ('UPDATE','DELETE'):
                c.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS immutable_v2_ledger_{op.lower()} BEFORE {op} ON v2_network_ledger BEGIN SELECT RAISE(ABORT,'append_only_record'); END")
    def record(self,kind,phase,attempt,payload):
        with self.engine.begin() as c:
            c.exec_driver_sql('INSERT INTO v2_network_ledger(kind,phase,attempt,payload) VALUES (?,?,?,?)',(kind,phase,attempt,encode({"at":now(),**payload})))
    def reserve(self,kind,reference):
        if not self.authorized:raise ContractError('online_budget_not_authorized')
        with self.engine.connect() as c:
            c.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                rows=c.exec_driver_sql('SELECT payload FROM v2_network_ledger WHERE phase=?',('result',)).scalars()
                if any(json.loads(x).get('http_status') in (401,402,403,429) for x in rows):raise ContractError('network_permission_or_rate_stop')
                used=c.exec_driver_sql('SELECT COUNT(*) FROM v2_network_ledger WHERE kind=? AND phase=?',(kind,'reserved')).scalar()
                if used>=self.limits[kind]:raise ContractError('network_request_budget_exhausted')
                attempt=uuid4().hex
                c.exec_driver_sql('INSERT INTO v2_network_ledger(kind,phase,attempt,payload) VALUES (?,?,?,?)',(kind,'reserved',attempt,encode({'at':now(),'reference':reference})))
                c.commit();return attempt
            except Exception:c.rollback();raise
    def records(self):
        with self.engine.connect() as c:
            return [dict(sequence=r[0],kind=r[1],phase=r[2],attempt=r[3],**json.loads(r[4])) for r in c.exec_driver_sql('SELECT * FROM v2_network_ledger ORDER BY sequence')]


class MeteredModelTransport:
    def __init__(self,transport,ledger):self.transport=transport;self.ledger=ledger
    def send(self,body,*,timeout):
        token=self.ledger.reserve('model','deepseek-flash:public_thesis_only')
        try:
            result=self.transport.send(body,timeout=timeout)
            self.ledger.record('model','result',token,{'http_status':result.status,'complete':result.complete,'received_bytes':result.received_bytes,'error_type':result.error_type})
            return result
        except Exception as exc:
            self.ledger.record('model','result',token,{'error_type':type(exc).__name__});raise


@dataclass(frozen=True)
class PublicResponse:
    url:str
    status:int
    body:bytes=field(repr=False)
    content_type:str
    acquired_at:str
    request_id:str


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):super().__init__(host,timeout=timeout);self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=self.host)
        except Exception:raw.close();raise


class PublicHTTPS:
    def __init__(self,ledger,*,hosts,timeout=25,max_bytes=15_000_000):
        self.ledger=ledger;self.hosts=frozenset(hosts);self.timeout=timeout;self.max_bytes=max_bytes;self.robots={}
    def validate(self,url):
        p=urlsplit(url)
        if p.scheme!='https' or p.hostname not in self.hosts or p.port not in (None,443) or p.username or p.password or p.fragment:
            raise ContractError('public_url_not_allowed')
        if any(x in p.query.lower() for x in ('api_key','apikey','token=','password','signature=')):
            raise ContractError('credential_like_query_forbidden')
        return p
    def get(self,url):
        p=self.validate(url)
        if p.hostname not in self.robots:
            response=self._get('https://'+p.hostname+'/robots.txt')
            parser=RobotFileParser()
            if response.status==404:parser.parse([])
            elif response.status==200:parser.parse(response.body.decode('utf-8','replace').splitlines())
            else:raise ContractError('robots_permission_unverified')
            self.robots[p.hostname]=parser
        if not self.robots[p.hostname].can_fetch('ThesisLabResearch',url):raise ContractError('robots_access_disallowed')
        return self._get(url)
    def _get(self,url):
        for hop in range(3):
            p=self.validate(url);attempt=self.ledger.reserve('public',url);connection=None;status=None;received=0
            try:
                addresses={item[4][0] for item in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
                if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):raise ContractError('public_dns_not_global')
                connection=_PinnedHTTPS(p.hostname,sorted(addresses)[0],self.timeout)
                connection.request('GET',p.path+('?' + p.query if p.query else ''),headers={'User-Agent':'ThesisLabResearch/2.0 (source verification; https://github.com/C1ra-Gao/investment-thesis-lab)','Accept-Encoding':'identity','Accept':'text/html,application/pdf,text/plain'})
                r=connection.getresponse();status=r.status
                if status in (301,302,303,307,308):
                    target=urljoin(url,r.getheader('Location',''));self.validate(target)
                    self.ledger.record('public','result',attempt,{'http_status':status,'redirect':target,'received_bytes':0,'complete':True});url=target;continue
                body=r.read(self.max_bytes+1);received=len(body)
                if received>self.max_bytes:raise ContractError('public_response_too_large')
                if r.getheader('Content-Length') is not None and int(r.getheader('Content-Length'))!=received:raise ContractError('public_response_incomplete')
                if r.getheader('Content-Encoding','identity').lower()!='identity':raise ContractError('unexpected_public_compression')
                self.ledger.record('public','result',attempt,{'http_status':status,'received_bytes':received,'complete':True})
                if status in (401,402,403,429):raise ContractError('public_permission_or_rate_denied')
                return PublicResponse(url,status,body,r.getheader('Content-Type','').split(';')[0],now(),attempt)
            except Exception as exc:
                self.ledger.record('public','failure',attempt,{'http_status':status,'received_bytes':received,'complete':False,'error_type':str(exc) if isinstance(exc,ContractError) else type(exc).__name__})
                raise ContractError(str(exc) if isinstance(exc,ContractError) else 'public_transport_'+type(exc).__name__) from None
            finally:
                if connection:connection.close()
        raise ContractError('public_redirect_limit')
