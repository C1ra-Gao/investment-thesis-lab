# Setup & Configuration


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

切换模型：停止服务，编辑 `.env` 中 Provider、模型及相应 Key，再启动。直接运行时，进程环境变量（包括空值）优先于 `.env`；任务保存在 `.local/agent.sqlite`。配置解析不执行 shell 命令。详细优先级见 [环境配置说明](ENV-CONFIGURATION.md)。

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


环境变量优先级与安全状态检查见 [环境配置](ENV-CONFIGURATION.md)。
