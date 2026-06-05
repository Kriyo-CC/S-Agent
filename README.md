# S-Agent

S-Agent 是一个工程级 Python AI Agent 运行时框架，提供完整的终端 CLI 交互式 AI 助手体验。项目围绕可测试的分层架构、统一工具注册、并发工具调度、权限控制、会话持久化、上下文压缩、Token 成本核算、SubAgent 与 MCP 集成展开，适合作为个人 AI 助手、Agent Runtime 原型或二次开发脚手架。

项目当前实现与描述总体匹配：核心分层、17 个本地内置工具、异步并发调度、三级权限、持久化会话/快照、System Prompt 分层构建、SubAgent、MCP 动态工具注册均有代码承载。当前包名为 `agent-scaffold`，安装后提供 `s-agent` console script。

## 核心能力

- **4 层运行时架构**：`cli/` 负责交互和渲染，`agent/` 负责循环、上下文、会话、事件和成本统计，`tools/` 负责工具实现与注册，`config/` 负责环境和权限配置。各层通过 `AgentContext` 注入依赖，降低耦合并方便测试。
- **流式 Agent Loop**：基于 Anthropic Messages API 流式输出模型响应；当模型返回 `tool_use` 时进入工具派发，再把 `tool_result` 写回消息历史继续循环。
- **并发工具调度引擎**：`asyncio.gather(return_exceptions=True)` 并发执行同一轮响应中的工具调用；同步工具通过 `asyncio.to_thread()` 进入线程池；每个工具有超时保护；单个工具失败不会取消同批其他工具。
- **写冲突串行化**：当多个 `write` / `edit` / `revert` 同时操作同一路径时，该路径的写操作会自动串行执行，避免并发覆盖。
- **17 个本地内置工具**：Shell 执行、文件读写/编辑/搜索/撤销、Web 检索、UserSpace 清单、Skill 加载、用户提问、记忆管理和子代理调度。
- **三级权限系统**：按 `always_deny`、`always_allow`、`ask_user`、默认允许的顺序评估 `config/permissions.yaml` 中的正则规则，拦截 `rm -rf /`、`sudo`、关机、管道执行远程脚本等危险操作。
- **持久化撤销系统**：`write` / `edit` 前自动写入 `.snapshots/`，每个文件最多保留 5 层历史，支持跨重启 `revert`。
- **会话持久化**：会话以 JSON 保存在 `.sessions/`，支持列表、恢复、分叉、保存和标题修改。
- **Token 成本核算**：从模型返回的 `usage` 字段读取真实 token 消耗，区分缓存未命中输入、缓存命中输入和输出 token，可通过 `:accounting` 查看，退出时自动汇总。
- **上下文压缩**：消息历史超过阈值后调用模型摘要早期消息，保留最近消息，并把摘要持久化到 `.agent_memory.md`。
- **事件总线**：`session_start`、`pre_tool_use`、`post_tool_use`、`agent_response`、`session_end` 生命周期事件支持 hook 扩展；当前内置工具统计和慢工具提示。
- **SubAgent 子系统**：从 `agents/<name>/agent.yaml` 加载定义，按 `allowed_tools` 过滤工具，在独立会话上下文中执行子任务，只返回最终文本给父 Agent。
- **MCP 协议集成**：读取 `mcp/config.yaml`，通过 stdio 连接 MCP Server，发现远端工具并以 `mcp__<server>__<tool>` 注册到统一工具中心。
- **5 层 System Prompt**：身份定义、运行环境、动态上下文、持久化记忆、可用子代理按轮构建；`UserSpace` 清单、Skill 列表、记忆、子代理列表自动注入。

## 快速开始

### 环境要求

- Python 3.10+
- Anthropic API Key，或兼容 Anthropic API 的代理服务

### 安装

```bash
git clone https://github.com/Kriyo-CC/S-Agent.git
cd S-Agent

python -m venv .venv
source .venv/bin/activate

pip install -e .
pip install -e ".[mcp]"   # 可选：启用 MCP 协议支持
pip install -e ".[feishu]" # 可选：启用飞书/Lark 长连接机器人
pip install -e ".[dev]"   # 可选：开发、测试、lint、类型检查
```

### 配置

仓库包含 `.env.example`，可复制后填写：

```bash
cp .env.example .env
```

常用环境变量：

```env
ANTHROPIC_API_KEY=sk-ant-...
MODEL_ID=claude-sonnet-4-20250514

# 使用兼容 Anthropic API 的网关或代理时设置：
# ANTHROPIC_BASE_URL=http://localhost:4000

# 飞书/Lark 长连接机器人：
# FEISHU_APP_ID=cli_xxx
# FEISHU_APP_SECRET=your_app_secret
```

### 运行

```bash
uv run s-agent
```

也可以使用兼容的直接入口：

```bash
uv run python main.py
```

启动后进入 REPL，直接输入问题或任务即可。退出使用 `q`、`exit` 或 `quit`。

### 运行飞书长连接机器人

项目提供 `s-agent-feishu` 入口，使用飞书官方 `lark-oapi` SDK 的 Channel/WebSocket 长连接能力接收消息并调用同一套 Agent Runtime。

```bash
uv run --extra feishu s-agent-feishu
```

飞书开放平台侧需要启用机器人能力，并在事件订阅中选择长连接模式。凭证通过 `.env` 中的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 读取；不要把真实 App Secret 写入 README、代码或提交记录。

## REPL 指令

这些元指令在 CLI 层直接拦截，不进入 Agent 循环，也不会产生模型调用延迟。

| 指令 | 功能 |
| --- | --- |
| `:sessions` | 列出历史会话 |
| `:resume <id>` | 按 ID 前缀恢复会话 |
| `:fork <id>` | 从指定会话分叉当前会话 |
| `:save` | 手动保存当前会话 |
| `:title <text>` | 修改当前会话标题 |
| `:tools` | 列出当前注册的工具 |
| `:accounting` | 查看当前会话 Token 用量和估算费用 |
| `q` / `exit` / `quit` | 退出 REPL |

## 内置工具

| 工具 | 说明 |
| --- | --- |
| `bash` | 使用 `shlex.split()` 和 list-form subprocess 安全执行命令，不启用 shell 解释 |
| `bash_shell` | 使用 `shell=True` 执行完整 shell 命令，支持管道、重定向和环境变量，风险更高 |
| `read` | 读取文件，支持行号范围 |
| `write` | 写入文件，写前自动快照 |
| `edit` | 精确替换文件中的唯一字符串，写前自动快照 |
| `grep` | 使用 `rg` 或 `grep` 搜索文件内容 |
| `glob` | 按 glob 模式查找文件 |
| `revert` | 从 `.snapshots/` 恢复最近一次写入或编辑前的状态 |
| `ledger_list` | 扫描 `UserSpace/*.md` 并返回文档头部清单 |
| `list_skills` | 列出 `skills/` 中可用技能 |
| `load_skill` | 加载指定 `skills/<name>/SKILL.md` |
| `web_search` | 使用 DuckDuckGo 搜索 Web |
| `ask_user` | 在终端向用户提问并返回回答 |
| `remember` | 写入持久化记忆 |
| `forget` | 删除持久化记忆 |
| `list_memories` | 列出持久化记忆 |
| `spawn_subagent` | 按 `agents/<name>/agent.yaml` 启动隔离子代理 |

MCP 工具会在启动时动态注册，命名格式为 `mcp__<server>__<tool>`。

## 项目结构

```text
.
├── main.py                    # CLI 入口，调用 cli.app.main()
├── pyproject.toml              # 项目元数据和依赖，当前包名为 agent-scaffold
├── config/
│   ├── settings.py             # .env 加载、Anthropic client 工厂、默认模型、权限检查
│   └── permissions.yaml        # deny / allow / ask 三级权限规则
├── cli/
│   ├── app.py                  # 应用装配：client、EventBus、ToolRegistry、MCP、AgentContext、REPL
│   ├── repl.py                 # REPL 主循环，拦截元指令并运行 Agent Loop
│   ├── commands.py             # :sessions、:resume、:fork、:save、:tools、:accounting 等
│   └── render.py               # Rich 终端渲染
├── agent/
│   ├── loop.py                 # 流式模型调用、tool_use 循环、并发工具调度
│   ├── types.py                # AgentContext 依赖注入容器
│   ├── prompt.py               # 5 层 System Prompt 构建
│   ├── context.py              # 上下文压缩和 .agent_memory.md 持久化
│   ├── session.py              # .sessions/ JSON 会话持久化
│   ├── events.py               # Pub/Sub 事件总线
│   ├── accounting.py           # 会话 token 和成本统计
│   └── costs.py                # 多模型价格表
├── tools/
│   ├── registry.py             # 统一工具注册、schema、handler、metadata
│   ├── bash.py                 # Shell 工具
│   ├── file_ops.py             # read/write/edit/grep/glob/revert
│   ├── snapshot.py             # .snapshots/ 持久化快照
│   ├── web_search.py           # DuckDuckGo 搜索后端
│   ├── memory_tools.py         # remember/forget/list_memories
│   ├── skill.py                # Skill 发现和按需加载
│   ├── subagent.py             # 子代理发现、过滤注册表、隔离执行
│   ├── ledger.py               # UserSpace 文档清单
│   └── ask_user.py             # 终端交互式提问工具
├── agents/
│   ├── main/agent.yaml         # 主代理定义
│   └── code-review/agent.yaml  # 代码审查子代理定义
├── skills/
│   ├── SKILL.md                # 技能模板
│   ├── agent-builder/SKILL.md
│   ├── code-review/SKILL.md
│   └── pdf/SKILL.md
├── integrations/
│   └── feishu_bot.py           # 飞书/Lark 长连接机器人入口
├── mcp/
│   ├── client.py               # MCP stdio 客户端
│   └── config.yaml             # MCP server 配置
├── UserSpace/                  # 用户结构化 Markdown 数据
├── memory/                     # remember 工具写入的持久化记忆
├── test/
│   ├── test_concurrent_dispatch.py
│   └── test_events.py
├── .sessions/                  # 运行时生成：会话 JSON
└── .snapshots/                 # 运行时生成：文件撤销快照
```

## 架构说明

### 运行时装配

`cli/app.py` 是唯一启动装配点：

1. 通过 `config.settings.create_client()` 创建 Anthropic client。
2. 读取 `MODEL_ID` 作为默认模型。
3. 创建 `EventBus` 并注册统计/耗时 hook。
4. 创建 `ToolRegistry`，注册本地工具。
5. 初始化 MCP 并注册远端工具。
6. 创建 `AgentContext`，把 client、model、bus、session、MCP executor、console 注入下游。
7. 进入 `cli.repl.run_repl()`。

### Agent Loop

`agent/loop.py` 的 `stream_loop()` 负责思考-行动循环：

1. 使用流式 API 输出模型文本。
2. 保存 assistant 消息。
3. 如果 `stop_reason != "tool_use"`，本轮结束。
4. 否则调用 `dispatch_tools()` 并发执行工具。
5. 将工具结果作为 user 消息写回历史，继续下一轮。

`dispatch_tools()` 会先做输入类型校验、hook 拦截、权限检查和工具查找，再执行工具。预检失败会直接形成 `tool_result`，不会启动任务。

### System Prompt

`agent/prompt.py` 每轮动态构建 5 层 Prompt：

- 身份、职责和运行约束
- 当前工作目录、日期时间
- `UserSpace` 文档清单和可用 Skill 列表
- `memory/` 中的持久化记忆
- 可用 SubAgent 列表

这种设计把动态信息放在 Prompt 构建阶段注入，减少模型额外调用工具获取环境信息的开销。

## 扩展指南

### 添加工具

1. 在 `tools/` 下新增模块或扩展现有模块。
2. 实现纯函数 handler，输入为 `dict`，输出为 `str`。
3. 提供 `register_xxx_tools(registry)`，调用 `registry.register()` 注册 name、description、input_schema、handler。
4. 在 `cli/app.py` 的 ToolRegistry 构建阶段调用注册函数。
5. 若工具会写文件，考虑在 `agent/loop.py` 的写冲突检测中登记，或通过 registry metadata 扩展冲突策略。
6. 为超时、错误隔离、权限规则和主要行为添加测试。

### 添加子代理

在 `agents/<name>/agent.yaml` 新增定义：

```yaml
name: code-review
description: "Performs thorough code review on patches and suggests improvements"
allowed_tools:
  - read
  - grep
  - glob
  - bash
system: |
  You are a specialist agent...
```

`allowed_tools` 必须是父注册表中已有工具。子代理不会继承父对话历史，只会获得独立输入和白名单工具集。

### 添加 Skill

在 `skills/<name>/SKILL.md` 添加技能文档。建议包含 YAML frontmatter：

```markdown
---
name: pdf
description: Use when working with PDF files.
---

# PDF Skill
...
```

技能不会默认全文注入 Prompt；系统只注入清单，模型需要时通过 `load_skill` 按需加载。

### 配置 MCP

安装可选依赖：

```bash
pip install -e ".[mcp]"
```

编辑 `mcp/config.yaml`：

```yaml
servers:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

当前实现支持 stdio transport。启动时成功连接的 MCP 工具会出现在 `:tools` 输出中。

### 配置飞书长连接机器人

安装可选依赖：

```bash
uv sync --extra feishu
```

在 `.env` 中配置：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=your_app_secret
```

启动：

```bash
uv run --extra feishu s-agent-feishu
```

入口文件是 `integrations/feishu_bot.py`。它会复用现有 `ToolRegistry`、`AgentContext`、`stream_loop()`、System Prompt、权限系统、会话保存和可选 MCP 工具。

## Token 计费

`agent/loop.py` 在每次模型响应结束后读取返回对象里的 `response.usage`，再交给 `SessionAccounting` 记录。当前会识别这些字段：

- `input_tokens`：普通输入 token，按缓存未命中输入价格计费。
- `cache_creation_input_tokens`：Anthropic 兼容字段，按缓存未命中输入价格计费。
- `cache_read_input_tokens`：Anthropic 兼容字段，按缓存命中输入价格计费。
- `prompt_cache_miss_tokens` / `input_cache_miss_tokens` 等别名：按缓存未命中输入价格计费。
- `prompt_cache_hit_tokens` / `input_cache_hit_tokens` 等别名：按缓存命中输入价格计费。
- `output_tokens`：输出 token。

DeepSeek-V4 价格按人民币/百万 tokens 配置：

| 模型 | 输入（缓存命中） | 输入（缓存未命中） | 输出 |
| --- | ---: | ---: | ---: |
| `deepseek-v4-flash` | ¥0.02 | ¥1 | ¥2 |
| `deepseek-v4-pro` | ¥0.025 | ¥3 | ¥6 |

## 测试

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

已有测试重点覆盖：

- 并发工具派发、错误隔离、超时、取消、写冲突串行化
- EventBus 注册、触发、错误隔离和集成行为

建议后续补充：

- 权限规则边界测试
- SubAgent 白名单和独立上下文测试
- MCP 工具注册/执行的 mock 测试
- Session resume/fork 的序列化兼容测试
- Prompt 构建的快照测试

## 规范性评估

当前项目结构已经接近规范的 Python Agent Runtime 框架：

- 分层清晰，启动装配集中在 `cli/app.py`，核心循环集中在 `agent/loop.py`。
- `AgentContext` 把共享依赖显式传入，避免全局状态蔓延。
- 工具以注册中心统一暴露 schema 和 handler，便于扩展与测试。
- 运行时状态目录 `.sessions/`、`.snapshots/`、`memory/`、`UserSpace/` 与代码目录分离。
- 测试目录已有对高风险并发调度和事件系统的覆盖。
- `pyproject.toml` 已配置 `s-agent` 命令入口、pytest、Ruff 和 mypy。
- `.github/workflows/ci.yml` 已配置 GitHub Actions，在 push/PR 时自动运行 lint、type check 和 test。

仍可进一步工程化：

- 统一项目命名：包名、启动 banner、README 标题目前存在 `agent-scaffold` / `S-Agent` 两套命名。
- 补充贡献指南和版本发布策略。
- 清理不应入库的运行时缓存或确认 `.gitignore` 已覆盖：`__pycache__/`、`.pytest_cache/`、`.sessions/`、`.snapshots/`、`.env`。

## 技术栈

- Python 3.10+
- Anthropic SDK
- Rich
- PyYAML
- python-dotenv
- ddgs
- MCP 可选依赖
- Redis 可选依赖，目前作为扩展依赖保留
- lark-oapi 可选依赖，用于飞书/Lark 长连接机器人
