# AGENTS.md

本文件面向后续接手开发的 Agent 和工程师，说明 S-Agent 的代码结构、约定、扩展方式和验证重点。修改代码前请先阅读本文件和 `README.md`。

## 项目定位

S-Agent 是一个工程级 Python AI Agent 运行时框架。它不是单一聊天脚本，而是由 CLI、Agent Engine、Tools、Config/MCP/Runtime State 组成的可扩展运行时：

- CLI 提供 REPL、Rich 渲染和元指令拦截。
- Agent Engine 负责流式模型调用、工具调度、会话、上下文压缩、事件和成本核算。
- Tools 通过统一注册中心暴露给模型。
- Config 负责模型环境变量和权限规则。
- Agents/Skills/MCP 提供子代理、按需知识和远端工具扩展。

## 目录职责

```text
main.py              启动入口，调用 cli.app.main()
cli/                 用户交互层：应用装配、REPL、命令、渲染
agent/               Agent 运行时核心：loop、context、prompt、session、events、accounting
tools/               本地工具实现和 ToolRegistry
config/              环境变量、模型默认值、权限规则
agents/              子代理 YAML 定义
skills/              按需加载的 SKILL.md 知识包
mcp/                 MCP stdio 客户端和 server 配置
integrations/        外部渠道入口，例如飞书/Lark 长连接机器人
test/                pytest 测试
UserSpace/           用户结构化 Markdown 数据
memory/              remember 工具持久化记忆
.sessions/           运行时会话快照
.snapshots/          文件写入/编辑撤销快照
```

运行时生成目录和私密文件不要随意提交：`.env`、`.sessions/`、`.snapshots/`、`.agent_memory.md`、`__pycache__/`、`.pytest_cache/`。

## 核心数据流

1. `main.py` 进入 `cli.app.main()`。
2. `cli/app.py` 创建 Anthropic client、`EventBus`、`ToolRegistry`、MCP client 和 `AgentContext`。
3. `cli/repl.py` 读取用户输入。`:sessions`、`:resume`、`:fork`、`:save`、`:tools`、`:accounting` 等命令在 CLI 层处理。
4. 普通用户输入追加到 session messages，然后调用 `agent.loop.stream_loop()`。
5. `stream_loop()` 流式调用模型；如果返回 `tool_use`，调用 `dispatch_tools()`。
6. `dispatch_tools()` 做输入校验、hook、权限检查、工具查找、并发执行和结果组装。
7. 工具结果作为 user message 写回，循环继续，直到模型给出最终回答。
8. 每轮后执行上下文压缩检查和会话保存。

## 架构约定

- `AgentContext` 是依赖注入边界。新增需要跨层共享的依赖时，优先显式加入 context，而不是增加隐式全局变量。
- `cli/app.py` 是启动装配点。新增工具、hook、MCP 装配逻辑时，从这里接入。
- `agent/loop.py` 只处理 Agent 循环、工具派发和错误隔离，不应塞入具体业务工具逻辑。
- `tools/` 中的工具 handler 尽量保持简单：输入 `dict`，返回 `str`，内部自己处理异常并截断大输出。
- 权限策略属于 `config/permissions.yaml` 和 `config/settings.py`，不要把危险命令硬编码散落到工具里。
- System Prompt 的动态注入集中在 `agent/prompt.py`，不要在 REPL 或工具注册阶段拼接额外 Prompt。
- 会话历史结构需要兼容 Anthropic SDK content block，修改序列化前先看 `agent/session.py`。
- 外部渠道入口放在 `integrations/`，应复用现有 `AgentContext`、`ToolRegistry`、`stream_loop()`、权限系统和会话保存，避免平行实现 Agent Loop。

## 工具开发规范

新增工具时按这个顺序做：

1. 在 `tools/<name>.py` 中实现 `run_xxx(...) -> str`。
2. 实现 `register_xxx_tools(registry) -> None`。
3. 使用 `registry.register(name, description, input_schema, handler, metadata=None)` 注册。
4. 在 `cli/app.py` 的 ToolRegistry 构建阶段调用注册函数。
5. 如果工具访问外部网络、执行命令、读写文件或处理用户隐私，补充权限规则或明确说明风险。
6. 为错误路径写测试。工具异常不应让整个 Agent Loop 崩溃。

工具描述要告诉模型“什么时候使用”，不只说明“是什么”。输出必须是模型容易理解的纯文本。长输出应截断，文件/命令类工具建议不超过 50k 字符。

### 写文件工具

涉及文件修改时优先复用 `tools/file_ops.py` 和 `tools/snapshot.py`。如果新增工具也会修改文件，请考虑：

- 写前保存快照，支持撤销。
- 并发写冲突是否需要在 `agent/loop.py` 的 `_detect_write_conflicts()` 中登记。
- 路径是否可能越权或误写运行时文件。

### Shell 工具

- `bash` 是默认安全工具，不使用 `shell=True`。
- `bash_shell` 支持管道和重定向，但风险更高。
- 危险命令通过 `config/permissions.yaml` 拦截；新增高风险模式时同步更新规则和测试。

## SubAgent 规范

子代理定义位于 `agents/<name>/agent.yaml`：

```yaml
name: my-agent
description: "What this agent is good at"
allowed_tools:
  - read
  - grep
  - glob
system: |
  You are a specialist agent...
```

约定：

- `name` 应与目录名一致。
- `allowed_tools` 只能列父注册表中真实存在的工具。
- 子代理应只拿完成任务所需的最小工具集。
- 子代理运行在独立消息上下文中，不要依赖父代理的完整历史。
- 复杂、风险高或需要隔离探索的任务适合交给子代理。

## Skill 规范

Skill 位于 `skills/<name>/SKILL.md`。推荐使用 frontmatter：

```markdown
---
name: code-review
description: Use when asked to review code or audit quality.
---
```

System Prompt 只注入技能清单，不注入全文。模型需要某个技能时应调用 `load_skill`。新增技能时保持内容操作性强，少写泛泛原则，多写流程、检查表、示例和常见陷阱。

## MCP 规范

MCP 配置在 `mcp/config.yaml`：

```yaml
servers:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
```

当前客户端只支持 stdio transport。远端工具注册名格式为 `mcp__<server>__<tool>`。如果扩展 transport 或鉴权方式，请保持 `MCPClient.connect()` 返回 Anthropic tool schema，`MCPClient.execute()` 返回纯文本，避免污染上层调度逻辑。

## 飞书长连接规范

飞书/Lark 机器人入口位于 `integrations/feishu_bot.py`，console script 为 `s-agent-feishu`。

运行方式：

```bash
uv run --extra feishu s-agent-feishu
```

约定：

- 凭证只从 `.env` 读取：`FEISHU_APP_ID` / `FEISHU_APP_SECRET`，兼容 `LARK_APP_ID` / `LARK_APP_SECRET`。
- 不要把真实 App Secret 写入代码、README、测试快照或提交记录。
- 收到消息后应复用现有 Agent Runtime，不要在集成层复制工具派发逻辑。
- 飞书开放平台侧需要启用机器人能力，并选择长连接/WebSocket 事件订阅模式。
- 如果添加更多渠道，按同样方式放在 `integrations/` 并新增独立 optional extra。

## 测试重点

运行测试：

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

高风险改动必须补测试：

- `agent/loop.py`：并发调度、错误隔离、超时、取消、写冲突串行化、MCP 工具执行。
- `config/settings.py` 和 `config/permissions.yaml`：deny/allow/ask 优先级和危险命令匹配。
- `agent/session.py`：SDK content block 序列化、resume、fork。
- `agent/prompt.py`：动态层是否稳定注入，避免意外膨胀 Prompt。
- `tools/subagent.py`：工具白名单过滤、缺失 agent、空工具集。
- `mcp/client.py`：连接失败、工具发现、执行失败。
- `integrations/feishu_bot.py`：凭证缺失、消息字段提取、发送失败和 Agent Loop 错误返回。

## 当前规范性判断

项目结构是比较规范的 Python Agent Runtime：

- 分层边界清楚。
- 依赖注入点明确。
- 工具注册和派发统一。
- 运行时状态与代码分离。
- 已有针对并发调度和事件系统的测试。
- 已配置 `s-agent` console script、Ruff、mypy、pytest 和 GitHub Actions CI。

后续建议优先做这些工程化增强：

- 统一项目命名：`S-Agent`、`agent-scaffold`、启动 banner 三处目前不完全一致。
- 扩展权限、SubAgent、MCP、session 的测试覆盖。
- 明确 `.gitignore` 是否覆盖运行时状态和私密文件。

## 修改前检查清单

- 先运行 `git status --short`，确认工作区是否已有用户改动。
- 阅读相关模块，不凭 README 猜实现。
- 对外部行为或工具 schema 的改动要同步更新 README。
- 对后续 Agent 开发约定的改动要同步更新本文件。
- 能用现有注册表、上下文、事件总线解决的问题，不新增平行机制。
