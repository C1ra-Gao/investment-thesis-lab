"""M3 local workspace: immutable history, explicit review and continued research."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import localcontext
import json
import re
from threading import RLock
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, Text, select

from .domain import ContractError, encode, require_text, Basis
from .finance import cumulative_to_single, gross_margin, yoy, margin_delta
from .research import validate_draft
from .research_store import ResearchEngine
from .schema import EvidenceRecord, ConflictRecord
from .store import now

metadata = MetaData()
tasks = Table("web_tasks", metadata, Column("id", String, primary_key=True),
              Column("owner", String, nullable=False), Column("title", Text), Column("created_at", String))
events = Table("web_events", metadata, Column("sequence", Integer, primary_key=True, autoincrement=True),
               Column("task_id", String, ForeignKey("web_tasks.id"), index=True), Column("payload", Text))
history = Table("web_schema_history", metadata, Column("version", Integer, primary_key=True))


class RevisionConflict(ContractError):pass


def migrate(engine):
    with engine.connect() as c:
        c.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            version = c.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version == 2:
                metadata.create_all(c)
                c.execute(history.insert().values(version=3))
                for table in metadata.tables:
                    for op in ("UPDATE", "DELETE"):
                        c.exec_driver_sql(f'CREATE TRIGGER "immutable_{table}_{op.lower()}" BEFORE {op} ON "{table}" '
                                          "BEGIN SELECT RAISE(ABORT,'append_only_record'); END")
                c.exec_driver_sql("PRAGMA user_version=3")
            elif version != 3 or c.execute(select(history.c.version)).scalar_one() != 3:
                raise ContractError("unsupported_workspace_schema")
            c.commit()
        except Exception:
            c.rollback();raise


def manual_design(statement):
    require_text(statement, "statement")
    if len(statement) > 2000 or statement.rstrip().endswith(("?", "？")):
        raise ContractError("enter_declarative_thesis_not_question")
    # Transparent editable single-node scaffold, never advertised as decomposition.
    return {"statement": statement, "root_id": "root", "claims": [{"id": "root", "statement": statement,
        "kind": "fact", "origin": "original", "spans": [{"start": 0, "end": len(statement), "text": statement}],
        "qualifiers": {"mode": "manual_scaffold_not_AI", "epistemic_status": "unverified_user_assertion"},
        "rule": "atomic", "important": True, "condition_gap": "请人工定义观察窗口、反例与重验来源。"}],
        "relations": [], "clarifications": [], "conditions": [], "tasks": [
            {"id": "root-" + p, "claim_id": "root", "purpose": p, "action": "人工制定并执行" + p + "证据核验。",
             "source_requirement": "待选择原始来源与定位。", "capability": "unverified", "acceptance": "口径、时间及引用核验。"}
            for p in ("support", "refute")]}


def schema_state(design):
    try:validate_draft(design);return {"status": "passed", "error": None}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        return {"status": "failed", "error": str(exc) if isinstance(exc, ContractError) else type(exc).__name__}


def predicate(scope):
    return {"scope": json.loads(encode(scope)), "operator": "gt", "threshold": "0"}


def financial_design(statement, claims):
    d = manual_design(statement)
    d["claims"][0]["rule"] = "and"
    d["claims"][0]["condition_gap"] = "同期间更正需重验；新期间披露不自动证伪旧判断。"
    d["tasks"] = []
    for key, caption, scope in claims:
        node = deepcopy(d["claims"][0]);node.update(id=key, statement=caption, rule="atomic", predicate=predicate(scope))
        d["claims"].append(node)
        d["relations"].append({"from_id": key, "to_id": "root", "kind": "and"})
        for purpose in ("support", "refute"):
            d["tasks"].append({"id": key + "-" + purpose, "claim_id": key, "purpose": purpose,
                "action": "核验已披露原始字段与确定性计算，检验方向大于零或其反例。",
                "source_requirement": "获准内部使用的官方报告与字段定位。", "capability": "local_verified",
                "acceptance": "同主体/期间/口径，确定性计算，未决日期原因不清空。"})
    years=[c[2].end.year for c in claims]
    d["conditions"] = [{"id": "correction", "kind": "revalidate", "claim_ids": [c[0] for c in claims],
        "observation": "同期间原始收入或成本被发行人更正。", "start":f"{min(years)}-01-01", "end":f"{max(years)+1}-12-31",
        "source_requirement": "定位到发行人正式更正公告；新一期公告不是同期间更正。", "mode": "manual_event"}]
    validate_draft(d)
    return d


class Workspace:
    owner = "local_operator"

    def __init__(self, store, *, provider=None, model_cache=None, model_mode=None):
        self.store, self.engine = store, ResearchEngine(store)
        migrate(store.engine)
        self.lock, self.provider, self.model_cache = RLock(), provider, model_cache
        self.model_mode = model_mode or ("deepseek_live" if provider is not None else "disabled")

    def _latest(self, session, task_id):
        identity = session.execute(select(tasks).where(tasks.c.id == task_id)).mappings().first()
        if identity is None or identity["owner"] != self.owner:raise KeyError(task_id)
        row = session.execute(select(events).where(events.c.task_id == task_id)
                              .order_by(events.c.sequence.desc()).limit(1)).mappings().first()
        return {**json.loads(row["payload"]), "version": row["sequence"], "id": task_id}

    def get(self, task_id):
        with self.store.sessions() as session:return self._latest(session, task_id)

    def list(self):
        with self.store.sessions() as session:
            ids = list(session.scalars(select(tasks.c.id).where(tasks.c.owner == self.owner)))
            return [self._latest(session, i) for i in ids][::-1]

    def save(self, state, expected, action):
        with self.store.sessions.begin() as s:
            previous = self._latest(s, state["id"])
            if previous["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            data = {k: v for k, v in state.items() if k not in ("version", "id")}
            data.update(saved_at=now(), action=action)
            s.execute(events.insert().values(task_id=state["id"], payload=encode(data)))
            self.store._audit(s, "workspace_" + action, state["id"])
        return self.get(state["id"])

    def create(self, statement, *, title=None):
        design = manual_design(statement)
        task_id = "study-" + uuid4().hex
        state = {"statement": statement, "title": title or statement[:60], "design": design, "schema": schema_state(design),
            "candidate_source": "manual_scaffold", "semantic_review": "pending", "semantic_notes": "",
            "confirmed_id": None, "draft_id": None, "run_id": None, "run_ids": [], "bindings": {},
            "calculation_plan": None, "stage": "draft", "followups": [], "comparisons": [], "condition_checks": [],
            "saved_at": now(), "action": "created", "model_receipt": None, "raw_candidate": None}
        with self.store.sessions.begin() as s:
            s.execute(tasks.insert().values(id=task_id, owner=self.owner, title=state["title"], created_at=now()))
            s.execute(events.insert().values(task_id=task_id, payload=encode(state)))
            self.store._audit(s, "workspace_created", task_id)
        return self.get(task_id)

    def edit(self, task_id, expected, design, bindings=None, *, reason="用户编辑命题与计划"):
        with self.lock:
            s = self.get(task_id)
            if s["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            require_text(design.get("statement"), "statement")
            if design["statement"].rstrip().endswith(("?", "？")):raise ContractError("enter_declarative_thesis_not_question")
            changed = encode(design) != encode(s["design"])
            if changed and s.get("orchestration"):
                s["orchestration"]["status"] = "needs_review"
            if changed and s.get("online"):
                s["online"]["status"] = "needs_review"
            if changed and s.get("financial_plan"):
                s["financial_plan"]["state"]="needs_review"
            s.update(design=design, statement=design["statement"], schema=schema_state(design))
            if bindings is not None:
                for b in bindings.values():self.store.evidence(b["evidence_id"])
                if encode(bindings) != encode(s["bindings"]) and s["run_id"]:s["stage"] = "needs_revalidation"
                s["bindings"] = bindings
            if changed:
                s.update(semantic_review="pending", semantic_notes="编辑后需重新审查保义与计划。", stage="draft",
                         candidate_source="manual_revision_of_model_candidate" if s["model_receipt"] else "manual_revision")
                if s["schema"]["status"] == "passed":
                    s["draft_id"] = self.engine.draft(task_id, design, origin="manual",
                        parent_id=s["confirmed_id"], reason=reason if s["confirmed_id"] else None)
            return self.save(s, expected, "edited")

    def confirm(self, task_id, expected, *, reviewer, notes, accepted_suggestions, meaning_reviewed):
        with self.lock:
            s = self.get(task_id)
            if s["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            require_text(notes, "semantic_review_notes")
            if not meaning_reviewed:raise ContractError("explicit_meaning_review_required")
            design = validate_draft(s["design"])
            draft = self.engine.draft(task_id, design, origin="model_candidate" if s["candidate_source"] == "deepseek" else "manual",
                                      parent_id=s["confirmed_id"], reason="用户确认修订" if s["confirmed_id"] else None)
            confirmed = self.engine.confirm(draft, reviewer=reviewer, meaning_reviewed=True,
                accepted_suggestions=accepted_suggestions, budget={"llm_calls": 0, "financial_calls": 0})
            s.update(draft_id=draft, confirmed_id=confirmed, semantic_review="user_confirmed", semantic_notes=notes,
                     confirmed_design_hash=encode(design), stage="confirmed")
            return self.save(s, expected, "confirmed")

    def run(self, task_id, expected, *, as_of, reviewer="local_operator"):
        with self.lock:
            s = self.get(task_id)
            if s["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            if s["semantic_review"] != "user_confirmed" or not s["confirmed_id"] or s.get("confirmed_design_hash") != encode(s["design"]):
                raise ContractError("confirm_current_graph_and_plan_before_research")
            if s["calculation_plan"]:
                outputs = self.execute_single(s["calculation_plan"])
                s["bindings"] = {t["id"]: {"evidence_id": outputs[t["claim_id"]]} for t in s["design"]["tasks"]}
            bindings = deepcopy(s["bindings"])
            nodes = {c["id"]: c for c in s["design"]["claims"]}
            for t in s["design"]["tasks"]:
                if t["id"] in bindings and "predicate" not in nodes[t["claim_id"]]:
                    bindings[t["id"]].update(direction="unverifiable", human_verified=True,
                        reason="本地首版未执行通用因果/预测/归因识别；不能以财务数值证明该断言。")
            run = self.engine.evaluate(s["confirmed_id"], bindings, reviewer=reviewer, as_of=as_of)
            s.update(run_id=run, stage="evaluated");s["run_ids"].append(run)
            return self.save(s, expected, "revalidated" if len(s["run_ids"]) > 1 else "evaluated")

    def catalog(self):
        with self.store.sessions() as s:
            return [json.loads(r.payload) for r in s.scalars(select(EvidenceRecord))]

    def conflicts(self):
        with self.store.sessions() as s:ids = list(s.scalars(select(ConflictRecord.id)))
        return [self.store.conflict_state(i) for i in ids]

    def example(self):
        # Build a labeled manual example from admitted metrics; never fixed outputs.
        items = [self.store.evidence(e["id"]) for e in self.catalog() if e["origin"] == "calculation"
                 and e["scope"]["metric"] in ("operating_income_yoy", "gross_margin_change")
                 and e["scope"]["basis"] == "ytd"]
        if not items:raise ContractError("verified_local_material_not_configured")
        entity = items[0].scope.entity
        items = [e for e in items if e.scope.entity == entity]
        sentence = entity + "已定义报告期合并营业收入同比增长且毛利率同比改善。"
        state = self.create(sentence, title="真实财报 · 收入与毛利率验证")
        keys = {e.id: "metric-" + str(i) for i, e in enumerate(items)}
        design = financial_design(sentence, [(keys[e.id], str(e.scope.end) + " " + e.scope.metric + " 大于零。", e.scope) for e in items])
        bindings = {keys[e.id] + "-" + p: {"evidence_id": e.id} for e in items for p in ("support", "refute")}
        edited = self.edit(state["id"], state["version"], design, bindings)
        edited.update(candidate_source="human_authored_real_evidence_example")
        return self.save(edited, edited["version"], "example_loaded")

    def model_generate(self, task_id, expected):
        if self.provider is None:raise ContractError("live_model_disabled_use_manual_or_cached_candidate")
        with self.lock:
            s = self.get(task_id)
            if s["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            original = s["statement"]
        if self.model_mode == "real_model_cache_replay_only" and self.model_cache:
            ledger=json.loads((self.model_cache/"ledger.json").read_text())
            found=False
            for a in ledger["attempts"]:
                suffix=".candidate.json" if a.get("m2_schema_pass") else ".rejected.txt"
                path=self.model_cache/f"attempt-{a['request_number']}-{a['case']}{suffix}"
                if json.loads(path.read_text()).get("statement")==original:found=True;break
            if not found:
                s.update(model_receipt={"error_type":"offline_cache_miss","new_model_requests":0,
                    "input_kind":self.model_mode},raw_candidate=None)
                return self.save(s,expected,"offline_cache_miss")
        from .deepseek import DeepSeekFailure, strict_json
        before = len(self.provider.attempts)
        failure = None
        try:design = self.provider.candidate(original)
        except DeepSeekFailure as exc:
            failure = str(exc)
            design = None
            if len(self.provider.attempts)>before and self.provider.last_content:
                try:design = strict_json(self.provider.last_content)
                except ValueError:pass
        receipt = deepcopy(self.provider.attempts[-1]) if len(self.provider.attempts) > before else {"error_type": failure}
        if self.model_mode != "deepseek_live":receipt.update(input_kind=self.model_mode,new_model_requests=0)
        with self.lock:
            if self.get(task_id)["version"] != expected:raise RevisionConflict("candidate_received_but_task_changed_reload_and_review")
            s.update(model_receipt=receipt, raw_candidate=self.provider.last_content if len(self.provider.attempts)>before else None,
                     candidate_source=("deepseek" if self.model_mode=="deepseek_live" else self.model_mode) if isinstance(design,dict) else s["candidate_source"],
                     semantic_review="pending", stage="draft", draft_id=None,bindings={})
            if s.get("orchestration"):s["orchestration"]["status"]="needs_review"
            if isinstance(design, dict):s.update(design=design, schema=schema_state(design))
            else:s["schema"] = {"status": "failed", "error": receipt.get("error_type")}
            if isinstance(design,dict) and design.get("statement") != original:
                s["schema"] = {"status":"failed","error":"provider_changed_original_statement"}
            if isinstance(design,dict):
                from .plan_repair import prepare_candidate
                try:
                    prepared,repairs=prepare_candidate(design,original)
                    s.update(design=prepared,schema=schema_state(prepared),planning_state="ready",internal_repairs=repairs,internal_repair_attempted=True)
                except (ValueError,TypeError,KeyError,AttributeError):s.update(planning_state="unavailable",internal_repair_attempted=True)
            else:s["planning_state"]="unavailable"
            return self.save(s, expected, "model_candidate_received")

    def prepare_plan(self,task_id,expected):
        """Recover an already received candidate without another model request."""
        with self.lock:
            s=self.get(task_id)
            if s["version"]!=expected:raise RevisionConflict("research_changed_reload_before_saving")
            if s.get("internal_repair_attempted"):return s
            from .plan_repair import prepare_candidate
            try:
                design,repairs=prepare_candidate(s["design"],s["statement"])
                s.update(design=design,schema=schema_state(design),planning_state="ready",internal_repairs=repairs,internal_repair_attempted=True)
            except (ValueError,TypeError,KeyError,AttributeError):s.update(planning_state="unavailable",internal_repair_attempted=True)
            return self.save(s,expected,"internal_plan_prepared")

    def edit_plan(self,task_id,expected,*,actions,answers):
        """Natural-language inputs only; clients never need to author a contract."""
        s=self.get(task_id);d=deepcopy(s["design"])
        if not isinstance(actions,dict) or not isinstance(answers,dict):raise ContractError("invalid_plan_edit")
        if set(actions)-{t['id'] for t in d['tasks']} or set(answers)-{q['id'] for q in d['clarifications']}:
            raise ContractError("unknown_plan_item")
        for t in d['tasks']:
            if t['id'] in actions:require_text(actions[t['id']],"research_action");t['action']=actions[t['id']]
        for q in d['clarifications']:
            if q['id'] in answers:q['answer']=answers[q['id']].strip() or None
        return self.edit(task_id,expected,d,s['bindings'],reason="User edits natural-language research plan")

    def history_financial_plan(self,statement):
        """Explicit limited financial template, not LLM inference or a verified result."""
        from .domain import Scope
        import calendar
        require_text(statement,'statement')
        s=self.create(statement)
        pattern=r'(?:贵州茅台|600519\.SH)\s*(?P<year>20\d{2})年(?P<window>上半年|第一季度)(?P<income>(?:营业)?收入(?:同比)?(?:增长|未增长|下降))[，,\s]*(?:且|但|并且)(?P<margin>毛利率(?:同比)?(?:未改善|改善|下降))[。.]?'
        match=re.fullmatch(pattern,statement.strip())
        if not match:
            s.update(planning_state='unavailable',candidate_source='manual_scaffold')
            return self.save(s,s['version'],'historical_plan_not_supported')
        year=int(match['year']);month=6 if match['window']=='上半年' else 3
        end=date(year,month,calendar.monthrange(year,month)[1]);start=date(year,1,1)
        d=manual_design(statement);d['claims'][0]['rule']='and';d['tasks']=[]
        for key,metric,unit,fragment,op in (
            ('income','operating_income_yoy','percent',match['income'],'le' if '未增长' in match['income'] else 'lt' if '下降' in match['income'] else 'gt'),
            ('margin','gross_margin_change','percentage_points',match['margin'],'le' if '未改善' in match['margin'] else 'lt' if '下降' in match['margin'] else 'gt')):
            node=deepcopy(d['claims'][0]);node.update(id=key,rule='atomic',statement=f'贵州茅台{year}年{match["window"]}{fragment}（与上年同期比较）。',
                spans=[{'start':match.start(key),'end':match.end(key),'text':fragment}],
                predicate={'scope':json.loads(encode(Scope('600519.SH',metric,start,end,'CNY',unit,'consolidated',Basis.YTD))),'operator':op,'threshold':'0'})
            node['qualifiers']['change_conditions_proposed']=[
                {'kind':'falsify','observation':'经同口径核验后的指标方向不满足本子命题。','criterion':'采用同期间收入同比或毛利率百分点变化，不从相关性推断因果。','window':None,'source_requirement':'同花顺字段与发行人原始财报'},
                {'kind':'weaken','observation':'指标变化接近零，或关键字段出现未决口径争议。','criterion':'重新审查重要性与可比口径。','window':None,'source_requirement':'可定位的原始字段及冲突记录'},
                {'kind':'revalidate','observation':'同期间收入或成本被正式更正，或用户改变期间和报表范围。','criterion':'重新获取或计算，保留旧结论。','window':None,'source_requirement':'正式更正材料；新一期披露不自动证伪旧命题'}]
            d['claims'].append(node);d['relations'].append({'from_id':key,'to_id':'root','kind':'and'})
            for purpose in ('support','refute'):
                d['tasks'].append({'id':key+'-'+purpose,'claim_id':key,'purpose':purpose,
                    'action':('核验支持判断的财务数据：' if purpose=='support' else '主动检查相反结果：')+node['statement'],
                    'source_requirement':'扶摇历史利润表及已有官方报告，核对合并、累计和同比口径。','capability':'local_verified',
                    'acceptance':'原始字段与财报页码一致后进行确定性计算；缺失数据不能补零。'})
        d['clarifications']=[]
        validate_draft(d)
        s=self.edit(s['id'],s['version'],d,{})
        s.update(candidate_source='financial_rules_plan',planning_state='ready',
            financial_context={'entity':'600519.SH','report_ends':[end.isoformat(),end.replace(year=year-1).isoformat()]},
            plan_notice='离线财务规则计划，未调用模型。同比基准为上年同期；合并累计；毛利率=(营业收入−营业成本)/营业收入。请确认此范围符合你的意图。')
        return self.save(s,s['version'],'historical_financial_plan_prepared')

    def cached_candidates(self):
        if not self.model_cache:return []
        ledger = json.loads((self.model_cache/"ledger.json").read_text())
        return [{"number": a["request_number"], "case": a.get("case"), "schema": a.get("m2_schema_pass"),
                 "model": a.get("returned_model"), "error": a.get("contract_error_code"),
                 "semantic_status": "requires_revision_or_user_review"} for a in ledger["attempts"] if a.get("state") == "completed"]

    def load_cached(self, number):
        if not self.model_cache:raise ContractError("model_cache_unavailable")
        ledger = json.loads((self.model_cache/"ledger.json").read_text())
        a = next((a for a in ledger["attempts"] if a["request_number"] == number and a.get("state") == "completed"), None)
        if not a:raise ContractError("unknown_cached_candidate")
        if not re.fullmatch(r"[A-Za-z0-9_]+",a["case"]):raise ContractError("invalid_cached_case_identifier")
        file = self.model_cache/f"attempt-{number}-{a['case']}"
        source = file.with_suffix(".candidate.json") if a["m2_schema_pass"] else file.with_suffix(".rejected.txt")
        from .deepseek import strict_json
        raw = source.read_text();design = strict_json(raw)
        s = self.create(design["statement"], title="DeepSeek真实缓存 · " + a["case"])
        s.update(design=design, schema=schema_state(design), model_receipt=a, raw_candidate=raw, candidate_source="deepseek")
        return self.save(s, s["version"], "cached_model_imported")

    def followup(self, task_id, expected, *, question, mode, topic="conclusion", entity=None):
        with self.lock:
            s = self.get(task_id)
            if s["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            require_text(question, "followup_question")
            if mode not in ("explain", "verify", "revise"):raise ContractError("unknown_followup_mode")
            record = {"id": "followup-" + uuid4().hex, "mode": mode, "question": question,
                      "created_at": now(), "run_id": s["run_id"], "financial_calls": 0, "model_calls": 0}
            if mode == "explain":
                run = self.engine.get(s["run_id"], "run") if s["run_id"] else None
                ids = run["conclusion"]["evidence_dependencies"] if run else []
                messages = {"conclusion": "本结论按确认的逻辑关系与已准入证据组合，不按支持/反对票数决定。缺口和冲突限制仍保留。",
                    "period": "季度标签不证明单季口径；请以字段期间与basis为准。H1累计不能直接当Q2单季，收入和成本需分别H1-Q1，毛利率不能直接相减。",
                    "date": "发行人披露日与供应商字段分别保存。采用官方披露日不解决供应商日期含义，当前财务数值与历史PIT能力是不同问题。"}
                if topic not in messages:raise ContractError("select_supported_evidence_explanation_topic")
                record.update(answer=messages[topic] if run else "尚无研究结果。可解释领域规则，但无法补充新金融事实。",
                              topic=topic, evidence_ids=ids)
            elif mode == "verify":
                if topic != "q2":
                    record.update(answer="已保存新增事实验证需求；当前无该数据适配，待人工补充计划与来源。", status="source_gap")
                else:
                    child = self.single_plan(entity)
                    record.update(answer="已创建待确认的Q2单季计划；原数可复用，收入/成本分别差分并重新判断。", child_task_id=child["id"])
            else:record.update(answer="修订需求已记录，请编辑原主张或候选图并重新确认；旧run不会改变。")
            s["followups"].append(record)
            return self.save(s, expected, "followup_saved")

    def single_plan(self, entity):
        require_text(entity, "choose_entity_for_single_quarter")
        raws = [self.store.evidence(e["id"]) for e in self.catalog() if e["origin"] == "issuer"
                and e["scope"]["entity"] == entity and e["scope"]["metric"] in ("operating_income", "operating_costs")]
        if not raws:raise ContractError("entity_has_no_verified_local_inputs")
        year = max(e.scope.end.year for e in raws)
        chosen = {}
        for y in (year, year-1):
            for m in (3, 6):
                for metric in ("operating_income", "operating_costs"):
                    candidates = [e for e in raws if e.scope.end.year == y and e.scope.end.month == m and e.scope.metric == metric]
                    if len(candidates) != 1:raise ContractError("missing_or_ambiguous_quarter_input")
                    chosen[f"{y}-{m}-{metric}"] = candidates[0].id
        revenue = self.store.evidence(chosen[f"{year}-6-operating_income"])
        earlier = self.store.evidence(chosen[f"{year}-3-operating_income"])
        from datetime import timedelta
        single = replace(revenue.scope, start=earlier.scope.end+timedelta(days=1), basis=Basis.SINGLE)
        descriptors = [("growth", "Q2单季营业收入同比增长。", replace(single, metric="operating_income_yoy", unit="percent")),
                       ("margin", "Q2单季毛利率同比改善。", replace(single, metric="gross_margin_change", unit="percentage_points"))]
        sentence = entity + " Q2单季收入同比增长且毛利率同比改善。"
        s = self.create(sentence, title="Q2单季 · 新窗口验证")
        s = self.edit(s["id"], s["version"], financial_design(sentence, descriptors))
        s.update(calculation_plan={"year": year, "entity": entity, "inputs": chosen}, candidate_source="human_requested_calculation_plan")
        return self.save(s, s["version"], "single_quarter_plan_created")

    def execute_single(self, plan):
        year, ids = plan["year"], plan["inputs"]
        yearly = {}
        for y in (year, year-1):
            values = []
            for metric in ("operating_income", "operating_costs"):
                calc = cumulative_to_single(self.store.evidence(ids[f"{y}-6-{metric}"]), self.store.evidence(ids[f"{y}-3-{metric}"]))
                self.store.put_calculation(calc);values.append(calc.result)
            gm = gross_margin(*values);self.store.put_calculation(gm)
            yearly[y] = [*values, gm.result]
        growth = yoy(yearly[year][0], yearly[year-1][0]);margin = margin_delta(yearly[year][2], yearly[year-1][2])
        for calc in (growth, margin):self.store.put_calculation(calc)
        return {"growth": growth.result.id, "margin": margin.result.id}

    def compare(self, task_id, expected, *, other_task_id, left_id=None, right_id=None):
        with self.lock:
            a, b = self.get(task_id), self.get(other_task_id)
            if a["version"] != expected:raise RevisionConflict("research_changed_reload_before_saving")
            result = {"id": "comparison-"+uuid4().hex, "left_task": a["id"], "right_task": b["id"],
                "left_version": a["version"], "right_version": b["version"], "left_run": a["run_id"], "right_run": b["run_id"],
                "left_evidence": left_id, "right_evidence": right_id, "created_at": now(), "alignment": [], "numeric_delta": None}
            if not left_id or not right_id:result.update(status="not_comparable", reason="evidence_coverage_missing")
            else:
                def allowed(state, eid):
                    ids = {v["evidence_id"] for v in state["bindings"].values()}
                    if state["run_id"]:ids |= set(self.engine.get(state["run_id"])["conclusion"]["evidence_dependencies"])
                    if eid not in ids:raise ContractError("comparison_evidence_not_in_selected_research")
                allowed(a, left_id);allowed(b, right_id)
                x,y = self.store.evidence(left_id), self.store.evidence(right_id)
                dimensions = ("entity", "metric", "currency", "unit", "consolidation", "basis", "accounting", "value_kind")
                for dim in dimensions:
                    l,r = getattr(x.scope,dim),getattr(y.scope,dim)
                    result["alignment"].append({"dimension": dim, "left": str(l), "right": str(r), "matches": l==r})
                calendar = (x.scope.start.month,x.scope.start.day,x.scope.end.month,x.scope.end.day) == (y.scope.start.month,y.scope.start.day,y.scope.end.month,y.scope.end.day)
                period = x.scope.start == y.scope.start and x.scope.end == y.scope.end
                result["alignment"].append({"dimension": "period", "left": str(x.scope.start)+" / "+str(x.scope.end),
                                            "right": str(y.scope.start)+" / "+str(y.scope.end), "matches": period or calendar})
                unknown = any(getattr(x.scope,d)=="unknown" or getattr(y.scope,d)=="unknown" for d in dimensions)
                comparable = all(r["matches"] for r in result["alignment"]) and not unknown and x.scope.value_kind=="actual" and x.value is not None and y.value is not None
                result.update(status="comparable" if comparable else "not_comparable",
                              reason="same_scope_calendar_aligned" if comparable else "scope_or_period_mismatch")
                if comparable:
                    with localcontext() as ctx:
                        ctx.prec=32;result["numeric_delta"]=str(x.value-y.value)
                    result.update(left_value=str(x.value),right_value=str(y.value),formula="left-right", unit="percentage_points" if x.scope.unit=="percent" else x.scope.unit,
                                  limitation="口径可对齐不证明季节性、因果或投资优劣；跨年差额不是同比百分比。")
            a["comparisons"].append(result)
            return self.save(a, expected, "comparison_saved")

    def timeline(self, task_id):
        self.get(task_id)
        with self.store.sessions() as s:
            return [{"version": r.sequence, **json.loads(r.payload)} for r in s.execute(
                select(events.c.sequence, events.c.payload).where(events.c.task_id==task_id).order_by(events.c.sequence))]
