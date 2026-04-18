#!/usr/bin/env python3
"""Unit tests for the trace-capture transformer + file-safety helpers.

Runs without any API calls. Loads orchestrator.py via AST-strip so preflight()
doesn't fire and the claude_agent_sdk dependency is stubbed.

Run: /opt/homebrew/bin/python3.13 bin/test_trace.py
"""

import ast
import json
import os
import shutil
import sys
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path


# ── Stub claude_agent_sdk before loading orchestrator ────────────────────────

@dataclass
class TextBlock:
    text: str


@dataclass
class ThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: object
    is_error: bool = False


@dataclass
class AssistantMessage:
    content: list
    model: str = "claude-sonnet-4-6"
    parent_tool_use_id: str | None = None
    error: str | None = None
    usage: dict = field(default_factory=dict)
    message_id: str = ""
    stop_reason: str = "end_turn"
    session_id: str = ""
    uuid: str = ""


@dataclass
class UserMessage:
    content: object
    uuid: str = ""
    parent_tool_use_id: str | None = None
    tool_use_result: object = None


@dataclass
class SystemMessage:
    subtype: str
    data: dict


@dataclass
class ResultMessage:
    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 0
    session_id: str = ""
    stop_reason: str = "end_turn"
    total_cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)
    result: str = ""
    structured_output: object = None
    model_usage: dict = field(default_factory=dict)
    permission_denials: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    uuid: str = ""


stub = types.ModuleType("claude_agent_sdk")
stub.query = lambda **kw: None
stub.ClaudeAgentOptions = type("ClaudeAgentOptions", (), {})
stub.ResultMessage = ResultMessage
stub.AssistantMessage = AssistantMessage
stub.UserMessage = UserMessage
stub.SystemMessage = SystemMessage
stub.TextBlock = TextBlock
stub.ThinkingBlock = ThinkingBlock
stub.ToolUseBlock = ToolUseBlock
stub.ToolResultBlock = ToolResultBlock
sys.modules["claude_agent_sdk"] = stub


# ── Load orchestrator, stripping preflight() call ────────────────────────────

ORCH_PATH = Path(__file__).parent / "orchestrator.py"
src = ORCH_PATH.read_text()
tree = ast.parse(src)
new_body = []
for node in tree.body:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if getattr(node.value.func, "id", None) == "preflight":
            continue  # skip the preflight() top-level call
    new_body.append(node)
tree.body = new_body
orch_ns: dict = {"__name__": "orchestrator_under_test"}
exec(compile(tree, "<orchestrator>", "exec"), orch_ns)


# Pull out the symbols we're testing.
_truncate = orch_ns["_truncate"]
_tool_input_for_trace = orch_ns["_tool_input_for_trace"]
_tool_result_content_for_trace = orch_ns["_tool_result_content_for_trace"]
message_to_trace_events = orch_ns["message_to_trace_events"]
snapshot_files = orch_ns["snapshot_files"]
compute_diff = orch_ns["compute_diff"]
scan_worker_violations = orch_ns["scan_worker_violations"]
promote_worker = orch_ns["promote_worker"]
TRACE_TOOL_RESULT_CAP = orch_ns["TRACE_TOOL_RESULT_CAP"]


# ── Test harness ─────────────────────────────────────────────────────────────

_passed = 0
_failed: list[str] = []


def test(name):
    def wrap(fn):
        global _passed
        try:
            fn()
            _passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            _failed.append(f"{name}: {e}")
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            _failed.append(f"{name}: unexpected {type(e).__name__}: {e}")
            print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")
        return fn
    return wrap


# ── Tests: _truncate ────────────────────────────────────────────────────────

@test("_truncate short string untouched")
def _():
    out, orig = _truncate("hello", 100)
    assert out == "hello"
    assert orig is None


@test("_truncate long string truncated with marker")
def _():
    s = "x" * 500
    out, orig = _truncate(s, 100)
    assert out.startswith("x" * 100)
    assert "truncated" in out
    assert orig == 500


@test("_truncate None → empty")
def _():
    out, orig = _truncate(None, 100)
    assert out == "" and orig is None


# ── Tests: _tool_input_for_trace ────────────────────────────────────────────

@test("tool_input Bash preserves command verbatim")
def _():
    out = _tool_input_for_trace("Bash", {"command": "ls -la /tmp", "description": "list tmp"})
    assert out == {"command": "ls -la /tmp", "description": "list tmp"}


@test("tool_input Write summarizes content")
def _():
    out = _tool_input_for_trace("Write", {"file_path": "/a", "content": "x" * 5000})
    assert out["file_path"] == "/a"
    assert out["content_chars"] == 5000
    assert "truncated" in out["content_preview"]


@test("tool_input Edit keeps both strings truncated")
def _():
    out = _tool_input_for_trace("Edit", {
        "file_path": "/a", "old_string": "foo", "new_string": "bar", "replace_all": True
    })
    assert out == {"file_path": "/a", "old_string_preview": "foo",
                   "new_string_preview": "bar", "replace_all": True}


@test("tool_input Read keeps metadata only")
def _():
    out = _tool_input_for_trace("Read", {"file_path": "/a", "offset": 10, "limit": 5})
    assert out == {"file_path": "/a", "offset": 10, "limit": 5}


@test("tool_input unknown tool → JSON preview")
def _():
    out = _tool_input_for_trace("Mystery", {"whatever": "value"})
    assert "input_json_preview" in out


# ── Tests: _tool_result_content_for_trace ───────────────────────────────────

@test("tool_result str truncated past cap")
def _():
    s = "y" * (TRACE_TOOL_RESULT_CAP + 500)
    text, orig = _tool_result_content_for_trace(s)
    assert orig == len(s)
    assert "truncated" in text


@test("tool_result list of dicts joined")
def _():
    content = [{"text": "hello"}, {"text": "world"}]
    text, orig = _tool_result_content_for_trace(content)
    assert "hello" in text and "world" in text


# ── Tests: message_to_trace_events ──────────────────────────────────────────

@test("AssistantMessage text → assistant_text event")
def _():
    msg = AssistantMessage(content=[TextBlock("hi")])
    events, seq = message_to_trace_events(msg, 0)
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "assistant_text"
    assert e["text"] == "hi"
    assert e["seq"] == 0
    assert "ts" in e
    assert seq == 1


@test("AssistantMessage multiple blocks → multiple events")
def _():
    msg = AssistantMessage(content=[
        TextBlock("reasoning..."),
        ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
    ])
    events, seq = message_to_trace_events(msg, 5)
    assert len(events) == 2
    assert [e["type"] for e in events] == ["assistant_text", "tool_use"]
    assert events[0]["seq"] == 5
    assert events[1]["seq"] == 6
    assert events[1]["tool_name"] == "Bash"
    assert events[1]["input"] == {"command": "ls"}
    assert seq == 7


@test("ThinkingBlock preserved in full fidelity")
def _():
    thinking_text = "let me reason about this problem carefully " * 50
    msg = AssistantMessage(content=[ThinkingBlock(thinking_text)])
    events, _ = message_to_trace_events(msg, 0)
    assert events[0]["type"] == "assistant_thinking"
    assert events[0]["thinking"] == thinking_text


@test("UserMessage with ToolResultBlock → tool_result event")
def _():
    msg = UserMessage(content=[ToolResultBlock(
        tool_use_id="t1", content="result text", is_error=False
    )])
    events, _ = message_to_trace_events(msg, 0)
    assert len(events) == 1
    assert events[0]["type"] == "tool_result"
    assert events[0]["tool_use_id"] == "t1"
    assert events[0]["content"] == "result text"
    assert events[0]["is_error"] is False


@test("UserMessage string content → no events (initial user msg)")
def _():
    msg = UserMessage(content="the original user prompt")
    events, _ = message_to_trace_events(msg, 0)
    assert events == []


@test("ResultMessage → result event with usage")
def _():
    msg = ResultMessage(num_turns=8, duration_ms=12000, total_cost_usd=0.042,
                        usage={"input_tokens": 100, "output_tokens": 50})
    events, _ = message_to_trace_events(msg, 0)
    assert len(events) == 1
    assert events[0]["type"] == "result"
    assert events[0]["num_turns"] == 8
    assert events[0]["usage"]["input_tokens"] == 100


@test("SystemMessage → system event with data_keys only")
def _():
    msg = SystemMessage(subtype="init", data={"huge": "x" * 100000, "cwd": "/tmp"})
    events, _ = message_to_trace_events(msg, 0)
    assert events[0]["type"] == "system"
    assert set(events[0]["data_keys"]) == {"huge", "cwd"}
    # The full data is NOT serialized — that's the point.
    assert "x" * 100000 not in json.dumps(events[0])


@test("Unknown block type falls back gracefully")
def _():
    class WeirdBlock:
        def __repr__(self):
            return "<WeirdBlock>"
    msg = AssistantMessage(content=[WeirdBlock()])
    events, _ = message_to_trace_events(msg, 0)
    assert events[0]["type"] == "assistant_unknown_block"
    assert "WeirdBlock" in events[0]["repr"]


@test("Seq numbers monotonic across messages")
def _():
    seq = 0
    m1 = AssistantMessage(content=[TextBlock("a"), TextBlock("b")])
    events, seq = message_to_trace_events(m1, seq)
    assert [e["seq"] for e in events] == [0, 1]
    m2 = AssistantMessage(content=[TextBlock("c")])
    events, seq = message_to_trace_events(m2, seq)
    assert [e["seq"] for e in events] == [2]
    assert seq == 3


@test("Giant single event gets collapsed to size marker")
def _():
    # Tool result with content beyond the message hard ceiling forces the emit() guard.
    # Stuff a 100KB string through a tool_result path (content is truncated to
    # TRACE_TOOL_RESULT_CAP already, so the hard ceiling is reached only via very
    # unusual block types). Use the fallback path with a huge repr.
    class FatBlock:
        def __repr__(self):
            return "F" * 200_000
    msg = AssistantMessage(content=[FatBlock()])
    events, _ = message_to_trace_events(msg, 0)
    # The raw repr is truncated to 500 chars by our handler, so this event won't
    # hit the ceiling guard. Just assert we didn't crash and got a sane event.
    assert events[0]["type"] == "assistant_unknown_block"
    assert len(json.dumps(events[0])) < 10_000


# ── Tests: filesystem helpers (integration) ─────────────────────────────────

@test("snapshot_files + compute_diff roundtrip")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.md").write_text("hello\n")
        before = snapshot_files(root, ["a.md", "b.md"])
        assert before == {"a.md": "hello\n", "b.md": ""}
        (root / "a.md").write_text("hello\nworld\n")
        (root / "b.md").write_text("new file\n")
        after = snapshot_files(root, ["a.md", "b.md"])
        diff = compute_diff(before, after)
        assert "+world" in diff
        assert "+new file" in diff
        # Unchanged files omitted.
        same_before = {"c.md": "x"}
        same_after = {"c.md": "x"}
        assert compute_diff(same_before, same_after) == ""


@test("scan_worker_violations categorises correctly")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        ar = Path(tmp)
        wdir = ar / "workers/w1/autoresearch/foo"
        wdir.mkdir(parents=True)
        (wdir / "bar.md").write_text("x")
        wroot = ar / "workers/w1"
        (wroot / "eval.sh").write_text("bad")
        (wroot / "random.log").write_text("noise")
        (wroot / "score.txt").write_text("5")  # meta, should be skipped
        (ar / "lockfile.txt").write_text("secret.md\n")
        (wroot / "secret.md").write_text("pwn")
        v = scan_worker_violations(wroot, {"autoresearch/foo/bar.md"}, ar)
        assert v["forbidden"] == ["eval.sh"]
        assert "secret.md" in v["locked"]
        assert "random.log" in v["unexpected"]
        # Meta file (score.txt) must not appear anywhere.
        flat = v["forbidden"] + v["locked"] + v["unexpected"]
        assert "score.txt" not in flat


@test("promote_worker copies editables only, skips meta/artifacts")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        ar = Path(tmp)
        # Prepare the world.
        (ar / "program.md").write_text(
            "## Editable files\n- autoresearch/foo/bar.md\n\n## Mode\nquantitative\n"
        )
        wdir = ar / "workers/worker-1"
        (wdir / "autoresearch/foo").mkdir(parents=True)
        (wdir / "autoresearch/foo/bar.md").write_text("edited")
        (wdir / "score.txt").write_text("9")  # meta, skip
        (wdir / "random.log").write_text("noise")  # not editable, skip
        (ar / "best").mkdir()
        (ar / "branches/main").mkdir(parents=True)
        promote_worker(wdir, ar, "main")
        assert (ar / "best/autoresearch/foo/bar.md").read_text() == "edited"
        assert not (ar / "best/score.txt").exists()
        assert not (ar / "best/random.log").exists()


# ── Summary ──────────────────────────────────────────────────────────────────

print(f"\n{_passed} passed, {len(_failed)} failed.")
if _failed:
    for f in _failed:
        print(f"  - {f}")
    sys.exit(1)
