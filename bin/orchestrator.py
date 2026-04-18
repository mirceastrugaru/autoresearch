#!/usr/bin/env python3
"""Autoresearch orchestrator — Claude Agent SDK with parallel workers and prompt caching."""

import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Preflight checks ────────────────────────────────────────────────────────

def preflight():
    """Check all requirements before doing anything."""
    errors = []

    # Python version
    if sys.version_info < (3, 10):
        errors.append(
            f"Python 3.10+ required (you have {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"  Install: brew install python@3.13\n"
            f"  Then run: python3.13 {sys.argv[0]}"
        )

    # claude-agent-sdk
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        errors.append(
            "claude-agent-sdk not installed.\n"
            "  Install: pip install claude-agent-sdk"
        )

    # No API key needed — everything runs through Claude Code via the Agent SDK.

    # Prompt templates
    prompts_dir = Path(__file__).parent.parent / "prompts"
    for name in ("supportive.md", "adversarial.md", "merge.md"):
        if not (prompts_dir / name).exists():
            errors.append(f"Missing prompt template: {prompts_dir / name}")

    # Project config — skip detailed checks here, main() handles initiative discovery

    if errors:
        print("PREFLIGHT FAILED:\n")
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}\n")
        sys.exit(1)


if __name__ == "__main__" or "orchestrator" in sys.argv[0]:
    preflight()

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from bin.program_parser import (
    parse_editable_files,
    read_eval_mode,
    read_parallelism,
    read_direction,
    read_strategy,
    validate_rubric,
    parse_roadmap,
    build_coverage_matrix,
    build_stance_coverage,
    sync_directions_from_roadmap,
    read_or,
    read_state,
    write_state,
    read_full_log,
)

# ── Constants ────────────────────────────────────────────────────────────────

MODEL = os.environ.get("AUTORESEARCH_MODEL", "claude-haiku-4-5-20251001")
SUMMARIZE_EVERY = 5
DISCARD_STREAK_WARN = 3
DISCARD_STREAK_PIVOT = 5
PLATEAU_THRESHOLD = 8
REVALIDATE_EVERY = 10
NOISE_THRESHOLD = 0.01
WORKER_TIMEOUT_SEC = int(os.environ.get("AUTORESEARCH_WORKER_TIMEOUT", "900"))  # 15 min default
MERGE_TIMEOUT_SEC = int(os.environ.get("AUTORESEARCH_MERGE_TIMEOUT", "300"))  # 5 min default
RUNAWAY_TURN_THRESHOLD = int(os.environ.get("AUTORESEARCH_RUNAWAY_TURNS", "15"))
LOG_BLOAT_THRESHOLD_BYTES = int(os.environ.get("AUTORESEARCH_LOG_BLOAT_BYTES", "51200"))  # 50KB
TRACE_TOOL_RESULT_CAP = 4000
TRACE_MESSAGE_HARD_CEILING = 50_000


# ── Trace serialization ─────────────────────────────────────────────────────


def _truncate(s: str, cap: int) -> tuple[str, int | None]:
    """Returns (possibly-truncated, original_chars_if_truncated_else_None)."""
    if s is None:
        return "", None
    if len(s) <= cap:
        return s, None
    return s[:cap] + f"...[truncated, {len(s) - cap} more chars]", len(s)


def _tool_input_for_trace(name: str, inp: dict) -> dict:
    """Preserve tool call intent, keep size bounded. Bash commands verbatim
    (high signal, small). Write/Edit/Read file_path verbatim; content summary only."""
    if not isinstance(inp, dict):
        return {"raw": _truncate(str(inp), TRACE_TOOL_RESULT_CAP)[0]}
    name_l = (name or "").lower()
    if name_l == "bash":
        return {k: inp.get(k) for k in ("command", "description", "timeout", "run_in_background") if k in inp}
    if name_l in ("write",):
        content = inp.get("content", "")
        return {
            "file_path": inp.get("file_path"),
            "content_chars": len(content) if isinstance(content, str) else None,
            "content_preview": _truncate(content if isinstance(content, str) else "", 2000)[0],
        }
    if name_l in ("edit", "notebookedit"):
        return {
            "file_path": inp.get("file_path"),
            "old_string_preview": _truncate(inp.get("old_string", ""), 1000)[0],
            "new_string_preview": _truncate(inp.get("new_string", ""), 1000)[0],
            "replace_all": inp.get("replace_all"),
        }
    if name_l == "read":
        return {k: inp.get(k) for k in ("file_path", "offset", "limit", "pages") if k in inp}
    # Default: JSON-dump and truncate.
    try:
        dump = json.dumps(inp, default=str)
    except Exception:
        dump = str(inp)
    trunc, orig = _truncate(dump, TRACE_TOOL_RESULT_CAP)
    out = {"input_json_preview": trunc}
    if orig is not None:
        out["input_orig_chars"] = orig
    return out


def _tool_result_content_for_trace(content) -> tuple[str, int | None]:
    """Serialize tool result content (may be str or list of dicts/blocks) and truncate."""
    if isinstance(content, str):
        return _truncate(content, TRACE_TOOL_RESULT_CAP)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or json.dumps(item, default=str))
            else:
                parts.append(str(item))
        return _truncate("\n".join(parts), TRACE_TOOL_RESULT_CAP)
    return _truncate(str(content), TRACE_TOOL_RESULT_CAP)


def message_to_trace_events(msg, seq_start: int) -> tuple[list[dict], int]:
    """Convert one SDK message to a list of trace events. Returns (events, next_seq).
    Each event is a small JSON-serializable dict. One message can produce multiple
    events (e.g. an AssistantMessage with 3 content blocks -> 3 events).
    """
    events: list[dict] = []
    seq = seq_start
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def emit(ev: dict):
        nonlocal seq
        ev["ts"] = ts
        ev["seq"] = seq
        # Final size safety
        try:
            size = len(json.dumps(ev, default=str))
        except Exception:
            size = 0
        if size > TRACE_MESSAGE_HARD_CEILING:
            ev = {"ts": ts, "seq": seq, "type": ev.get("type", "unknown"),
                  "truncated_giant_event": True, "orig_size": size}
        events.append(ev)
        seq += 1

    if isinstance(msg, AssistantMessage):
        for block in (msg.content or []):
            if isinstance(block, TextBlock):
                emit({"type": "assistant_text", "text": block.text,
                      "model": getattr(msg, "model", None),
                      "stop_reason": getattr(msg, "stop_reason", None)})
            elif isinstance(block, ThinkingBlock):
                emit({"type": "assistant_thinking", "thinking": block.thinking})
            elif isinstance(block, ToolUseBlock):
                emit({"type": "tool_use",
                      "tool_id": block.id,
                      "tool_name": block.name,
                      "input": _tool_input_for_trace(block.name, block.input)})
            else:
                emit({"type": "assistant_unknown_block", "repr": _truncate(repr(block), 500)[0]})
    elif isinstance(msg, UserMessage):
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, ToolResultBlock):
                    text, orig = _tool_result_content_for_trace(block.content)
                    ev = {"type": "tool_result",
                          "tool_use_id": block.tool_use_id,
                          "is_error": block.is_error,
                          "content": text}
                    if orig is not None:
                        ev["content_orig_chars"] = orig
                    emit(ev)
                else:
                    emit({"type": "user_unknown_block", "repr": _truncate(repr(block), 500)[0]})
        else:
            # initial user message (string) — skip, it's the user_prompt we already logged
            pass
    elif isinstance(msg, SystemMessage):
        # System messages carry init data etc. — keys only, data often huge.
        data = getattr(msg, "data", None)
        emit({"type": "system",
              "subtype": getattr(msg, "subtype", None),
              "data_keys": list(data.keys()) if isinstance(data, dict) else None})
    elif isinstance(msg, ResultMessage):
        emit({"type": "result",
              "subtype": msg.subtype,
              "num_turns": msg.num_turns,
              "duration_ms": msg.duration_ms,
              "total_cost_usd": msg.total_cost_usd,
              "usage": msg.usage,
              "is_error": msg.is_error,
              "stop_reason": msg.stop_reason})
    else:
        emit({"type": "unknown", "repr": _truncate(repr(msg), 500)[0]})

    return events, seq

# ── Agent runner ─────────────────────────────────────────────────────────────


async def run_agent(
    system_prompt: str,
    user_prompt: str,
    cwd: str | Path,
    name: str = "agent",
    trace_path: Path | None = None,
) -> tuple[str, ResultMessage | None]:
    """Run an agent to completion. Returns (result_text, result_message).

    If trace_path is provided, every SDK message is streamed as JSONL trace
    events to that file. Trace survives mid-run crashes/timeouts — events
    reach disk as they arrive.
    """
    result_msg = None
    trace_fp = None
    seq = 0
    if trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_fp = open(trace_path, "w", buffering=1)  # line-buffered
        # Header event so you can tell which agent this is
        header = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "seq": seq,
            "type": "meta_header",
            "agent_name": name,
            "cwd": str(cwd),
            "model": MODEL,
            "system_prompt_chars": len(system_prompt),
            "user_prompt_chars": len(user_prompt),
        }
        trace_fp.write(json.dumps(header, default=str) + "\n")
        seq += 1

    try:
        async for msg in query(
            prompt=user_prompt,
            options=ClaudeAgentOptions(
                model=MODEL,
                system_prompt=system_prompt,
                permission_mode="bypassPermissions",
                cwd=str(cwd),
                extra_args={"no-session-persistence": None},
            ),
        ):
            if trace_fp is not None:
                try:
                    events, seq = message_to_trace_events(msg, seq)
                    for ev in events:
                        trace_fp.write(json.dumps(ev, default=str) + "\n")
                except Exception as trace_err:
                    # Never let trace-serialization errors kill a worker.
                    trace_fp.write(json.dumps({
                        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "seq": seq,
                        "type": "trace_error",
                        "error": str(trace_err)[:500],
                    }) + "\n")
                    seq += 1
            if isinstance(msg, ResultMessage):
                result_msg = msg
    except Exception as e:
        print(f"    [{name}] ERROR: {e}")
        if trace_fp is not None:
            trace_fp.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "seq": seq,
                "type": "run_error",
                "error": str(e)[:2000],
            }) + "\n")
            trace_fp.close()
        return f"Agent error: {e}", None
    finally:
        if trace_fp is not None and not trace_fp.closed:
            trace_fp.close()

    result_text = result_msg.result if result_msg and result_msg.result else ""
    cost = result_msg.total_cost_usd if result_msg else 0
    duration = result_msg.duration_ms if result_msg else 0
    turns = result_msg.num_turns if result_msg else 0
    usage = result_msg.usage or {}
    input_tok = usage.get("input_tokens", 0)
    output_tok = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    runaway_marker = " [RUNAWAY]" if turns > RUNAWAY_TURN_THRESHOLD else ""
    print(f"    [{name}] done ({duration}ms, ${cost:.4f}, {turns} turns{runaway_marker}, "
          f"in={input_tok} out={output_tok} cache_read={cache_read} cache_create={cache_create})")
    return result_text, result_msg


# ── Program.md parsing (imported from program_parser.py) ───────────────────


def assign_directions(directions: list[dict], parallelism: int, matrix: dict[str, int]) -> list[dict]:
    """Assign directions to workers. First half supportive, second half adversarial.
    Returns list of {"direction": dict, "stance": "supportive"|"adversarial"} for each worker slot.
    Priority (roadmap position) is the primary signal — the judge ordered the roadmap
    by impact, so we respect that. Coverage is the tiebreaker within the same priority."""
    if not directions:
        return []

    half = parallelism // 2
    sorted_dirs = sorted(directions, key=lambda d: (d["priority"], matrix.get(d["id"], 0)))

    assignments = []
    for i in range(half):
        d = sorted_dirs[i % len(sorted_dirs)]
        assignments.append({"direction": d, "stance": "supportive"})

    for i in range(half):
        d = sorted_dirs[i % len(sorted_dirs)]
        assignments.append({"direction": d, "stance": "adversarial"})

    return assignments


# read_strategy, read_or, read_full_log, read_state, write_state — imported from program_parser


def append_log(ar_dir: Path, entry: dict):
    entry["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(ar_dir / "log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def append_branch(ar_dir: Path, entry: dict):
    with open(ar_dir / "branches.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def dlog(ar_dir: Path, section: str, **fields):
    """Append a debug log entry to debug.log. Survives worker cleanup."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "section": section,
        **fields,
    }
    with open(ar_dir / "debug.log", "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Filesystem-based worker inspection ─────────────────────────────────────

# Orchestrator-managed metadata files workers legitimately write.
WORKER_META_FILES = {
    "experiment_id_output.txt",
    "score.txt", "hypothesis.txt",
    "diff.txt", "parent.txt", "summary.txt", "eval_scores.json",
    "writeup.md", "roadmap_append.md",
}
WORKER_META_PREFIXES = ("artifact",)

# Files no worker may ever produce/modify — orchestrator-owned state.
FORBIDDEN_BASENAMES = {
    "eval.sh", "lockfile.txt", "program.md", "best_score.txt",
    "state.json", "log.jsonl", "branches.jsonl",
}


def _is_meta_file(rel_name: str) -> bool:
    return rel_name in WORKER_META_FILES or any(rel_name.startswith(p) for p in WORKER_META_PREFIXES)


def snapshot_files(root: Path, rel_paths: list[str]) -> dict[str, str]:
    """Read rel_paths (relative to root) into a {rel_path: content} dict.
    Missing files map to empty string."""
    out = {}
    for rel in rel_paths:
        p = root / rel
        out[rel] = p.read_text() if p.exists() else ""
    return out


def compute_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Unified diff across known editable files. Source of truth — authoritative."""
    parts = []
    for rel in sorted(set(before) | set(after)):
        a = before.get(rel, "").splitlines(keepends=True)
        b = after.get(rel, "").splitlines(keepends=True)
        if a == b:
            continue
        parts.append("".join(difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}")))
    return "".join(parts)


def scan_worker_violations(wdir: Path, editable: set[str], ar_dir: Path) -> dict:
    """Walk the worker dir. Detect:
      - edits to forbidden basenames (eval.sh, program.md, etc.)
      - edits to locked paths (from lockfile.txt)
      - any new non-meta, non-editable files the worker created
    Returns {"forbidden": [...], "locked": [...], "unexpected": [...]}.
    """
    locked: list[str] = []
    lf = ar_dir / "lockfile.txt"
    if lf.exists():
        locked = [l.strip() for l in lf.read_text().splitlines() if l.strip()]

    forbidden_hits: list[str] = []
    locked_hits: list[str] = []
    unexpected: list[str] = []

    for p in wdir.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(wdir))
        name = p.name
        if _is_meta_file(name):
            continue
        if name in FORBIDDEN_BASENAMES:
            forbidden_hits.append(rel)
            continue
        for l in locked:
            if rel == l or rel.endswith("/" + l) or name == l:
                locked_hits.append(rel)
                break
        else:
            if rel not in editable:
                unexpected.append(rel)

    return {"forbidden": forbidden_hits, "locked": locked_hits, "unexpected": unexpected}


def passed_hard_gates(wdir: Path, worker_score: float) -> bool:
    """In collaborative mode: did this worker pass hard gates?
    Reads eval_scores.json if present. Falls back to score > 0."""
    eval_scores_path = wdir / "eval_scores.json"
    if eval_scores_path.exists():
        try:
            data = json.loads(eval_scores_path.read_text())
            return not data.get("hard_gate_failed", True)
        except (json.JSONDecodeError, OSError):
            pass
    return worker_score > 0


def check_noise(new_score: float, best_score: float, direction: str = "maximize") -> bool:
    if best_score == 0:
        return new_score != 0
    delta = (new_score - best_score) / abs(best_score)
    if direction == "minimize":
        return delta < -NOISE_THRESHOLD
    return delta > NOISE_THRESHOLD


# ── Worker management ────────────────────────────────────────────────────────


def prepare_workers(ar_dir: Path, active_branch: str, parallelism: int):
    """Set up worker dirs with editable files at their correct project-relative paths.

    Editable files are listed in program.md as project-relative paths (e.g.
    autoresearch/timsort-explainer/explanation.md). eval.sh receives the worker
    dir as $1 and reads files at worker_dir/editable_file_path. So files must
    live at that exact relative path inside each worker dir.
    """
    workers = ar_dir / "workers"
    if workers.exists():
        shutil.rmtree(workers)
    branch_dir = ar_dir / "branches" / active_branch
    editable_files = parse_editable_files(ar_dir)
    for i in range(1, parallelism + 1):
        wdir = workers / f"worker-{i}"
        wdir.mkdir(parents=True)
        if branch_dir.exists():
            for rel_path in editable_files:
                src = branch_dir / rel_path
                if src.exists():
                    dest = wdir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)


def promote_worker(wdir: Path, ar_dir: Path, active_branch: str):
    """Copy editable files from worker to best/ and branch/. Only editable files —
    this prevents worker-created artifacts (logs, tmp files) from polluting best/."""
    editable = parse_editable_files(ar_dir)
    for rel in editable:
        src = wdir / rel
        if not src.exists():
            continue
        for dest_base in [ar_dir / "best", ar_dir / "branches" / active_branch]:
            dest = dest_base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def collect_roadmap_proposals(ar_dir: Path, parallelism: int) -> str:
    """Collect roadmap_append.md from all worker dirs. Returns combined text."""
    proposals = []
    for i in range(1, parallelism + 1):
        wfile = ar_dir / "workers" / f"worker-{i}" / "roadmap_append.md"
        if wfile.exists():
            text = wfile.read_text().strip()
            if text:
                proposals.append(f"--- Worker {i} ---\n{text}")
    return "\n\n".join(proposals) if proposals else ""


def cleanup_workers(ar_dir: Path):
    w = ar_dir / "workers"
    if w.exists():
        shutil.rmtree(w)


# ── Convergence ──────────────────────────────────────────────────────────────


def force_pivot(state: dict, ar_dir: Path, project_dir: Path):
    new_branch = f"pivot-{state['experiment_count']}"
    print(f"\n=== FORCED PIVOT: '{new_branch}' from baseline ===")
    dlog(ar_dir, "forced_pivot", new_branch=new_branch,
         discard_streak=state["discard_streak"],
         best_score=state["best_score"],
         experiment_count=state["experiment_count"])

    branch_dir = ar_dir / "branches" / new_branch
    branch_dir.mkdir(parents=True, exist_ok=True)

    # Copy from best/ (the actual baseline, works for both existing-code and from-scratch projects)
    best_dir = ar_dir / "best"
    if best_dir.exists():
        for src in best_dir.rglob("*"):
            if src.is_file():
                dest = branch_dir / src.relative_to(best_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    append_branch(ar_dir, {
        "branch": new_branch, "forked_from": "baseline", "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "experiments": 0, "best_score": 0,
        "notes": f"pivot after {state['discard_streak']} discards",
    })

    state["active_branch"] = new_branch
    state["discard_streak"] = 0
    state["best_unchanged_count"] = 0
    state["last_pivot_experiment"] = state["experiment_count"]


def revalidate_best(ar_dir: Path, state: dict):
    print(f"\n--- REVALIDATION (experiment {state['experiment_count']}) ---")
    best_dir = ar_dir / "best"
    try:
        r = subprocess.run(
            ["bash", str(ar_dir / "eval.sh"), str(best_dir)],
            capture_output=True, text=True, timeout=120,
        )
        reval_score = float(r.stdout.strip())
    except Exception as e:
        print(f"  Revalidation failed: {e}")
        return

    best = state["best_score"]
    drift = abs(best - reval_score) / best if best != 0 else 0
    print(f"  Revalidation: {reval_score} (recorded: {best}, drift: {drift:.4f})")
    if drift > 0.02:
        print("  WARNING: drift > 2%")


# ── Shared context builder (for prompt caching) ──────────────────────────────


def _build_shared_context(ar_dir: Path, skill_text: str, is_qualitative: bool = False) -> str:
    """Build a system prompt with shared context pre-loaded for cache efficiency.

    All workers of the same stance in a round receive identical system prompt content,
    so the second worker gets cache hits on the shared context.
    Only worker-specific content (exp ID, worker dir, assigned direction) stays in the user prompt.

    For qualitative mode, workers produce write-ups only — they don't need to see the full
    main document in detail, but they need enough to know what exists. Include the document
    so workers can reference and argue about its content.
    """
    program = read_or(ar_dir / "program.md", "")
    findings = read_or(ar_dir / "findings.md", "")
    full_log = read_full_log(ar_dir)
    roadmap = read_or(ar_dir / "roadmap.md", "")
    meta = read_or(ar_dir / "meta.md", "")

    best_dir = ar_dir / "best"
    editable_files = parse_editable_files(ar_dir)
    best_docs = []
    for f in editable_files:
        p = best_dir / f
        if p.exists():
            best_docs.append(f"=== CURRENT MAIN DOCUMENT: {f} ===\n{p.read_text()}")
    best_content = "\n\n".join(best_docs) if best_docs else "[no document yet]"

    parts = [
        f"{skill_text}\n\n",
        f"---\n\n",
        f"## SHARED CONTEXT (pre-loaded for all workers this round)\n\n",
        f"### program.md\n{program}\n\n",
        f"### findings.md\n{findings}\n\n",
        f"### log.jsonl (full history)\n{full_log}\n\n",
        f"### roadmap.md\n{roadmap}\n\n",
        f"### Current main document\n{best_content}",
    ]
    if meta:
        parts.append(f"\n\n### meta.md (research process tracking)\n{meta}")

    return "".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────────


async def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="orchestrator.py",
        description="Autoresearch orchestrator — runs parallel experiment agents.",
    )
    parser.add_argument("rounds", nargs="?", type=int, default=10,
                        help="Number of experiment rounds (default: 10)")
    parser.add_argument("project_dir", nargs="?", default=None,
                        help="Path to project with autoresearch/ config (default: cwd)")
    parser.add_argument("initiative", nargs="?", default=None,
                        help="Initiative name under autoresearch/ (default: auto-detect)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Override parallelism from program.md")
    parser.add_argument("--max-cost", type=float, default=None,
                        help="Stop when total API cost exceeds this amount (USD)")
    args = parser.parse_args()

    max_rounds = args.rounds
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    initiative_name = args.initiative
    workers_override = args.workers
    max_cost = args.max_cost

    # Find or select the initiative
    ar_base = project_dir / "autoresearch"
    if initiative_name:
        ar_dir = ar_base / initiative_name
    else:
        # Auto-detect: find initiatives with program.md
        if ar_base.exists():
            initiatives = [
                d.name for d in ar_base.iterdir()
                if d.is_dir() and (d / "program.md").exists()
            ]
        else:
            initiatives = []

        if len(initiatives) == 1:
            initiative_name = initiatives[0]
            ar_dir = ar_base / initiative_name
        elif len(initiatives) > 1:
            print(f"Multiple initiatives found in {ar_base}:")
            for name in sorted(initiatives):
                score = read_or(ar_base / name / "best_score.txt", "no score").strip()
                print(f"  {name}  (best: {score})")
            print(f"\nSpecify one: orchestrator.py {max_rounds} {project_dir} <name>")
            sys.exit(1)
        else:
            # Check for legacy flat autoresearch/ layout (program.md directly in autoresearch/)
            if ar_base.exists() and (ar_base / "program.md").exists():
                print(f"Found legacy autoresearch/ layout (no named initiative).")
                print(f"Migrate by moving files into autoresearch/<name>/")
                ar_dir = ar_base  # backward compat
                initiative_name = "default"
            else:
                print(f"No initiatives found in {ar_base}/")
                print(f"Run /autoresearch:design in Claude Code first.")
                sys.exit(1)

    # Load skill texts
    prompts_dir = Path(__file__).parent.parent / "prompts"
    supportive_skill = (prompts_dir / "supportive.md").read_text()
    adversarial_skill = (prompts_dir / "adversarial.md").read_text()
    merge_skill = (prompts_dir / "merge.md").read_text()

    print("=== AUTORESEARCH ORCHESTRATOR ===")
    print(f"Project: {project_dir}")
    print(f"Initiative: {initiative_name}")
    print(f"Model: {MODEL}")
    print(f"Max rounds: {max_rounds}")

    state_file = ar_dir / "state.json"

    # ── Phase 0: Resume or Init ──

    if state_file.exists():
        print("\nResuming...")
        state = read_state(ar_dir)
        state["eval_mode"] = read_eval_mode(ar_dir)
        state["strategy"] = read_strategy(ar_dir)
        state["parallelism"] = workers_override if workers_override else read_parallelism(ar_dir)
        state["direction"] = read_direction(ar_dir)
        print(f"  Round: {state['round']} / Experiments: {state['experiment_count']} / Best: {state['best_score']}")
        print(f"  Branch: {state['active_branch']} / Discard streak: {state['discard_streak']}")
        print(f"  Strategy: {state['strategy']} / Measurement: {state['eval_mode']}")
        if workers_override:
            print(f"  Workers overridden: {workers_override}")
    else:
        eval_mode = read_eval_mode(ar_dir)
        strategy = read_strategy(ar_dir)
        parallelism = workers_override if workers_override else read_parallelism(ar_dir)
        direction = read_direction(ar_dir)

        # Warn about unusual combinations, but allow override.
        if strategy == "collaborative" and eval_mode == "quantitative":
            print("WARNING: collaborative + quantitative is unusual — merging numeric results")
            print("  loses information. Proceeding anyway; passing-threshold defaults to score > 0.")
        if strategy == "competitive" and eval_mode == "qualitative":
            print("WARNING: competitive + qualitative may plateau quickly (score has a ceiling).")
            print("  Proceeding anyway; consider collaborative if you see repeated ties.")

        # Validate rubric structure for qualitative initiatives
        if eval_mode == "qualitative":
            validate_rubric(ar_dir)

        print(f"Strategy: {strategy} / Measurement: {eval_mode} / Parallelism: {parallelism} / Direction: {direction}")
        print("\n--- INIT ---")

        from bin.init import init_project
        output = init_project(project_dir, ar_dir, eval_mode, parallelism)
        dlog(ar_dir, "init_output", output=output)

        if not state_file.exists():
            print("INIT FAILED: state.json not created. Aborting.")
            sys.exit(1)

        state = read_state(ar_dir)
        state["direction"] = direction
        state["strategy"] = strategy
        print(f"Baseline score: {state['best_score']}")

    # ── Phase 2: Experiment loop ──

    round_num = state["round"]
    total_cost = 0.0
    while round_num < max_rounds:
        round_num += 1
        state["round"] = round_num
        parallelism = state["parallelism"]

        # Pause check
        pause_sentinel = ar_dir / "pause_requested"
        if pause_sentinel.exists():
            print(f"\n  Paused. Waiting for resume...")
            dlog(ar_dir, "paused", round=round_num)
            while pause_sentinel.exists():
                time.sleep(2)
            print(f"  Resumed.")
            dlog(ar_dir, "resumed", round=round_num)

        # Budget check
        if max_cost is not None and total_cost >= max_cost:
            print(f"\n  Budget exhausted: ${total_cost:.4f} >= max_cost ${max_cost:.2f}. Stopping.")
            dlog(ar_dir, "budget_exhausted", total_cost=total_cost, max_cost=max_cost)
            break

        print(f"\n{'=' * 50}")
        print(f"  ROUND {round_num}/{max_rounds}  (experiments: {state['experiment_count']}, best: {state['best_score']:.2f})")
        if max_cost is not None:
            print(f"  Cost so far: ${total_cost:.4f} / ${max_cost:.2f}")
        print(f"{'=' * 50}")
        dlog(ar_dir, "round_start", round=round_num, max_rounds=max_rounds,
             experiments=state["experiment_count"], best_score=state["best_score"],
             branch=state["active_branch"], discard_streak=state["discard_streak"])

        # Convergence — different logic for qualitative vs quantitative
        if is_qualitative:
            directions_for_convergence = parse_roadmap(ar_dir)
            if directions_for_convergence:
                stance_cov = build_stance_coverage(ar_dir, directions_for_convergence)
                fully_covered = sum(1 for v in stance_cov.values() if v["supportive"] and v["adversarial"])
                total_dirs = len(stance_cov)
                coverage_pct = fully_covered / total_dirs if total_dirs else 0
                no_new_dirs = state.get("rounds_without_new_directions", 0)
                print(f"  Coverage: {fully_covered}/{total_dirs} directions fully covered ({coverage_pct:.0%}), "
                      f"{no_new_dirs} rounds without new directions")
                dlog(ar_dir, "qualitative_convergence", round=round_num,
                     fully_covered=fully_covered, total_dirs=total_dirs,
                     coverage_pct=round(coverage_pct, 3),
                     rounds_without_new_directions=no_new_dirs)
                if coverage_pct >= 1.0 and no_new_dirs >= 2:
                    print(f"\n  CONVERGED: all {total_dirs} directions covered from both stances, "
                          f"no new directions for {no_new_dirs} rounds. Stopping early.")
                    dlog(ar_dir, "qualitative_converged", round=round_num,
                         fully_covered=fully_covered, total_dirs=total_dirs)
                    break
        else:
            if state["discard_streak"] >= DISCARD_STREAK_PIVOT:
                force_pivot(state, ar_dir, project_dir)
            elif state["best_unchanged_count"] >= PLATEAU_THRESHOLD:
                force_pivot(state, ar_dir, project_dir)

        if not is_qualitative and state["experiment_count"] > 0 and state["experiment_count"] % REVALIDATE_EVERY == 0:
            revalidate_best(ar_dir, state)

        # Round timing
        round_timing: dict[str, float] = {}
        t_prepare = time.time()

        # Log-bloat check (context cost grows linearly with log.jsonl).
        log_size = (ar_dir / "log.jsonl").stat().st_size if (ar_dir / "log.jsonl").exists() else 0
        if log_size > LOG_BLOAT_THRESHOLD_BYTES:
            print(f"  WARN: log.jsonl is {log_size} bytes — every worker's system prompt now includes this. "
                  f"Consider pruning or summarizing.")
            dlog(ar_dir, "log_bloat_warn", round=round_num, log_bytes=log_size,
                 threshold=LOG_BLOAT_THRESHOLD_BYTES)

        # Prepare workers
        prepare_workers(ar_dir, state["active_branch"], parallelism)
        round_timing["prepare_ms"] = int((time.time() - t_prepare) * 1000)

        # Build guardrail message if needed
        guardrail_msg = ""
        if not is_qualitative:
            # Quantitative: discard-streak guardrails
            if state["discard_streak"] >= DISCARD_STREAK_PIVOT:
                recent_log = read_full_log(ar_dir)
                recent_failures = []
                for line in recent_log.strip().splitlines()[-15:]:
                    try:
                        entry = json.loads(line)
                        if entry.get("status") == "discard":
                            h = entry.get("hypothesis", "")
                            s = entry.get("score", 0)
                            if h:
                                recent_failures.append(f"  - [{entry.get('status')}] score={s}: {h}")
                    except (json.JSONDecodeError, KeyError):
                        pass
                failures_text = "\n".join(recent_failures) if recent_failures else "  (none recorded)"
                guardrail_msg = (
                    f"\nCRITICAL: {state['discard_streak']} consecutive rounds with no improvement. Strategy pivot forced.\n"
                    f"Recent failed/thought experiments:\n{failures_text}\n\n"
                    f"You are on a new branch. You MUST:\n"
                    f"1. Identify what assumption ALL of the above failures share.\n"
                    f"2. INVERT that assumption as your hypothesis — not a minor variant.\n"
                    f"3. Check roadmap.md (provided in system prompt) for untried directions.\n"
                    f"Do NOT try anything resembling the failed experiments above."
                )
                dlog(ar_dir, "guardrail_built", round=round_num, trigger="pivot",
                     discard_streak=state["discard_streak"],
                     failures=recent_failures, guardrail_text=guardrail_msg)
            elif state["discard_streak"] >= DISCARD_STREAK_WARN:
                recent_log = read_full_log(ar_dir)
                recent_failures = []
                for line in recent_log.strip().splitlines()[-9:]:
                    try:
                        entry = json.loads(line)
                        if entry.get("status") == "discard":
                            h = entry.get("hypothesis", "")
                            if h:
                                recent_failures.append(f"  - {h}")
                    except (json.JSONDecodeError, KeyError):
                        pass
                failures_text = "\n".join(recent_failures) if recent_failures else "  (none recorded)"
                guardrail_msg = (
                    f"\nWARNING: {state['discard_streak']} consecutive rounds with no improvement.\n"
                    f"Recent failed approaches:\n{failures_text}\n"
                    f"Before your next hypothesis, identify what these share. Try inverting that assumption, "
                    f"or pick an untested direction from roadmap.md (provided in system prompt)."
                )
                dlog(ar_dir, "guardrail_built", round=round_num, trigger="warn",
                     discard_streak=state["discard_streak"],
                     failures=recent_failures, guardrail_text=guardrail_msg)

        is_collaborative = state.get("strategy", "competitive") == "collaborative"
        is_qualitative = state.get("eval_mode", "quantitative") == "qualitative"

        # Snapshot editable files per worker BEFORE launch — used for authoritative
        # diff computation and change detection after workers finish.
        editable_files_for_round = parse_editable_files(ar_dir)
        snapshots: dict[int, dict[str, str]] = {}
        for i in range(1, parallelism + 1):
            wdir = ar_dir / "workers" / f"worker-{i}"
            snapshots[i] = snapshot_files(wdir, editable_files_for_round)

        # Parse roadmap and assign directions to workers (pro/con split).
        directions = parse_roadmap(ar_dir)
        direction_assignments = []
        if directions:
            coverage = build_coverage_matrix(ar_dir, directions)
            direction_assignments = assign_directions(directions, parallelism, coverage)
            assignment_summary = [(a["direction"]["id"], a["stance"]) for a in direction_assignments]
            print(f"  Direction assignments: {assignment_summary}")
            dlog(ar_dir, "direction_assignments", round=round_num,
                 assignments=assignment_summary,
                 coverage={did: cnt for did, cnt in coverage.items()})

        # Launch parallel workers
        tasks = []
        exp_ids = []
        worker_direction_ids: list[str | None] = []
        worker_stances: list[str] = []
        for i in range(1, parallelism + 1):
            wdir = ar_dir / "workers" / f"worker-{i}"
            exp_num = state["experiment_count"] + i
            exp_id = f"exp-{round_num}-{i}-{hashlib.md5(f'{time.time()}{i}'.encode()).hexdigest()[:8]}"
            exp_ids.append(exp_id)

            parent_exp = state.get("last_promoted_experiment", 0)

            # Determine stance and assigned direction
            assigned_direction_id = None
            assigned_direction_title = ""
            stance = "supportive" if i <= parallelism // 2 else "adversarial"
            if direction_assignments and (i - 1) < len(direction_assignments):
                da = direction_assignments[i - 1]
                stance = da["stance"]
                assigned_direction_id = da["direction"]["id"]
                assigned_direction_title = da["direction"]["title"]

            worker_direction_ids.append(assigned_direction_id)
            worker_stances.append(stance)

            # Select the right prompt template for this worker's stance
            worker_skill = supportive_skill if stance == "supportive" else adversarial_skill
            worker_context = _build_shared_context(ar_dir, worker_skill, is_qualitative=is_qualitative)

            direction_directive = ""
            if assigned_direction_title:
                direction_directive = (
                    f"\n\nASSIGNED DIRECTION [{assigned_direction_id}]: {assigned_direction_title}\n"
                    f"Stance: {stance.upper()}. Focus on this direction only. Other workers are covering other directions.\n"
                    f"Tag your roadmap_append.md proposals with parent: {assigned_direction_id}"
                )

            user_msg = (
                f"Run experiment {exp_num} (ID: {exp_id}).\n"
                f"Worker {i}/{parallelism}. Stance: {stance.upper()}\n"
                f"Worker directory: {wdir}\n"
                f"Autoresearch directory: {ar_dir}\n"
                f"Eval command: bash {ar_dir}/eval.sh {wdir}\n"
                f"Active branch: {state['active_branch']}\n"
                f"Current best score: {state['best_score']}\n"
                f"Parent experiment: #{parent_exp}\n"
                f"Time budget: {WORKER_TIMEOUT_SEC}s (hard limit — orchestrator will kill after)\n"
                f"{direction_directive}"
                f"{guardrail_msg}\n\n"
                f"All context (program.md, findings.md, log, roadmap, current main document) is in your system prompt.\n"
                f"Write new direction proposals to {wdir}/roadmap_append.md.\n"
                f"CRITICAL: Write '{exp_id}' to {wdir}/experiment_id_output.txt as your LAST action."
            )

            prompt_save_dir = ar_dir / "prompts"
            prompt_save_dir.mkdir(parents=True, exist_ok=True)
            prompt_file = prompt_save_dir / f"{exp_id}.txt"
            prompt_file.write_text(user_msg)

            traces_dir = ar_dir / "traces"
            traces_dir.mkdir(parents=True, exist_ok=True)
            trace_file = traces_dir / f"{exp_id}.jsonl"

            dlog(ar_dir, "worker_launch",
                 round=round_num, worker=i, exp=exp_num, exp_id=exp_id,
                 stance=stance,
                 assigned_direction=assigned_direction_id,
                 parent_exp=parent_exp,
                 guardrail_active=bool(guardrail_msg),
                 user_msg_chars=len(user_msg),
                 prompt_file=str(prompt_file),
                 trace_file=str(trace_file))

            print(f"  Launching worker-{i} ({stance}, experiment {exp_num})...")
            tasks.append(
                asyncio.wait_for(
                    run_agent(
                        system_prompt=worker_context,
                        user_prompt=user_msg,
                        cwd=wdir,
                        name=f"worker-{i}",
                        trace_path=trace_file,
                    ),
                    timeout=WORKER_TIMEOUT_SEC,
                )
            )

        print(f"  Waiting for {parallelism} workers (timeout {WORKER_TIMEOUT_SEC}s each)...")
        t0 = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - t0
        round_timing["workers_ms"] = int(elapsed * 1000)
        print(f"  All workers done. ({elapsed:.1f}s)")

        # Track costs and token usage
        round_input_tokens = 0
        round_output_tokens = 0
        round_cache_read = 0
        round_cache_create = 0
        for r in results:
            if not isinstance(r, Exception) and r[1] is not None:
                total_cost += r[1].total_cost_usd or 0
                u = r[1].usage or {}
                round_input_tokens += u.get("input_tokens", 0)
                round_output_tokens += u.get("output_tokens", 0)
                round_cache_read += u.get("cache_read_input_tokens", 0)
                round_cache_create += u.get("cache_creation_input_tokens", 0)

        # Collect results
        best_worker = None
        best_worker_score = None
        round_had_improvement = False

        for i in range(1, parallelism + 1):
            wdir = ar_dir / "workers" / f"worker-{i}"
            exp_num = state["experiment_count"] + i

            # Agent crashed or timed out?
            if isinstance(results[i - 1], Exception):
                err = results[i - 1]
                kind = "TIMEOUT" if isinstance(err, asyncio.TimeoutError) else "CRASH"
                print(f"  worker-{i}: {kind} ({err})")
                dlog(ar_dir, f"worker_{kind.lower()}", worker=i, exp=exp_num, error=str(err))
                append_log(ar_dir, {
                    "experiment_id": exp_num, "branch": state["active_branch"],
                    "worker": i, "status": kind.lower(),
                    "hypothesis": f"Agent {kind.lower()}: {err}", "diff": "",
                    "score": 0, "best_score_at_time": state["best_score"],
                    "improved": False,
                })
                continue

            # Instruction-violation check: did the worker write experiment_id_output.txt?
            expected = exp_ids[i - 1]
            actual = read_or(wdir / "experiment_id_output.txt", "MISSING").strip()
            if expected != actual:
                print(f"  worker-{i}: INSTRUCTION_VIOLATION (expected {expected}, got {actual})")
                dlog(ar_dir, "worker_instruction_violation", worker=i, exp=exp_num,
                     expected=expected, actual=actual,
                     files_present=[f.name for f in wdir.iterdir() if f.is_file()] if wdir.exists() else [])
                append_log(ar_dir, {
                    "experiment_id": exp_num, "branch": state["active_branch"],
                    "worker": i, "status": "crash",
                    "hypothesis": "Did not finalize experiment_id_output.txt",
                    "diff": "",
                    "score": 0, "best_score_at_time": state["best_score"],
                    "improved": False,
                })
                continue

            hypothesis = read_or(wdir / "hypothesis.txt", "").strip()
            summary = read_or(wdir / "summary.txt", "").strip()

            # Score (robust: take the last numeric line of score.txt)
            score_str = read_or(wdir / "score.txt", "0").strip()
            worker_score = 0.0
            for line in reversed(score_str.splitlines()):
                try:
                    worker_score = float(line.strip())
                    break
                except ValueError:
                    continue

            # Compute diff from the filesystem — authoritative, not worker-reported.
            after = snapshot_files(wdir, editable_files_for_round)
            diff_text = compute_diff(snapshots[i], after)

            # Scan for violations by walking the filesystem.
            violations = scan_worker_violations(wdir, set(editable_files_for_round), ar_dir)

            print(f"  worker-{i}: score={worker_score:.2f} (best={state['best_score']:.2f})")
            dlog(ar_dir, "worker_result", worker=i, exp=exp_num,
                 score=worker_score, best=state["best_score"],
                 hypothesis=hypothesis, summary=summary,
                 diff_chars=len(diff_text), has_diff=bool(diff_text),
                 has_summary=bool(summary),
                 violations=violations)

            # Mechanical critique (filesystem-based, not diff-text-based).
            # Forbidden and locked edits are hard rejections — they violate the sandbox.
            # Unexpected files (non-meta, non-editable) are warnings only — promote_worker
            # only pulls editable files anyway, so they can't corrupt best/.
            skip = False
            if violations["forbidden"]:
                print(f"  worker-{i}: REJECTED (forbidden edits: {violations['forbidden']})")
                skip = True
            if violations["locked"]:
                print(f"  worker-{i}: REJECTED (locked edits: {violations['locked']})")
                skip = True
            if violations["unexpected"]:
                print(f"  worker-{i}: WARN (unexpected files, ignored: {violations['unexpected'][:3]}"
                      f"{'...' if len(violations['unexpected']) > 3 else ''})")
            if is_qualitative:
                writeup = read_or(wdir / "writeup.md", "").strip()
                if not hypothesis or not writeup:
                    print(f"  worker-{i}: REJECTED (no hypothesis or no writeup)")
                    skip = True
            else:
                if not hypothesis or not diff_text:
                    print(f"  worker-{i}: REJECTED (no hypothesis or no edits)")
                    skip = True

            improved = False if skip else check_noise(worker_score, state["best_score"], state.get("direction", "maximize"))

            parent = str(parent_exp)

            # Capture judge gate details if available (qualitative mode)
            eval_scores = None
            eval_scores_path = wdir / "eval_scores.json"
            if eval_scores_path.exists():
                try:
                    eval_scores = json.loads(eval_scores_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            worker_result = results[i - 1]
            worker_usage = {}
            if not isinstance(worker_result, Exception) and worker_result[1] is not None:
                worker_usage = worker_result[1].usage or {}

            exp_id_local = exp_ids[i - 1]
            log_entry = {
                "experiment_id": exp_num, "branch": state["active_branch"],
                "parent": parent, "worker": i,
                "status": "keep" if improved else "discard",
                "hypothesis": hypothesis, "summary": summary, "diff": diff_text,
                "score": worker_score, "best_score_at_time": state["best_score"],
                "improved": improved,
                "tokens": {
                    "input": worker_usage.get("input_tokens", 0),
                    "output": worker_usage.get("output_tokens", 0),
                    "cache_read": worker_usage.get("cache_read_input_tokens", 0),
                    "cache_create": worker_usage.get("cache_creation_input_tokens", 0),
                },
                "cost_usd": results[i - 1][1].total_cost_usd if not isinstance(results[i - 1], Exception) and results[i - 1][1] else 0,
                "num_turns": results[i - 1][1].num_turns if not isinstance(results[i - 1], Exception) and results[i - 1][1] else 0,
                "trace_path": f"traces/{exp_id_local}.jsonl",
                "prompt_file": f"prompts/{exp_id_local}.txt",
                "assigned_direction": worker_direction_ids[i - 1],
                "stance": worker_stances[i - 1],
            }
            if eval_scores:
                log_entry["eval_scores"] = eval_scores
            append_log(ar_dir, log_entry)

            if improved:
                round_had_improvement = True
                direction = state.get("direction", "maximize")
                if best_worker_score is None or (
                    worker_score < best_worker_score if direction == "minimize" else worker_score > best_worker_score
                ):
                    best_worker = i
                    best_worker_score = worker_score

        # Strategy fork: competitive vs collaborative
        strategy = state.get("strategy", "competitive")

        if strategy == "collaborative" and is_qualitative:
            # Qualitative collaborative: judge scores all write-ups, synthesizes
            # the main document, and curates the roadmap in one call.
            writeups = {}
            for i in range(1, parallelism + 1):
                wdir = ar_dir / "workers" / f"worker-{i}"
                if isinstance(results[i - 1], Exception):
                    continue
                writeup = read_or(wdir / "writeup.md", "").strip()
                hypothesis = read_or(wdir / "hypothesis.txt", "").strip()
                if writeup:
                    wid = f"worker-{i}"
                    writeups[wid] = {
                        "stance": worker_stances[i - 1],
                        "direction": worker_direction_ids[i - 1],
                        "hypothesis": hypothesis,
                        "writeup": writeup,
                    }

            proposals = collect_roadmap_proposals(ar_dir, parallelism)

            if writeups:
                print(f"\n  JUDGE: {len(writeups)} write-ups collected, calling judge...")
                dlog(ar_dir, "judge_start", round=round_num,
                     writeup_workers=list(writeups.keys()),
                     has_proposals=bool(proposals))

                eval_script = str(Path(__file__).parent / "eval_qualitative.py")
                writeups_json_str = json.dumps(writeups)
                t_judge = time.time()
                try:
                    judge_result = subprocess.run(
                        [sys.executable, eval_script, "--judge",
                         str(ar_dir), writeups_json_str, proposals or ""],
                        capture_output=True, text=True,
                        timeout=MERGE_TIMEOUT_SEC,
                    )
                    judge_output = judge_result.stdout.strip()
                    judge_data = json.loads(judge_output)
                except subprocess.TimeoutExpired:
                    print(f"  JUDGE TIMEOUT after {MERGE_TIMEOUT_SEC}s")
                    dlog(ar_dir, "judge_timeout", timeout_sec=MERGE_TIMEOUT_SEC)
                    judge_data = None
                except (json.JSONDecodeError, Exception) as e:
                    print(f"  JUDGE ERROR: {e}")
                    dlog(ar_dir, "judge_error", error=str(e),
                         stderr=judge_result.stderr[:500] if 'judge_result' in dir() else "")
                    judge_data = None

                judge_ms = int((time.time() - t_judge) * 1000)
                round_timing["judge_ms"] = judge_ms

                if judge_data:
                    # Write updated documents to best/ and branch/
                    editable_files = parse_editable_files(ar_dir)
                    for fpath, content in judge_data.get("documents", {}).items():
                        for dest_base in [ar_dir / "best", ar_dir / "branches" / state["active_branch"]]:
                            dest = dest_base / fpath
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_text(content)

                    # Write updated roadmap and sync direction registry
                    prev_direction_count = len(directions)
                    if judge_data.get("roadmap"):
                        (ar_dir / "roadmap.md").write_text(judge_data["roadmap"])
                        updated_directions = parse_roadmap(ar_dir)
                        # Build parent map: new directions proposed this round inherit
                        # from the direction their proposing worker was assigned to
                        parent_map = {}
                        for d in updated_directions:
                            if d["id"] not in {rd["id"] for rd in directions}:
                                parent_map[d["id"]] = None
                        # Try to attribute parentage from worker proposals
                        for i in range(1, parallelism + 1):
                            if (i - 1) < len(direction_assignments):
                                parent_did = direction_assignments[i - 1]["direction"]["id"]
                                wfile = ar_dir / "workers" / f"worker-{i}" / "roadmap_append.md"
                                if wfile.exists():
                                    proposal_text = wfile.read_text()
                                    for d in updated_directions:
                                        if d["id"] in parent_map and d["title"].lower() in proposal_text.lower():
                                            parent_map[d["id"]] = parent_did
                        sync_directions_from_roadmap(
                            ar_dir, updated_directions,
                            parent_map=parent_map,
                            source=f"round-{round_num}",
                        )

                        # Track whether the judge added new directions (for convergence)
                        new_direction_count = len(updated_directions)
                        if new_direction_count > prev_direction_count:
                            state["rounds_without_new_directions"] = 0
                        else:
                            state["rounds_without_new_directions"] = state.get("rounds_without_new_directions", 0) + 1

                    # Write meta document
                    if judge_data.get("meta"):
                        (ar_dir / "meta.md").write_text(judge_data["meta"])

                    # Update scores (only if scoring succeeded)
                    scores = judge_data.get("scores", {})
                    merged_parents = [state["experiment_count"] + i for i in range(1, parallelism + 1)
                                      if f"worker-{i}" in writeups]
                    state["last_promoted_experiment"] = merged_parents[0] if merged_parents else state["last_promoted_experiment"]
                    state["last_promoted_experiments"] = merged_parents

                    if scores:
                        best_score_this_round = 0
                        for wid, wscores in scores.items():
                            s = wscores.get("final_score", 0)
                            if s > best_score_this_round:
                                best_score_this_round = s
                            print(f"  {wid}: score={s} (hard_fail={wscores.get('hard_gate_failed', False)})")
                        state["best_score"] = best_score_this_round
                        (ar_dir / "best_score.txt").write_text(f"{best_score_this_round}\n")
                    else:
                        print("  SCORE call failed — keeping previous best score")

                    has_any_output = bool(judge_data.get("documents") or judge_data.get("roadmap") or scores)
                    if has_any_output:
                        state["discard_streak"] = 0
                        state["best_unchanged_count"] = 0
                    else:
                        state["discard_streak"] += 1
                        state["best_unchanged_count"] += parallelism
                    dlog(ar_dir, "judge_done", round=round_num,
                         scores={wid: ws.get("final_score", 0) for wid, ws in scores.items()},
                         merged_parents=merged_parents,
                         judge_ms=judge_ms)
                else:
                    state["discard_streak"] += 1
                    state["best_unchanged_count"] += parallelism
                    print(f"\n  Judge failed. Discard streak: {state['discard_streak']}")
                    dlog(ar_dir, "no_improvement", discard_streak=state["discard_streak"],
                         best_unchanged_count=state["best_unchanged_count"],
                         reason="judge_failed")
            else:
                state["discard_streak"] += 1
                state["best_unchanged_count"] += parallelism
                print(f"\n  No valid write-ups. Discard streak: {state['discard_streak']}")
                dlog(ar_dir, "no_improvement", discard_streak=state["discard_streak"],
                     best_unchanged_count=state["best_unchanged_count"])

        elif strategy == "collaborative":
            # Quantitative collaborative: merge agent synthesizes code changes
            passing = []
            for i in range(1, parallelism + 1):
                wdir = ar_dir / "workers" / f"worker-{i}"
                exp_num = state["experiment_count"] + i
                if isinstance(results[i - 1], Exception):
                    continue
                score_str = read_or(wdir / "score.txt", "0").strip()
                try:
                    wscore = float(score_str)
                except ValueError:
                    wscore = 0.0
                summary = read_or(wdir / "summary.txt", "").strip()
                if passed_hard_gates(wdir, wscore):
                    worker_file_snapshots = {}
                    for f in parse_editable_files(ar_dir):
                        p = wdir / f
                        if p.exists():
                            worker_file_snapshots[f] = p.read_bytes()
                    passing.append((i, wscore, summary, exp_num, worker_file_snapshots))

            if passing:
                best_passing_score = max(s for _, s, _, _, _ in passing)
                passing_nums = [i for i, _, _, _, _ in passing]
                print(f"\n  COLLABORATIVE MERGE: {len(passing)} workers passed hard gates {passing_nums}")
                dlog(ar_dir, "collaborative_merge_start", passing_workers=passing_nums,
                     best_score=best_passing_score)

                editable_files = parse_editable_files(ar_dir)
                base_docs = []
                for f in editable_files:
                    p = ar_dir / "best" / f
                    base_docs.append(f"=== BASE: {f} ===\n{read_or(p, '[not found]')}")

                worker_docs = []
                for i, wscore, wsummary, wexp, _ in passing:
                    wdir = ar_dir / "workers" / f"worker-{i}"
                    parts = [f"--- Worker {i} (score={wscore:.2f}, exp=#{wexp}) ---"]
                    parts.append(f"Summary: {wsummary}")
                    for f in editable_files:
                        p = wdir / f
                        parts.append(f"=== {f} ===\n{read_or(p, '[not found]')}")
                    worker_docs.append("\n".join(parts))

                merge_user_msg = (
                    f"Merge passing worker outputs into the baseline.\n"
                    f"Autoresearch directory: {ar_dir}\n"
                    f"Active branch: {state['active_branch']}\n"
                    f"Editable files: {editable_files}\n"
                    f"Output paths: best/ = {ar_dir / 'best'}, branch/ = {ar_dir / 'branches' / state['active_branch']}\n\n"
                    f"BASE DOCUMENTS:\n" + "\n\n".join(base_docs) + "\n\n"
                    f"PASSING WORKER OUTPUTS:\n" + "\n\n".join(worker_docs)
                )

                merge_trace = ar_dir / "traces" / f"merge-round-{round_num}.jsonl"
                t_merge = time.time()
                try:
                    merge_output, _ = await asyncio.wait_for(
                        run_agent(
                            system_prompt=merge_skill,
                            user_prompt=merge_user_msg,
                            cwd=ar_dir,
                            name="merge",
                            trace_path=merge_trace,
                        ),
                        timeout=MERGE_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    print(f"  MERGE TIMEOUT after {MERGE_TIMEOUT_SEC}s — using best worker as fallback")
                    dlog(ar_dir, "merge_timeout", timeout_sec=MERGE_TIMEOUT_SEC)
                    merge_output = "MERGE TIMEOUT"
                    best_i, best_s, _, best_exp, best_snapshots = max(passing, key=lambda x: x[1])
                    for f in editable_files:
                        content = best_snapshots.get(f)
                        if content is not None:
                            for dest_base in [ar_dir / "best", ar_dir / "branches" / state["active_branch"]]:
                                dest = dest_base / f
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                dest.write_bytes(content)

                merge_ms = int((time.time() - t_merge) * 1000)
                round_timing["merge_ms"] = merge_ms
                dlog(ar_dir, "merge_output", round=round_num,
                     output=str(merge_output)[:500], merge_ms=merge_ms)

                state["best_score"] = best_passing_score
                merged_parents = [exp_num for _, _, _, exp_num, _ in passing]
                state["last_promoted_experiment"] = merged_parents[0]
                state["last_promoted_experiments"] = merged_parents
                (ar_dir / "best_score.txt").write_text(f"{best_passing_score}\n")
                state["discard_streak"] = 0
                state["best_unchanged_count"] = 0
                dlog(ar_dir, "collaborative_merge_done",
                     passing_workers=passing_nums,
                     merged_parents=merged_parents,
                     new_best=best_passing_score)
            else:
                state["discard_streak"] += 1
                state["best_unchanged_count"] += parallelism
                print(f"\n  No workers passed hard gates. Discard streak: {state['discard_streak']}")
                dlog(ar_dir, "no_improvement", discard_streak=state["discard_streak"],
                     best_unchanged_count=state["best_unchanged_count"])

        else:
            # Competitive: promote single best worker
            if round_had_improvement and best_worker is not None:
                promoted_exp = state["experiment_count"] + best_worker
                print(f"\n  PROMOTED worker-{best_worker} / experiment #{promoted_exp} (score: {best_worker_score:.2f})")
                wdir = ar_dir / "workers" / f"worker-{best_worker}"
                promote_worker(wdir, ar_dir, state["active_branch"])
                state["best_score"] = best_worker_score
                state["last_promoted_experiment"] = promoted_exp
                (ar_dir / "best_score.txt").write_text(f"{best_worker_score}\n")
                state["discard_streak"] = 0
                state["best_unchanged_count"] = 0
                dlog(ar_dir, "promoted", worker=best_worker, exp=promoted_exp,
                     new_best=best_worker_score)
            else:
                state["discard_streak"] += 1
                state["best_unchanged_count"] += parallelism
                print(f"\n  No improvement. Discard streak: {state['discard_streak']}")
                dlog(ar_dir, "no_improvement", discard_streak=state["discard_streak"],
                     best_unchanged_count=state["best_unchanged_count"])

        state["experiment_count"] += parallelism
        write_state(ar_dir, state)

        # For quantitative mode, auto-append roadmap proposals (judge handles this for qualitative)
        if not is_qualitative:
            proposals = collect_roadmap_proposals(ar_dir, parallelism)
            if proposals:
                roadmap_path = ar_dir / "roadmap.md"
                existing = read_or(roadmap_path, "# Roadmap\n")
                roadmap_path.write_text(existing + "\n\n## Worker proposals (round " + str(round_num) + ")\n" + proposals + "\n")
                dlog(ar_dir, "roadmap_proposals_appended", round=round_num, proposals_chars=len(proposals))

        # Persist writeups before cleanup
        from bin.writeup_store import persist_writeups
        persist_writeups(ar_dir, parallelism, round_num)

        cleanup_workers(ar_dir)

        # Cache-efficiency ratio: how much of the input was cache-read vs fresh create?
        total_input_cost_tokens = round_cache_read + round_cache_create + round_input_tokens
        cache_hit_ratio = (round_cache_read / total_input_cost_tokens) if total_input_cost_tokens else 0.0

        print(f"  Round tokens: in={round_input_tokens} out={round_output_tokens} "
              f"cache_read={round_cache_read} cache_create={round_cache_create} "
              f"(cache_hit_ratio={cache_hit_ratio:.2%})")
        dlog(ar_dir, "round_end", round=round_num,
             tokens_in=round_input_tokens, tokens_out=round_output_tokens,
             cache_read=round_cache_read, cache_create=round_cache_create,
             cache_hit_ratio=round(cache_hit_ratio, 4),
             total_cost_so_far=total_cost)

        # Periodic summarize (also always on final round)
        is_last_round = round_num >= max_rounds
        is_budget_last = max_cost is not None and total_cost >= max_cost
        if round_num % SUMMARIZE_EVERY == 0 or is_last_round or is_budget_last:
            print(f"\n--- SUMMARIZE (round {round_num}) ---")
            t_sum = time.time()
            from bin.summarize import summarize
            output = summarize(ar_dir)
            round_timing["summarize_ms"] = int((time.time() - t_sum) * 1000)
            print(output)

        # Final per-round timing record (always — makes perf trends visible).
        round_timing["total_ms"] = (
            round_timing.get("prepare_ms", 0)
            + round_timing.get("workers_ms", 0)
            + round_timing.get("merge_ms", 0)
            + round_timing.get("summarize_ms", 0)
        )
        dlog(ar_dir, "round_timing", round=round_num, **round_timing)

    # Generate verdict
    from bin.verdict import generate_verdict
    try:
        verdict = generate_verdict(ar_dir)
        print(f"\n--- VERDICT: {verdict['headline']} (supportive={verdict['tension']['supportive']}%, adversarial={verdict['tension']['adversarial']}%) ---")
    except Exception as e:
        print(f"\n  Warning: verdict generation failed: {e}")

    print(f"\n=== AUTORESEARCH COMPLETE ===")
    print(f"Ran {round_num} rounds ({state['experiment_count']} experiments). Best: {state['best_score']:.2f}")
    print(f"Total API cost: ${total_cost:.4f}")
    print(f"Best code: {ar_dir}/best/")

    # Clean up headless agent sessions (--no-session-persistence doesn't work with SDK)
    try:
        from claude_agent_sdk import list_sessions, delete_session
        sessions = list_sessions()
        cleaned = 0
        for s in sessions:
            prompt = (s.first_prompt or "")[:200]
            if any(
                x in prompt.lower()
                for x in [
                    "run experiment", "initialize the autoresearch",
                    "summarize the experiment", "worker directory:",
                ]
            ):
                delete_session(s.session_id)
                cleaned += 1
        if cleaned:
            print(f"Cleaned up {cleaned} headless agent sessions.")
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
