"""Loopback-only Web MVP. No public deployment, arbitrary file serving or API keys in HTTP."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit, unquote

from .cli import private_output, PROJECT_ROOT
from .domain import ContractError, encode
from .schema import SourceRecord
from .store import Store
from .workspace import Workspace, RevisionConflict

STATIC = Path(__file__).parent / "web"


def make_server(workspace, port=0, *, online=None, financial_tools=None, agent=None, bind_host='127.0.0.1'):
    session_secret, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    from .orchestrator import Orchestrator
    orchestrator = Orchestrator(workspace,financial_tools=financial_tools)
    if agent is None:
        from .agent_runtime import AgentRuntime
        agent = AgentRuntime(workspace.store)
    class Handler(BaseHTTPRequestHandler):
        server_version = "ThesisLabLocal"
        def setup(self):
            super().setup();self.connection.settimeout(120)
        def log_message(self, *args):pass  # Never log user URLs, bodies or cookies.
        def headers_common(self, media):
            self.send_header("Content-Type", media)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        def send(self, status, body, media="application/json; charset=utf-8", cookie=False):
            self.send_response(status);self.headers_common(media)
            if cookie:self.send_header("Set-Cookie", "thesislab_session="+session_secret+"; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
        def result(self, data, status=200):self.send(status,encode(data).encode())
        def allowed_host(self):
            p = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{p}",f"localhost:{p}")
        def authenticated(self):
            cookie=SimpleCookie()
            try:cookie.load(self.headers.get("Cookie", ""))
            except Exception:return False
            return bool(cookie.get("thesislab_session")) and secrets.compare_digest(cookie["thesislab_session"].value,session_secret)
        def do_GET(self):
            if not self.allowed_host():return self.result({"error":"host_not_allowed"},403)
            path=unquote(urlsplit(self.path).path)
            if path in ("/","/app.js","/style.css","/research","/research.js","/research.css"):
                name={"/":"index.html","/app.js":"app.js","/style.css":"style.css",'/research':'research.html','/research.js':'research.js','/research.css':'research.css'}[path]
                media='text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                return self.send(200,(STATIC/name).read_bytes(),media,cookie=path in ('/','/research'))
            if not self.authenticated():return self.result({"error":"local_session_required"},401)
            try:
                if path=='/api/agent/settings':return self.result(agent.settings.public())
                if path=='/api/agent/tasks':return self.result(agent.list())
                if path.startswith('/api/agent/tasks/'):
                    parts=path.split('/');task=agent.get(parts[4])
                    if len(parts)==6 and parts[5]=='evidence':return self.result([agent.evidence(i) for i in task['evidence_ids']])
                    return self.result(task)
                if path=="/api/session":return self.result({"csrf":csrf,"mode":"local_private","model_enabled":workspace.provider is not None,"model_mode":workspace.model_mode,"version":"M4 Workspace" if financial_tools else "V2" if online else "V1","financial_mode":"fuyao_real_history" if financial_tools else "live_public_disclosures" if online else "offline_internal_corpus","financial_history":financial_tools is not None,"online_enabled":online is not None,"issuer_options":list(__import__('thesislab.online_research',fromlist=['ISSUERS']).ISSUERS) if online else []})
                if path=="/api/tasks":return self.result(workspace.list())
                if path=="/api/evidence":return self.result(workspace.catalog())
                if path=="/api/conflicts":return self.result(workspace.conflicts())
                if path=="/api/model-candidates":return self.result(workspace.cached_candidates())
                if path.startswith("/api/tasks/"):
                    parts=path.split("/");task_id=parts[3]
                    if len(parts)==5 and parts[4]=="history":return self.result(workspace.timeline(task_id))
                    return self.result(workspace.get(task_id))
                if path.startswith("/api/runs/"):return self.result(workspace.engine.get(path.split("/")[3],"run"))
                if path.startswith("/api/evidence/"):return self.result(workspace.store.trace(path.split("/")[3]))
                if path.startswith("/api/artifacts/"):
                    a=workspace.store.artifact(path.split("/")[3]);source=workspace.store._payload(SourceRecord,a["source_id"])
                    if a["media_type"]!="application/pdf" or source["kind"]!="issuer_report":
                        return self.result({"error":"raw_provider_material_not_served"},403)
                    return self.send(200,a["body"],"application/pdf")
                return self.result({"error":"not_found"},404)
            except (KeyError,ValueError):return self.result({"error":"not_found_or_invalid_reference"},404)
        def do_POST(self):
            if not self.allowed_host() or not self.authenticated():return self.result({"error":"local_session_required"},403)
            if self.headers.get("Origin") not in (f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"):
                return self.result({"error":"same_origin_required"},403)
            if not secrets.compare_digest(self.headers.get("X-ThesisLab-CSRF", ""),csrf):return self.result({"error":"csrf_required"},403)
            if self.headers.get("Content-Type")!="application/json":return self.result({"error":"json_content_type_required"},415)
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=512000:return self.result({"error":"invalid_request_size"},413)
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ContractError("json_object_required")
                path=urlsplit(self.path).path
                if path=='/api/agent/settings':
                    return self.result({'error':'provider_configuration_is_environment_only'},405)
                if path=='/api/agent/consent':
                    if set(body)!={'enabled'}:raise ContractError('only_public_consent_allowed')
                    if agent.workers:raise ContractError('wait_for_running_tasks_before_consent_change')
                    return self.result(agent.settings.consent(body['enabled']))
                if path=='/api/agent/tasks':return self.result(agent.create(body),201)
                if path.startswith('/api/agent/tasks/'):
                    parts=path.split('/')
                    if len(parts)!=6:return self.result({'error':'not_found'},404)
                    task_id,action=parts[4:]
                    if action=='edit':return self.result(agent.edit(task_id,body))
                    if action in ('launch','execute','resume'):return self.result(agent.launch(task_id,{**body,'action':action}),202)
                    if action=='pause':return self.result(agent.pause(task_id))
                    if action=='followup':return self.result(agent.followup(task_id,body))
                    if action=='compare':return self.result(agent.compare(task_id,body['other_id']))
                    if action=='revise':
                        parent=agent.get(task_id)
                        return self.result(agent.create({**parent,**body,'parent_id':task_id}),201)
                    return self.result({'error':'not_found'},404)
                if path=="/api/tasks":return self.result(workspace.create(body["statement"]))
                if path=="/api/research-plan":
                    if financial_tools is None:raise ContractError('historical_financial_tools_not_configured')
                    return self.result(workspace.history_financial_plan(body['statement']))
                if path=="/api/example":return self.result(workspace.example())
                if path=="/api/import-model":return self.result(workspace.load_cached(int(body["number"])))
                parts=path.split("/")
                if len(parts)!=5 or parts[1:3]!=["api","tasks"]:return self.result({"error":"not_found"},404)
                task_id,action=parts[3:]
                expected=body["version"]
                if type(expected) is not int:raise ContractError("version_required")
                if action=="save":return self.result(workspace.edit(task_id,expected,body["design"],body.get("bindings"),reason=body.get("reason","用户编辑")))
                if action=="prepare-plan":return self.result(workspace.prepare_plan(task_id,expected))
                if action=="edit-plan":return self.result(workspace.edit_plan(task_id,expected,actions=body.get('actions',{}),answers=body.get('answers',{})))
                if action=="manual-fallback":
                    from .workspace import manual_design
                    state=workspace.get(task_id)
                    return self.result(workspace.edit(task_id,expected,manual_design(state["statement"]),{},reason="用户明确回退人工草稿；保留原模型输出"))
                if action=="confirm":return self.result(workspace.confirm(task_id,expected,reviewer="local_operator",notes=body["notes"],
                    accepted_suggestions=body.get("accepted_suggestions",[]),meaning_reviewed=body.get("meaning_reviewed") is True))
                if action=="run":return self.result(workspace.run(task_id,expected,as_of=body["as_of"]))
                if action=="orchestrate":return self.result(orchestrator.start(task_id,expected,body["as_of"]))
                if action=="agent-step":return self.result(orchestrator.step(task_id,expected))
                if action in ("pause","resume"):return self.result(orchestrator.control(task_id,expected,action))
                if action=="version-compare":return self.result(orchestrator.compare_versions(task_id,body["left_version"],body["right_version"]))
                if action=="generate":
                    if workspace.model_mode=="deepseek_live" and body.get("model_consent") is not True:
                        raise ContractError("explicit_model_call_consent_required")
                    return self.result(workspace.model_generate(task_id,expected))
                if action.startswith('online-'):
                    if online is None:raise ContractError('online_tools_disabled')
                    if action=='online-start':return self.result(online.start(task_id,expected,entity=body['entity'],year=body['year'],period=body['period'],as_of=body['as_of'],consent=body.get('public_consent')))
                    if action=='online-step':return self.result(online.step(task_id,expected))
                    if action in ('online-pause','online-resume'):return self.result(online.control(task_id,expected,action.split('-')[1]))
                    if action=='online-rules':return self.result(online.accept_rules(task_id,expected,accepted=body.get('accepted'),notes=body['notes']))
                if action=="followup":return self.result(workspace.followup(task_id,expected,question=body["question"],mode=body["mode"],topic=body.get("topic","conclusion"),entity=body.get("entity")))
                if action=="compare":return self.result(workspace.compare(task_id,expected,other_task_id=body["other_task_id"],left_id=body.get("left_id"),right_id=body.get("right_id")))
                if action=="review-conflict":
                    with workspace.lock:
                        state=workspace.get(task_id)
                        if state["version"]!=expected:raise RevisionConflict("research_changed_reload_before_saving")
                        workspace.store.review(body["conflict_id"],reviewer="local_operator",reason=body["reason"],
                            selected_evidence_id=body.get("evidence_id"),field=body.get("field"),keep_unresolved=body.get("keep_unresolved",True))
                        state["stage"]="needs_revalidation"
                        return self.result(workspace.save(state,expected,"conflict_reviewed"))
                if action=="condition":
                    with workspace.lock:
                        state=workspace.get(task_id)
                        if state["version"]!=expected:raise RevisionConflict("research_changed_reload_before_saving")
                        if state["semantic_review"]!="user_confirmed":raise ContractError("confirm_plan_before_condition_check")
                        result=workspace.engine.check_condition(state["confirmed_id"],body["condition_id"],reviewer="local_operator",observed_on=body["observed_on"],
                            evidence_id=body.get("evidence_id"),event_occurred=body.get("event_occurred"),reason=body.get("reason"))
                        state["condition_checks"].append({"id":result,**workspace.engine.get(result)})
                        if workspace.engine.get(result)["triggered"]:state["stage"]="needs_revalidation"
                        return self.result(workspace.save(state,expected,"condition_checked"))
                return self.result({"error":"not_found"},404)
            except RevisionConflict as exc:return self.result({"error":str(exc)},409)
            except ContractError as exc:return self.result({"error":str(exc)},400)
            except (KeyError,ValueError,TypeError,AttributeError):return self.result({"error":"invalid_input_or_reference"},400)
            except Exception:return self.result({"error":"operation_failed_not_saved"},500)
    return ThreadingHTTPServer((bind_host,port),Handler)


def main(argv=None):
    p=argparse.ArgumentParser(description="ThesisLab loopback Web MVP; no public deployment")
    p.add_argument("--db",default=".local/m3.sqlite");p.add_argument("--port",type=int,default=8765)
    p.add_argument("--phase3-root");p.add_argument("--model-cache");p.add_argument("--enable-deepseek",action="store_true")
    p.add_argument('--enable-public-research',action='store_true')
    p.add_argument('--model-limit',type=int,default=2);p.add_argument('--public-limit',type=int,default=8)
    p.add_argument('--output-limit',type=int,default=8000)
    args=p.parse_args(argv)
    store=Store(private_output(args.db))
    if args.phase3_root:
        from .regression import verify_phase3
        root=Path(args.phase3_root).resolve()
        if root.is_relative_to(PROJECT_ROOT):raise ContractError("real_source_material_must_stay_outside_project")
        verify_phase3(root,store)
    provider=None
    online=None
    from .online_transport import NetworkLedger,MeteredModelTransport,PublicHTTPS
    ledger=NetworkLedger(store.engine,authorized=args.enable_deepseek or args.enable_public_research,model_limit=args.model_limit,public_limit=args.public_limit)
    if args.enable_deepseek:
        from .deepseek import CallBudget,DeepSeekCandidateProvider
        from .deepseek_transport import HTTPSDeepSeekTransport
        from .deepseek_keychain import read_authorized_key
        from .deepseek_prompt import PROMPTS
        provider=DeepSeekCandidateProvider(CallBudget(args.model_limit,args.output_limit,True),transport=MeteredModelTransport(HTTPSDeepSeekTransport(read_authorized_key),ledger),
            system_prompt=PROMPTS["thesislab-candidate-v2"],prompt_version="thesislab-candidate-v2",character_map=True)
    cache=Path(args.model_cache).resolve() if args.model_cache else None
    if cache and not cache.is_relative_to((PROJECT_ROOT/".local").resolve()):raise ContractError("model_cache_must_stay_private_local")
    workspace=Workspace(store,provider=provider,model_cache=cache)
    if args.enable_public_research:
        from .online_research import OnlineResearch
        online=OnlineResearch(workspace,PublicHTTPS(ledger,hosts=['www.moutaichina.com']))
    server=make_server(workspace,args.port,online=online)
    print(f"ThesisLab local-only: http://127.0.0.1:{server.server_port}",flush=True)
    print("Private data stays local. Model calls occur only on explicit Generate; no automatic retry.",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();store.close()


if __name__=="__main__":main()
