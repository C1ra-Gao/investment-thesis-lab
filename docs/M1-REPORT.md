# Phase 5 / M1 completion record

日期：2026-10-14（Asia/Shanghai）。阶段：仅M1。本地独立克隆正式仓库并原创实现，没有Fork参考项目、线上金融调用、Keychain、LLM、iFinD、Web开发、交易或部署。远程只读元数据确认private=false、fork=false；未改变仓库可见性。

## 实际执行

| 项目 | 实际结果与边界 |
|---|---|
| 安装 | Python 3.12隔离venv，SQLAlchemy 2.0.44、pdfplumber 0.11.7及锁定传递依赖；本地editable包安装成功 |
| 完整测试 | `THESISLAB_PHASE3_ROOT=../ThesisLab-Phase3-Data-Validation .venv/bin/python tools/run_tests.py --require-real`：**68 tests，OK，无skip**；实际耗时见本地日志，速度不作为性能承诺 |
| 原始数字 | 实际重新解析4份PDF的指定合并利润表／列及单位；8个收入／成本字段全部与真实缓存一致，非硬编码真实金额 |
| 计算 | Q1、H1、Q2单季的同比、毛利率及百分点差与既有独立Phase 3审计基准一致；差分保留2输入，不减比率 |
| 日期冲突 | 两个2025期间各2字段，生成4条日期冲突；投影官网披露日但供应商原因保持UNVERIFIED |
| 持久化 | CLI回归写入私有SQLite，另一进程restore成功；4未决冲突、4子命题Assessment恢复 |
| 人工操作 | CLI review保留未决、trace输出私有来源链成功；调用前后原始值相同；裁决追加审计 |
| 依赖一致性 | `pip check`：No broken requirements found |
| 编译／变更格式 | compileall通过；git diff --check通过 |

测试启动脚本首次执行曾因工具目录sys.path导致5个import错误；修正为明确仓库root／unittest top_level_dir后完整重跑通过。没有把失败当通过，日志与金融详情仅保存在忽略目录，公开报告不包含私人响应或真实金额。

## 测试分层

68项中11项为实际私有材料回归，57项为领域／财务／冲突／存储与安全边界测试。未配置真实材料时该组明确skip；`--require-real`要求输入且拒绝skip，不能以合成通过替代真数据。真实回归额外禁止socket connect；数据均为既有缓存，并非本次实时采集。

负向测试覆盖：float/NaN、null、零／负分母、期间／单位／合并／实际预测不对齐、未知scope、错误原文列／金额或日期重标、模型式自造位置／计算结果、SQL覆写/删除、冒充已核验质量、外来子命题、缺真实文件、输出落到公开路径和不完整JSON。

## 实现与范围

已实现M1的七项：最小契约；原始bytes／source／locator／字段；Decimal命名算子；口径／日期／数值冲突；字段级采用与未决／审计；本地checkpoint与恢复；单元和真实回归。

未实现完整MVP：LLM拆解／Agent、比较／追问、条件自动监控、完整结论服务、Web／鉴权、多用户并发、在线数据适配、iFinD、PIT、PostgreSQL部署。保存的手工关系与数值方向只是M1契约与基准链，不扩展为M2功能。

M1技术完成标准 **PASS**；数据权利及历史时间能力沿用Phase 3 **CONDITIONAL**，没有因为代码通过就宣称供应商日期原因、公开展示权或其他实体已验证。项目自身许可证待所有者选择；依赖元数据与局限见RIGHTS-AND-LICENSES。

## 安全与提交内容审计

提交前需运行`tools/audit_staged.py --private-baseline-root <private Phase3 root>`，检查本次暂存文件白名单、常见秘密／私人绝对路径、8字段及派生基准实际数值、运行源码的网络／凭证／外部进程客户端。这里只输出文件名和问题类型，不泄露匹配内容。SQLAlchemy参数化写入，无eval／pickle或金融SDK。

本次实际暂存审计：**29个文件，findings为空，退出码0**；git diff --cached --check亦通过。真实数据库、回归JSON、venv均通过git check-ignore确认不在提交范围。私有输入位于仓库外；原始快照、数据库、trace、测试日志、venv与个人文件均不提交。审计结果另留本地记录；该检查不是完整秘密扫描／CVE扫描／渗透测试。首次Push须用户明确批准，不因本地Commit自动授权。

**完成M1后停止，等待验收，不自动进入M2/M3。**
