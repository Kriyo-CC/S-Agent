#!/usr/bin/env python3
"""Tests for concurrent tool dispatch and error handling.

Tests the full error-handling matrix:
  - Input validation errors
  - Permission denials (pre-execution)
  - System hook blocks (pre-execution)
  - Unknown tools (pre-execution)
  - Tool execution exceptions (in-flight, error-isolated)
  - Tool timeouts (in-flight, error-isolated)
  - User cancellation (propagates to all siblings)
  - Resource conflict serialization
  - Result ordering preservation
  - Mixed sync/async handler dispatch

All async operations use asyncio.run() for portability (no pytest-asyncio required).
"""

import asyncio
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.registry import ToolRegistry
from tools.errors import (
    ToolError,
    ToolTimeoutError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolBlockedError,
    ToolInputValidationError,
    is_transient,
    error_to_result,
)
from agent.events import EventBus
from agent.loop import (
    dispatch_tools,
    _execute_single_tool,
    _extract_input_summary,
    _classify_tool_block,
    _detect_write_conflicts,
    DEFAULT_TOOL_TIMEOUT,
)

# ── Helper: run async function synchronously ───────────────


def run(async_func):
    """Run an async function via asyncio.run()."""
    return asyncio.run(async_func)


# ── Fake ToolUse block ─────────────────────────────────────


class FakeToolUse:
    """Minimal fake for an Anthropic API ToolUseBlock."""

    def __init__(self, name: str, input: dict, id: str = None):
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id or f"fake-{name}"


def fake_text_block(text: str = "hello"):
    """Create a fake text content block."""
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


# ═══════════════════════════════════════════════════════════════
# Error hierarchy tests
# ═══════════════════════════════════════════════════════════════


class TestErrorHierarchy:
    """Test the ToolError exception hierarchy."""

    def test_base_error(self):
        err = ToolError("generic")
        assert str(err) == "generic"
        assert isinstance(err, Exception)

    def test_timeout_error(self):
        err = ToolTimeoutError("bash timed out")
        assert isinstance(err, ToolError)

    def test_execution_error_wraps_original(self):
        orig = ValueError("bad value")
        err = ToolExecutionError("bash", orig)
        assert err.tool_name == "bash"
        assert err.original is orig
        assert "ValueError" in str(err)
        assert "bad value" in str(err)

    def test_not_found_error(self):
        err = ToolNotFoundError("no_such_tool")
        assert isinstance(err, ToolError)

    def test_permission_denied_error(self):
        err = ToolPermissionDeniedError("blocked by policy")
        assert isinstance(err, ToolError)

    def test_blocked_error(self):
        err = ToolBlockedError("hook blocked")
        assert isinstance(err, ToolError)

    def test_input_validation_error(self):
        err = ToolInputValidationError("expected dict")
        assert isinstance(err, ToolError)


class TestTransientCheck:
    """Test is_transient helper for retry decisions."""

    def test_timeout_is_transient(self):
        assert is_transient(ToolTimeoutError("timeout"))

    def test_connection_error_wrapped(self):
        err = ToolExecutionError("mcp_tool", ConnectionError("refused"))
        assert is_transient(err)

    def test_value_error_not_transient(self):
        err = ToolExecutionError("bash", ValueError("bad"))
        assert not is_transient(err)

    def test_direct_timeout_error(self):
        assert is_transient(TimeoutError("timed out"))


class TestErrorToResult:
    """Test error_to_result conversion."""

    def test_timeout_error_format(self):
        result = error_to_result("tid-1", ToolTimeoutError("bash timed out after 120s"))
        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "tid-1"
        assert "timed out" in result["content"].lower()

    def test_permission_error_format(self):
        result = error_to_result("tid-2", ToolPermissionDeniedError("rm not allowed"))
        assert "Permission Policy" in result["content"]

    def test_blocked_error_format(self):
        result = error_to_result("tid-3", ToolBlockedError("hook"))
        assert "system hook" in result["content"].lower()

    def test_not_found_error_format(self):
        result = error_to_result("tid-4", ToolNotFoundError("ghost"))
        assert "Unknown tool" in result["content"]

    def test_input_validation_error_format(self):
        result = error_to_result("tid-5", ToolInputValidationError("not a dict"))
        assert "Invalid input" in result["content"]

    def test_generic_error_format(self):
        result = error_to_result("tid-6", RuntimeError("something broke"))
        assert "something broke" in result["content"]

    def test_with_traceback(self):
        result = error_to_result("tid-7", ToolTimeoutError("timeout"), include_traceback=True)
        assert "Error" in result["content"]


# ═══════════════════════════════════════════════════════════════
# Helpers tests
# ═══════════════════════════════════════════════════════════════


class TestExtractInputSummary:
    """Test _extract_input_summary helper."""

    def test_extracts_command_key(self):
        summary = _extract_input_summary({"command": "ls -la", "verbose": True}, "bash")
        assert summary == "ls -la"

    def test_extracts_path_key(self):
        summary = _extract_input_summary({"path": "/tmp/foo.txt", "content": "x"}, "write")
        assert summary == "/tmp/foo.txt"

    def test_falls_back_to_first_value(self):
        summary = _extract_input_summary({"foo": "bar"}, "unknown_tool")
        # Input has no priority key, so falls back to first iter value
        assert summary == "bar"

    def test_falls_back_to_tool_name_on_empty(self):
        summary = _extract_input_summary({}, "empty_tool")
        assert summary == "empty_tool"


# ═══════════════════════════════════════════════════════════════
# Classification tests
# ═══════════════════════════════════════════════════════════════


class TestClassifyToolBlock:
    """Test _classify_tool_block pre-flight checks."""

    def test_unknown_tool(self):
        registry = ToolRegistry()
        block = FakeToolUse("nonexistent", {"x": 1})
        status, msg, handler = _classify_tool_block(
            block, registry, bus=None, rules=None,
            use_permissions=False, mcp_executor=None,
        )
        assert status == "unknown"
        assert isinstance(msg, ToolNotFoundError)
        assert "Unknown" in str(msg)

    def test_invalid_input_type(self):
        registry = ToolRegistry()
        block = MagicMock()
        block.type = "tool_use"
        block.name = "bash"
        block.input = "not_a_dict"  # string instead of dict
        block.id = "tid-1"
        status, msg, handler = _classify_tool_block(
            block, registry, bus=None, rules=None,
            use_permissions=False, mcp_executor=None,
        )
        assert status == "invalid_input"
        assert isinstance(msg, ToolInputValidationError)
        assert "str" in str(msg)

    def test_none_input_is_ok(self):
        """None input is converted to {} and treated as valid (empty dict)."""
        registry = ToolRegistry()
        registry.register("test", "desc", {"type": "object", "properties": {}}, lambda inp: "ok")
        block = MagicMock()
        block.type = "tool_use"
        block.name = "test"
        block.input = None
        block.id = "tid-2"
        status, msg, handler = _classify_tool_block(
            block, registry, bus=None, rules=None,
            use_permissions=False, mcp_executor=None,
        )
        assert status == "executable"

    def test_hook_blocked(self):
        registry = ToolRegistry()
        registry.register("test", "desc", {"type": "object", "properties": {}}, lambda inp: "ok")
        bus = EventBus()
        bus.on("pre_tool_use", lambda event, **payload: {"block": True})
        block = FakeToolUse("test", {})
        status, msg, handler = _classify_tool_block(
            block, registry, bus=bus, rules=None,
            use_permissions=False, mcp_executor=None,
        )
        assert status == "blocked"

    def test_valid_tool(self):
        registry = ToolRegistry()
        handler = lambda inp: "ok"
        registry.register("test", "desc", {"type": "object", "properties": {}}, handler)
        block = FakeToolUse("test", {"key": "val"})
        status, msg, h = _classify_tool_block(
            block, registry, bus=None, rules=None,
            use_permissions=False, mcp_executor=None,
        )
        assert status == "executable"
        assert h is handler

    def test_mcp_tool_no_handler_but_executor(self):
        """MCP tools may not have a local handler but the executor handles them."""
        registry = ToolRegistry()
        block = FakeToolUse("mcp__server__tool", {"arg": 1})
        status, msg, handler = _classify_tool_block(
            block, registry, bus=None, rules=None,
            use_permissions=False, mcp_executor=lambda n, i: "mcp result",
        )
        assert status == "executable"
        assert handler is None  # No local handler, executor handles it


# ═══════════════════════════════════════════════════════════════
# Write conflict detection tests
# ═══════════════════════════════════════════════════════════════


class TestDetectWriteConflicts:
    """Test _detect_write_conflicts resource conflict detection."""

    def test_no_conflicts(self):
        specs = [
            (0, FakeToolUse("read", {"path": "/tmp/a.txt"}), None, "executable", None),
            (1, FakeToolUse("write", {"path": "/tmp/b.txt", "content": "x"}), None, "executable", None),
            (2, FakeToolUse("edit", {"path": "/tmp/c.txt", "old_string": "a", "new_string": "b"}), None, "executable", None),
        ]
        conflicts = _detect_write_conflicts(specs)
        assert conflicts == set()

    def test_write_conflict_same_path(self):
        specs = [
            (0, FakeToolUse("write", {"path": "/tmp/same.txt", "content": "a"}), None, "executable", None),
            (1, FakeToolUse("write", {"path": "/tmp/same.txt", "content": "b"}), None, "executable", None),
        ]
        conflicts = _detect_write_conflicts(specs)
        assert "/tmp/same.txt" in conflicts

    def test_write_edit_conflict_same_path(self):
        specs = [
            (0, FakeToolUse("write", {"path": "/tmp/x.txt", "content": "a"}), None, "executable", None),
            (1, FakeToolUse("edit", {"path": "/tmp/x.txt", "old_string": "a", "new_string": "b"}), None, "executable", None),
        ]
        conflicts = _detect_write_conflicts(specs)
        assert "/tmp/x.txt" in conflicts

    def test_read_not_a_conflict(self):
        """Read operations on the same file are NOT conflicts."""
        specs = [
            (0, FakeToolUse("read", {"path": "/tmp/y.txt"}), None, "executable", None),
            (1, FakeToolUse("read", {"path": "/tmp/y.txt"}), None, "executable", None),
        ]
        conflicts = _detect_write_conflicts(specs)
        assert conflicts == set()

    def test_no_path_key_no_conflict(self):
        """Tools without a 'path' key can't be tracked for conflicts."""
        specs = [
            (0, FakeToolUse("write", {"content": "a"}), None, "executable", None),
            (1, FakeToolUse("write", {"content": "b"}), None, "executable", None),
        ]
        conflicts = _detect_write_conflicts(specs)
        assert conflicts == set()


# ═══════════════════════════════════════════════════════════════
# Single tool execution tests
# ═══════════════════════════════════════════════════════════════


class TestExecuteSingleTool:
    """Test _execute_single_tool atomic execution."""

    def test_sync_handler(self):
        """Sync handler runs in thread pool and returns result."""
        result = run(_execute_single_tool(
            tool_name="test",
            tool_input={"x": 1},
            tool_use_id="tid-1",
            handler=lambda inp: f"got {inp['x']}",
        ))
        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "tid-1"
        assert "got 1" in result["content"]

    def test_async_handler(self):
        """Async handler is awaited directly."""
        async def async_handler(inp):
            await asyncio.sleep(0.01)
            return f"async got {inp['x']}"

        result = run(_execute_single_tool(
            tool_name="test_async",
            tool_input={"x": 42},
            tool_use_id="tid-async",
            handler=async_handler,
        ))
        assert result["tool_use_id"] == "tid-async"
        assert "async got 42" in result["content"]

    def test_handler_raises_exception(self):
        """Handler exception is caught and converted to error string."""
        def broken(inp):
            raise ValueError("intentional failure")

        result = run(_execute_single_tool(
            tool_name="broken",
            tool_input={},
            tool_use_id="tid-err",
            handler=broken,
        ))
        assert result["type"] == "tool_result"
        assert "Error" in result["content"]
        assert "intentional failure" in result["content"]

    def test_no_handler(self):
        """Missing handler returns descriptive error."""
        result = run(_execute_single_tool(
            tool_name="missing",
            tool_input={},
            tool_use_id="tid-missing",
            handler=None,
        ))
        assert "Error" in result["content"]
        assert "No handler" in result["content"]

    def test_mcp_executor_path(self):
        """MCP executor is used when tool name starts with mcp__."""
        async def mcp_exec(name, inp):
            return f"mcp: {name} -> {inp}"

        result = run(_execute_single_tool(
            tool_name="mcp__server__action",
            tool_input={"key": "val"},
            tool_use_id="tid-mcp",
            handler=None,  # MCP tools often have no local handler
            mcp_executor=mcp_exec,
        ))
        assert "mcp:" in result["content"]
        assert "server__action" in result["content"]

    def test_mcp_fallback_when_no_executor(self):
        """MCP-prefixed tool without executor falls through to handler."""
        result = run(_execute_single_tool(
            tool_name="mcp__stale__tool",
            tool_input={},
            tool_use_id="tid-mcp2",
            handler=lambda inp: "local fallback",
            mcp_executor=None,
        ))
        assert "local fallback" in result["content"]

    def test_post_tool_event_emitted(self):
        """Bus receives post_tool_use event after execution."""
        bus = EventBus()
        events = []

        def track(event, **payload):
            events.append((event, payload.get("output")))

        bus.on("post_tool_use", track)

        result = run(_execute_single_tool(
            tool_name="test",
            tool_input={"x": 1},
            tool_use_id="tid-event",
            handler=lambda inp: "success",
            bus=bus,
        ))
        assert len(events) == 1
        assert events[0][0] == "post_tool_use"
        assert "success" in events[0][1]

    def test_event_bus_error_does_not_affect_result(self):
        """If event emission crashes, the tool result is still returned."""
        bus = EventBus()

        def broken_hook(event, **payload):
            raise RuntimeError("hook crash")

        bus.on("post_tool_use", broken_hook)

        # Should not raise
        result = run(_execute_single_tool(
            tool_name="test",
            tool_input={},
            tool_use_id="tid-bushook",
            handler=lambda inp: "still works",
            bus=bus,
        ))
        assert "still works" in result["content"]

    def test_timeout_returns_error(self):
        """Timeout is caught and converted to error string."""
        async def slow(inp):
            await asyncio.sleep(10.0)  # never completes under timeout
            return "never"

        result = run(_execute_single_tool(
            tool_name="slow_tool",
            tool_input={},
            tool_use_id="tid-slow",
            handler=slow,
            timeout=0.05,  # very short timeout for test
        ))
        assert "Error" in result["content"]
        assert "timed out" in result["content"].lower()


# ═══════════════════════════════════════════════════════════════
# Concurrent dispatch tests
# ═══════════════════════════════════════════════════════════════


class TestDispatchToolsBasic:
    """Test basic dispatch_tools functionality."""

    def test_empty_response(self):
        """No tool_use blocks -> empty result list."""
        registry = ToolRegistry()
        results = run(dispatch_tools(
            [fake_text_block("hello")], registry, use_permissions=False
        ))
        assert results == []

    def test_single_tool(self):
        """Single tool_use block executes correctly."""
        registry = ToolRegistry()
        registry.register(
            "echo", "echoes input",
            {"type": "object", "properties": {"msg": {"type": "string"}}},
            lambda inp: f"echo: {inp.get('msg', '')}",
        )
        block = FakeToolUse("echo", {"msg": "hello world"}, id="tid-1")
        results = run(dispatch_tools([block], registry, use_permissions=False))
        assert len(results) == 1
        assert results[0]["tool_use_id"] == "tid-1"
        assert "echo: hello world" in results[0]["content"]

    def test_multiple_independent_tools(self):
        """Multiple independent tools execute (at least all complete)."""
        registry = ToolRegistry()
        execution_order = []

        def make_handler(name):
            def handler(inp):
                execution_order.append(name)
                return f"{name} done"
            return handler

        registry.register("tool_a", "a", {"type": "object", "properties": {}}, make_handler("a"))
        registry.register("tool_b", "b", {"type": "object", "properties": {}}, make_handler("b"))
        registry.register("tool_c", "c", {"type": "object", "properties": {}}, make_handler("c"))

        blocks = [
            FakeToolUse("tool_a", {}, id="a"),
            FakeToolUse("tool_b", {}, id="b"),
            FakeToolUse("tool_c", {}, id="c"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 3
        # All should have completed
        assert set(execution_order) == {"a", "b", "c"}

    def test_result_ordering_preserved(self):
        """Results must map back to the original tool_use block order."""
        registry = ToolRegistry()

        async def slow_handler(inp):
            await asyncio.sleep(0.1)
            return "slow"

        registry.register("fast", "fast", {"type": "object", "properties": {}}, lambda inp: "fast")
        registry.register("slow", "slow", {"type": "object", "properties": {}}, slow_handler)
        registry.register("fast2", "fast2", {"type": "object", "properties": {}}, lambda inp: "fast2")

        blocks = [
            FakeToolUse("slow", {}, id="id-slow"),
            FakeToolUse("fast", {}, id="id-fast"),
            FakeToolUse("fast2", {}, id="id-fast2"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        # Results must be in original order: slow, fast, fast2
        assert [r["tool_use_id"] for r in results] == ["id-slow", "id-fast", "id-fast2"]


class TestDispatchToolsErrors:
    """Test error handling in concurrent dispatch."""

    def test_unknown_tool_returns_error(self):
        """Unknown tool returns error result, does not crash dispatcher."""
        registry = ToolRegistry()
        block = FakeToolUse("ghost_tool", {}, id="tid-ghost")
        results = run(dispatch_tools([block], registry, use_permissions=False))
        assert len(results) == 1
        assert "Error" in results[0]["content"]

    def test_invalid_input_type_returns_error(self):
        """Non-dict input returns error before any execution."""
        registry = ToolRegistry()
        block = MagicMock()
        block.type = "tool_use"
        block.name = "read"
        block.input = ["not", "a", "dict"]
        block.id = "tid-badinput"
        results = run(dispatch_tools([block], registry, use_permissions=False))
        assert len(results) == 1
        assert "Error" in results[0]["content"]
        assert "list" in results[0]["content"]

    def test_error_isolation_one_failure_others_succeed(self):
        """When one tool crashes, sibling tools still complete successfully."""
        registry = ToolRegistry()

        def broken(inp):
            raise RuntimeError("boom!")

        registry.register("broken", "breaks", {"type": "object", "properties": {}}, broken)
        registry.register("ok_a", "ok a", {"type": "object", "properties": {}}, lambda inp: "ok_a_result")
        registry.register("ok_b", "ok b", {"type": "object", "properties": {}}, lambda inp: "ok_b_result")

        blocks = [
            FakeToolUse("ok_a", {}, id="ok-a"),
            FakeToolUse("broken", {}, id="broken"),
            FakeToolUse("ok_b", {}, id="ok-b"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 3

        # ok_a succeeded
        assert "ok_a_result" in results[0]["content"]
        # broken failed with error isolation
        assert "Error" in results[1]["content"]
        # ok_b still succeeded (error isolation!)
        assert "ok_b_result" in results[2]["content"]

    def test_failure_path_ordering_preserved(self):
        """When tool 0 fails and tool 1 succeeds, results keep [error, success] order."""
        registry = ToolRegistry()

        def broken(inp):
            raise RuntimeError("boom!")

        registry.register("broken", "breaks", {"type": "object", "properties": {}}, broken)
        registry.register("ok", "works", {"type": "object", "properties": {}}, lambda inp: "ok_result")

        blocks = [
            FakeToolUse("broken", {}, id="fail-first"),
            FakeToolUse("ok", {}, id="success-second"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 2
        # Order must be preserved: first tool's result first (even though it failed)
        assert results[0]["tool_use_id"] == "fail-first"
        assert "Error" in results[0]["content"]
        assert results[1]["tool_use_id"] == "success-second"
        assert "ok_result" in results[1]["content"]

    def test_mixed_error_and_success(self):
        """Mix of valid, unknown, and blocked tools."""
        registry = ToolRegistry()
        registry.register("valid", "works", {"type": "object", "properties": {}}, lambda inp: "works")

        bus = EventBus()
        bus.on("pre_tool_use", lambda event, **payload: (
            {"block": True} if payload.get("tool") == "blocked_tool" else None
        ))

        blocks = [
            FakeToolUse("valid", {}, id="v"),
            FakeToolUse("unknown", {}, id="u"),
            FakeToolUse("blocked_tool", {}, id="b"),
        ]
        results = run(dispatch_tools(blocks, registry, bus=bus, use_permissions=False))
        assert len(results) == 3
        assert "works" in results[0]["content"]       # success
        assert "Error" in results[1]["content"]       # unknown
        assert "Error" in results[2]["content"]       # blocked


class TestDispatchToolsResourceConflicts:
    """Test resource conflict serialization in concurrent dispatch."""

    def test_write_conflict_serializes(self):
        """Two writes to the same file complete (with conflict handling)."""
        registry = ToolRegistry()
        write_order = []
        target_path = f"/tmp/concurrent_test_{os.getpid()}.txt"

        def make_write_handler(label):
            def handler(inp):
                write_order.append(label)
                assert inp.get("path") == target_path
                return f"{label} wrote to {inp.get('path', '?')}"
            return handler

        registry.register("write", "write file",
            {"type": "object",
             "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
             "required": ["path", "content"]},
            make_write_handler("write"))

        blocks = [
            FakeToolUse("write", {"path": target_path, "content": "first"}, id="w1"),
            FakeToolUse("write", {"path": target_path, "content": "second"}, id="w2"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 2
        # Both completed
        assert "wrote" in results[0]["content"]
        assert "wrote" in results[1]["content"]
        # Results preserved order: w1 then w2
        assert results[0]["tool_use_id"] == "w1"
        assert results[1]["tool_use_id"] == "w2"

    def test_read_no_conflict(self):
        """Multiple reads of the same file are not serialized."""
        registry = ToolRegistry()
        registry.register("read", "read file",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            lambda inp: f"read {inp['path']}")

        blocks = [
            FakeToolUse("read", {"path": "/tmp/same.txt"}, id="r1"),
            FakeToolUse("read", {"path": "/tmp/same.txt"}, id="r2"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 2
        assert "read" in results[0]["content"]
        assert "read" in results[1]["content"]


# ═══════════════════════════════════════════════════════════════
# Registry metadata tests
# ═══════════════════════════════════════════════════════════════


class TestRegistryMetadata:
    """Test ToolRegistry metadata support."""

    def test_default_metadata_empty(self):
        registry = ToolRegistry()
        assert registry.get_metadata("nonexistent") == {}

    def test_register_with_metadata(self):
        registry = ToolRegistry()
        registry.register(
            "test", "desc", {"type": "object", "properties": {}},
            lambda inp: "ok",
            metadata={"timeout": 60.0, "writes_files": True},
        )
        assert registry.get_metadata("test") == {"timeout": 60.0, "writes_files": True}

    def test_get_timeout_with_override(self):
        registry = ToolRegistry()
        registry.register(
            "slow_tool", "desc", {"type": "object", "properties": {}},
            lambda inp: "ok",
            metadata={"timeout": 600.0},
        )
        assert registry.get_timeout("slow_tool") == 600.0
        assert registry.get_timeout("slow_tool", default=300.0) == 600.0

    def test_get_timeout_default(self):
        registry = ToolRegistry()
        registry.register("fast_tool", "desc", {"type": "object", "properties": {}}, lambda inp: "ok")
        assert registry.get_timeout("fast_tool", default=300.0) == 300.0

    def test_reset_clears_all(self):
        registry = ToolRegistry()
        registry.register("t1", "d", {"type": "object", "properties": {}}, lambda i: "ok", metadata={"k": "v"})
        assert len(registry) == 1
        registry.reset()
        assert len(registry) == 0
        assert registry.get_metadata("t1") == {}

    def test_merge_includes_metadata(self):
        r1 = ToolRegistry()
        r1.register("t1", "d1", {"type": "object", "properties": {}}, lambda i: "1", metadata={"timeout": 10})
        r2 = ToolRegistry()
        r2.register("t2", "d2", {"type": "object", "properties": {}}, lambda i: "2", metadata={"timeout": 20})
        r1.merge(r2)
        assert "t1" in r1 and "t2" in r1
        assert r1.get_timeout("t1") == 10
        assert r1.get_timeout("t2") == 20


# ═══════════════════════════════════════════════════════════════
# Integration: dispatch_tools with real file ops
# ═══════════════════════════════════════════════════════════════


class TestIntegrationFileOps:
    """Integration tests using real file operations."""

    def test_concurrent_reads(self):
        """Multiple concurrent reads of different files."""
        from tools.file_ops import register_file_tools

        registry = ToolRegistry()
        register_file_tools(registry)

        # Create temp files
        f1 = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f1.write("content one")
        f1.close()

        f2 = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        f2.write("content two")
        f2.close()

        try:
            blocks = [
                FakeToolUse("read", {"path": f1.name}, id="r1"),
                FakeToolUse("read", {"path": f2.name}, id="r2"),
            ]
            results = run(dispatch_tools(blocks, registry, use_permissions=False))
            assert len(results) == 2
            assert "content one" in results[0]["content"]
            assert "content two" in results[1]["content"]
        finally:
            os.unlink(f1.name)
            os.unlink(f2.name)

    def test_concurrent_grep_and_glob(self):
        """Concurrent search operations on the project."""
        from tools.file_ops import register_file_tools

        registry = ToolRegistry()
        register_file_tools(registry)

        blocks = [
            FakeToolUse("grep", {"pattern": "def dispatch", "path": "agent/"}, id="g1"),
            FakeToolUse("glob", {"pattern": "agent/*.py"}, id="g2"),
        ]
        results = run(dispatch_tools(blocks, registry, use_permissions=False))
        assert len(results) == 2
        # glob should find files
        assert "loop.py" in results[1]["content"]
        # grep should find dispatch_tools
        assert "dispatch_tools" in results[0]["content"]


# ═══════════════════════════════════════════════════════════════
# Cancellation test
# ═══════════════════════════════════════════════════════════════


class TestCancellation:
    """Test that CancelledError propagates correctly."""

    def test_cancellation_propagates_from_single_tool(self):
        """CancelledError from _execute_single_tool propagates, not caught."""
        async def cancelled_handler(inp):
            raise asyncio.CancelledError("interrupted")

        with pytest.raises(asyncio.CancelledError):
            run(_execute_single_tool(
                tool_name="cancelled",
                tool_input={},
                tool_use_id="tid-cancel",
                handler=cancelled_handler,
            ))


# ═══════════════════════════════════════════════════════════════
# Run main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
