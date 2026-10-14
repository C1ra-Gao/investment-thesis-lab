# Phase 5 M2 implementation report

2026-10-14。**用户选择的离线M2范围已实现并测试；通用LLM拆解与真实模型语义评测仍UNVERIFIED，未调用模型，不能宣称完整AI能力验收通过。** M2验收待用户确认，不进入M3，不推送M2。

## Authorized M1 Push

只正常推送已审计M1提交 `a2ea0af87b4e9c3a24aec6efcbf9145532ff4472` 至正式仓库main。远程推送前为 `e9ad3a19a268aa2b5ab9b381443453fbaa10258c`，正常fast-forward成功，随后 `git ls-remote origin refs/heads/main` 核对完整SHA一致。无Force Push、权限变更或额外文件上传。此后所有M2改动仅本地。

## Implemented / not implemented

| 授权需求 | 结果及关键路径 |
|---|---|
| 陈述式原主张、逻辑Subclaims、保义审查 | IMPLEMENTED：`research.validate_draft`检查陈述、原文span／覆盖、original与suggestion、限定注释、组合规则、无环依赖。`CandidateProvider`为未接通接口，人工导入可用。保义只能约束结构并需人工审核，通用LLM解析UNVERIFIED |
| Research Plan / Evidence Tasks | IMPLEMENTED：候选设计快照与独立task引用；支持、反证、竞争解释辨别目的分离；来源要求、能力状态、准入条件；重要节点condition或明确缺口；关键澄清阻止确认，数据缺口不变澄清循环 |
| 支持／反对／无法验证及组合 | IMPLEMENTED：`ResearchEngine.evaluate`从既有M1证据读取精确口径，Decimal阈值判断；AND/OR/必要条件，机制不沿边传播成立，竞争解释不投票；重大未决、裁决排除输入、双向方向分歧保留无法验证 |
| 证伪／削弱／重验条件 | IMPLEMENTED：`check_condition`阈值／人工事件、观察窗口、来源与受影响节点、unknown/触发/未触发；产生不同影响建议和祖先影响集合，不修改旧结论，不提供后台监控 |
| 用户确认和修订 | IMPLEMENTED：`draft/confirm`严格确认保义及系统新增建议，预算固定零；新revision以父confirmation绑定同thesis，保存修改理由、影响预览；新run重新评估，不复制旧方向 |
| 三类语义测试 | IMPLEMENTED（人工契约）：状态／背离保存否定；因果／预测拆分事实前提、机制和未来结果；归因保留贡献识别与竞争解释缺口。合成测试不是模型质量或实际估值／因果／归因结论 |
| 本地持久化及CLI | IMPLEMENTED：`research_store.py`只追加draft/confirmation/run/condition_check及审计；显式v1→v2迁移；`cli.py`导入、确认、评估、条件检查、按ID或thesis历史恢复 |
| 自动取数／文本证据准入／模型适配 | NOT_IMPLEMENTED：不新增金融请求，不读取凭证；本次仅M1已存财务证据。通用文本抽取、因果识别算法、利润贡献桥与模型供应商SDK均未新增 |

## Actual validation

使用现有Python 3.12隔离环境、SQLAlchemy 2.0.44与pdfplumber 0.11.7，未新增运行依赖。实际命令：

```bash
THESISLAB_PHASE3_ROOT=../ThesisLab-Phase3-Data-Validation \
  .venv/bin/python tools/run_tests.py --require-real
.venv/bin/python -m unittest tests.test_research -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q src tests tools
```

完整回归 **112 tests OK，0 skipped**：M1原68项（含11项真实私有材料），新增M2人工／合成41项和真实组合回归3项。最后完整运行2.771秒，仅为本机一次测量，不是性能承诺。pip check无依赖冲突。公开文档中的人工JSON例子经实际契约校验通过。

真实案例读取既有4份官方财报／8个原始财务数字，不下载、不取新API。M1计算仍涵盖Q1、H1、Q2单季差分、同比和毛利率。M2以真实M1计算ID与Scope建立**人工确认的**图，两个收入节点支持、两个毛利率改善节点反对，AND主命题反对；依赖闭包回到原始字段／公式，四条日期冲突仍未决。另一测试用披露前检查日期验证禁止未来披露进入当时结论，**不是历史PIT回放测试通过**。

完整CLI真实演练也已运行：人工候选→确认→任务绑定→评估→关闭重开读取run及history。结果opposes，research_status=evaluated；原财报字段与日期原因未覆盖。运行数据库及全部输入／结果仅在忽略的 `.local/m2-case.sqlite`、`m2-draft.json`、`m2-bindings.json`、`m2-case-run.json`、`m2-case-history.json`，不提交公开仓库。详细测试日志 `.local/m2-test-results.log` 也仅本地。

新增边界测试覆盖：问答节点拒绝、span错误／原文丢失、依赖环与混用组合、未确认运行／歧义／建议、未知字段、反证任务缺失、重大冲突与计算输入冲突、裁决后被弃用的旧值、未来披露／未观察预测、unknown与forecast数据、因果与主营归因缺口、竞争解释不投票、条件窗口／未知事件、修订影响与不覆盖历史、v2迁移／故障回滚／重开／append-only、CLI恢复。原68项全部保持通过。

## Engineering / AI / rights boundaries

- 本次模型调用0、金融调用0、凭证读取0。测试中禁止socket连接，且源码暂存审计继续拒绝网络／凭证客户端导入。
- 候选图及测试图由本项目人工编写；本地真实财务值来自Phase 3缓存／原始报告，计算来自M1命名Decimal程序。没有Mock模型输出或通用LLM准确率声明。
- Run用量记录零调用／重试、模型未调用、Token与费用null、本机耗时和本地证据绑定次数。没有供应商价格或真实Token记录。
- 候选／计划确认是人审记录，不证明金融真值；非数值方向需明确审核理由。缺归因识别资料不允许仅凭收入值判主营贡献；预测不到观察期限保持无法验证。
- M2结论与数据/研究完成状态分开；缺任务时partial，仍可由有效必要反例反对主张。Conditions定义缺口与未检查结果保留，不显示监控安全。
- 单用户本地库，无Web、ACL、并发头指针、多Agent、在线worker、比较／追问、交易、公开部署。未修改Phase1–4原报告、未Fork／移植开源资产，代码许可证仍未选择。
- Phase 3数据权利／计费和供应商日期语义仍CONDITIONAL；不外推其他公司／指标可用，不向外部模型发送任何材料。SQLite非加密／防管理员篡改存储。

## Gate

提交内容审计已执行 `tools/audit_staged.py --private-baseline-root ../ThesisLab-Phase3-Data-Validation`：12个源码／文档文件，findings为空，未打印匹配内容。原始响应、PDF、数据库、研究输入输出与日志均未纳入暂存；`git diff --check`通过。这是路径／秘密模式及私有基准值扫描，不是完整漏洞扫描或数据权利授权。最终本地提交SHA由完成消息报告，M2不推送。

**离线引擎：PASS（待用户验收）；完整通用LLM能力：UNVERIFIED／用户明确延后；数据对外使用：CONDITIONAL。** 后续如需真实LLM拆解，须另外确认供应商、费用、预算和安全配置，再实现适配并用三类原文做真实语义评测。当前不进入M3，也不自动推送本地M2代码。
