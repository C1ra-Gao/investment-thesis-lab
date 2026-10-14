# MVP acceptance — 2026-10-14, Asia/Shanghai

Latest scope: complete local Web product, environment-only Provider configuration,
no new public deployment. Existing M1/M2/M4/V1 files/databases preserved.

## Actually executed

- Baseline: 184 tests, OK, 2 private-fixture suites skipped.
- Before env change: 194 tests, OK, 2 private-fixture suites skipped.
- After env change: 199 tests, OK, 2 private-fixture suites skipped (11.236s).
- Browser: real localhost:8767 workspace opens; creates/persists a new task;
  missing model gives explicit error, never a fake plan; returning to research
  library after server restart restores the task.
- Browser environment acceptance: Provider page shows deepseek/deepseek-chat,
  unconfigured model/finance status, environment permission and separate public
  consent. DOM password field count=0; model_key/financial_key fields count=0.
  Separate public consent checkbox saves and renders checked; no key form exists.
- HTTP fixtures: environment secret configured only server-side; GET settings
  never returns it; POST settings=405; injecting a key into consent=400; complete
  background research, source lineage, followup and revision are exercised.
- Real public smoke was attempted (no model or paid financial API). DNS pinning
  rejected the current network's non-global resolution: public_dns_not_global.
  No successful real network retrieval is claimed. Results stay in ignored .local.
- No paid model/Fuyao credentials were read or used in this run. .env was created
  with blank keys, ignored by Git, mode 0600; existing .env would be preserved.
- Docker binary absent on this machine: Compose/Dockerfile provided, runtime build
  not executed or claimed. Python localhost service actually runs.

Screenshot of readonly Provider/consent page is retained privately in
`.local/provider-env-browser.jpg` and is not uploaded to GitHub.

## Reproducible cases and origin labels

| Scenario | Fixture test | Expected behavior |
| --- | --- | --- |
| Revenue 120 vs 100 | RuntimeTests end-to-end | deterministic 20% support, raw JSON provenance |
| Revenue 80 vs 100 | negative evidence | deterministic -20% refutation |
| Ambiguous profit meaning | critical ambiguity | cannot execute until critical answer |
| Same period 120 vs 130 | conflicting vintages | both preserved, unverifiable |
| SEC HTTP403 | missing/failure | explicit failed call, no evidence/no retry |
| Second company same scope | company comparison | comparable numeric rows |
| Explain causality | followup | model inference, needs new research |
| Interrupted in-flight call | restart | no replay, continue unexecuted jobs |
| .env permission=false + key | environment gate | disclosure consent rejected |
| Forged Web settings key | AgentHTTPTests | write rejected, secrets never returned |

These model and SEC HTTP cases are **synthetic fixtures**, not live SEC/model
results. Existing project-local original PDF/historical supplier tests are
**offline real-material regression**, not new authorized supplier requests.

Run `python tools/run_tests.py` in the installed venv. Optional private-original
tests require THESISLAB_PHASE3_ROOT and --require-real, as described in historical
README sections. Browser checks can be repeated by opening /research, inspecting
settings, creating a task, restarting and restoring it. No API Key is entered in
the browser.

## Remaining acceptance limitations

Real model + paid supplier end-to-end run requires operator-filled .env and a
network with public DNS/authorized HTTPS connectivity. The legal credentials,
supplier quotas/billing and current schema compatibility must be tested with the
user's account. No substitution of test fixtures is permitted in production.
Public-source parsing is deliberately narrow. Qualitative causal/forecast claims
remain unverifiable. Docker execution and authenticated live provider acceptance
remain unverified; these are not described as completed deployment.

## 自然语言改造验收（2026-10-14）

- 离线回归：214 tests，OK，2 skipped（私有材料未配置）；随后新增的真实观察错配回归与自然语言套件 9 tests 全通过。六类合成模型/数据与真实服务严格分离。
- 浏览器：六类自然语言输入、主体澄清、计划编辑/新增/删除、执行、证据定位、追问、保存刷新、修订命题及加入苹果比较对象通过隔离夹具验收。截图仅存 `.local`，所有金融数字均为合成数据。
- 真实模型：用户更新 `.env` 后使用配置的 DeepSeek；累计实际发送 **14/14**，其中包含此前 HTTP401 和一次计划契约失败。两次已记录的发送前网络失败不占实际发送预算。已知用量 prompt=11,861，completion=19,443，total=31,304；三个审计尝试没有用量返回，不能推断实际总账单为此数值。没有未决或不确定传输。
- 六类均完成真实 Understand；均提出澄清。以明确标注的验收范围编辑理解后，六类均生成结构有效计划（10/10/7/12/12/10 项，具体以私有结果记录为准），未执行 Execute、追问模型或 Deep Research。真实结果与预算保存在 `.local/natural-live-acceptance-result.json` 与追加账本，不提交原始账户记录。
- **语义验收未完全通过**：模型过度澄清；部分盈利计划将 operating_income（收入）称为营业利润；估值计划生成未支持的 revenue_yoy；宏观计划夹带无关发行人；单公司跨期现金转换率错误使用双公司类型。能力不足问题被标为无法执行，金融数字不会由模型填充。已增加明显的收入/营业利润与跨年度比率错配执行阻断；提示已补充指标含义和相关对象约束，但预算已耗尽，未真实复验该提示，不能声称修复已通过真实模型验收。计划须用户审核与修订。
- 公开真实披露 smoke 仍被非全局 DNS 地址规则拒绝，已验证金融字段 0；没有将回归响应作为在线数据。
- 同花顺/扶摇付费查询 **0**。Docker 当前宿主机未安装，仅做 Compose 静态契约检查；没有宣称实际容器验收或公网部署。
