# ThesisLab — Investment Thesis Verification Agent MVP

面向需要审查投资命题、而非只阅读生成答案的研究者。完整本地 Web 工作区复用现有 M1/M2/M4，模型规划、真实工具查询、确定性核验与来源记录分别保存。最新范围是 **localhost 产品**，不要求或宣称公网部署。

源码：[C1ra-Gao/investment-thesis-lab](https://github.com/C1ra-Gao/investment-thesis-lab)，开发分支 `feat/thesislab-agent-mvp`，不合并 main。旧版入口与已有私有数据库保留。

## 本地启动

需要 Python 3.12+；Docker 方式需要 Docker Desktop 或 Docker Engine + Compose。

```bash
cp .env.example .env
chmod 600 .env
```

用终端编辑器打开 `.env`，填入自己的授权密钥。不要通过聊天、浏览器表单或命令行参数提交密钥。

```dotenv
THESISLAB_LLM_PROVIDER=deepseek
THESISLAB_LLM_MODEL=deepseek-chat
THESISLAB_LLM_API_KEY=
THESISLAB_FINANCIAL_PROVIDER=fuyao
THESISLAB_FINANCIAL_API_KEY=
THESISLAB_ALLOW_PUBLIC_DISCLOSURES=true
THESISLAB_SEC_CONTACT=
```

- DeepSeek：`deepseek` + 账户支持的模型，如 `deepseek-chat`。
- OpenAI：`openai` + 支持 Chat Completions / JSON object 输出的模型，如 `gpt-4.1-mini`。
- 通义千问：`qwen` + 支持兼容接口的模型，如 `qwen-plus`。
- 金融数据：`fuyao` 使用有授权的同花顺扶摇 `X-api-key`；`none` 禁用付费金融接口。直接 iFinD MCP 尚未接入，不能把扶摇接口描述为 iFinD 已连接。
- SEC 无需金融 Key，但须在 `THESISLAB_SEC_CONTACT` 提供有效联系邮箱。该邮箱不通过 API 返回。
- `THESISLAB_ALLOW_PUBLIC_DISCLOSURES` 是服务端权限上限。启动后在“模型与数据源”页面单独同意本次运行的公开披露查询；环境配置不会自动代表用户同意。

### Docker Compose

```bash
docker compose up --build -d
```

打开 [ThesisLab 本地工作区](http://localhost:8767/research)。容器内前端静态资源、HTTP API、后台 Agent Runtime 与 SQLite 完整运行；宿主机只发布 `127.0.0.1:8767`。Docker 命名卷 `research` 保存任务与证据，普通停止/重启不删除数据。

```bash
docker compose logs -f workspace
docker compose stop
```

修改 `.env` 切换模型/权限后，必须重新创建容器，单纯 `restart` 不重新读取 `env_file`：

```bash
docker compose up -d --force-recreate
```

Compose 使用 `env_file: .env`，不把 `.env` COPY 到镜像。不要运行 `docker compose down -v`，它会删除研究数据卷。不要把容器环境、数据库或真实响应贴到 Issue。参考 [DeerFlow 本地 Compose 组织方式](https://github.com/bytedance/deer-flow/blob/main/frontend/src/content/en/application/deployment-guide.mdx)，本项目保留既有同源 Python/JS 架构，不为拆服务而迁移到 Next.js/PostgreSQL。

### 直接 Python 启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m thesislab.agent_server --port 8767
```

打开 [http://127.0.0.1:8767/research](http://127.0.0.1:8767/research)。在仓库根目录启动，程序读取 `.env`；已设置的进程环境变量优先。解析器不执行 shell 命令、不进行变量插值；有空格的值请用引号。修改配置后停止并重启服务。直接运行的任务保存在 `.local/agent.sqlite`。

## 用户流程

1. 在只读连接状态页检查 Provider 和模型。配置成功只表示存在配置，不表示供应商连接已通过；真实连接结果显示在实际调用记录中。页面没有密钥输入、保存密钥或查询密钥功能。
2. 直接输入自然语言命题，支持单公司、多公司、估值、产业链、宏观和行业。无需先填写股票代码、CIK、年份或报告期；无法确定的主体才需澄清。
3. 点击“开始理解命题”。模型识别关键歧义；必要时回答澄清问题。计划显示范围、子问题、数值阈值与可观察失效条件，用户可修改、删除、补充子问题，编辑范围并确认。
4. 执行后可以离开页面。逐个实际工具调用保存参数、开始/结束、状态、错误、来源和结果，页面轮询读取状态。
5. 审查支持/反对/无法验证。展开原始 URL、报告期间、JSON Pointer 或 PDF 页/表/行/列、哈希、公式和输入证据链。
6. 基于报告追问；修订命题创建保留父任务的新版本；为第二家公司创建研究，完成后检查期间、币种、单位与会计口径是否可比。比较不对不可比数字排名。
7. 所有步骤自动保存，研究库可重新打开；可导出不含密钥的研究 JSON。

推荐首轮案例：“微软2025年净利润同比增长”。它需要自己的模型 Key、有效 SEC 联系信息、公开披露授权与可用网络。A 股案例：“贵州茅台2025年上半年收入同比增长且毛利率改善”。同花顺账户未配置时金融工具明确失败，公开官网披露仍可独立查询。

## Agent 与验证设计

`Understand → Clarify（必要时）→ Plan → Execute → Verify → Revise（有界补查）→ Conclude` 是持久化状态机，不是一次性文本生成。一个后台线程执行顺序工具，最多两项同时研究；自然语言计划最多 12 个子问题、24 个初始工具任务，目录可追加财报任务，总队列受限；一次补查决策最多 2 项，不静默重复失败/不确定的调用。自然语言主链路由独立 Understand 和 Plan 模型调用生成；用户澄清后重新理解。执行按实体和时间范围编译任务，补查仅使用尚未查询的合法资料。最终数值结论由核验结果确定。

- **AI 角色**：识别歧义、提出可验证问题/反证与失效条件、基于实际缺口选择补查、解释报告。结构输出经过白名单校验；模型不能写入可信金融数值或新增未经用户/目录提供的 URL。
- **数据工具**：新同花顺 API 响应、公开发行人目录与原始 PDF、SEC CompanyFacts 原始 XBRL。没有任何生产历史缓存回退。
- **M1**：不可变来源/原始快照、定位重验、Decimal32 公式、输入谱系与冲突。
- **M2**：复用 `compare_predicate` 校验真实证据、完整 scope 与数值谓词。旧 M2 Claim Graph 与历史审核功能保留于旧版工作区。
- **结论**：当前 MVP 将审核后的子问题按必要条件合取，任何反证使合取被反驳，剩余缺口使其无法验证；这是明确的逻辑规则，不代表复杂命题全部可自动表达。定性归因、因果、预测不从相关性获得“支持”。
- **三类内容**：原始数值是直接事实；公式产物是计算结果；追问/补查解释标记模型推断。失效条件来自用户审核的模型计划，尚无自动监控。
- **冲突**：同口径不同数字全部保留、阻止采用冲突输入；不同累计起点/币种/单位记录口径冲突，不静默取有利来源。供应商披露时间语义未知时保留限制。
- **恢复**：SQLite WAL、追加版本与检查点。重启将执行中的请求标记中断；用户恢复尚未执行步骤，不自动重发可能已计费的请求。中断的模型调用需显式创建修订重试。用户公开披露同意在重启后重新确认。

## 数据来源与边界

同花顺使用 [官方金融 API](https://fuyao.aicubes.cn/docs/api-reference/financials/) 的 income-statements 契约，不绕过授权；当前仅利润表，API 流量累计口径未知时保留 `partial`，不能用于数值结论。原始 PDF 验证当前仅支持可解析的 CNY/元/合并利润表，严格检查期间与列。内置官网目录仅贵州茅台；其他 A 股须用户提供公开 PDF 与披露日期（日期标记用户提供、未独立验证）。扫描、万元单位或不同表布局可能返回无法验证，不使用 OCR/模型补数字。

[SEC 官方 CompanyFacts](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) 当前只接入 entity-wide US-GAAP/USD 的年度收入、成本、净利润、营业利润、经营现金流标签。保留所有查询到的披露版本及 accession 原始文件链接；数字与 CIK、起止期、披露日期、form、单位、标签和 JSON Pointer 一起校验。52/53 周年度同比采用单独可重算的 `fiscal_yoy`，明确期间长度可能不同；普通 M1 日历期间 guards 保留。非美 GAAP、季度、行业专用标签或缺失数据不自动改口径。

网络使用 TLS 校验、全局地址验证与 DNS pinning，供应商失败不重试。公开 PDF 访问遵守 robots；SEC API 遵守低速请求与联系信息要求。私网/回环地址、携密钥 URL、未授权请求被拒绝。VPN/Fake-IP DNS 将公网域名映射为私网或保留地址时查询会失败；请使用正常公网 DNS 网络，公开数据查询不会关闭安全检查。模型传输单独允许服务端白名单中的官方固定 HTTPS 端点使用 198.18.0.0/15 Fake-IP 映射，仍校验证书、SNI、固定路径且禁止重定向；其他私网与任意 URL 仍拒绝。

当前限制：单用户本地产品；无自动行情/估值、价格预测、买卖建议、后台变化监控、任意金融 Provider 插件 UI、PostgreSQL、多用户协作或复杂语义可靠性保证。密钥通过服务器 `.env`/环境读取，进程内使用，不在任务表持久化或 API 返回；`.env` 与 `.local` 已被 Git/Docker 忽略。旧供应商内部验证材料没有被复制到新产品数据库或上传。

## 验收与复现

```bash
.venv/bin/python tools/run_tests.py
node --check src/thesislab/web/research.js
```

`tests/test_agent_runtime.py` 与 `tests/test_environment.py` 的模型/SEC HTTP 明确为合成夹具，覆盖拆解澄清、真值计算谱系、正反结论、冲突、缺失/API 错误、后台执行、追问、公司可比性、保存恢复和密钥隔离；不能描述为真实在线模型/金融验收。既有 M1/M4 私有真实材料测试属于离线回归，仍不冒充新查询。

真实公开披露连接与 PDF 核验（不调用模型/付费同花顺）：

```bash
.venv/bin/python tools/live_public_smoke.py --public-consent --year 2025 --period H1
```

结果只保存到 `.local/live-public-smoke-result.json`，失败也记录。当前环境实际尝试被 `public_dns_not_global` 阻止，没有真实下载成功。没有配置本次模型/金融账户密钥，所以未宣称真实付费端到端验收通过。Docker 当前机器未安装，Compose 文件已提供但未宣称容器构建通过。详细验收记录见 [MVP-ACCEPTANCE](docs/MVP-ACCEPTANCE.md)，审计与主要决定见 [MVP-AUDIT](docs/MVP-AUDIT-2026-10-14.md)。

## 旧版成果与历史说明（保留）

以下为 M1/M2/M4/V1 的历史说明。旧文档中的“当前未实现”、旧版密钥授权与推送状态描述对应历史阶段；新版入口、配置与分支交付以本文上方为准。

# ThesisLab — local evidence and thesis verification

ThesisLab V1 is a local Agentic Investment Research Workspace. M1 supplies immutable evidence and Decimal calculations; M2 verifies human-confirmed claim graphs; M2.5 supplies a real DeepSeek candidate adapter; V1 adds persisted research orchestration, reports and version comparison. No trading or investment ratings.

正式仓库：<https://github.com/C1ra-Gao/investment-thesis-lab>。经批准的M1提交已正常推送并核对SHA；M2仅在本地，未获推送许可。

## V1 本地 Web（默认离线）

```bash
.venv/bin/python -B tools/serve_v1.py --port 8766 --seed-local-corpus
```

打开 <http://127.0.0.1:8766>。服务仅绑定127.0.0.1；在启动它的终端按 `Ctrl+C` 关闭。
首次显式seed仅复制项目内已有获准材料到`.local/v1.sqlite`，保留原库；没有材料不会伪造。
再次启动恢复已有任务。无内部材料也可直接运行`.venv/bin/python -m thesislab.web_server --port 8766`
保存命题，但不会凭空得到金融研究结果。

首页选择“开始贵州茅台财报演示（人工计划）”，审查计划、填写审核说明、确认，点击
“Agent 开始研究”。无需填写Schema、字段ID或Decimal阈值。可查看报告、证据公式与页码、
保留冲突、保存恢复和比较同一命题的两个历史版本。高级编辑仍保留。

**离线演示的真实性边界**：财报计划明确是人工编制；真实DeepSeek候选通过“导入真实模型缓存”
单独加载，保留原文、原始失败与人工审核要求。任意新命题只保存草稿，没有匹配AI缓存就明确
缺口。结构通过不等于保义通过。金融材料仍仅限本地内部验证，不能公开展示或再分发。

默认不读取凭证、不产生付费请求。Live适配器保留，但本轮未启用；需要另行授权启动权限、
费用预算与明确的页面调用同意。本地报告不会以模型记忆替代金融数据。

V1验收、角色边界及修改清单见 [V1-DELIVERY](docs/V1-DELIVERY.md)。旧M1/M2记录保留如下。

## 核心环境安装

要求：Python **3.12+**、Git；SQLite由Python提供。核心依赖SQLAlchemy，真实PDF回归另需pdfplumber。无需API Key、Keychain、LLM或金融SDK。

在仓库根目录创建隔离环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m thesislab init-db
```

构建工具固定setuptools 80.9.0；首次安装需要下载公开依赖，不调用金融服务。requirements.lock记录本次验证的完整运行依赖版本；不同OS的wheel可用性尚未验证。Windows可使用 `.venv\Scripts\python.exe` 替换路径。

### 合成单元测试

```bash
.venv/bin/python tools/run_tests.py
```

未配置私人材料时，真实回归组会明确 **skip**；合成测试通过不表示真实财报核验通过。

### 私人真实材料回归（不随仓库发布）

将已有Phase 3目录放在仓库之外；本次工作区默认相邻路径为 `../ThesisLab-Phase3-Data-Validation`。缺材料时失败，程序不下载、不调用认证接口、不用合成数据替代。

必需本地文件：

```text
<Phase3 root>/
  diagnostic-followup/income-response-new-1.json
  diagnostic-followup/new-request-records.json
  final-evidence/verified-numeric-trace.json
  final-evidence/original-document-manifest.json
  final-evidence/issuer-report-index.html
  final-evidence/original-reports/<four locally verified PDFs>
```

```bash
THESISLAB_PHASE3_ROOT=../ThesisLab-Phase3-Data-Validation \
  .venv/bin/python tools/run_tests.py --require-real

.venv/bin/python -m thesislab regress \
  --phase3-root ../ThesisLab-Phase3-Data-Validation
.venv/bin/python -m thesislab restore
```

首个命令实际读取四份PDF的页／表／本期列，并核对八个收入成本值、统计单位与日期目录；计算同比、毛利率、累计转单季并与既有独立审计基准比较。第二个命令将来源、原始快照、字段、计算、关系和审计存入 `.local/regression.sqlite`；第三个命令重新打开并恢复未决冲突。详细结果存入 `.local/regression.json` 和 `.local/restored.json`，终端只显示计数与状态。

**所有 `.local/` 内容含内部数据，禁止提交、上传到Issue／PR或公开展示。** CLI强制数据库和结果写到项目 `.local/`。测试材料必须在仓库外；`.env.example`只提供本地路径示例，不加载秘密。环境变量只配置测试输入路径，不存API凭证。

## 已实现

- 不可变领域契约：Subclaim、逻辑关系、Revision、Evidence／Scope／Locator、Assessment；没有LLM拆解。
- 原始JSON／PDF／目录的本地快照、hash、来源、获取与披露时间；JSON Pointer与财报页／行／列定位。
- Decimal 32位局部上下文：同比、毛利率、毛利率百分点差、YTD累计转下一单季；记录输入ID、公式与版本，禁止float、缺数补零或不对齐计算。
- 期间、合并范围、币种／单位、实际／预测与未知口径分类；同口径数字差异；供应商日期与发行人目录日期冲突。
- 字段级采用依据、未决冲突、追加审计；原始Evidence与RawArtifact不被审核覆盖。
- SQLAlchemy＋SQLite schema v1、只追加约束、revision／检查点、关闭数据库后恢复与源链递归读取。
- 合成边界／安全测试；显式私有真实回归，缺文件不会伪造。

日期冲突按**字段**生成：两个已核验期间、各两个字段形成四条日期冲突，不是四次独立供应商异常。回归中自动投影已核验的官网日期，审计者明确为自动规则；不伪造新的人工确认，供应商字段原因仍未决。

如需人工保留未决或采用字段，在私有结果中取conflict／evidence ID，使用本地命令：

```bash
.venv/bin/python -m thesislab review --conflict '<local-conflict-id>' \
  --reviewer '<operator-id>' --reason 'Keep unresolved pending source clarification'
.venv/bin/python -m thesislab review --conflict '<local-conflict-id>' \
  --reviewer '<operator-id>' --reason 'Use verified issuer-index date' \
  --selected-evidence '<issuer-evidence-id>' --field original_disclosure_date
.venv/bin/python -m thesislab trace --evidence '<local-evidence-id>'
```

命令仅写私有数据库／输出，不能修改原始字段。日期采用依据后原因仍未决；对同口径数字冲突可以显式 `--resolve`，必须有审核理由和所选证据，原数两侧均保留。

## 明确未实现

通用模型保义可靠性保证、在线金融检索、后台变化监控、交易／评级、公开部署、历史PIT回放、多用户访问控制与PostgreSQL运行仍未实现。真实模型候选、离线Agent工作流、比较、追问和本地Web已有实现，范围见V1交付报告。人工确认非数值证据方向是审核记录，不是机器证明因果／归因。

## M2 离线研究流程

用户本次选择暂不调用模型。不会用固定案例解析器或Mock回答替代通用LLM。可人工建立候选图，或导入外部候选后人工审查；来源模式会保存。精确候选契约、JSON例子和CLI流程见 [M2-USAGE](docs/M2-USAGE.md)。

```bash
.venv/bin/python -m thesislab draft --thesis local-research \
  --input .local/draft.json --origin manual
.venv/bin/python -m thesislab confirm --draft '<draft-id>' \
  --reviewer '<operator>' --meaning-reviewed
.venv/bin/python -m thesislab evaluate --confirmation '<confirmation-id>' \
  --bindings .local/bindings.json --reviewer '<operator>' --as-of 2026-10-14
.venv/bin/python -m thesislab research-show --thesis local-research
```

`draft.json`需要由研究者按契约填写，不是将自然语言自动转换成图。先保存拆解候选，只有关键歧义未回答时才阻止确认；计划的支持／反证任务、竞争解释及变化条件单独保存。修改后重新导入 `draft --parent-confirmation '<id>' --reason '...'`，确认后新运行；原始证据、旧结论保留。`research-show`可恢复完整候选、确认、计划、运行与条件检查历史。

M2自动判断针对已确认的精确数值谓词；AND／OR／必要条件按规则组合，不平均置信度。预测未到观察期限保持无法验证；机制不从事实前提自动获支持。CLI使用既有M1证据ID，不能传入数字或模型文本当新可信事实。变化条件产生有记录的变化建议／重验需求，不能覆盖旧结论。

M2首次研究操作显式追加SQLite v2表，M1原表／schema_version=1留作历史；M1 CLI识别v2不会降级。当前是单用户本地工具。实际结果见 [M2-REPORT](docs/M2-REPORT.md)。

## 数据与许可

Phase 3数据仅获准用于内部验证，公开展示／长期留存／二次使用权和供应商历史日期语义仍未完全确认。原始报告URL是来源，不授予API数据再分发权。`verified`表示所定义定位、范围与核验步骤通过，不保证发行人财务绝对真实；hash是完整性，不是真实性。

所有应用代码为本项目自行实现，未Fork／复制参考项目、Prompt或受限资产。项目尚未选择开源许可证；公开可见性不应被描述为已有MIT／Apache授权。依赖许可和已知限制见[RIGHTS-AND-LICENSES](docs/RIGHTS-AND-LICENSES.md)。

## 提交前检查

```bash
.venv/bin/python -m pip check
.venv/bin/python tools/audit_staged.py \
  --private-baseline-root ../ThesisLab-Phase3-Data-Validation
```

审计只读Git暂存内容，输出文件名／问题类型，不输出匹配内容；路径白名单排除JSON响应、PDF、数据库、环境文件和本地证据，另检测常见秘密／私人绝对路径与基准实际数字。它不是完整DLP或漏洞扫描。审计通过也不授权新Push；M2推送仍需另获批准。

数据库模型与迁移见[STORAGE](docs/STORAGE.md)；M1历史验证记录见[M1-REPORT](docs/M1-REPORT.md)。这是历史M2说明；当前本地V1实现见文档顶部，未自动推送或公开部署。

## 自然语言改造与验收

竞品公开功能、实际查阅的开源代码及未借用内容见 [竞品映射](docs/COMPETITOR-REDESIGN.md)。保留 M1/M2/M4，新增独立命题理解契约和计划编译器；没有复制竞品 UI 或 AGPL 代码。证据工作区按子命题展示事实、计算、原始位置、冲突、必要/背景主张及判断改变条件。版本历史界面和定时监控留待后续。

`.env` 的 Provider/模型/Key 名称与后端一致。进程变量（包括空值）优先于文件；当前 Compose 没有 Provider `environment` 覆盖，直接读取 `env_file`。安全配置检查：

```bash
.venv/bin/python tools/check_provider_config.py
```

详细优先级、引号与重启步骤见 [环境配置](docs/ENV-CONFIGURATION.md)。检查仅返回配置布尔状态和非敏感模型信息，不返回密钥。

离线测试使用隔离的合成模型和数据：

```bash
.venv/bin/python tools/run_tests.py
.venv/bin/python tools/serve_natural_fixture.py
```

夹具页面使用独立数据库和醒目的合成标签，不读取真实账户。六类命题、计划编辑、冲突/错误、追问、新增比较对象及保存恢复均有回归测试。真实模型验收工具仅在用户明确授权后运行，有持久化最多 14 次实际或不确定传输预算，不调用金融工具、不执行 Deep Research。实际结果及未解决限制见 [验收记录](docs/MVP-ACCEPTANCE.md)。
