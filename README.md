# ThesisLab — Investment Thesis Verification Agent MVP

## 1. Product Overview

ThesisLab 是面向投资研究的 AI Agent：将自然语言投资命题转化为可验证子问题，通过可用工具收集证据，形成支持、反对与无法验证的研究记录，并明确结论的修订条件。

目标用户是需要审查判断依据的投资研究者、分析师及产品评审。普通金融问答主要提供文字答案；ThesisLab 让用户检查研究范围、计划、实际工具调用、原始证据、计算过程和缺口。模型生成计划不等于命题成立，工具连接成功也不等于数据已核验。

当前交付为**单用户本地 Web 产品**。源码位于 [GitHub 开发分支](https://github.com/C1ra-Gao/investment-thesis-lab/tree/feat/thesislab-agent-mvp)，保留原有技术资料与实现。真实模型规划已执行；真实金融数据与公开披露的在线端到端验收尚未通过。

## 2. Key Features

- **自然语言入口**：无需先填写股票代码、CIK、年份或报告期，可提出单公司、多公司、估值、产业链、宏观和行业命题。实体解析范围有限，未解析主体不会使用模型猜测的代码查询。
- **理解与澄清**：LLM 提取对象、时间、评价标准与歧义，关键问题未回答时暂停；用户可以编辑研究范围。
- **动态计划**：独立 Plan 调用生成最多 12 个子问题，包含支持/反证检验、来源要求和判断改变条件；可修改、删除、补充后确认执行。
- **执行记录**：按对象、期间和指标编译工具任务，保存参数、状态、错误与结果来源；不支持的任务保留能力缺口。
- **Evidence Workspace**：逐个子命题展示支持、反对、无法验证，区分原始事实、确定性计算和模型推断；保留来源与口径冲突。
- **研究延续**：基于已有上下文追问、修订命题、加入比较对象、检查已完成研究的数值可比性；自动保存、重新打开及导出研究记录。

完整交互链路已通过合成浏览器验收；这些结果不代表真实金融上游查询成功。真实 LLM 规划仍存在语义问题，见 Evaluation 和 Known Limitations。

## 3. Product Workflow

**输入命题 → 理解与澄清 → 审核计划 → 执行与验证 → 结论 → 追问、修订或保存**。

| 步骤 | 实际职责与用户操作 |
| --- | --- |
| Understand / Clarify | LLM 理解命题；关键歧义未解决时请用户回答。未说明时间可列出假设，不能冒称最新材料已核实。 |
| Plan | LLM 提议子问题、工具和检验标准；程序校验结构与能力。用户审核意义、范围及必要/背景主张，编辑后确认执行。 |
| Execute | 外部工具获取数据和原始材料，程序记录实际调用。付费工具需自己的授权账户；公开披露需单独同意。 |
| Verify | 确定性程序检查来源位置、期间、单位与口径，计算指标、识别冲突并评估数值谓词。 |
| Revise / Conclude | 有尚未查询的合法候选资料时，LLM 可选择最多两项补查，限一轮。结论按已核验的必要子问题汇总；缺口不由背景事实填补。 |
| Continue | 追问标为模型推断；新命题或比较对象创建保留父任务的新研究。任务在本地持久化。 |

整体判断使用必要条件合取：存在反证则反驳；仍有必要条件无法核验则无法验证。它不自动证明相反投资结论。数据缺失、工具失败、未决数值冲突、预测或因果问题超出能力时，返回明确错误或 `unverifiable`，不从模型记忆补齐金融事实。

## 4. Quick Start

### 依赖与直接启动（已实际运行）

需要 Python **3.12+**、Git；SQLite 随 Python 提供。以下命令在仓库根目录执行，首次安装需要获取锁定依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
chmod 600 .env
```

已有 `.env` 时跳过复制，用终端编辑器填写配置，不在浏览器或聊天中输入 Key：

```dotenv
THESISLAB_LLM_PROVIDER=deepseek
THESISLAB_LLM_MODEL=deepseek-chat
THESISLAB_LLM_API_KEY=
THESISLAB_FINANCIAL_PROVIDER=none
THESISLAB_FINANCIAL_API_KEY=
THESISLAB_ALLOW_PUBLIC_DISCLOSURES=true
THESISLAB_SEC_CONTACT=
```

| 配置 | 当前支持范围 |
| --- | --- |
| LLM | `deepseek`、`openai`、`qwen` 的固定官方 Chat Completions 端点；选用账户支持且具备 JSON object 输出的模型。真实验收只使用 DeepSeek。 |
| 金融数据 | `none` 禁用付费查询；`fuyao` 使用有授权的同花顺扶摇 Key。直接 iFinD MCP 尚未连接。 |
| 公开披露 | `THESISLAB_ALLOW_PUBLIC_DISCLOSURES` 是权限上限；页面还需勾选本次公开检索同意，启动不会自动查询。 |
| SEC | 需要在 `THESISLAB_SEC_CONTACT` 填有效联系邮箱；无需金融 Key。 |

```bash
.venv/bin/python tools/check_provider_config.py
.venv/bin/python -m thesislab.agent_server --port 8767
```

打开 [本地 Research Workspace](http://127.0.0.1:8767/research)。在启动终端按 **Ctrl+C** 停止。设置页仅显示安全状态；“已配置”不表示连接已验证。点击“开始理解命题”会调用配置的模型账户，确认计划后可能调用所选数据工具。

切换模型：停止服务，编辑 `.env` 中 Provider、模型及相应 Key，再启动。直接运行时，进程环境变量（包括空值）优先于 `.env`；任务保存在 `.local/agent.sqlite`。配置解析不执行 shell 命令。详细优先级见 [环境配置说明](docs/ENV-CONFIGURATION.md)。

### Docker Compose（已提供，未构建或启动验收）

参考 DeerFlow 的本地运行体验，保留现有同源服务，不拆分成多个新框架。需要 Docker Engine/Desktop 和 Compose；**当前验收机器没有 Docker，以下是仓库配置的使用方式，不是已通过的容器运行记录**。

```bash
docker compose up --build -d
docker compose stop
```

Compose 定义单个 `workspace` 服务，承载静态前端、API、Runtime 和 SQLite；仅映射宿主机 `127.0.0.1:8767`，命名卷 `research` 保存数据。直接 Python 服务和容器不能同时占用该端口。

`env_file: .env` 加载配置，当前没有 Provider 的 `environment` 覆盖；宿主机同名变量不会自动替换这些条目。更改 `.env` 后使用：

```bash
docker compose up -d --force-recreate
```

普通 `restart` 不重读 env_file；不要使用 `down -v` 删除研究卷。Compose 对 `$` 的解析与直接 Python 不同，含 `$` 的字面值使用单引号；不要输出展开后的容器环境。`.env` 不进入镜像。

## 5. Architecture

| 层 | 当前实现 |
| --- | --- |
| Web Interface | 原生 JavaScript/CSS Research Workspace；Python 同源 HTTP API，页面轮询研究状态。没有独立 React/Next.js 服务。 |
| Agent Runtime | 持久化 `Understand → Clarify → Plan → Execute → Verify → Revise → Conclude` 状态机，后台线程执行，最多两项并行研究。 |
| LLM Provider | 固定官方端点 Adapter；独立理解、计划、受限补查与上下文追问。模型输出先经过契约校验。 |
| Financial / Disclosure Tools | 扶摇利润表、SEC CompanyFacts、已配置发行人目录与公开 PDF；执行能力取决于授权、网络和解析覆盖。 |
| Verification | 复用 M1 来源/定位/Decimal 计算与 M2 数值谓词核验；复用 M4 扶摇契约及明确标注的历史离线链路。 |
| Persistence | SQLAlchemy + SQLite，WAL、追加快照和检查点。重启后标记中断，不自动重放可能已计费的请求。 |

动态能力体现在 LLM 按命题提出不同问题和工具建议、程序按对象/期间编译查询，以及根据实际缺口选择有限补查；固定状态机本身不保证自主研究质量。没有全网自主搜索、无限循环或多 Agent 架构。旧版工作区仍保留。

历史资料：[M1 验证](docs/M1-REPORT.md)、[M2 用法](docs/M2-USAGE.md)、[M2 报告](docs/M2-REPORT.md)、[M4 契约](docs/M4-FUYAO-INCOME-CONTRACT.md)、[存储设计](docs/STORAGE.md)、[V1 交付](docs/V1-DELIVERY.md)。这些记录对应当时阶段，当前入口与验收状态以本文和最新验收记录为准。

## 6. Data & Evidence

| 来源 | 数据与真实性边界 |
| --- | --- |
| 同花顺扶摇 | 利润表 HTTP Adapter；合法授权 Key 才能访问。历史响应仅用于离线回归，没有生产历史缓存回退。本轮未进行付费查询。 |
| SEC CompanyFacts | 年度、entity-wide US-GAAP/USD 的收入、成本、净利润、营业利润、经营现金流标签；保留 CIK、期间、单位、披露日期、accession 和原始文件链接。当前在线验收未成功。 |
| 发行人原始披露 | 内置目录仅贵州茅台；可处理经提供的公开 PDF。核验范围为可解析的 CNY/元合并利润表；用户提供日期不冒充独立核实的披露日。 |
| 私有历史材料 | 原有响应与四份原始 PDF 的本地回归，属于真实历史材料，不是新上游请求；材料、数据库与原始数字不随源码发布。 |
| 合成测试数据 | `tests/natural_fixtures.py` 等明确的模型/HTTP 夹具；专用浏览器环境显示合成标签，不读取真实账户。 |

证据包含来源 URL、JSON Pointer 或 PDF 页/表/行/列、报告期及原始快照哈希。哈希证明内容一致性，不保证发行人财务绝对真实。计算使用命名 Decimal 算子并保留公式及输入 ID，缺数不补零，口径不对齐不计算。

同口径不同数值全部保留，未决冲突阻止采用输入；跨期间、单位或币种差异记录为口径限制，不静默选择有利来源。未知供应商累计口径保留 `partial`。历史成功访问不证明当前接口、账户配额或数据再分发权限仍有效。

## 7. Evaluation

截至 **2026-10-14（Asia/Shanghai）** 的可核实结果：

| 类别 | 已执行结果 |
| --- | --- |
| 本轮离线回归 | 215 项测试：213 通过、0 失败、2 跳过；跳过组依赖未配置的私有材料。依赖一致性与前端语法检查通过。 |
| 合成浏览器验收 | 六类命题输入、主体澄清、计划编辑/增删、执行、证据定位、追问、修订、比较和保存恢复已验证。金融数字为合成数据。 |
| 真实 LLM | 累计 14 次实际请求，含一次 HTTP401 和一次计划契约失败；六类完成理解，采用明确验收范围后生成结构有效计划。已返回 Token 总计 31,304，部分审计尝试未返回用量，不能推算完整账单。语义验收未全部通过。 |
| 真实金融 API | 本轮付费扶摇查询 0；未取得对应新上游响应，不能声称在线金融验证成功。 |
| 原始 PDF | 历史 M1 记录实际解析四份私有 PDF、核验八个字段；属于离线真实材料回归。当前公开披露 smoke 被 `public_dns_not_global` 阻止，新在线 PDF 验收未通过。 |
| Docker / 部署 | Compose 静态配置检查通过；Docker 未安装，没有构建/启动成功记录。Python 本地 Web 已运行，无公网部署。 |

离线复现：

```bash
.venv/bin/python tools/run_tests.py
.venv/bin/python -m pip check
node --check src/thesislab/web/research.js
```

隔离的合成浏览器环境：

```bash
.venv/bin/python tools/serve_natural_fixture.py
```

打开 `http://127.0.0.1:8768/research`，按 Ctrl+C 停止。六类样例为：单公司盈利改善、估值回落与基本面、两家公司盈利质量、产业链利润转移、宏观事件影响、对象模糊的命题。真实 LLM 的 14 次授权预算已经耗尽，本轮未新增模型请求。

详细证据见 [验收记录](docs/MVP-ACCEPTANCE.md)、[冻结审查](docs/MVP-FREEZE-2026-10-14.md)。私有材料回归需自行提供获准材料，方法见 M1/M4 文档；不能用合成测试替代。

## 8. Known Limitations

- **金融上游与公开披露仍未完成在线端到端验收**：当前网络的非全局/Fake-IP DNS 触发公网安全校验。扶摇连接存在这一限制且未获本轮付费查询授权；公开披露 smoke 实际被阻止。安全检查没有放宽为任意私网访问。
- **真实规划语义尚不可靠**：过度澄清、收入/营业利润混用、无关公司问题、跨年度比率误用等曾出现。明显指标错配有执行阻断；提示修正只做离线回归，未再次真实模型复验。用户仍须审核计划含义与阈值。
- 工具覆盖有限：无行情/估值历史、宏观时间序列、产业链利润份额、全面盈利质量或因果验证；未解析公司不会凭空产生金融标识。
- PDF 不支持扫描件 OCR、任意布局或单位；SEC 仅上述年度口径。合成数据不包含所有真实上游变化与解析异常。
- 本地单用户，无多用户鉴权、PostgreSQL 或分布式任务队列。恢复不会自动重发中断的模型请求；需用户明确修订/重试。
- Docker 运行未验证，未提供公网部署；失效条件只记录，不执行定时监控。产品不执行交易或给出投资评级。

## 9. Roadmap / Not Implemented

1. 在合规授权与正常公网 DNS 环境下完成真实金融接口、原始披露及端到端验证。
2. 改进计划语义与工具匹配，以新增真实评估验证，保留人工审核。
3. 验证 Docker 构建/恢复，再考虑版本历史界面与有明确预算的命题监控。

## 10. Security

所有 Provider、模型名称、Key 及服务端权限通过 `.env`/进程环境配置。Web 不接收、显示或返回密钥；密钥不写入任务、研究导出或工具参数。公开披露同意与 Key 分开，重启后重新确认。

`.gitignore` 排除真实 `.env*`（仅放行空凭证示例）、`.local/`、数据库、运行日志和内部材料；Docker 同样排除这些输入。不要上传真实配置、原始响应、数据库、日志或含敏感内容的截图。提交前检查工作区、暂存区与待推送提交历史；发现疑似真实凭证即停止推送，历史删除不能代替密钥轮换。

外部传输保持 TLS/证书校验，数据源使用公网 DNS 校验与地址绑定、拒绝携凭证 URL及重定向；仅模型官方固定端点单独兼容 `198.18.0.0/15` Fake-IP 映射，不能用于任意源地址。供应商失败不自动重试，robots、SEC 联系信息和低速请求要求保留。

服务默认仅监听 loopback；Compose 仅发布到宿主机 loopback。源码公开不代表私人数据或供应商数据有再分发许可；项目尚未选定开源许可证，见 [许可说明](docs/RIGHTS-AND-LICENSES.md)。上述检查不是完整漏洞或泄漏检测保证。
