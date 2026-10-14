# README 首页参考

2026-10-14 实际查阅下列仓库的 `main/README.md`。这里记录的是 README 的信息组织方式，不是 ThesisLab 已实现这些项目的能力，也不表示采用其 Runtime、许可证或代码。

- [DeerFlow](https://github.com/bytedance/deer-flow/blob/main/README.md)：开头包含项目定位、少量技术信息和演示，随后提供配置与运行入口；深层配置指向独立文档。借鉴“先看产品，再运行”的顺序，不移植多 Agent、沙箱或其大规模配置。
- [Dify](https://github.com/langgenius/dify/blob/main/README.md)：封面与显眼的产品、Self-hosting、Documentation 链接；Quick Start 给出短 Compose 流程，功能按用户能力组织。借鉴导航与短安装路径，不照搬其云服务、复杂部署或社区 Badge。
- [Deep Agents](https://github.com/langchain-ai/deepagents/blob/main/README.md)：一句话定位、简短原则与功能、最小调用示例；FAQ 与 Resources 承接详细技术说明。借鉴短功能介绍和分层文档，不声称 ThesisLab 使用其框架或具备其生产能力。
- [Claude Code](https://github.com/anthropics/claude-code/blob/main/README.md)：开头解释自然语言能完成的用户任务，紧跟真实 Demo 与安装入口，其余细节链接官方文档。借鉴直观任务说明和实际操作截图，不复制品牌、文案、资产或安装脚本。

## ThesisLab 的取舍

首页使用一句英文定位、中文场景、真实浏览器截图、五项简短功能和最短本地启动流程。技术信息只保留 Python 版本与 Local MVP；不使用测试通过率、性能、用户评价或许可证 Badge。

详细安装、架构、证据及限制从旧 README 迁至 `SETUP.md` 和 `PRODUCT-GUIDE.md`，历史工程报告保留。重要验收限制集中在 Development Status；每张示例截图明确是 Synthetic Demo。

上述仓库的 README 会继续变化；链接是当时查阅入口，不代表固定版本，也不作为其功能独立测试记录。
