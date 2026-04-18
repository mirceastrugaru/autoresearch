"""Run manager for Autoresearch API.

Manages orchestrator subprocesses per session.
Provides start/pause/resume/stop and SSE event streaming.
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator


class RunInfo:
    def __init__(self, session_id: str, process: subprocess.Popen, ar_dir: Path):
        self.session_id = session_id
        self.process = process
        self.ar_dir = ar_dir
        self.started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunManager:
    def __init__(self):
        self._runs: dict[str, RunInfo] = {}

    def start_run(self, session_id: str, ar_dir: Path, rounds: int = 10,
                  workers: int | None = None, max_cost: float | None = None) -> dict:
        """Spawn orchestrator subprocess."""
        if session_id in self._runs and self._runs[session_id].process.poll() is None:
            return {"error": "Run already in progress", "status": 409}

        orchestrator_path = Path(__file__).parent / "orchestrator.py"
        project_dir = ar_dir.parent.parent  # autoresearch/<name> → project root
        initiative = ar_dir.name

        cmd = [
            sys.executable, str(orchestrator_path),
            str(rounds), str(project_dir), initiative,
        ]
        if workers:
            cmd.extend(["--workers", str(workers)])
        if max_cost:
            cmd.extend(["--max-cost", str(max_cost)])

        env = os.environ.copy()
        # Ensure the bin directory is in PYTHONPATH for imports
        bin_dir = str(Path(__file__).parent.parent)
        env["PYTHONPATH"] = bin_dir + ":" + env.get("PYTHONPATH", "")

        process = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

        run_info = RunInfo(session_id, process, ar_dir)
        self._runs[session_id] = run_info

        return {
            "runId": f"run-{session_id[:8]}",
            "startedAt": run_info.started_at,
        }

    def pause_run(self, session_id: str) -> bool:
        """Create pause sentinel file."""
        run = self._runs.get(session_id)
        if not run:
            return False
        sentinel = run.ar_dir / "pause_requested"
        sentinel.write_text("paused")
        return True

    def resume_run(self, session_id: str) -> bool:
        """Remove pause sentinel."""
        run = self._runs.get(session_id)
        if not run:
            return False
        sentinel = run.ar_dir / "pause_requested"
        if sentinel.exists():
            sentinel.unlink()
        return True

    def stop_run(self, session_id: str) -> bool:
        """Send SIGTERM to orchestrator process."""
        run = self._runs.get(session_id)
        if not run or run.process.poll() is not None:
            return False
        try:
            run.process.send_signal(signal.SIGTERM)
            run.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            run.process.kill()
        return True

    def is_running(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        if not run:
            return False
        return run.process.poll() is None

    def get_workers_snapshot(self, session_id: str) -> dict | None:
        """Get current worker state from debug.log."""
        run = self._runs.get(session_id)
        ar_dir = run.ar_dir if run else None
        if not ar_dir:
            return None
        return _build_workers_snapshot(ar_dir)


def _build_workers_snapshot(ar_dir: Path) -> dict:
    """Build worker snapshot from debug.log."""
    debug_path = ar_dir / "debug.log"
    if not debug_path.exists():
        return {"workers": [], "round": 0, "tension": {"pro": 50, "con": 50}, "cost": 0, "tokens": 0, "stallStreak": 0}

    # Build direction ID → short title lookup
    dir_titles = {}
    try:
        from bin.program_parser import parse_roadmap
        for d in parse_roadmap(ar_dir):
            title = d.get("title", "")
            title = re.sub(r'\*\*([^*]+)\*\*', r'\1', title)
            title = re.sub(r'^\[(REJECTED|RETRY|FLAGGED FOR REVIEW|COVERED[^]]*|PRIORITY[^]]*)\]\s*', '', title.strip())
            title = title.strip()
            short = title[:60] + "…" if len(title) > 60 else title
            dir_titles[d["id"]] = short
    except Exception:
        pass

    workers = {}
    round_num = 0
    cost = 0.0
    tokens = 0
    stall_streak = 0

    for line in debug_path.read_text().strip().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue

        section = e.get("section", "")

        if section == "round_start":
            round_num = e.get("round", round_num)
            stall_streak = e.get("discard_streak", stall_streak)
            workers = {}

        elif section == "worker_launch":
            w_num = e.get("worker", 0)
            dir_id = e.get("assigned_direction", "")
            dir_name = e.get("direction_title", "") or dir_titles.get(dir_id, dir_id)
            workers[w_num] = {
                "id": f"w{w_num}",
                "stance": e.get("stance", ""),
                "dir": dir_name,
                "status": "running",
                "tool": "",
                "pct": 0,
            }

        elif section == "worker_result":
            w_num = e.get("worker", 0)
            if w_num in workers:
                workers[w_num]["status"] = "done"
                workers[w_num]["pct"] = 100

        elif section in ("round_end", "round_complete"):
            cost = e.get("total_cost_so_far", cost)
            tokens += e.get("tokens_in", 0) + e.get("tokens_out", 0)

    # Compute tension from log.jsonl
    tension = {"pro": 50, "con": 50}
    log_path = ar_dir / "log.jsonl"
    if log_path.exists():
        pro_total = 0
        con_total = 0
        for line in log_path.read_text().strip().splitlines():
            try:
                entry = json.loads(line)
                score = entry.get("score", 0) or 0
                if entry.get("stance") == "pro":
                    pro_total += score
                elif entry.get("stance") == "con":
                    con_total += score
            except json.JSONDecodeError:
                continue
        total = pro_total + con_total or 1
        tension = {"pro": int(round(pro_total / total * 100)), "con": int(round(con_total / total * 100))}

    # Supplement with state.json for cost/round data
    state_path = ar_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            if state.get("round", 0) > round_num:
                round_num = state["round"]
            if state.get("total_cost", 0) > cost:
                cost = state["total_cost"]
            if state.get("total_tokens", 0) > tokens:
                tokens = state["total_tokens"]
            if state.get("discard_streak", 0) > stall_streak:
                stall_streak = state["discard_streak"]
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "workers": list(workers.values()),
        "round": round_num,
        "tension": tension,
        "cost": round(cost, 2),
        "tokens": tokens,
        "stallStreak": stall_streak,
    }


async def stream_events(ar_dir: Path) -> AsyncIterator[str]:
    """Stream SSE events by tailing debug.log."""
    debug_path = ar_dir / "debug.log"
    offset = 0

    # Start from end of existing file
    if debug_path.exists():
        offset = debug_path.stat().st_size

    yield _sse_event("stage", {"stage": "run"})

    while True:
        if not debug_path.exists():
            await asyncio.sleep(0.5)
            continue

        content = debug_path.read_text()
        if len(content) <= offset:
            await asyncio.sleep(0.5)
            continue

        new_content = content[offset:]
        offset = len(content)

        for line in new_content.strip().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue

            events = _map_debug_to_sse(e, ar_dir)
            for evt in events:
                yield evt

            # Stop streaming after run completion
            if e.get("section") == "summarize_output":
                yield _sse_event("run.complete", _build_run_complete(ar_dir))
                return

        await asyncio.sleep(0.5)


def _map_debug_to_sse(e: dict, ar_dir: Path) -> list[str]:
    """Map a debug.log entry to one or more SSE events."""
    section = e.get("section", "")
    events = []

    if section == "round_start":
        events.append(_sse_event("round.start", {
            "round": e.get("round"),
            "startedAt": e.get("ts"),
        }))

    elif section == "worker_launch":
        events.append(_sse_event("worker.update", {
            "id": f"w{e.get('worker')}",
            "stance": e.get("stance", ""),
            "dir": e.get("direction_title", "") or e.get("assigned_direction", ""),
            "status": "running",
            "tool": "",
            "pct": 0,
        }))
        events.append(_sse_event("activity", {
            "t": e.get("ts", "")[:19].replace("T", " "),
            "who": f"w{e.get('worker')}",
            "stance": e.get("stance", ""),
            "msg": f"Starting experiment {e.get('exp_id', '')}",
        }))

    elif section == "worker_result":
        events.append(_sse_event("worker.update", {
            "id": f"w{e.get('worker')}",
            "stance": e.get("stance", ""),
            "dir": "",
            "status": "done",
            "tool": "",
            "pct": 100,
        }))
        if e.get("score") is not None:
            events.append(_sse_event("judge.score", {
                "workerId": f"w{e.get('worker')}",
                "score": e.get("score", 0),
            }))

    elif section == "round_end" or section == "round_complete":
        scores = []
        for k, v in e.items():
            if k.startswith("w") and isinstance(v, dict) and "score" in v:
                scores.append({"workerId": k, "score": v["score"]})
        events.append(_sse_event("round.complete", {
            "round": e.get("round"),
            "scores": scores,
        }))

    elif section == "judge_start":
        events.append(_sse_event("activity", {
            "t": e.get("ts", "")[:19].replace("T", " "),
            "who": "judge",
            "msg": "Scoring and synthesizing write-ups",
        }))

    elif section == "judge_done" or section == "judge_complete":
        events.append(_sse_event("doc.update", {
            "doc": "main",
            "content": "",  # Full doc available via GET main.md
        }))

    elif section == "guardrail_built":
        events.append(_sse_event("stall.update", {
            "streak": e.get("discard_streak", 0),
            "pivotAt": 5,
        }))

    elif section == "forced_pivot":
        events.append(_sse_event("activity", {
            "t": e.get("ts", "")[:19].replace("T", " "),
            "who": "system",
            "msg": f"Forced pivot to branch {e.get('new_branch', '')}",
        }))

    return events


def _build_run_complete(ar_dir: Path) -> dict:
    """Build run.complete event data."""
    verdict_path = ar_dir / "verdict.json"
    verdict = None
    if verdict_path.exists():
        try:
            verdict = json.loads(verdict_path.read_text())
        except json.JSONDecodeError:
            pass

    state_path = ar_dir / "state.json"
    cost = 0
    tokens = 0
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {}

    return {
        "verdict": verdict,
        "cost": cost,
        "tokens": tokens,
    }


def _sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
