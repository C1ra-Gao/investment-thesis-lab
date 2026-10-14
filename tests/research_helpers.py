"""Human-authored semantic fixtures only. Never general LLM outputs."""

from copy import deepcopy
import json
from thesislab.domain import encode
from tests.helpers import fact


def node(id, statement, original, *, rule="atomic", kind="fact", origin="original", pred=None):
    result = {"id": id, "statement": statement, "kind": kind, "origin": origin,
              "spans": [{"start": 0, "end": len(original), "text": original}] if origin == "original" else [],
              "qualifiers": {"human_review_required": True}, "rule": rule, "important": True,
              "condition_gap": "阈值与观察来源尚待研究者定义；不能自动监控。"}
    if pred:result["predicate"] = pred
    return result


def pred(item=None, operator="gt", threshold="0"):
    return {"scope": json.loads(encode((item or fact()).scope)), "operator": operator, "threshold": threshold}


def design(statement=None, kind="state"):
    statement = statement or {"state": "合成公司估值回落，但基本面未恶化。",
        "causal": "外部政策将通过议价传导提高上游利润份额。",
        "attribution": "合成公司盈利改善主要来自主营业务。"}[kind]
    labels = {"state": ("估值相对已确认基准下降。", "指定基本面指标未恶化。", "fact"),
              "causal": ("政策在研究范围内生效。", "未来上游利润份额提高。", "forecast"),
              "attribution": ("指定口径利润改善。", "主营业务贡献占利润改善的主要部分。", "attribution")}
    a, b, k = labels[kind]
    nodes = [node("root", statement, statement, rule="and"),
             node("a", a, statement, pred=pred()), node("b", b, statement, kind=k)]
    if kind == "causal":nodes[2]["qualifiers"]["forecast_end"] = "2027-12-31"
    if kind == "attribution":nodes[2]["qualifiers"]["identification_gap"] = "缺主营贡献桥及非经常性项目原始字段。"
    relations = [{"from_id": i, "to_id": "root", "kind": "and"} for i in ("a", "b")]
    if kind == "causal":relations.append({"from_id": "a", "to_id": "b", "kind": "necessary_for"})
    tasks = [{"id": i + "-" + purpose, "claim_id": i, "purpose": purpose,
              "action": "核验既有材料，支持或检验相反结果。", "source_requirement": "可定位的原始材料。",
              "capability": "unverified", "acceptance": "限定期间与口径一致；模型文本不作为事实。"}
             for i in ("a", "b") for purpose in ("support", "refute")]
    if kind == "causal":
        mechanism = node("m", "政策通过议价传导改变利润分配的机制成立。", statement, kind="causal")
        mechanism["qualifiers"]["identification_gap"] = "缺价格、销量周期等竞争解释的辨别材料。"
        nodes.append(mechanism)
        relations.extend([{"from_id": "a", "to_id": "m", "kind": "necessary_for"},
                          {"from_id": "m", "to_id": "b", "kind": "mechanism"},
                          {"from_id": "m", "to_id": "root", "kind": "and"}])
        for purpose in ("support", "refute", "discriminate"):
            tasks.append({"id": "m-" + purpose, "claim_id": "m", "purpose": purpose,
                "action": "比较议价传导与价格、销量周期解释。", "source_requirement": "可定位机制与竞争解释材料。",
                "capability": "unavailable", "acceptance": "不能由政策与利润同时变化证明因果。"})
    return {"statement": statement, "root_id": "root", "claims": nodes, "relations": relations,
            "clarifications": [], "tasks": tasks, "conditions": []}


def condition(data, kind="revalidate", mode="threshold"):
    c = {"id": "change-a", "kind": kind, "claim_ids": ["a"], "observation": "复核已定义指标。",
         "start": "2025-01-01", "end": "2026-12-31", "source_requirement": "人工核验原始材料。", "mode": mode}
    if mode == "threshold":c["predicate"] = pred(operator="lt")
    data["conditions"].append(c)
    return data
