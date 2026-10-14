# M2 offline contracts and CLI

M2使用已有M1依赖，不安装模型SDK。下例为**人工编写的合成契约**，不是金融事实、模型回答或通用语义拆解示范。数据输入与输出放在忽略的 `.local/`，不得提交研究者原文、供应商响应或证据文件。

## Candidate / Research Plan

`research.validate_draft`严格检查顶层字段；`statement`保持原主张，`root_id`指向原文节点，`claims`是陈述而非验证动作，`tasks`单独定义动作。节点可以是fact/causal/forecast/attribution/assumption；rule是atomic/and/or。关系支持and/or/necessary_for/mechanism/alternative/comparison，有向依赖必须无环；mechanism不能自动传递支持，alternative/comparison不参与投票。

每个original节点有原文span（Python Unicode字符索引，不是UTF-8字节或JS UTF-16索引），所有原文非标点字符需要映射。`qualifiers`保留研究者确认的范围、否定、量词、比较基准等，预测节点用 `forecast_end` 定义观察期；未定义或尚未到期时不形成确定方向。span校验不证明保义，用户必须阅读原文与图并明确确认。

新增假设／竞争解释用origin=suggestion，与原断言分开；确认需逐个 `--accept-suggestion`，不接受的建议通过新草案删除。重要节点必须有变化条件或明示condition_gap，不臆造阈值。original atomic节点必须有support/refute任务；适用竞争解释另建discriminate任务，不计入主张支持票。

将以下内容人工保存为 `.local/draft.json` 可导入（这里只检查结构，不会取数）：

```json
{
  "statement": "合成指标大于零。",
  "root_id": "metric-positive",
  "claims": [{
    "id": "metric-positive", "statement": "合成指标大于零。",
    "kind": "fact", "origin": "original",
    "spans": [{"start": 0, "end": 8, "text": "合成指标大于零。"}],
    "qualifiers": {"input_kind": "synthetic_contract_only"},
    "rule": "atomic", "important": true,
    "condition_gap": "指标定义、后续观察与来源需人工确定。",
    "predicate": {
      "scope": {"entity": "SYNTHETIC:ENTITY", "metric": "operating_income",
        "start": "2025-01-01", "end": "2025-03-31", "currency": "CNY", "unit": "yuan",
        "consolidation": "consolidated", "basis": "ytd", "accounting": "statutory", "value_kind": "actual"},
      "operator": "gt", "threshold": "0"
    }
  }],
  "relations": [], "clarifications": [], "conditions": [],
  "tasks": [
    {"id": "verify-positive", "claim_id": "metric-positive", "purpose": "support",
      "action": "核对已确认指标的原始字段及大于零条件。", "source_requirement": "可定位原始字段。",
      "capability": "unverified", "acceptance": "单位、期间、主体及指标完全一致。"},
    {"id": "test-nonpositive", "claim_id": "metric-positive", "purpose": "refute",
      "action": "检验已确认指标小于等于零的反例。", "source_requirement": "可定位原始字段。",
      "capability": "unverified", "acceptance": "同一指标口径，不补造缺失值。"}
  ]
}
```

关键澄清结构：`id, claim_ids, field, question, critical(bool), answer(string|null)`。先保存拆图候选；critical且answer缺失才阻止确认。回答时应同时修改相关qualifiers/predicate/任务，再创建修订草案；系统不会假称已理解回答并自动改写图。来源能力unavailable/unverified属于数据缺口，不强迫用户反复澄清。

## Confirm / evaluate / recover

```bash
.venv/bin/python -m thesislab draft --thesis manual-example \
  --input .local/draft.json --origin manual
.venv/bin/python -m thesislab confirm --draft '<draft-id>' \
  --reviewer '<operator>' --meaning-reviewed
.venv/bin/python -m thesislab evaluate --confirmation '<confirmation-id>' \
  --bindings .local/bindings.json --reviewer '<operator>' --as-of 2026-10-14
.venv/bin/python -m thesislab research-show --id '<run-id>'
.venv/bin/python -m thesislab research-show --thesis manual-example \
  --output .local/history.json
```

第一次可将bindings.json写为 `{}`：研究会保存evidence_missing任务与unverifiable结论，不请求任何服务。有效绑定格式为 `{"verify-positive": {"evidence_id": "<existing-M1-evidence-id>"}}`；这些ID必须已经存入同一数据库。默认数据库 `.local/thesislab.sqlite`，可各命令统一使用 `--db .local/regression.sqlite` 来引用既有内部回归材料。

数值原子命题predicate包含完整Scope、gt/ge/lt/le/eq和Decimal字符串threshold；不同主体、期间、指标或单位拒绝判断，unknown/forecast值保持无法验证。不能直接传入新value；所有数来自M1准入与命名计算。只有已核验的原子fact可以自动数值判断。

非数值原子命题需要绑定 `human_verified: true, direction: supports|opposes|unverifiable, reason: 非空审核理由`，记录审核者。这是人工方向判定而非机器因果证明；M1目前只有财务数值证据，不提供通用文本准入，真实因果／归因场景数据仍不足。预测期限未来或缺失，不接受当前证据给出的确定方向。

AND有必要反例即可反对；全部必要项支持才能支持；OR一个支持可支持，全部反对才反对；必要条件反对可反对目标，但前提支持不会自动证明机制。双向有效证据保留assessment disagreement，不投票。discriminate结果单独记录。重大未决冲突阻止受影响节点；裁决未采用的旧字段／含该字段的计算仍被阻止，需重绑有效证据或重算。

`as-of`只是检查已保存财报的期间和已核验发行人披露日是否越界，不是历史point-in-time回放。provider_report_date不当作公开可知日，缺独立披露日的provider叶子不能直接形成确定判断。仅元数据日期原因未决不推翻已核验当前财务数值；完整冲突留在运行快照。结论方向与research_status独立，缺任务时partial，即使存在足够反例可反对主张。

## Revision / Change Conditions

```bash
.venv/bin/python -m thesislab draft --thesis manual-example \
  --input .local/revised-draft.json --parent-confirmation '<confirmation-id>' \
  --reason 'Change metric threshold and review the research plan'
```

修订必须指向同thesis已确认版本。修改节点、关系或条件后生成影响列表及祖先重验标记；新图需再确认、新run需再评估，不复制旧方向。原始证据不覆盖；原始数据能否复用仍需检验口径、披露时点和新任务。当前不做自动检索或增量worker。

condition定义：`id, kind(falsify|weaken|revalidate), claim_ids, observation, start, end, source_requirement, mode(threshold|manual_event)`；threshold额外带完整predicate。检查日须在观察窗口内；证据披露晚于检查日、重大未决冲突、provider日期未知不能作为已触发依据。

```bash
.venv/bin/python -m thesislab check-condition --confirmation '<confirmation-id>' \
  --condition '<condition-id>' --reviewer '<operator>' --observed-on 2026-10-14 \
  --evidence '<existing-M1-evidence-id>'
```

人工事件另外提供 `--event true|false --reason '...'`，并引用已准入证据。未检查/证据不足记unknown，不显示安全。触发只追加falsification_proposed/weakening_proposed/needs_revalidation及受影响节点；旧结论不变。要据此改变当前判断，需研究者修订并重新评估，没有后台自动监控。

## Model boundary and limits

`research.CandidateProvider`和`request_candidate`只定义可注入候选接口与拒绝未授权调用的门槛。没有供应商适配器、模型SDK、Keychain或凭证读取。`model_candidate`是导入来源标签，不是模型经过验证的证明。本次没有运行任何模型，无通用语义准确率／Token／费用结果；手工图与合成测试不能代替真实模型评测。后续模型调用必须另获授权并实现预算与费用检查。

CLI错误中只显示受控ContractError代码或错误类型，不打印输入、证据值或堆栈。输入文件允许本地人工指定；输出与数据库强制 `.local/`。库调用不是安全沙箱，受信任本地使用者仍须保护文件权限。本地研究历史含私人投资观点，不上传公开仓库。
