# Agent Scaffold

An engineering-stable scaffold for building AI agents. Observable state machine, tool registry with built-in tools, skills support, MCP integration, and session persistence.

## Quick Start

```bash
cp .env.example .env   # edit with your API key
uv venv && source .venv/bin/activate
uv pip install -e .
python main.py
```

Running without args starts the interactive REPL. Use `python main.py --task "do something"` for a single non-interactive task.

## Project Layout

### `main.py`

CLI entry point. Wires up the EventBus, ObservableAgent FSM, ToolRegistry, MCP client, system prompt, session management, and the REPL loop. Handles session commands (`:sessions`, `:resume`, `:fork`, `:save`, `:tools`).

### `agent/` — Core agent runtime

| File | Role |
|------|------|
| `events.py` | Pub/Sub EventBus for lifecycle hooks: `session_start`, `pre_tool_use`, `post_tool_use`, `agent_response`, `tool_error`, `session_end`. |
| `fsm.py` | Observable agent state machine. States: `IDLE → THINKING → ACTING → IDLE`, with `WAITING_USER` and `ERROR` for side paths. Each transition fires callbacks (e.g. terminal icons). |
| `loop.py` | The thinking-acting loop: streams LLM responses, prints text, dispatches tool_use blocks, feeds results back, repeats until `stop_reason != tool_use`. Includes permission gating and MCP execution path. |
| `context.py` | Context compressor. When history exceeds 40k chars, summarizes older messages via LLM, persists to `.agent_memory.md`, collapses history into 1 system message + recent N messages. |
| `session.py` | Session persistence: create/load/save/list JSON sessions in `.sessions/`. Supports `<uuid-prefix>` lookups. |

### `config/` — Settings & policy

| File | Role |
|------|------|
| `settings.py` | Loads `.env` via python-dotenv, creates the Anthropic client, defines dangerous command blocklist, and implements rule-based `check_permission()` (regex-matches tool input against `permissions.yaml` rules). |
| `permissions.yaml` | Rule-based trust system: `always_deny` patterns (sudo, rm -rf /, fork bombs, pipe-to-shell), `always_allow` (ls, cat, grep, git status/log/diff), `ask_user` (rm, git commit/push, pip install, chmod, .env access). |

### `tools/` — Built-in tool implementations

| File | Role |
|------|------|
| `registry.py` | `ToolRegistry` class: stores `{name, description, input_schema}` + handler callable. Supports register, dispatch, list_schemas, merge. |
| `bash.py` | `bash` tool: runs shell commands via subprocess with a blocklist check and 120s timeout. |
| `file_ops.py` | `read`, `write`, `grep`, `glob`, `revert` tools. Write auto-snapshots previous content for revert. Read supports line ranges. |
| `skill.py` | `list_skills` and `load_skill` tools. Scans `skills/` directories for `SKILL.md` files, extracts descriptions from YAML frontmatter. Guards against path traversal. |
| `subagent.py` | `spawn_subagent` tool: forks an isolated agent loop for a subtask. Only final text is returned, keeping the parent context clean. |

### `mcp/` — Model Context Protocol (optional)

| File | Role |
|------|------|
| `client.py` | `MCPClient`: connects to stdio-based MCP servers, discovers tools, namespaces them as `mcp__<server>__<tool>`, and routes execution. Requires `pip install mcp`. |
| `config.yaml` | MCP server definitions. Add entries with `name`, `transport: stdio`, `command`, `args`. Empty by default. |

### `skills/` — Extensible domain knowledge

Each subdirectory is a skill. The agent discovers them at startup and can load full instructions on demand. Contains three example skills: `agent-builder`, `code-review`, `pdf`. Add new skills by copying the template and writing a `SKILL.md`.

### Root files

| File | Role |
|------|------|
| `pyproject.toml` | Project metadata and dependencies. Core: `anthropic`, `python-dotenv`, `pyyaml`, `colorama`. Optional: `mcp`, `redis`. |
| `.env.example` | Env template: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` (proxy), `MODEL_ID`. |
| `.gitignore` | Ignores `.env`, `__pycache__/`, `.venv/`, `.sessions/`, build artifacts. |
