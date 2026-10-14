# ThesisLab｜测试、复现与能力边界

> 本文记录**截至 2026-10-14 M2 离线引擎阶段**有来源支持的执行结果。M2.5 DeepSeek 的六次真实评测另见 [DEEPSEEK-EVALUATION.md](DEEPSEEK-EVALUATION.md)。后续 Web 的 HTTP／浏览器测试暂无提交的最终结果，本文件不将其列为已通过。

## 1. 环境与依赖

- Python 3.12+；本地 SQLite。
- M1/M2 报告中的已测主要包：SQLAlchemy 2.0.44、pdfplumber 0.11.7。
- 核心依赖固定版本见项目 `requirements.lock`；需在已克隆的项目根目录运行。
- 不需要金融 API Key 运行离线契约测试；**真实材料回归依赖仓库外已获准使用的 Phase 3 材料**。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m thesislab init-db
```

## 2. 已报告的真实执行结果

| 阶段 | 用例数 | 结果 | 数据类别 | 解释 |
|---|---:|---|---|---|
| M1 | 68 | 68 OK，0 skip | 57 项领域／安全边界 + 11 项真实私有材料回归 | 真实 PDF、字段对照、数值计算、冲突与恢复 |
| M2 总回归 | 112 | 112 OK，0 skip | 既有 M1 68 项 + 41 项人工／合成 M2 测试 + 3 项真实组合回归 | 包含人工确认 Claim Graph 的组合判断，不代表真实 LLM 语义评测 |
| M2.5 真实 DeepSeek | 6 次模型请求 | 初轮契约 0/3；二轮契约 2/3 | 公开命题的真实模型响应 | 属于模型质量实验，不属于上述 112 项离线自动化测试 |
| Web HTTP／浏览器 | 未收到完成报告 | **未验证** | — | 不把“已获准运行”写成“已通过” |

以上是当时本地项目报告的结果，并非当前任意 Git commit 的最新回归保证。若合并 M2.5/M3 代码，必须重新执行全套测试并记录新结果。

## 3. 复现命令

### 3.1 不含真实财务材料的离线测试

```bash
.venv/bin/python tools/run_tests.py
.venv/bin/python -m unittest tests.test_research -q
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q src tests tools
```

若未配置真实材料，真实回归组应清楚标 `skip`；**不能将该结果称为 112/112 全部真实执行无跳过**。

### 3.2 获授权的真实财务材料回归

```bash
THESISLAB_PHASE3_ROOT=/path/to/authorized-phase3 \
  .venv/bin/python tools/run_tests.py --require-real

.venv/bin/python -m thesislab regress \
  --phase3-root /path/to/authorized-phase3
.venv/bin/python -m thesislab restore
```

`--require-real` 要求真正提供财报 PDF、既有供应商缓存和核验清单；材料缺失时应失败，不以合成数据自动顶替。输入保存在代码仓库外，生成数据库／结果写入 Git 忽略的 `.local/`。该回归**不会发送新金融 API 请求**。

### 3.3 命题研究引擎 CLI 示例

先参照 [M2-USAGE.md](M2-USAGE.md) 生成**明确标记为人工／合成**的 `.local/draft.json`，再执行：

```bash
.venv/bin/python -m thesislab draft \
  --thesis manual-example --input .local/draft.json --origin manual

.venv/bin/python -m thesislab confirm \
  --draft '<draft-id>' --reviewer '<operator>' --meaning-reviewed

.venv/bin/python -m thesislab evaluate \
  --confirmation '<confirmation-id>' --bindings .local/bindings.json \
  --reviewer '<operator>' --as-of 2026-10-14

.venv/bin/python -m thesislab research-show --id '<run-id>'
```

其中 `<draft-id>`、`<confirmation-id>`、`<run-id>` 由实际 CLI 返回；不可原样执行占位符。空 bindings 可以验证“证据缺失 → 无法验证／部分完成”的行为，但不能证明某个真实投资命题成立。`as-of` 仅做保存材料的披露日越界检查，**不是完整历史 PIT 回放**。

## 4. 覆盖的正确性与异常类别

**M1：** Decimal 精度、空值与非有限数、零／负分母、期间、币种／单位、合并范围、实际与预测混用、未经定位的数值、原 PDF 列／日期不匹配、响应不完整、只追加存储、未决日期冲突、关闭后恢复。

**M2：** 原文 span、候选图合法性、环形依赖、支持与反证任务、用户未确认时禁止执行、竞争解释不能投票、因果机制不自动成立、预测尚未观察、unknown 与历史披露时间限制、重大冲突阻断、条件窗口与修订影响、版本迁移及 CLI 恢复。

**合规边界：** 测试中的网络连接受限；密钥不得随源码或回归产物输出；真实输入与结果保持本地；缺授权来源不得升级为已核验事实。安全扫描不能被描述为正式渗透测试或数据再分发许可证明。

## 5. 目前尚未通过的验收项目

- DeepSeek 对任意陈述式投资命题的语义可靠性（六次样本显示多种失败）。
- 金融 API 在线稳定性、其他公司与指标覆盖、iFinD。
- 历史 point-in-time 完整回放、原始文本通用核验、自动因果识别。
- 公开 Web URL 的可用性、多用户权限、安全部署及浏览器主流程。
- 金融数据公开展示／缓存／商业使用许可确认。

## 6. 公开提交前检查

```bash
.venv/bin/python -m pip check
.venv/bin/python tools/audit_staged.py \
  --private-baseline-root /path/to/authorized-phase3

git diff --cached --check
git status --short
```

审计并不能覆盖所有凭证形式或代码漏洞。确认暂存区**不包含** `.env`、API Key、私人 JSON/PDF、`.local/` 数据库与 trace、Keychain 信息、私人绝对路径或无再分发权的数据。若阶段报告引用文件位于仓库外，替换为公开可访问的官方链接或受控复现说明，不复制私人目录。

## 7. 本次提交的技术结论

可重现的核心价值是：**有审查门槛的命题与任务契约 + 确定性财务计算 + 原始来源链 + 未决冲突保留 + 结论改变条件 + 追加式版本记录**。这与“任意命题的 AI 全自动验证”和“已上线的专业研究平台”不同，README 应保持相同边界表述。
