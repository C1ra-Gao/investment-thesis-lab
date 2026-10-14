# ThesisLab — M1 local evidence core

ThesisLab is an investment thesis verification workspace. **This repository currently implements only M1:** offline evidence provenance, deterministic financial calculations, conflict detection, field-level review and local recovery. It is not a chatbot, investment rating service, Web application or trading system.

正式仓库：<https://github.com/C1ra-Gao/investment-thesis-lab>。M1在本地开发；首次Push须用户另行批准。

## 安装与运行

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

LLM／Agent工作流、比较与追问服务、变化条件监控、完整结论生成、Web前端／API、iFinD／扶摇在线适配、交易／评级、公开部署、历史PIT回放、多用户访问控制与PostgreSQL运行。M1的符号关系与单指标方向仅用于证据契约／回归，不等于完整研究判决系统。

## 数据与许可

Phase 3数据仅获准用于内部验证，公开展示／长期留存／二次使用权和供应商历史日期语义仍未完全确认。原始报告URL是来源，不授予API数据再分发权。`verified`表示所定义定位、范围与核验步骤通过，不保证发行人财务绝对真实；hash是完整性，不是真实性。

所有应用代码为本项目自行实现，未Fork／复制参考项目、Prompt或受限资产。项目尚未选择开源许可证；公开可见性不应被描述为已有MIT／Apache授权。依赖许可和已知限制见[RIGHTS-AND-LICENSES](docs/RIGHTS-AND-LICENSES.md)。

## 提交前检查

```bash
.venv/bin/python -m pip check
.venv/bin/python tools/audit_staged.py \
  --private-baseline-root ../ThesisLab-Phase3-Data-Validation
```

审计只读Git暂存内容，输出文件名／问题类型，不输出匹配内容；路径白名单排除JSON响应、PDF、数据库、环境文件和本地证据，另检测常见秘密／私人绝对路径与基准实际数字。它不是完整DLP或漏洞扫描。审计通过也不授权Push，首次Push仍需批准。

数据库模型与迁移见[STORAGE](docs/STORAGE.md)；本次实际验证记录见[M1-REPORT](docs/M1-REPORT.md)。M1完成后停止，不自动进入M2/M3。
