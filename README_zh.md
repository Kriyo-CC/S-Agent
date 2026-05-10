# Agent Scaffold

一个工程稳定的 AI Agent 脚手架。包含可观测状态机、工具注册中心、内置工具集、技能系统、MCP 集成与会话持久化。

## 快速开始

```bash
cp .env.example .env   # 编辑填入你的 API 密钥
uv venv && source .venv/bin/activate
uv pip install -e .
python main.py
```

直接运行启动交互式 REPL。使用 `python main.py --task "你的指令"` 执行单次非交互式任务。

## 项目结构

### `main.py`

CLI 入口。组装 EventBus、ObservableAgent FSM、ToolRegistry、MCP 客户端、系统提示词、会话管理以及 REPL 循环。处理会话命令（`:sessions`、`:resume`、`:fork`、`:save`、`:tools`）。

### `agent/` — 核心 Agent 运行时

| 文件 | 作用 |
|------|------|
| `events.py` | 发布/订阅事件总线，提供生命周期钩子：`session_start`、`pre_tool_use`、`post_tool_use`、`agent_response`、`tool_error`、`session_end`。 |
| `fsm.py` | 可观测状态机。状态流转：`IDLE → THINKING → ACTING → IDLE`，另有 `WAITING_USER` 和 `ERROR` 状态。每次转换触发回调（如终端图标显示）。 |
| `loop.py` | 思考-行动主循环：流式输出 LLM 回复，打印文本，分发 tool_use 块，将结果返回模型，直到 `stop_reason != tool_use`。内含权限检查和 MCP 执行路径。 |
| `context.py` | 上下文压缩器。当历史超过 40k 字符时，通过 LLM 摘要旧消息，持久化到 `.agent_memory.md`，将历史折叠为 1 条系统消息 + 最近 N 条消息。 |
| `session.py` | 会话持久化：在 `.sessions/` 中创建/加载/保存/列出 JSON 会话。支持通过 UUID 前缀查找。 |

### `config/` — 配置与安全策略

| 文件 | 作用 |
|------|------|
| `settings.py` | 通过 python-dotenv 加载 `.env`，创建 Anthropic 客户端，定义危险命令黑名单，并基于 `permissions.yaml` 规则实现 `check_permission()`（正则匹配工具输入）。 |
| `permissions.yaml` | 基于规则的信任体系：`always_deny`（sudo、rm -rf /、fork 炸弹、curl-bash 管道）、`always_allow`（ls、cat、grep、git status/log/diff）、`ask_user`（rm、git commit/push、pip install、chmod、.env 访问）。 |

### `tools/` — 内置工具实现

| 文件 | 作用 |
|------|------|
| `registry.py` | `ToolRegistry` 类：存储 `{name, description, input_schema}` + 处理函数。支持 register、dispatch、list_schemas、merge。 |
| `bash.py` | `bash` 工具：通过 subprocess 执行 shell 命令，含黑名单检查和 120 秒超时。 |
| `file_ops.py` | `read`、`write`、`grep`、`glob`、`revert` 工具。写入时自动快照旧内容以便 revert。read 支持行号范围。 |
| `skill.py` | `list_skills` 和 `load_skill` 工具。扫描 `skills/` 目录中的 `SKILL.md` 文件，从 YAML frontmatter 提取描述。防止路径穿越攻击。 |
| `subagent.py` | `spawn_subagent` 工具：派生独立 Agent 循环执行子任务。只返回最终文本，保持父级上下文干净。 |

### `mcp/` — 模型上下文协议（可选）

| 文件 | 作用 |
|------|------|
| `client.py` | `MCPClient`：连接基于 stdio 的 MCP 服务器，发现工具，以 `mcp__<server>__<tool>` 命名空间化，并路由执行。需要 `pip install mcp`。 |
| `config.yaml` | MCP 服务器定义。添加 `name`、`transport: stdio`、`command`、`args` 条目。默认空列表。 |

### `skills/` — 可扩展领域知识

每个子目录是一个技能。Agent 在启动时发现技能，可按需加载完整指令。内含三个示例技能：`agent-builder`、`code-review`、`pdf`。复制模板并编写 `SKILL.md` 即可添加新技能。

### 根目录文件

| 文件 | 作用 |
|------|------|
| `pyproject.toml` | 项目元信息与依赖。核心依赖：`anthropic`、`python-dotenv`、`pyyaml`、`colorama`。可选依赖：`mcp`、`redis`。 |
| `.env.example` | 环境变量模板：`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`（代理）、`MODEL_ID`。 |
| `.gitignore` | 忽略 `.env`、`__pycache__/`、`.venv/`、`.sessions/` 以及构建产物。 |
