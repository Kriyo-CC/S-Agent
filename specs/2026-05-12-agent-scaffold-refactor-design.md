# Agent Scaffold Refactor Design

**Date:** 2026-05-12
**Status:** Approved
**Author:** Staff Software Architect

## 1. Executive Summary

This document specifies a layered architecture refactor for the agent-scaffold project at `/home/szu/agent-scaffold`. The current codebase is functional but has accumulated architectural debt: a monolithic `main.py` (297 lines), `print()` calls scattered across 8 files using raw ANSI escape codes, insecure Bash execution (`shell=True`), no structured memory or accounting systems, and hardcoded sub-agent behavior.

The refactor introduces four layers (CLI, Agent Engine, Tools, Config) with clear boundaries, upgrades all tool implementations to production quality, adds memory persistence, token accounting, folder-based agent definitions, and replaces all output with Rich-formatted console rendering.

## 2. Current State Analysis

### 2.1 Architecture (Before)

```
main.py (297 lines)
├── REPL loop (raw input())
├── Command dispatch (:sessions, :resume, :fork, etc.)
├── Tool registration (bash, file_ops, ledger, skill, subagent, MCP)
├── EventBus setup (stats hook, timer hook)
├── MCP initialization
├── Session management (create, save, compress)
└── Error handling / shutdown
```

### 2.2 Pain Points

| Issue | Location | Impact |
|---|---|---|
| `print()` with ANSI codes | 8 files, ~27 calls | Unreadable, unmaintainable, no structured output |
| `subprocess.run(shell=True)` | `tools/bash.py` | Command injection risk |
| `_SNAPSHOTS` in-memory dict | `tools/file_ops.py` | Revert lost on restart |
| Grep uses system `grep` | `tools/file_ops.py` | No ripgrep, slower |
| No Edit tool | N/A | Agent must use Write for all file changes |
| No WebSearch | N/A | Agent can't browse web |
| No AskUserQuestion | N/A | Agent can't ask user mid-task |
| No Memory tool | N/A | No structured preference storage |
| No token/cost tracking | N/A | No accounting |
| Hardcoded subagent prompt | `tools/subagent.py` | Can't customize per-agent behavior |
| `config/settings.py` global state | Module-level `client`, `MODEL` | Can't mock, can't multi-session |
| `main.py` does everything | Single monolithic file | Hard to test, hard to extend |

## 3. Architectural Approaches Considered

### 3.1 Approach A: Incremental Cleanup (Minimal Restructuring)

Keep existing structure intact, upgrade components one by one in-place.

- `main.py` stays whole, `print()` replaced with Rich calls
- Tools upgraded in-place (Bash gets shlex, Edit added, grep gets ripgrep)
- `memory/` and `agents/` added as new directories
- Accounting injected as EventBus hook

**Pros:** Lowest risk, easy merge path for parallel work, any step can be rolled back independently.
**Cons:** `main.py` remains a 300+ line orchestrator; `print()` -> Rich replacement must touch every file; EventBus hooks are coupled to implementation details.

### 3.2 Approach B: Layered Architecture (Recommended)

Refactor into four distinct layers with well-defined boundaries:

- **CLI Layer** (new `cli/` package): REPL, command parsing, Rich rendering
- **Agent Engine Layer** (existing `agent/` package, plus `accounting/`): Loop, session, context, prompt, token accounting
- **Tool Layer** (existing `tools/` package, plus new tools): All tool implementations + registry
- **Config Layer** (existing `config/` package): Settings, permissions

`main.py` collapses to a 5-line entry point calling `cli/app.py`.

**Pros:** Clean separation of concerns; each layer can be understood and tested independently; standard Python package structure for future extensions; dependency injection makes mocking simple.
**Cons:** Git history disruption due to file moves; requires one atomic large-refactor commit; backward compatibility with existing sessions needs explicit handling.

### 3.3 Approach C: Microkernel / Plugin Architecture

Core runtime dispatches tool calls and manages events; everything else is a independently-loaded plugin.

- Each tool is its own Python package with `tool.yaml` metadata
- Agent definitions are plugins with YAML frontmatter
- CLI is itself a plugin
- Registry acts as kernel

**Pros:** Maximum modularity and extensibility; third-party tools as plugins.
**Cons:** Heavily over-engineered for a single-user CLI tool; YAGNI violation; dynamic discovery at load time adds complexity with no tangible benefit.

### 3.4 Recommendation: Approach B

This is the best ROI point. It solves all listed problems (monolithic main.py, print() scattered, low-quality tools) without the meta-programming overhead of a plugin system. The layers map to natural concerns -- a new contributor can look at `cli/`, `agent/`, or `tools/` without understanding the entire codebase.

## 4. Target Architecture

### 4.1 Layer Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          CLI LAYER (cli/)                                │
│                                                                          │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────────────┐  │
│  │   main.py    │  │   repl.py     │  │      render.py               │  │
│  │ (entry point)│  │ (REPL loop,   │  │ (Rich Console wrapper,       │  │
│  │    3 lines)  │  │  input history)│  │  markdown formatting)        │  │
│  └──────────────┘  └───────┬───────┘  └─────────────────────────────┘  │
│                            │ calls                                      │
│                      ┌─────▼───────┐                                   │
│                      │  app.py     │  (bootstrap, orchestration)        │
│                      └─────┬───────┘                                   │
├────────────────────────────┼─────────────────────────────────────────────┤
│                   AGENT ENGINE LAYER (agent/)                           │
│                            │                                             │
│  ┌──────────┐  ┌──────────▼──┐  ┌──────────┐  ┌─────────────────────┐  │
│  │ loop.py  │  │  session.py │  │context.py│  │   prompt.py          │  │
│  │(stream   │  │(JSON file   │  │(compress)│  │(layered system       │  │
│  │ +dispatch)│  │ persistence)│  │          │  │ prompt builder)      │  │
│  └──────────┘  └─────────────┘  └──────────┘  └─────────────────────┘  │
│  ┌──────────┐  ┌─────────────┐  ┌───────────────────────────────────┐  │
│  │events.py │  │ accounting  │  │       memory.py                    │  │
│  │(pub/sub) │  │ .py (token  │  │ (load/inject memories into        │  │
│  └──────────┘  │  tracking,  │  │  system prompt each turn)         │  │
│                │  cost calc) │  └───────────────────────────────────┘  │
│                └─────────────┘                                         │
├──────────────────────────────────────────────────────────────────────────┤
│                          TOOL LAYER (tools/)                            │
│                                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │registry  │  │ bash.py  │  │ file_ops.py  │  │ web_search.py     │  │
│  │.py       │  │(shlex,   │  │(Read/Write/  │  │(DuckDuckGo        │  │
│  │          │  │ no shell)│  │ Edit/Grep/   │  │ backend,          │  │
│  └──────────┘  └──────────┘  │ Glob/Revert)│  │ switchable)       │  │
│                               └──────────────┘  └───────────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │skill.py  │  │ ledger   │  │ subagent.py  │  │ ask_user.py       │  │
│  │(discover │  │ .py      │  │(spawn from   │  │(blocking question │  │
│  │ +load)   │  │(UserSpace│  │ agents/      │  │ via REPL)         │  │
│  └──────────┘  │ scanner) │  │ folder)      │  └───────────────────┘  │
│                └──────────┘  └──────────────┘                          │
│  ┌───────────────┐  ┌──────────────┐                                   │
│  │ snapshot.py   │  │ memory_tools │                                   │
│  │(persistent    │  │ .py (remember│                                   │
│  │ undo history) │  │ /forget/list)│                                   │
│  └───────────────┘  └──────────────┘                                   │
├──────────────────────────────────────────────────────────────────────────┤
│                         CONFIG LAYER (config/)                          │
│                                                                          │
│  ┌──────────────────┐  ┌──────────────────────────────┐                │
│  │  settings.py     │  │  permissions.yaml             │                │
│  │ (.env loading,   │  │ (regex-based allow/deny/ask)  │                │
│  │  client factory) │  └──────────────────────────────┘                │
│  └──────────────────┘                                                   │
├──────────────────────────────────────────────────────────────────────────┤
│                       INFRASTRUCTURE (mcp/)                             │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  client.py (MCP stdio transport, tool discovery & execution)       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow

```
                      USER INPUT
                         │
                         ▼
              ┌──────────────────────┐
              │    cli/repl.py       │
              │  REPL: parse input   │
              └────────┬─────────────┘
                       │ query string
                       ▼
              ┌──────────────────────┐
              │  cli/commands.py     │
              │ :command? -> handled │
              └────────┬─────────────┘
                       │ (not a command)
                       ▼
              ┌──────────────────────┐
              │   cli/app.py         │
              │ session[messages]    │
              │ .append(user_msg)    │
              └────────┬─────────────┘
                       │ messages + system + tools
                       ▼
              ┌──────────────────────┐
              │  agent/loop.py       │
              │  stream_loop()       │
              │                      │
              │ 1. Call API           │
              │ 2. Stream to console  │
              │ 3. Check stop_reason  │
              │ 4. dispatch_tools()   │
              │ 5. Repeat              │
              └────────┬─────────────┘
                       │ tool calls
                       ▼
              ┌──────────────────────┐
              │ tools/registry.py    │
              │ dispatch() -> handler │
              └────────┬─────────────┘
                       │ result text
                       ▼
              ┌──────────────────────┐
              │  agent/loop.py       │
              │ append tool_result   │
              │ loop or stop         │
              └────────┬─────────────┘
                       │ final response
                       ▼
              ┌──────────────────────┐
              │   cli/app.py         │
              │ save_session()       │
              │ maybe_compress()     │
              │ accounting.record()  │
              └────────┬─────────────┘
                       │ next turn
                       ▼
                    (back to REPL)
```

### 4.3 System Prompt Build Flow (Per Turn)

```
app.py: build_system_prompt(agent_context)
         │
         ├── _layer_identity()        -> from agents/<name>/agent.yaml system field
         ├── _layer_environment()     -> cwd, datetime
         ├── _layer_dynamic_context() -> UserSpace inventory, skills catalog
         ├── _layer_memories()        -> loaded from memory/*.md files
         └── _layer_agents()          -> catalog of available sub-agents
```

## 5. Key Design Decisions

### D1: Dependency Injection via AgentContext

**Problem:** `config/settings.py` creates module-level `client = Anthropic(...)` and `MODEL = ...`. Modules import them directly -- impossible to test or swap per-session.

**Decision:** `agent/types.py` defines `AgentContext` dataclass. `app.py` creates it, injects into all layers. `config/settings.py` becomes pure functions (no module-level side effects).

```python
@dataclass
class AgentContext:
    client: Anthropic
    model: str
    bus: EventBus
    session: dict
```

### D2: Rich Console Replacement for print()

**Problem:** 27 `print()` calls across 8 files with raw ANSI escapes.

**Decision:** `cli/render.py` provides shared Rich `Console` instance. All user-facing output routed through it. Python `logging` used for diagnostics (file logging), separate from user output.

Style guide:
- Headings/separators: `console.rule("[bold]Title[/bold]")`
- Tool invocations: `console.print(f"[yellow]{tool_name}[/yellow] {summary}")`
- Errors: `console.print(f"[red]Error: {msg}[/red]")`
- Status/dim: `console.print(f"[dim]{msg}[/dim]")`
- Session output: Rich `Syntax` highlighting or `Markdown` render

### D3: Bash Security -- shlex, no shell=True

**Problem:** `subprocess.run(command, shell=True)` is an injection risk.

**Decision:** Use `shlex.split()` + list-form `subprocess.run(args)`. No `shell=True`. If shell features (pipes, redirects) are needed, a separate `bash_shell` tool with documented risks.

```python
def run_bash(command: str, timeout: int = 120) -> str:
    args = shlex.split(command)
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
    )
```

### D4: Edit Tool -- Exact String Replacement

New `edit` tool: find exact `old_string` in file, replace with `new_string`. Fails if 0 or >1 matches. More reliable than line numbers (which shift during edits).

```python
def run_edit(path: str, old_string: str, new_string: str) -> str:
    content = Path(path).read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        return "Error: string not found"
    if count > 1:
        return f"Error: found {count} occurrences, must be exactly 1"
    snapshot(path)  # save before modifying
    content = content.replace(old_string, new_string)
    Path(path).write_text(content, encoding="utf-8")
    return f"edited: {path}"
```

### D5: Persistent Snapshots (.snapshots/)

**Problem:** Snapshots are in-memory (`_SNAPSHOTS` dict), lost on restart.

**Decision:** `tools/snapshot.py` -- shared module for persistent snapshots in `.snapshots/` directory. Max depth 5 per file. Used by Write, Edit, and Revert tools.

```
.snapshots/
├── a1b2c3d4.json
├── e5f6g7h8.json
```

Each snapshot file:
```json
{
  "original_path": "/home/user/project/file.py",
  "timestamp": "2026-05-12T20:00:00",
  "snapshot_id": "a1b2c3d4",
  "previous_snapshot_id": null,
  "content": "..."
}
```

### D6: Agent Definition Folder (agents/)

New `agents/` directory. Each subdirectory has an `agent.yaml` file:

```yaml
# agents/code-review/agent.yaml
name: code-review
description: "Performs thorough code review on patches"
model: claude-sonnet-4-20250514
allowed_tools:
  - read
  - grep
  - glob
  - bash
  - write
system: |
  You are a code review specialist. Review the provided code for:
  - Correctness
  - Security vulnerabilities
  - Performance issues
```

The `agents/main/agent.yaml` defines the primary agent. `agent/prompt.py` gets a `_layer_agents()` that lists available agents (excluding `main`). The `spawn_agent` tool looks up agent by name, loads its system prompt and allowed tools, and spawns an isolated loop with only those tools available.

### D7: Memory System (memory/ folder)

Each memory is a markdown file with YAML frontmatter stored in `memory/`.

**Tools:**
- `remember(key, value)`: Save/update memory. Stored as `memory/<slug>.md`.
- `forget(key)`: Delete a memory.
- `list_memories()`: List all active memories.

**Injection:** Every turn, `agent/prompt.py` adds a `_layer_memories()` that loads and concatenates `memory/` contents into the system prompt. The agent sees memories without needing to call a tool.

**Size limit:** If total memory chars exceed 2000, truncate with "(+ N more memories)" note.

### D8: Accounting -- Token Tracking + Cost

**New modules:**
- `agent/accounting.py`: `SessionAccounting` class with per-turn recording and session summary
- `agent/costs.py`: Per-model pricing table mapping model IDs to per-token costs

**Integration:** `stream_loop` captures `response.usage` after each API call, records via `SessionAccounting`, emits via EventBus. Session-end summary printed via Rich panel. New `:accounting` REPL command shows current session stats.

### D9: WebSearch -- DuckDuckGo with Swappable Backend

`tools/web_search.py` with abstract backend interface. Default: DuckDuckGo (free, no API key). Swappable to Brave or Tavily via config (future). Returns structured results (title, URL, snippet).

```python
class SearchBackend(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...

class DuckDuckGoBackend(SearchBackend): ...
```

## 6. File-by-File Change Breakdown

### New Files

| File | Purpose |
|---|---|
| `cli/__init__.py` | Package init |
| `cli/app.py` | Bootstrap: client creation, tool registration, session setup, main loop pass-through |
| `cli/repl.py` | REPL loop with `prompt_toolkit`, input history, command dispatch |
| `cli/commands.py` | `:sessions`, `:resume`, `:fork`, `:title`, `:save`, `:tools`, `:accounting` handlers |
| `cli/render.py` | Rich `Console` singleton, style constants, helper functions |
| `agent/__init__.py` | Package init |
| `agent/types.py` | `AgentContext` dataclass, `TurnCost` dataclass |
| `agent/accounting.py` | `SessionAccounting` class, turn recording, session summary |
| `agent/costs.py` | Per-model token cost lookup table |
| `tools/__init__.py` | Package init |
| `tools/snapshot.py` | Persistent snapshot save/restore/list on disk |
| `tools/web_search.py` | DuckDuckGo backend with `SearchBackend` abstract base, Brave/Tavily stubs |
| `tools/ask_user.py` | Blocking question via `input()`, returns answer text |
| `tools/memory_tools.py` | `remember`, `forget`, `list_memories` tool implementations |
| `agents/main/agent.yaml` | Primary agent definition (name, tools, system prompt) |
| `memory/.gitkeep` | Placeholder for memory directory |

### Modified Files

| File | Changes |
|---|---|
| `main.py` | Rewrite to 3-line entry point |
| `agent/loop.py` | Accept `AgentContext`; use `render.console`; return accounting data |
| `agent/prompt.py` | Add `_layer_memories()` and `_layer_agents()`; read from `agents/` and `memory/` |
| `agent/context.py` | Use `render.console` instead of `print()` |
| `agent/session.py` | Use `render.console` instead of `print()` |
| `tools/bash.py` | Rewrite: `shlex.split()` + `shell=False` |
| `tools/file_ops.py` | Add `edit` tool; move `_SNAPSHOTS` to `tools/snapshot.py`; `grep` uses ripgrep |
| `tools/subagent.py` | Rewrite: read `agents/<name>/agent.yaml`, load system prompt + allowed tools, filter registry |
| `config/settings.py` | Remove module-level `client` and `MODEL`; export pure functions |
| `mcp/client.py` | Use `render.console` instead of `print()` |

### Unchanged Files

| File | Reason |
|---|---|
| `agent/events.py` | Already stable and correct |
| `tools/registry.py` | Already stable and correct |
| `tools/skill.py` | Already stable and correct |
| `tools/ledger.py` | Already stable and correct |
| `config/permissions.yaml` | Already stable and correct |

## 7. Error Handling Strategy

| Layer | Strategy |
|---|---|
| CLI | `try/except` wrapping whole REPL loop; catch `KeyboardInterrupt`, `EOFError`, `Exception`; print with Rich error style; continue |
| Agent Engine | `stream_loop` has `try/except` around API call; API errors propagate to CLI for retry or abort |
| Tools | Each tool handles its own exceptions and returns error strings (does not throw); `dispatch_tools` catches `Exception` as safety net |
| Snapshots | Written with restrictive permissions; read errors degrade gracefully (no snapshot = no undo) |
| Accounting | Degrades gracefully if token counts unavailable from API |

**Key principle:** Tools never throw -- they always return strings. The loop catches unexpected exceptions and logs them rather than crashing.

## 8. Testing Strategy

| Level | What | Tools |
|---|---|---|
| Unit / Tools | Each tool in isolation, mocked filesystem and HTTP | `pytest` + `tmp_path` fixture |
| Unit / Registry | Register, dispatch, merge, edge cases (duplicate names) | `pytest` |
| Unit / Session | Save, load, serialize, deserialize | `pytest` + `tmp_path` |
| Unit / Memory | Save, load, forget, injection size limit | `pytest` + `tmp_path` |
| Unit / Accounting | Token counting, cost calculation, rounding | `pytest` |
| Unit / Snapshot | Save, restore, multi-level undo, cleanup | `pytest` + `tmp_path` |
| Unit / Prompt | Each layer produces expected output, memory injection, agent catalog | `pytest` |
| Integration / Loop | Tool dispatch with mocked API responses | `pytest` + `unittest.mock` |
| Integration / Sub-agent | Agent definition loading, tool filtering, prompt construction | `pytest` + `tmp_path` |
| E2E | Full REPL to output (smoke test only) | Manual or `pytest` with subprocess |

## 9. Backward Compatibility

- Old session JSON files in `.sessions/*.json` remain loadable. The content block structure is unchanged.
- No migration script needed. Old files work with new code.
- **Breaking change:** `from config.settings import client, MODEL` breaks. These imports must be updated to receive client/model via `AgentContext`.

## 10. Out of Scope

The following are explicitly excluded from this refactor:

1. **Background tasks** (s08 pattern) -- all tools remain synchronous
2. **Multi-agent teams / mailboxes** (s09+ patterns) -- sub-agent spawning is supported, but orchestration layers are future work
3. **Redis or database persistence** -- JSON files suffice for a single-user CLI tool
4. **Web UI** -- this is a CLI refactor, not an API server
5. **MCP server implementation** -- MCP client is already well-structured; extending it is separate work

## 11. Implementation Order

Recommended implementation sequence (each step produces a working state):

1. **Foundation**: Create `cli/render.py`, `agent/types.py`; update `config/settings.py` to remove globals; update all files to use injected `AgentContext` and `render.console`
2. **CLI extraction**: Create `cli/app.py`, `cli/repl.py`, `cli/commands.py`; rewrite `main.py` to 3 lines
3. **Tool upgrades**: `bash.py` (shlex), `file_ops.py` (edit, grep ripgrep), `snapshot.py` (persistent)
4. **New tools**: `web_search.py`, `ask_user.py`, `memory_tools.py`
5. **Agent folder**: `agents/main/agent.yaml`; rewrite `subagent.py` for folder-based definitions; update `prompt.py` with agent catalog layer
6. **Memory system**: `memory/` directory; `prompt.py` memory injection layer
7. **Accounting**: `accounting.py`, `costs.py`; integrate into `loop.py` and EventBus; add `:accounting` command
