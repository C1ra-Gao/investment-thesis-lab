"""Human semantic review forms and readable candidate exports; no model judging."""

import json

PUBLIC_CASES = {
    "state": "估值回落，但基本面未恶化。",
    "causal": "某项外部变化将影响产业链利润分配。",
    "attribution": "盈利改善主要来自主营业务。",
    "state_conditional": "若公司A未来两个季度的市盈率相对行业中位数回落，而同期扣非净利润同比未下降且经营现金流未恶化，则估值回落不意味着基本面恶化。",
    "causal_conditional": "若关税政策自2027年1月1日起实施且上游能够转嫁新增成本，则2027年上半年上游利润份额可能上升；若需求显著下滑，这一判断不成立。",
    "attribution_qualified": "公司A在2027年上半年的归母净利润同比改善主要来自主营业务，但不能仅凭营业收入增长排除投资收益、税率变化和非经常性项目的贡献。",
}

RUBRIC = {
    "meaning": "原文限定、否定、主要、比较及不确定方向是否保留，没有添加原文未提出的事实？",
    "source_mapping": "original节点的原文映射和归属是否合理，而不只形式上覆盖整句？",
    "premises_logic": "事实前提与必要条件是否清晰，必要不被当充分，依赖是否合理？",
    "causal_attribution": "机制、未来结果、盈利贡献是否分离，相关不当因果，主要不变全部？",
    "alternatives": "是否给出适用竞争解释和辨别任务，不将替代解释当事实或投票？",
    "suggestions": "所有新假设、具体机制、隐含必要前提是否标suggestion并待用户确认？",
    "change_conditions": "是否给出具体证伪/削弱/重验路径，缺窗口阈值明确为待确认，而非可执行？",
    "research_plan": "Claim与验证动作分开，支持/反证/辨别任务可审查且不声称来源已连接？",
}


def review_form(statement, attempt):
    return {"statement": statement, "request_number": attempt["request_number"],
            "input_kind": "public_generic_statement_no_financial_materials",
            "json_pass": attempt["json_pass"], "m2_schema_pass": attempt["m2_schema_pass"],
            "reviewer": None, "overall": "UNVERIFIED", "notes": "需阅读候选后人工填写，不自动评分。",
            "criteria": {k: {"question": text, "status": "UNVERIFIED", "claim_ids": [], "evidence_quote": None}
                         for k, text in RUBRIC.items()}}


def render_candidate(design):
    lines = ["# 投资命题候选 · 待人工审查", "",
             "模型候选不是金融事实。没有检索或验证任何财务资料，未自动确认或生成投资建议。", "",
             "## 原主张", design["statement"], "", "## Claim Graph"]
    for c in design["claims"]:
        lines.extend([f"- {c['id']} · {c['origin']} / {c['kind']} / {c['rule']}：{c['statement']}",
                      "  限定：" + json.dumps(c["qualifiers"], ensure_ascii=False),
                      "  条件缺口：" + c["condition_gap"]])
    lines.append("\n## 逻辑关系")
    for r in design["relations"]:lines.append(f"- {r['from_id']} → {r['to_id']}：{r['kind']}")
    lines.append("\n## 必要澄清")
    for q in design["clarifications"]:lines.append(f"- {q['field']}：{q['question']}（critical={q['critical']}，answer={q['answer']}）")
    lines.append("\n## Research Plan / Evidence Tasks")
    for t in design["tasks"]:
        lines.extend([f"- {t['id']} → {t['claim_id']} · {t['purpose']}：{t['action']}",
                      f"  所需来源：{t['source_requirement']} · 能力：{t['capability']}",
                      "  准入：" + t["acceptance"]])
    lines.append("\n## 可执行变化条件")
    if not design["conditions"]:lines.append("尚无已定义窗口的可执行条件；请审查节点中的条件建议与缺口。")
    for c in design["conditions"]:lines.append("- " + json.dumps(c, ensure_ascii=False))
    lines.append("\n编辑相邻candidate.json后可用M2 draft命令导入新候选；确认仍需原文保义审查、关键澄清与建议接受。")
    return "\n".join(lines) + "\n"


def summarize(attempts):
    count = len(attempts)
    json_success = sum(a.get("json_pass") is True for a in attempts)
    schema_success = sum(a.get("m2_schema_pass") is True for a in attempts)
    def total(field):
        values = [a.get("usage", {}).get(field) for a in attempts]
        return sum(values) if values and all(type(v) is int for v in values) else None
    return {"request_attempts": count, "json_passes": json_success, "schema_passes": schema_success,
            "json_rate_all_attempts": json_success/count if count else None,
            "schema_rate_all_attempts": schema_success/count if count else None,
            "schema_rate_given_valid_json": schema_success/json_success if json_success else None,
            "prompt_tokens": total("prompt_tokens"), "completion_tokens": total("completion_tokens"),
            "total_tokens": total("total_tokens"), "actual_fee": None,
            "semantic_review": "separate_human_review_required",
            "returned_models": sorted({a["returned_model"] for a in attempts if a.get("returned_model")})}
