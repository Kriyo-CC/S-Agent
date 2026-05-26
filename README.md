# S-Agent

一个工程级 Python AI Agent 运行时框架，在终端中提供完整的交互式 AI 助手体验。

## 特性

### 架构设计

- **四层分层架构**：CLI（交互与渲染）/ Agent Engine（循环与调度）/ Tools（工具实现）/ Config（配置与权限），各层职责清晰，通过 AgentContext 集中管理依赖，可独立测试。
- **事件驱动的 Pub/Sub 总线**：支持 `session_start`、`pre_tool_use`、`post_tool_use`、`session_end` 等生命周期事件，内置工具调用统计与慢工具检测（>5s 告警）。
- **5 层 System Prompt 构建**：身份定义 → 运行环境 → 动态上下文 → 持久化记忆 → 可用子代理，每轮按需重组，记忆和上下文自动注入，无需额外工具调用。

### 并发工具调度引擎

- 基于 `asyncio` 的异步并行派发，单次对话中的所有工具调用并发执行。
- **错误隔离**：单个工具崩溃不影响同一批次的其他工具。
- **超时控制**：支持 per-tool 超时配置（默认 300s），超时即终止，不影响并行任务。
- **资源冲突自动串行化**：多个工具同时写入同一文件时，自动降级为串行执行，避免 last-write-wins 数据丢失。

### 统一工具注册中心

- 17+ 内置工具通过中央注册表统一管理，支持注册、派发、合并、过滤。
- 同步与异步 handler 透明支持：同步函数自动丢入线程池执行，不阻塞事件循环。
- MCP 远端工具以 `mcp__<server>__<tool>` 命名空间注册，与本地工具无差别派发。

### 安全体系

- **三级权限引擎**：`always_deny` → `always_allow` → `ask_user` → 默认允许。基于正则匹配，配置文件 `config/permissions.yaml` 独立维护。
- **命令注入防护**：`bash` 工具使用 `shlex.split()` + list-form `subprocess.run()`（无 `shell=True`），管道/重定向不可用。仅 `bash_shell` 提供 shell 解释能力，并明确标注风险。
- **路径穿越防护**：Skill 加载时拦截 `..`、`/`、`\` 字符。
- **文件快照撤销**：write/edit 操作前自动保存快照至 `.snapshots/`，每个文件最多保留 5 层历史，跨重启持久化，支持 `revert` 恢复。

### SubAgent 子系统

- 基于文件夹的代理定义（`agents/<name>/agent.yaml`），声明名称、描述、允许的工具白名单、系统提示词。
- 运行时通过 `build_filtered_registry()` 从完整注册表中过滤出子代理工具子集。
- 子代理在**独立会话上下文**中运行，内部试错过程不污染父代理的对话历史，仅返回最终文本结果。
- 内置 `main`（通用助手）和 `code-review`（代码审查）两个代理定义。

### 会话管理

- 会话以 JSON 格式持久化到 `.sessions/` 目录，每轮对话自动保存。
- 支持 `:sessions`（列表）、`:resume <id>`（恢复）、`:fork <id>`（分叉）、`:save`（手动保存）、`:title <text>`（重命名）等 REPL 元指令，在 CLI 层直接拦截处理，零 API 调用延迟。

### 生产级辅助系统

- **上下文压缩**：对话历史超过 40K 字符时，自动调用 LLM 将早期消息压缩为摘要，保留最近 6 条完整消息，摘要持久化到 `.agent_memory.md`。
- **Token 成本追踪**：内置 Claude / DeepSeek / GPT 多模型价格表，每轮统计 input/output token 与费用，会话结束自动打印汇总，支持 `:accounting` 指令随时查看。
- **Skill 技能系统**：从 `skills/<name>/SKILL.md` 按需加载领域知识，避免 System Prompt 膨胀。内置 agent-builder、code-review、pdf 等技能。
- **记忆系统**：`remember`/`forget`/`list_memories` 工具管理持久化记忆，支持 YAML frontmatter 分类，自动注入每轮 System Prompt（上限 2000 字符）。

### MCP 协议集成

- 实现 MCP stdio 传输协议客户端，通过 `mcp/config.yaml` 配置远端服务器。
- 启动时自动连接并发现远端工具，以 `mcp__<server>__<tool>` 格式注册到本地注册中心。
- 使用 `AsyncExitStack` 管理连接生命周期，退出时优雅关闭。
- MCP 为可选依赖：`pip install mcp` 后可用。

### 多模型支持

- 通过 `ANTHROPIC_BASE_URL` 环境变量支持任意兼容 Anthropic API 的后端（Claude、DeepSeek、GPT 等）。
- `MODEL_ID` 环境变量指定模型，默认 `claude-sonnet-4-20250514`。

## 快速开始

### 环境要求

- Python 3.10+
- Anthropic API Key（或兼容的代理地址）

### 安装

```bash
git clone https://github.com/Kriyo-CC/S-Agent.git
cd S-Agent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e .            # 核心依赖
pip install -e ".[mcp]"     # 可选：MCP 协议支持
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
ANTHROPIC_API_KEY=sk-ant-...        # API Key
MODEL_ID=claude-sonnet-4-20250514   # 模型 ID

# 使用第三方代理（DeepSeek / GPT 等）时设置：
# ANTHROPIC_BASE_URL=http://localhost:4000
```

### 运行

```bash
python main.py
```

启动后进入 REPL 交互界面，直接输入对话内容即可。

### REPL 指令

| 指令 | 功能 |
|------|------|
| `:sessions` | 列出所有历史会话 |
| `:resume <id>` | 恢复到指定会话（支持 ID 前缀匹配） |
| `:fork <id>` | 从指定会话分叉出一个新会话 |
| `:save` | 手动保存当前会话 |
| `:title <text>` | 设置当前会话标题 |
| `:tools` | 列出所有已注册工具 |
| `:accounting` | 查看当前会话 Token 用量与费用 |
| `q` / `exit` | 退出 |

### 配置 MCP 服务器（可选）

创建 `mcp/config.yaml`：

```yaml
servers:
  - name: filesystem
    command: npx
    args: ["-y", "@anthropic/mcp-filesystem", "/path/to/dir"]
```

### 添加自定义子代理

在 `agents/` 下创建新目录和 `agent.yaml`：

```yaml
name: my-agent
description: "我的自定义代理"
allowed_tools:
  - read
  - grep
  - bash
system: |
  You are a specialist agent. ...
```

## 项目结构

```
├── main.py                 # 入口
├── pyproject.toml           # 项目元数据与依赖
├── .env.example             # 环境变量模板
├── config/
│   ├── settings.py          # 客户端工厂 / 权限检查
│   └── permissions.yaml     # 三级权限规则
├── cli/
│   ├── app.py               # 应用编排启动
│   ├── repl.py              # REPL 交互循环
│   ├── render.py            # Rich 终端渲染
│   └── commands.py          # REPL 元指令处理
├── agent/
│   ├── loop.py              # 流式思考-行动核心循环 + 并发工具调度
│   ├── types.py             # AgentContext 依赖注入容器
│   ├── events.py            # Pub/Sub 事件总线
│   ├── session.py           # 会话持久化（JSON）
│   ├── prompt.py            # 5 层 System Prompt 构建
│   ├── memory.py            # 记忆文件加载与格式化
│   ├── context.py           # 上下文压缩
│   ├── accounting.py        # Token 成本追踪
│   └── costs.py             # 多模型价格表
├── tools/
│   ├── registry.py          # 统一工具注册/派发/合并
│   ├── errors.py            # 工具异常层次结构
│   ├── bash.py              # Shell 执行（安全/完整两种模式）
│   ├── file_ops.py          # 文件读写/编辑/搜索/撤销
│   ├── snapshot.py          # 持久化文件快照（5 层回滚）
│   ├── web_search.py        # Web 搜索（DuckDuckGo）
│   ├── memory_tools.py      # 记忆管理（记/忘/列）
│   ├── skill.py             # Skill 发现与按需加载
│   ├── subagent.py          # 子代理生成与工具过滤
│   ├── ledger.py            # UserSpace 文档清单
│   └── ask_user.py          # 终端交互式提问
├── agents/
│   ├── main/agent.yaml      # 主代理定义
│   └── code-review/agent.yaml  # 代码审查子代理
├── skills/                  # 按需加载的技能定义
├── mcp/
│   └── client.py            # MCP stdio 协议客户端
├── memory/                  # 持久化记忆文件
└── test/
    ├── test_concurrent_dispatch.py  # 并发调度测试（820 行）
    └── test_events.py               # 事件系统集成测试
```

## 技术栈

- **语言**：Python 3.10+
- **核心依赖**：Anthropic SDK、Rich（终端渲染）、PyYAML、python-dotenv
- **可选依赖**：MCP（Model Context Protocol）、Redis
- **搜索引擎**：DuckDuckGo（免费，无需 API Key）
