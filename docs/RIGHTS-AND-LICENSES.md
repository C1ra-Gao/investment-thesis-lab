# Rights, references and known limitations

## Original project code

M1为独立原始实现，未Fork／移植Quantifact、Mira、VerumTrade、Thesis OS、AgenticThesis或Claimify。参考仅为已审计方法与既定产品契约。未复制代码、Prompt、UI或金融资产。初始仓库没有项目LICENSE，当前亦不擅自替所有者授予开源许可证；首次公开代码发布前请由所有者选择许可证。本地测试不因此阻塞。

## Runtime / PDF dependencies

本次读取实际安装包元数据；声明如下（不把参考项目许可证扩展到依赖）：

| 依赖 | 元数据声明 |
|---|---|
| SQLAlchemy 2.0.44 | MIT |
| pdfplumber 0.11.7 | MIT classifier |
| pdfminer.six 20250506 | MIT |
| Pillow 12.3.0 | MIT-CMU |
| cryptography 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cffi 2.1.1 | MIT-0 |
| typing-extensions 4.16.0 | PSF-2.0 |
| pypdfium2 5.14.0 | BSD-3-Clause、Apache-2.0及dependency licenses |
| charset-normalizer 3.5.2 | MIT |
| pycparser 3.11 | BSD-3-Clause |

pypdfium2的包装、生成代码、PDFium二进制及第三方组件分别有声明，不能简化成单一MIT。固定版本见requirements.lock；使用依赖，不复制其源代码到本仓库。构建工具setuptools 80.9.0由隔离构建安装，与金融运行输入分开。

依赖存在多项传递许可，源／二进制分发时需保留各自要求的声明。此次检查包元数据和依赖一致性，不构成全部供应链法律审查或漏洞扫描。

## Internal financial evidence

真实输入来自已获准内部验证的Phase 3目录，程序不包含其真实金额、原响应、PDF、数据库或个人目录。运行数据库／trace含内部材料，均在`.local/`或测试临时目录中，不能公开提交。官方原文与供应商转存、展示和二次使用权分开；不能仅因报告公开就再分发供应商数据。

供应商日期不等于独立已核实的原始披露日，采用官网日只建立字段投影；供应商缓存／更新时间／历史修订原因仍UNVERIFIED。不提供历史PIT、因果结论或未来预测。八字段的定位/数值核验只证明本次范围的对应关系，不保证发行人财务审计真实性，也不推及其他公司。

## Operational boundaries

M1应用包没有网络、LLM、金融SDK、Keychain或交易客户端；CLI不读取任何API秘密。依赖安装可访问公开包仓库，金融回归离线。无账户账单、留存展示权的新核实，Phase 3总Gate仍CONDITIONAL；本地M1测试通过不解除数据权利边界。

当前没有Web／认证、多人并发、自动监控、分布式队列、图数据库、远程GitHub写入、发布或部署。测试不是完整渗透测试；私有文件访问控制由本机文件系统负责。提交审计只做路径／文本模式／已知私有数字检查，不保证所有未知秘密均可识别。
