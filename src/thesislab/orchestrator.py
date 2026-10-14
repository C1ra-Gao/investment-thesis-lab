"""Auditable local research roles; no LLM text is admitted as financial evidence."""

from copy import deepcopy
from uuid import uuid4

from .domain import ContractError, encode
from .store import now
from .workspace import RevisionConflict

ROLES = (
    ("retrieval", "Evidence Retrieval Agent"),
    ("counter", "Counter-Evidence Agent"),
    ("conflict", "Conflict Resolution Agent"),
    ("assessment", "Conclusion Assessment Agent"),
    ("report", "Research Report Agent"),
)


class Orchestrator:
    def __init__(self, workspace, *, financial_tools=None):self.ws = workspace;self.financial_tools=financial_tools

    def plan_financial_requests(self,task_id,version,*,entity,report_ends):
        """Compile confirmed Evidence Tasks; official sources remain verification-only."""
        from .financial_tools import FinancialRequest
        from datetime import date,timedelta
        with self.ws.lock:
            s=self._checked(task_id,version);nodes={c['id']:c for c in s['design']['claims']};planned=[]
            ends=tuple(date.fromisoformat(x) if isinstance(x,str) else x for x in report_ends)
            for task in s['design']['tasks']:
                claim=nodes[task['claim_id']];pred=claim.get('predicate');dates=ends
                if pred:
                    scope=pred['scope']
                    if scope['entity']!=entity:raise ContractError('financial_request_entity_must_match_confirmed_claim')
                    end=date.fromisoformat(scope['end']);start=date.fromisoformat(scope['start'])
                    prior=end.replace(year=end.year-1,day=min(end.day,__import__('calendar').monthrange(end.year-1,end.month)[1]))
                    dates=(end,prior)
                    if scope['basis']=='single_period' and start.month!=1:
                        earlier=start-timedelta(days=1);dates+=(earlier,earlier.replace(year=earlier.year-1))
                    metric=scope['metric']
                    metrics=('operating_income','operating_costs') if metric in ('gross_margin','gross_margin_change') else ('operating_income',) if metric=='operating_income_yoy' else (metric,)
                elif claim['kind']=='attribution':
                    metrics=('operating_income','operating_costs','operating_profit','net_profit','parent_holder_net_profit','profit_total')
                    if task['purpose']=='discriminate':metrics+=('non_recurring_profit',)
                else:metrics=('operating_income','operating_costs')
                request=FinancialRequest(entity,metrics,dates,consolidation=pred['scope']['consolidation'] if pred else 'consolidated')
                planned.append({'task_id':task['id'],'claim_id':task['claim_id'],'purpose':task['purpose'],
                    'request':__import__('json').loads(encode(request)),
                    'reason':'confirmed_numeric_scope' if pred else 'context_only_cannot_prove_causal_or_attribution_claim'})
            s['financial_plan']={'confirmation_id':s['confirmed_id'],'design_hash':encode(s['design']),
                'primary_providers':['fuyao','ifind_mcp'],'official_disclosure_role':'original_fact_crosscheck_only',
                'requests':planned,'state':'planned','results':[]}
            return self.ws.save(s,version,'financial_plan_compiled')

    def acquire_financial(self,task_id,version):
        """Run provider tools; offline providers cannot send requests or load credentials."""
        from .financial_tools import FinancialRequest
        with self.ws.lock:
            s=self._checked(task_id,version);plan=s.get('financial_plan')
            if not plan or self.financial_tools is None:raise ContractError('financial_tools_and_plan_required')
            if plan['design_hash']!=encode(s['design']) or plan['confirmation_id']!=s['confirmed_id']:
                raise ContractError('financial_plan_requires_reconfirmation')
            if plan['state']!='planned':raise ContractError('financial_acquisition_already_recorded')
            for item in plan['requests']:
                request=FinancialRequest.from_dict(item['request']);result=self.financial_tools.fetch(request)
                record={'task_id':item['task_id'],'purpose':item['purpose'],**result.audit_summary()}
                try:record['admitted_ids']=self.financial_tools.admit(result,self.ws.store)
                except (ValueError,TypeError,KeyError):record.update(state='call_failed',reason='M1_admission_failed',admitted_ids=[])
                plan['results'].append(record)
            plan['state']='acquired_with_gaps' if any(r['state']!='available' or not r['admitted_ids'] for r in plan['results']) else 'acquired'
            return self.ws.save(s,version,'financial_acquisition_recorded')

    def calculate_financial(self,task_id,version):
        """Approved scope -> named M1 Decimal functions -> M2 task bindings."""
        from datetime import date,timedelta
        from .finance import gross_margin,yoy,margin_delta,cumulative_to_single
        import json
        with self.ws.lock:
            s=self._checked(task_id,version);plan=s.get('financial_plan')
            if not plan or plan['state'] not in ('acquired','acquired_with_gaps'):raise ContractError('acquire_financial_before_calculation')
            if plan['confirmation_id']!=s['confirmed_id'] or plan['design_hash']!=encode(s['design']):raise ContractError('financial_plan_requires_reconfirmation')
            ids={i for r in plan['results'] for i in r.get('issuer_evidence_ids',[]) if i in r.get('admitted_ids',[]) or r.get('admitted_ids')}
            candidates=[self.ws.store.evidence(i) for i in ids];derived=[];missing=[];bindings={}
            def raw(year,end_month,metric,entity):
                found=[e for e in candidates if e.scope.entity==entity and e.scope.end.year==year and e.scope.end.month==end_month and e.scope.metric==metric]
                if len(found)!=1:raise ContractError('unique_verified_financial_field_required')
                return found[0]
            def save(calc):self.ws.store.put_calculation(calc);derived.append(calc.id);return calc.result
            for c in s['design']['claims']:
                if 'predicate' not in c:continue
                scope=c['predicate']['scope'];end=date.fromisoformat(scope['end']);start=date.fromisoformat(scope['start']);entity=scope['entity'];metric=scope['metric']
                try:
                    def field(year,name):
                        e=raw(year,end.month,name,entity)
                        if scope['basis']=='single_period' and start.month!=1:
                            earlier=raw(year,(start-timedelta(days=1)).month,name,entity)
                            e=save(cumulative_to_single(e,earlier))
                        return e
                    if metric=='operating_income_yoy':e=save(yoy(field(end.year,'operating_income'),field(end.year-1,'operating_income')))
                    elif metric in ('gross_margin','gross_margin_change'):
                        gm=save(gross_margin(field(end.year,'operating_income'),field(end.year,'operating_costs')))
                        e=gm if metric=='gross_margin' else save(margin_delta(gm,save(gross_margin(field(end.year-1,'operating_income'),field(end.year-1,'operating_costs')))))
                    else:e=field(end.year,metric)
                    if json.loads(encode(e.scope))!=scope:raise ContractError('financial_calculation_scope_mismatch')
                    for task in s['design']['tasks']:
                        if task['claim_id']==c['id']:bindings[task['id']]={'evidence_id':e.id}
                except (ValueError,KeyError):missing.append({'claim_id':c['id'],'reason':'verified_input_or_approved_scope_missing'})
            s['bindings']=bindings;plan.update(state='calculated_with_gaps' if missing else 'calculated',calculation_ids=sorted(set(derived)),missing_claims=missing)
            return self.ws.save(s,version,'financial_calculations_bound')

    def _checked(self, task_id, version):
        s = self.ws.get(task_id)
        if s["version"] != version:raise RevisionConflict("research_changed_reload_before_saving")
        if s["semantic_review"] != "user_confirmed" or s.get("confirmed_design_hash") != encode(s["design"]):
            raise ContractError("confirm_current_graph_and_plan_before_research")
        return s

    def start(self, task_id, version, as_of):
        from datetime import date
        date.fromisoformat(as_of)
        with self.ws.lock:
            s = self._checked(task_id, version)
            old = s.get("orchestration")
            if old and old["status"] in ("running", "paused"):
                raise ContractError("resume_or_finish_existing_execution")
            s["orchestration"] = {"id": "execution-" + uuid4().hex, "status": "running",
                "as_of": as_of, "confirmation_id": s["confirmed_id"], "design_hash": encode(s["design"]),
                "input_version": version, "started_at": now(), "model_calls": 0, "financial_calls": 0,
                "mode": "offline_admitted_local_tools", "steps": [
                    {"id": key, "agent": role, "status": "pending", "attempts": 0} for key, role in ROLES]}
            return self.ws.save(s, version, "orchestrator_started")

    def control(self, task_id, version, action):
        with self.ws.lock:
            s = self._checked(task_id, version);o = s.get("orchestration")
            if action not in ("pause", "resume") or not o:raise ContractError("invalid_execution_control")
            if o["status"] != ("running" if action == "pause" else "paused"):
                raise ContractError("execution_not_in_requested_state")
            o["status"] = "paused" if action == "pause" else "running"
            return self.ws.save(s, version, "orchestrator_" + action)

    def step(self, task_id, version):
        with self.ws.lock:
            s = self._checked(task_id, version);o = s.get("orchestration")
            if not o or o["status"] != "running":raise ContractError("execution_not_running")
            if o["confirmation_id"] != s["confirmed_id"] or o["design_hash"] != encode(s["design"]):
                raise ContractError("execution_plan_changed")
            interrupted=next((x for x in o["steps"] if x["status"]=="running"),None)
            if interrupted:
                interrupted.update(status="failed",error="interrupted_step_outcome_requires_manual_review",finished_at=now())
                o["status"]="failed"
                return self.ws.save(s,version,"interrupted_agent_halted")
            pending = next((x for x in o["steps"] if x["status"] == "pending"), None)
            if not pending:raise ContractError("execution_has_no_pending_step")
            pending.update(status="running", started_at=now(), attempts=pending["attempts"]+1)
            s = self.ws.save(s, version, "agent_started_" + pending["id"])
            o = s["orchestration"];p = next(x for x in o["steps"] if x["id"] == pending["id"])
            try:
                if p["id"] in ("retrieval", "counter"):
                    purpose = "support" if p["id"] == "retrieval" else "refute"
                    if self.financial_tools and p['id']=='retrieval' and s.get('financial_context'):
                        context=s['financial_context']
                        s=self.plan_financial_requests(task_id,s['version'],entity=context['entity'],report_ends=context['report_ends'])
                        s=self.acquire_financial(task_id,s['version']);s=self.calculate_financial(task_id,s['version'])
                        o=s['orchestration'];p=next(x for x in o['steps'] if x['id']=='retrieval')
                    if s["calculation_plan"] and p["id"] == "retrieval":
                        outputs = self.ws.execute_single(s["calculation_plan"])
                        s["bindings"] = {t["id"]:{"evidence_id":outputs[t["claim_id"]]} for t in s["design"]["tasks"]}
                    records = self.ws.catalog();nodes={c["id"]:c for c in s["design"]["claims"]}
                    matches=[];missing=[]
                    for t in s["design"]["tasks"]:
                        if t["purpose"] != purpose:continue
                        pred=nodes[t["claim_id"]].get("predicate")
                        # An exact declared financial scope is mandatory. Never infer
                        # causation/attribution or financial meaning from text alone.
                        candidates=[e for e in records if pred and e["scope"]==pred["scope"] and e.get("value") is not None]
                        bound=s["bindings"].get(t["id"])
                        if bound and pred:
                            e=self.ws.store.evidence(bound["evidence_id"])
                            if encode(e.scope) != encode(pred["scope"]):raise ContractError("predicate_evidence_scope_mismatch")
                        elif len(candidates)==1:
                            bound={"evidence_id":candidates[0]["id"]};s["bindings"][t["id"]]=bound
                        else:bound=None
                        if bound and pred:
                            self.ws.store.trace(bound["evidence_id"])
                            matches.append({"task_id":t["id"],"claim_id":t["claim_id"],"evidence_id":bound["evidence_id"],
                                            "purpose":purpose,"tool":"M1.source_trace_and_scope_match"})
                        else:missing.append({"task_id":t["id"],"claim_id":t["claim_id"],
                            "reason":"no_unique_admitted_scope_or_no_deterministic_claim_rule"})
                    output={"matches":matches,"missing":missing,"catalog_count":len(records),
                            "limitation":"Local corpus only; no new announcements or competing explanations retrieved."}
                    status="completed_with_gaps" if missing else "completed"
                elif p["id"] == "conflict":
                    ids=set()
                    def collect(n):
                        if n.get("evidence"):ids.add(n["evidence"]["id"])
                        for x in n.get("inputs",[]):collect(x)
                        for x in n.get("crosschecks",[]):collect(x["provider_field"])
                    for b in s["bindings"].values():collect(self.ws.store.trace(b["evidence_id"]))
                    conflicts=[x for x in self.ws.conflicts() if {x["conflict"]["left_id"],x["conflict"]["right_id"]}&ids]
                    output={"conflicts":conflicts,"evidence_ids":sorted(ids),"tool":"M1.recorded_conflict_audit",
                            "policy":"No automatic source overwrite; unresolved conflicts retained."}
                    status="needs_review" if any(x["state"]=="unresolved" for x in conflicts) else "completed"
                elif p["id"] == "assessment":
                    s=self.ws.save(s,s["version"],"agent_assessment_inputs")
                    s=self.ws.run(task_id,s["version"],as_of=o["as_of"])
                    o=s["orchestration"];p=next(x for x in o["steps"] if x["id"]=="assessment")
                    r=self.ws.engine.get(s["run_id"])
                    output={"run_id":s["run_id"],"conclusion":r["conclusion"],"tool":"M2.evaluate",
                            "research_status":r["research_status"]}
                    status="completed_with_gaps" if r["conclusion"]["state"]=="unverifiable" else "completed"
                else:
                    r=self.ws.engine.get(s["run_id"])
                    s["report"]={"statement":s["statement"],"run_id":s["run_id"],"confirmation_id":s["confirmed_id"],
                        "created_at":now(),"mode":"deterministic_evidence_report", "conclusion":r["conclusion"],
                        "claims":r["claims"],"tasks":r["tasks"],"change_conditions":deepcopy(s["design"]["conditions"]),
                        "claim_statements":{c["id"]:c["statement"] for c in s["design"]["claims"]},
                        "evidence_ids":r["conclusion"]["evidence_dependencies"],
                        "data_origin":"real_historical_response" if s.get('financial_plan') else "existing_local_evidence",
                        "financial_queries":deepcopy(s.get('financial_plan',{}).get('results',[])),
                        "change_condition_proposals":[x for c in s['design']['claims'] for x in c['qualifiers'].get('change_conditions_proposed',[])],
                        "limitations":["限定于已确认的主体、期间和财务口径，不证明因果或投资优劣。",
                            "离线内部材料；未检索最新公告，公开展示和再分发权未确认。",
                            "未决日期含义继续保留；新信息不自动证伪旧命题。"],
                        "conflict_ids":[x["conflict"]["id"] for st in o["steps"] if st["id"]=="conflict" for x in st.get("output",{}).get("conflicts",[])]}
                    output={"run_id":s["run_id"],"report_created":True,"tool":"M2.run_to_structured_report"};status="completed"
                p.update(status=status,finished_at=now(),output=output)
                if all(x["status"] != "pending" for x in o["steps"]):o.update(status="completed",finished_at=now())
                return self.ws.save(s,s["version"],"agent_finished_"+p["id"])
            except Exception as exc:
                # Persist controlled failure, halt; never retry or invent output.
                s=self.ws.get(task_id);o=s["orchestration"];p=next(x for x in o["steps"] if x["id"]==pending["id"])
                p.update(status="failed",finished_at=now(),error=str(exc) if isinstance(exc,ContractError) else type(exc).__name__)
                o["status"]="failed"
                return self.ws.save(s,s["version"],"agent_failed_"+p["id"])

    def compare_versions(self, task_id, left, right):
        versions={x["version"]:x for x in self.ws.timeline(task_id)}
        if left not in versions or right not in versions:raise ContractError("unknown_research_version")
        a,b=versions[left],versions[right]
        def snapshot(s):
            r=self.ws.engine.get(s["run_id"]) if s.get("run_id") else None
            stale=s.get("semantic_review")!="user_confirmed" or s.get("stage")=="needs_revalidation"
            return {"version":s["version"],"statement":s["statement"],"review":s["semantic_review"],
                "conclusion":r["conclusion"] if r else None,"conclusion_is_historical":stale,
                "run_id":s.get("run_id"),"evidence_ids":r["conclusion"]["evidence_dependencies"] if r else [],
                "conditions":s["design"]["conditions"],"claims":s["design"]["claims"]}
        x,y=snapshot(a),snapshot(b)
        return {"task_id":task_id,"left":x,"right":y,"evidence_added":sorted(set(y["evidence_ids"])-set(x["evidence_ids"])),
            "evidence_removed":sorted(set(x["evidence_ids"])-set(y["evidence_ids"])),
            "conditions_changed":encode(x["conditions"])!=encode(y["conditions"]),
            "claim_graph_changed":encode(a["design"])!=encode(b["design"]),
            "limitation":"Same research lineage; historical run does not validate a revised unconfirmed graph."}
