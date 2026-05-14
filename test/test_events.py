#!/usr/bin/env python3
"""验证整个事件系统：注册 → emit → handler 全链路。

每一项测试打印 [PASS] 或 [FAIL]，最后统计结果。
"""

# ── 1. EventBus 基础 ─────────────────────────────────────

import asyncio
from agent.events import EventBus

bus = EventBus()
results = []


def record(event: str, **payload):
    """测试用 handler：记录收到的事件。"""
    results.append((event, payload))


bus.on("test_event", record)

bus.emit("test_event", foo="bar")
assert len(results) == 1, f"Expected 1 call, got {len(results)}"
assert results[0] == ("test_event", {"foo": "bar"}), f"Unexpected: {results[0]}"
results.clear()
print("[PASS] EventBus register + emit")


def fails(event: str, **payload):
    raise RuntimeError("intentional")
    return 42


bus.on("bad_handler", fails)
bus.emit("bad_handler")  # should NOT crash, just print error
print("[PASS] EventBus handler exception is caught, no crash")


bus.remove("test_event", record)
bus.emit("test_event")
assert len(results) == 0, f"Expected 0 calls after remove, got {len(results)}"
results.clear()
print("[PASS] EventBus remove handler")


def blocker(event: str, **payload):
    return {"block": True}


bus.on("pre_tool_use", blocker)
pre_results = bus.emit("pre_tool_use", tool="bash", input={"command": "rm -rf /"})
is_blocked = any(r.get("block") for r in pre_results if isinstance(r, dict))
assert is_blocked, "Expected block signal"
print("[PASS] EventBus block signal (pre_tool_use interception)")
bus.remove("pre_tool_use", blocker)


# ── 2. Tool dispatch events (pre/post_tool_use) ──────────

from tools.registry import ToolRegistry
from tools.bash import register_bash_tool
from tools.file_ops import register_file_tools
from tools.skill import register_skill_tools
from agent.loop import dispatch_tools

registry = ToolRegistry()
register_bash_tool(registry)
register_file_tools(registry)
register_skill_tools(registry)

dispatch_bus = EventBus()
pre_log = []
post_log = []


def pre_hook(event: str, **payload):
    pre_log.append(payload["tool"])


def post_hook(event: str, **payload):
    post_log.append((payload["tool"], str(payload.get("output", ""))[:50]))


dispatch_bus.on("pre_tool_use", pre_hook)
dispatch_bus.on("post_tool_use", post_hook)

# 构造一个假的 tool_use API 返回块
class FakeToolUse:
    type = "tool_use"
    name = "list_skills"
    input = {}
    id = "fake-1"


results = asyncio.run(dispatch_tools([FakeToolUse], registry, dispatch_bus, use_permissions=False))

assert len(pre_log) == 1 and pre_log[0] == "list_skills"
assert len(post_log) == 1 and post_log[0][0] == "list_skills"
assert len(results) == 1
assert results[0]["type"] == "tool_result"
print("[PASS] dispatch_tools emits pre_tool_use + post_tool_use")

# ── 4. Revert tool ───────────────────────────────────────

import tempfile, os

tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt")
tmp.write("original content")
tmp.close()

# write 触发快照
from tools.file_ops import run_write, run_revert

out = run_write(tmp.name, "new content")
assert out.startswith("updated:"), f"Unexpected write output: {out}"
out = run_revert(tmp.name)
assert "reverted" in out, f"Unexpected revert output: {out}"
with open(tmp.name) as f:
    assert f.read() == "original content", "Revert should restore original"
os.unlink(tmp.name)
print("[PASS] file_ops write + revert snapshot")

# ── 5. Skill discovery + load ────────────────────────────

from tools.skill import discover_skills, run_list_skills, run_load_skill

skills = discover_skills()
assert len(skills) >= 1, f"Expected at least 1 skill, got {len(skills)}"
assert "code-review" in skills

output = run_list_skills()
assert "code-review" in output

content = run_load_skill("code-review")
assert "SKILL" in content
assert "END SKILL" in content

print("[PASS] skill discovery + list + load")

# ── 6. Skill path traversal protection ───────────────────

assert "invalid" in run_load_skill("../../etc/passwd")
assert "invalid" in run_load_skill("foo/bar")
print("[PASS] skill path traversal blocked")

# ── 7. Stats hook (simulated session) ────────────────────

from collections import defaultdict

counts = defaultdict(int)


def stats_hook(event: str, **payload):
    if event == "session_start":
        counts.clear()
    elif event == "post_tool_use":
        counts[payload.get("tool", "?")] += 1
    elif event == "session_end":
        pass  # just check counts


stats_bus = EventBus()
stats_bus.on("session_start", stats_hook)
stats_bus.on("post_tool_use", stats_hook)
stats_bus.on("session_end", stats_hook)

stats_bus.emit("session_start")
assert len(counts) == 0

# Simulate a few tool calls
for i, tool in enumerate(["read", "write", "read", "bash"]):
    stats_bus.emit("post_tool_use", tool=tool, output=f"result {i}")

assert counts["read"] == 2
assert counts["write"] == 1
assert counts["bash"] == 1

stats_bus.emit("session_end")
print(f"[PASS] stats hook: {dict(counts)}")

# ── 8. ToolRegistry.get_handlers() returns copy of handlers ──────

reg2 = ToolRegistry()

# empty registry
assert reg2.get_handlers() == {}, f"Expected empty dict, got {reg2.get_handlers()}"

# after registration
def dummy():
    pass

reg2.register("test_tool", "A test tool", {"type": "object", "properties": {}}, dummy)
handlers = reg2.get_handlers()
assert "test_tool" in handlers
assert handlers["test_tool"] is dummy

# verify it's a copy (mutating returned dict does not affect registry)
handlers["injected"] = "bad"
assert "injected" not in reg2._handlers, "get_handlers() must return a copy"

print("[PASS] ToolRegistry.get_handlers() returns a copy of _handlers")

# ── Summary ──────────────────────────────────────────────

print("\n" + "=" * 50)
print("All tests passed. Event system is working correctly.")
print("=" * 50)
