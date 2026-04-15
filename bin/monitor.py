#!/usr/bin/env python3
"""
Autoresearch Web Monitor — real-time browser dashboard for watching orchestrator runs.

Usage:
    python bin/monitor.py <project_dir> <initiative_name> [--port 8080]

Example:
    python bin/monitor.py . my-research-initiative
    python bin/monitor.py /path/to/project my-research-initiative
"""

import argparse
import json
import sys
import time
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return now_utc()


def elapsed_str(start: datetime) -> str:
    secs = int((now_utc() - start).total_seconds())
    if secs < 0:
        secs = 0
    m, s = divmod(secs, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


_EPHEMERAL_NAMES = {
    "score.txt", "summary.txt", "hypothesis.txt", "parking_lot_addition.txt",
    "experiment_id.txt", "violations.txt", "experiment_10_output.txt",
}

def _is_persistent_file(fp: str) -> bool:
    """Return True if this file is likely to still exist when the user clicks."""
    p = Path(fp)
    if p.name in _EPHEMERAL_NAMES:
        return False
    # Allow editable doc files in worker dirs (they exist while worker runs)
    if "workers" in p.parts and p.suffix in (".md", ".html", ".txt", ".json"):
        if p.name not in _EPHEMERAL_NAMES:
            return True
    # Worker dirs scratch files are not linkable
    if "workers" in p.parts:
        return False
    return True


def _parse_preview(inp: dict) -> dict:
    """input_json_preview is a JSON-encoded string — parse it to get the real fields."""
    preview = inp.get("input_json_preview", "")
    if preview:
        try:
            return json.loads(preview)
        except Exception:
            pass
    return inp


def fmt_tool(event: dict) -> tuple[str, str | None]:
    """Returns (display_text, file_path_or_None). file_path is set for Read/Write/Edit."""
    name = event.get("tool_name", "?")
    raw = event.get("input", {})
    inp = _parse_preview(raw) if raw.get("input_json_preview") else raw

    if name == "Bash":
        cmd = inp.get("command", "")
        # Trim to most meaningful part — skip long paths
        cmd = cmd.replace("\n", " ").strip()[:90]
        return f"Bash  {cmd}", None
    elif name == "Read":
        fp = inp.get("file_path", "")
        label = "/".join(Path(fp).parts[-3:]) if fp else "?"
        # Only link persistent files (not ephemeral worker scratch files)
        linkable = fp and _is_persistent_file(fp)
        return f"Read  {label}", fp if linkable else None
    elif name == "Write":
        fp = inp.get("file_path", "")
        label = "/".join(Path(fp).parts[-3:]) if fp else "?"
        linkable = fp and _is_persistent_file(fp)
        return f"Write  {label}", fp if linkable else None
    elif name == "Edit":
        fp = inp.get("file_path", "")
        label = "/".join(Path(fp).parts[-3:]) if fp else "?"
        linkable = fp and _is_persistent_file(fp)
        return f"Edit  {label}", fp if linkable else None
    elif name == "WebSearch":
        q = inp.get("query", inp.get("input_json_preview", str(raw)))[:70]
        return f'WebSearch  "{q}"', None
    elif name == "WebFetch":
        url = inp.get("url", "")[:80]
        return f"WebFetch  {url}", None
    elif name == "Glob":
        return f"Glob  {inp.get('pattern', '')[:60]}", None
    elif name == "Grep":
        return f"Grep  {inp.get('pattern', inp.get('query', ''))[:50]}", None
    elif name == "ToolSearch":
        q = inp.get("query", "")[:50]
        return f"ToolSearch  {q}", None
    elif name == "Agent":
        desc = inp.get("description", inp.get("prompt", ""))[:60]
        return f"Agent  {desc}", None
    else:
        # Flatten to something readable
        parts = []
        for k, v in list(inp.items())[:3]:
            if isinstance(v, str) and v:
                parts.append(f"{k}={v[:40]}")
        summary = "  ".join(parts) if parts else str(inp)[:60]
        return f"{name}  {summary}", None


def tail_new_lines(path: Path, offset: int) -> tuple[list[str], int]:
    if not path.exists():
        return [], offset
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            new_offset = offset + len(data)
        lines = data.decode("utf-8", errors="replace").splitlines()
        return [l for l in lines if l.strip()], new_offset
    except Exception:
        return [], offset


def parse_jsonl_lines(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ── State model ───────────────────────────────────────────────────────────────

class WorkerState:
    def __init__(self, worker_num, exp_id, role_bias, trace_file, launch_ts):
        self.worker_num = worker_num
        self.exp_id = exp_id
        self.role_bias = role_bias
        self.trace_file = Path(trace_file) if trace_file else None
        self.launch_ts = parse_ts(launch_ts)
        self.trace_offset = 0
        self.tools: list[tuple[str, str | None]] = []  # (display_text, file_path_or_None)
        self.hypothesis: str = ""
        self.done: bool = False
        self.score = None
        self.cost = None
        self.num_turns = None
        self.result_type: str = ""

    def to_dict(self):
        return {
            "worker_num": self.worker_num,
            "exp_id": self.exp_id,
            "role_bias": self.role_bias,
            "elapsed": elapsed_str(self.launch_ts),
            "tools": [{"text": t, "file": f} for t, f in self.tools],
            "hypothesis": self.hypothesis,
            "done": self.done,
            "score": self.score,
            "cost": self.cost,
            "num_turns": self.num_turns,
            "result_type": self.result_type,
        }


class MonitorState:
    def __init__(self):
        self.round_num = 0
        self.max_rounds = 0
        self.best_score = None
        self.branch = "main"
        self.discard_streak = 0
        self.total_cost = 0.0
        self.strategy = ""
        self.eval_mode = ""
        self.parallelism = 0
        self.experiment_count = 0
        self.workers: dict[int, WorkerState] = {}
        self.merge_active = False
        self.merge_round = 0
        self.merge_start_ts: datetime | None = None
        self.merge_trace_file: Path | None = None
        self.merge_trace_offset = 0
        self.merge_tools: list[tuple[str, str | None]] = []
        self.log_entries: list[dict] = []
        self.debug_events: list[str] = []
        self.debug_offset = 0
        self.log_offset = 0

    def to_dict(self):
        return {
            "round_num": self.round_num,
            "max_rounds": self.max_rounds,
            "best_score": self.best_score,
            "branch": self.branch,
            "discard_streak": self.discard_streak,
            "total_cost": self.total_cost,
            "strategy": self.strategy,
            "eval_mode": self.eval_mode,
            "parallelism": self.parallelism,
            "experiment_count": self.experiment_count,
            "workers": [w.to_dict() for w in sorted(self.workers.values(), key=lambda x: x.worker_num)],
            "merge_active": self.merge_active,
            "merge_round": self.merge_round,
            "merge_elapsed": elapsed_str(self.merge_start_ts) if self.merge_start_ts and self.merge_active else None,
            "merge_tools": [{"text": t, "file": f} for t, f in self.merge_tools],
            "log_entries": self.log_entries[-40:],
            "debug_events": self.debug_events[-80:],
        }


# ── Poller ────────────────────────────────────────────────────────────────────

class Poller:
    def __init__(self, project_dir: Path, initiative: str):
        self.project_dir = project_dir
        self.initiative = initiative
        self.ar_dir = project_dir / "autoresearch" / initiative
        self.state = MonitorState()
        self._lock = threading.Lock()
        self._running = True

    def get_snapshot(self) -> dict:
        with self._lock:
            d = self.state.to_dict()
            # Find the best document path for the clickable link
            best_dir = self.ar_dir / "best"
            if best_dir.exists():
                for f in sorted(best_dir.iterdir()):
                    if f.suffix in (".md", ".html") and f.name not in ("eval_scores.json",):
                        d["best_doc_path"] = str(f)
                        break
            return d

    def run(self):
        while self._running:
            with self._lock:
                self._poll_state_json()
                self._poll_debug_log()
                self._poll_log_jsonl()
                self._poll_worker_traces()
                self._poll_merge_trace()
            time.sleep(0.5)

    def stop(self):
        self._running = False

    def _poll_state_json(self):
        path = self.ar_dir / "state.json"
        if not path.exists():
            return
        try:
            s = json.loads(path.read_text())
            st = self.state
            st.eval_mode = s.get("eval_mode", "")
            st.strategy = s.get("strategy", "")
            st.parallelism = s.get("parallelism", 0)
            st.experiment_count = s.get("experiment_count", 0)
        except Exception:
            pass

    def _poll_debug_log(self):
        path = self.ar_dir / "debug.log"
        lines, new_off = tail_new_lines(path, self.state.debug_offset)
        if not lines:
            return
        self.state.debug_offset = new_off
        events = parse_jsonl_lines(lines)
        st = self.state
        for e in events:
            section = e.get("section", "")
            ts = e.get("ts", "")[:19].replace("T", " ")

            if section == "round_start":
                st.round_num = e.get("round", st.round_num)
                st.max_rounds = e.get("max_rounds", st.max_rounds)
                st.best_score = e.get("best_score", st.best_score)
                st.branch = e.get("branch", st.branch)
                st.discard_streak = e.get("discard_streak", st.discard_streak)
                st.workers = {}
                st.merge_active = False
                st.debug_events.append(f"{ts}  round_start  round={e.get('round')}  best={e.get('best_score')}")

            elif section == "worker_launch":
                w = WorkerState(
                    worker_num=e.get("worker", 0),
                    exp_id=e.get("exp_id", "?"),
                    role_bias=e.get("role_bias", "?"),
                    trace_file=e.get("trace_file", ""),
                    launch_ts=e.get("ts", ""),
                )
                st.workers[e.get("worker", 0)] = w
                st.debug_events.append(f"{ts}  worker_launch  worker={e.get('worker')}  [{e.get('role_bias','')}]  exp={e.get('exp_id','')[:16]}")

            elif section == "worker_result":
                wnum = e.get("worker", 0)
                if wnum in st.workers:
                    w = st.workers[wnum]
                    w.score = e.get("score")
                    w.hypothesis = e.get("hypothesis", "")[:500]
                st.debug_events.append(f"{ts}  worker_result  worker={e.get('worker')}  score={e.get('score')}")

            elif section in ("worker_timeout", "worker_crash"):
                wnum = e.get("worker", 0)
                if wnum in st.workers:
                    st.workers[wnum].done = True
                    st.workers[wnum].result_type = section.replace("worker_", "")
                st.debug_events.append(f"{ts}  {section}  worker={e.get('worker')}")

            elif section == "collaborative_merge_start":
                st.merge_active = True
                st.merge_round = st.round_num
                st.merge_start_ts = parse_ts(e.get("ts", ""))
                st.merge_tools = []
                st.merge_trace_file = self.ar_dir / "traces" / f"merge-round-{st.round_num}.jsonl"
                st.merge_trace_offset = 0
                st.debug_events.append(f"{ts}  merge_start  passing={e.get('passing_workers', [])}")

            elif section == "collaborative_merge_done":
                st.merge_active = False
                new_best = e.get("new_best")
                if new_best is not None:
                    st.best_score = new_best
                st.debug_events.append(f"{ts}  merge_done  new_best={new_best}")

            elif section == "promoted":
                st.best_score = e.get("new_best", st.best_score)
                st.discard_streak = 0
                st.debug_events.append(f"{ts}  promoted  worker={e.get('worker')}  new_best={e.get('new_best')}")

            elif section == "no_improvement":
                st.discard_streak = e.get("discard_streak", st.discard_streak)
                st.debug_events.append(f"{ts}  no_improvement  streak={e.get('discard_streak')}")

            elif section == "round_end":
                st.total_cost = e.get("total_cost_so_far", st.total_cost)
                ratio = e.get("cache_hit_ratio", 0)
                st.debug_events.append(f"{ts}  round_end  cost=${e.get('total_cost_so_far', 0):.2f}  cache={ratio:.0%}")

            elif section == "forced_pivot":
                st.debug_events.append(f"{ts}  forced_pivot  new_branch={e.get('new_branch')}")

            elif section == "init_output":
                st.debug_events.append(f"{ts}  init_output  {e.get('output','')[:60]}")

        if len(st.debug_events) > 200:
            st.debug_events = st.debug_events[-200:]

    def _poll_log_jsonl(self):
        path = self.ar_dir / "log.jsonl"
        lines, new_off = tail_new_lines(path, self.state.log_offset)
        if not lines:
            return
        self.state.log_offset = new_off
        entries = parse_jsonl_lines(lines)
        for entry in entries:
            self.state.log_entries.append(entry)
            wnum = entry.get("worker")
            if wnum and wnum in self.state.workers:
                w = self.state.workers[wnum]
                w.done = True
                w.result_type = entry.get("status", "")
                w.score = entry.get("score")
                w.cost = entry.get("cost_usd")
                w.num_turns = entry.get("num_turns")
                if not w.hypothesis:
                    w.hypothesis = (entry.get("hypothesis") or "")[:500]

    def _poll_worker_traces(self):
        for w in self.state.workers.values():
            # Read hypothesis.txt if worker hasn't set one yet
            if not w.hypothesis and w.trace_file:
                hyp_path = w.trace_file.parent.parent / "workers" / f"worker-{w.worker_num}" / "hypothesis.txt"
                if hyp_path.exists():
                    try:
                        w.hypothesis = hyp_path.read_text().strip()[:300]
                    except Exception:
                        pass
            if not w.trace_file or not w.trace_file.exists():
                continue
            lines, new_off = tail_new_lines(w.trace_file, w.trace_offset)
            if not lines:
                continue
            w.trace_offset = new_off
            events = parse_jsonl_lines(lines)
            for e in events:
                etype = e.get("type", "")
                if etype == "tool_use":
                    w.tools.append(fmt_tool(e))
                    if len(w.tools) > 8:
                        w.tools = w.tools[-8:]
                elif etype == "assistant_text":
                    text = (e.get("text") or "")[:400].strip()
                    if text and len(text) > 30:
                        w.tools.append((f"💬 {text}", None))
                        if len(w.tools) > 8:
                            w.tools = w.tools[-8:]
                elif etype == "result":
                    w.done = True
                    w.cost = e.get("total_cost_usd")
                    w.num_turns = e.get("num_turns")

    def _poll_merge_trace(self):
        if not self.state.merge_active or not self.state.merge_trace_file:
            return
        lines, new_off = tail_new_lines(self.state.merge_trace_file, self.state.merge_trace_offset)
        if not lines:
            return
        self.state.merge_trace_offset = new_off
        events = parse_jsonl_lines(lines)
        for e in events:
            if e.get("type") == "tool_use":
                self.state.merge_tools.append(fmt_tool(e))
                if len(self.state.merge_tools) > 8:
                    self.state.merge_tools = self.state.merge_tools[-8:]


# ── HTTP server ───────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Autoresearch Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #c9d1d9; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
  #header { background: #0053aa; padding: 8px 16px; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
  #header h1 { font-size: 14px; font-weight: bold; color: #fff; letter-spacing: 1px; }
  #header .meta { color: #a8c8ff; font-size: 12px; }
  #header .best { color: #39d353; font-weight: bold; }
  #header .cost { color: #ffa657; }
  #header .doc-link { color: #79c0ff; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 2px; font-size: 12px; }
  #header .doc-link:hover { color: #fff; }
  #statusbar { background: #161b22; padding: 4px 16px; border-bottom: 1px solid #30363d; font-size: 11px; color: #8b949e; flex-shrink: 0; display: flex; gap: 16px; }
  #main { display: flex; flex-direction: row; flex: 1; min-height: 0; overflow: hidden; }
  #left-col { display: flex; flex-direction: column; flex: 3; min-width: 0; overflow-y: auto; }
  #right-col { display: flex; flex-direction: column; flex: 1; min-width: 280px; max-width: 340px; border-left: 1px solid #30363d; overflow: hidden; }
  #workers-section { padding: 8px; }
  #workers-title { font-size: 11px; color: #0053aa; font-weight: bold; padding: 0 4px 6px; letter-spacing: 1px; }
  #workers-grid { display: flex; flex-direction: column; gap: 8px; }
  .worker-card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px 12px; max-height: 30vh; overflow-y: auto; }
  #log-section-left { padding: 8px; border-top: 1px solid #30363d; }
  .worker-card.done { border-color: #21262d; opacity: 0.85; }
  .whead { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-weight: bold; }
  .bias-CONSERVATIVE { color: #39d353; }
  .bias-MODERATE { color: #ffa657; }
  .bias-AGGRESSIVE { color: #f85149; }
  .bias-UNKNOWN { color: #8b949e; }
  .running-tag { color: #ffa657; font-size: 11px; }
  .done-tag { font-size: 11px; }
  .done-keep { color: #39d353; }
  .done-discard { color: #f85149; }
  .done-crash { color: #f85149; font-weight: bold; }
  .done-timeout { color: #f85149; }
  .hypothesis { color: #c9a227; font-size: 11px; font-style: italic; margin-bottom: 6px; line-height: 1.4; word-break: break-word; }
  .tool-line { font-size: 11px; padding: 1px 0; word-break: break-word; }
  .tool-done { color: #6e7681; }
  .tool-active { color: #ffa657; }
  .tool-thought { color: #c9d1d9; font-style: italic; font-size: 11px; padding: 3px 0; opacity: 0.85; word-break: break-word; line-height: 1.4; }
  .merge-card { background: #1c1610; border: 1px solid #bb7f2b; border-radius: 6px; padding: 8px 10px; min-width: 320px; flex: 1; }
  .merge-head { color: #ffa657; font-weight: bold; margin-bottom: 4px; }
  #events-section { flex: 1; overflow-y: auto; padding: 8px; }
  .section-title { font-size: 11px; color: #0053aa; font-weight: bold; letter-spacing: 1px; margin-bottom: 6px; }
  .log-entry { font-size: 11px; padding: 2px 0; border-bottom: 1px solid #161b22; }
  .log-keep { color: #39d353; }
  .log-discard { color: #f85149; }
  .log-crash { color: #f85149; font-weight: bold; }
  .log-other { color: #8b949e; }
  .event-line { font-size: 11px; color: #6e7681; padding: 1px 0; }
  .event-important { color: #79c0ff; }
  .event-error { color: #f85149; }
  .event-good { color: #39d353; }
  #pulse { width: 8px; height: 8px; border-radius: 50%; background: #39d353; margin-left: auto; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
  .waiting { color: #6e7681; font-style: italic; padding: 8px; }
  .score { color: #39d353; }
  .exp-id { color: #8b949e; font-size: 10px; }
  .tool-link { cursor: pointer; text-decoration: underline dotted; text-underline-offset: 2px; }
  .tool-link:hover { opacity: 0.8; }
  /* File viewer panel */
  #file-viewer { display: none; position: fixed; top: 0; right: 0; width: 55%; height: 100vh; background: #0d1117; border-left: 2px solid #0053aa; z-index: 100; flex-direction: column; }
  #file-viewer.open { display: flex; }
  #fv-header { background: #161b22; padding: 8px 12px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #30363d; flex-shrink: 0; }
  #fv-title { flex: 1; color: #79c0ff; font-size: 12px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #fv-close { cursor: pointer; color: #8b949e; font-size: 16px; padding: 0 4px; }
  #fv-close:hover { color: #f85149; }
  #fv-refresh { cursor: pointer; color: #8b949e; font-size: 12px; padding: 2px 6px; border: 1px solid #30363d; border-radius: 4px; }
  #fv-refresh:hover { color: #79c0ff; border-color: #79c0ff; }
  #fv-body { flex: 1; overflow-y: auto; padding: 12px; }
  #fv-content { white-space: pre-wrap; font-size: 12px; line-height: 1.6; color: #c9d1d9; }
  #fv-content .md-h1 { font-size: 16px; font-weight: bold; color: #fff; margin: 16px 0 8px; }
  #fv-content .md-h2 { font-size: 14px; font-weight: bold; color: #79c0ff; margin: 14px 0 6px; }
  #fv-content .md-h3 { font-size: 13px; font-weight: bold; color: #ffa657; margin: 10px 0 4px; }
  #fv-content .md-bold { color: #fff; font-weight: bold; }
  #fv-content .md-hr { border: none; border-top: 1px solid #30363d; margin: 12px 0; }
</style>
</head>
<body>
<div id="header">
  <h1>AUTORESEARCH MONITOR</h1>
  <span class="meta" id="hd-initiative">—</span>
  <span class="meta" id="hd-round">—</span>
  <span class="meta">best: <span class="best" id="hd-best">—</span></span>
  <span class="meta cost" id="hd-cost">$0.00</span>
  <span class="meta doc-link" id="hd-doc" onclick="openBestDoc()">📄 best document</span>
  <div id="pulse"></div>
</div>
<div id="statusbar">
  <span id="sb-strategy">—</span>
  <span id="sb-eval">—</span>
  <span id="sb-parallelism">—</span>
  <span id="sb-experiments">—</span>
  <span id="sb-streak">—</span>
  <span id="sb-branch">—</span>
</div>
<div id="main">
  <div id="left-col">
    <div id="workers-section">
      <div id="workers-title">WORKERS</div>
      <div id="workers-grid"><div class="waiting">Waiting for orchestrator to start...</div></div>
    </div>
    <div id="log-section-left">
      <div class="section-title">EXPERIMENT LOG</div>
      <div id="log-inner"><div class="waiting">No experiments yet...</div></div>
    </div>
  </div>
  <div id="right-col">
    <div id="events-section">
      <div class="section-title">EVENTS</div>
      <div id="events-inner"><div class="waiting">Waiting for events...</div></div>
    </div>
  </div>
</div>
<!-- File viewer panel -->
<div id="file-viewer">
  <div id="fv-header">
    <span id="fv-title">—</span>
    <button id="fv-refresh" onclick="refreshFile()">↻ refresh</button>
    <span id="fv-close" onclick="closeFile()">✕</span>
  </div>
  <div id="fv-body">
    <pre id="fv-content"></pre>
  </div>
</div>
<script>
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

let _currentFile = null;
let _bestDocPath = null;

function openBestDoc() {
  if (_bestDocPath) openFile(_bestDocPath);
}

function openFile(path) {
  if (!path) return;
  _currentFile = path;
  document.getElementById('fv-title').textContent = path.split('/').slice(-3).join('/');
  document.getElementById('fv-content').textContent = 'Loading...';
  document.getElementById('file-viewer').classList.add('open');
  fetchFile(path);
}

function renderMd(text) {
  // Basic markdown rendering for readability
  return text.split('\n').map(line => {
    const e = esc(line);
    if (/^# /.test(line)) return `<div class="md-h1">${e.slice(2)}</div>`;
    if (/^## /.test(line)) return `<div class="md-h2">${e.slice(3)}</div>`;
    if (/^### /.test(line)) return `<div class="md-h3">${e.slice(4)}</div>`;
    if (/^---\s*$/.test(line)) return `<hr class="md-hr">`;
    // Bold: **text**
    return e.replace(/\*\*(.+?)\*\*/g, '<span class="md-bold">$1</span>');
  }).join('\n');
}

function fetchFile(path) {
  fetch('/file?path=' + encodeURIComponent(path))
    .then(r => {
      if (!r.ok) return `(HTTP ${r.status})`;
      return r.text();
    })
    .then(text => {
      const el = document.getElementById('fv-content');
      if (path.endsWith('.md')) {
        el.innerHTML = renderMd(text || '(empty file)');
      } else {
        el.textContent = text || '(empty file)';
      }
    })
    .catch(e => { document.getElementById('fv-content').textContent = '(fetch error: ' + e + ')'; });
}

function refreshFile() {
  if (_currentFile) fetchFile(_currentFile);
}

function closeFile() {
  document.getElementById('file-viewer').classList.remove('open');
  _currentFile = null;
}

function toolHtml(tool, isLast, isDone) {
  const prefix = (isLast && !isDone) ? '▸' : '●';
  const cls = (isLast && !isDone) ? 'tool-active' : 'tool-done';
  const text = esc(typeof tool === 'object' ? (tool.text || '') : String(tool));
  const filePath = typeof tool === 'object' ? tool.file : null;
  // Assistant text snippets get special styling
  if (text.startsWith('💬')) {
    return `<div class="tool-thought">${text}</div>`;
  }
  if (filePath) {
    return `<div class="tool-line ${cls}"><span class="tool-link" data-file="${esc(filePath)}">${prefix} ${text}</span></div>`;
  }
  return `<div class="tool-line ${cls}">${prefix} ${text}</div>`;
}

function renderWorkers(data) {
  const grid = document.getElementById('workers-grid');
  const workers = data.workers || [];
  const merge = data.merge_active;

  if (!workers.length && !merge) {
    grid.innerHTML = '<div class="waiting">Waiting for round to start...</div>';
    return;
  }

  let html = '';
  for (const w of workers) {
    const biasClass = 'bias-' + (w.role_bias || 'UNKNOWN');
    let statusHtml = '';
    if (w.done) {
      const sc = w.score != null ? ` score=${w.score.toFixed(3)}` : '';
      const co = w.cost != null ? ` $${w.cost.toFixed(3)}` : '';
      const tu = w.num_turns != null ? ` ${w.num_turns}t` : '';
      const dc = {keep:'done-keep',discard:'done-discard',crash:'done-crash',timeout:'done-timeout'}[w.result_type] || 'done-keep';
      const resultLabel = w.result_type === 'discard' ? 'contributed' : w.result_type;
      statusHtml = `<span class="done-tag ${dc}">✓ ${esc(resultLabel)}${sc}${co}${tu}</span>`;
    } else {
      statusHtml = `<span class="running-tag">running ${esc(w.elapsed)}</span>`;
    }
    const tools = (w.tools || []).map((t, i) =>
      toolHtml(t, i === w.tools.length - 1, w.done)
    ).join('');
    const hyp = w.hypothesis ? `<div class="hypothesis">${esc(w.hypothesis)}</div>` : '';
    html += `
      <div class="worker-card${w.done?' done':''}">
        <div class="whead">
          <span>worker-${w.worker_num}</span>
          <span class="${biasClass}">${esc(w.role_bias)}</span>
          ${statusHtml}
        </div>
        ${hyp}
        ${tools}
      </div>`;
  }

  if (merge) {
    const mtools = (data.merge_tools || []).map((t, i) =>
      toolHtml(t, i === data.merge_tools.length - 1, false)
    ).join('');
    html += `
      <div class="merge-card">
        <div class="merge-head">⟳ MERGE  round ${data.merge_round}  <span class="running-tag">running ${esc(data.merge_elapsed||'')}</span></div>
        ${mtools}
      </div>`;
  }

  grid.innerHTML = html;
}

function renderLog(data) {
  const inner = document.getElementById('log-inner');
  const entries = data.log_entries || [];
  if (!entries.length) {
    inner.innerHTML = '<div class="waiting">No experiments completed yet...</div>';
    return;
  }
  inner.innerHTML = entries.map(e => {
    const status = e.status || '';
    const kept = status === 'keep';
    const discarded = status === 'discard';
    const crashed = status === 'crash' || status === 'timeout';
    const score = e.score != null ? e.score.toFixed(1) : '?';
    const improved = e.improved;
    const hyp = (e.hypothesis || '').trim();
    const worker = e.worker || '?';
    const round = e.round || '?';

    let badge, borderColor;
    if (kept && improved) { badge = `<span style="color:#39d353;font-weight:bold">✓ KEPT  score ${score} ↑ new best</span>`; borderColor = '#39d353'; }
    else if (kept) { badge = `<span style="color:#39d353">✓ KEPT  score ${score}</span>`; borderColor = '#39d353'; }
    else if (discarded) { badge = `<span style="color:#8b949e">~ CONTRIBUTED  score ${score} <span style="font-size:10px">(merged in, no new best)</span></span>`; borderColor = '#444'; }
    else if (crashed) { badge = `<span style="color:#f85149;font-weight:bold">💥 ${status.toUpperCase()}</span>`; borderColor = '#f85149'; }
    else { badge = `<span style="color:#8b949e">${esc(status)}  score ${score}</span>`; borderColor = '#30363d'; }

    return `<div class="log-entry" style="border-left:3px solid ${borderColor};padding-left:8px;margin-bottom:6px;border-bottom:none">
      <div style="margin-bottom:2px">${badge} &nbsp; <span style="color:#6e7681;font-size:10px">round ${round}, worker ${worker}</span></div>
      <div style="color:#c9d1d9;font-size:11px;line-height:1.4">${esc(hyp)}</div>
    </div>`;
  }).join('');
  inner.scrollTop = inner.scrollHeight;
}

function humanEvent(line) {
  // Convert raw debug log lines into readable sentences
  if (/round_start/.test(line)) {
    const r = line.match(/round=(\d+)/); const b = line.match(/best=([\d.]+)/);
    return { text: `Round ${r?r[1]:'?'} started — best score so far: ${b?b[1]:'?'}`, cls: 'event-important' };
  }
  if (/worker_launch/.test(line)) {
    const w = line.match(/worker=(\d+)/); const bias = line.match(/\[(\w+)\]/); const exp = line.match(/exp=([\w-]+)/);
    return { text: `Worker ${w?w[1]:'?'} launched (${bias?bias[1]:'?'})`, cls: 'event-important' };
  }
  if (/worker_result/.test(line)) {
    const w = line.match(/worker=(\d+)/); const s = line.match(/score=([\d.]+)/);
    return { text: `Worker ${w?w[1]:'?'} finished — score ${s?s[1]:'?'}`, cls: 'event-line' };
  }
  if (/merge_start/.test(line)) {
    const p = line.match(/passing=(\[[\d, ]+\])/);
    return { text: `Merge started — combining results from workers ${p?p[1]:'?'}`, cls: 'event-important' };
  }
  if (/merge_done/.test(line)) {
    const b = line.match(/new_best=([\d.]+)/);
    return { text: `Merge done — new best score: ${b?b[1]:'?'}`, cls: 'event-good' };
  }
  if (/promoted/.test(line)) {
    const w = line.match(/worker=(\d+)/); const b = line.match(/new_best=([\d.]+)/);
    return { text: `Worker ${w?w[1]:'?'} promoted — new best: ${b?b[1]:'?'}`, cls: 'event-good' };
  }
  if (/no_improvement/.test(line)) {
    const s = line.match(/streak=(\d+)/);
    return { text: `No new best this round (streak: ${s?s[1]:'?'} rounds without improvement)`, cls: 'event-line' };
  }
  if (/round_end/.test(line)) {
    const c = line.match(/cost=\$([\d.]+)/); const ca = line.match(/cache=(\d+%)/);
    return { text: `Round complete — total cost ${c?'$'+c[1]:'?'}, cache hit ${ca?ca[1]:'?'}`, cls: 'event-good' };
  }
  if (/forced_pivot/.test(line)) {
    return { text: `Forced pivot to new branch (stuck on same score too long)`, cls: 'event-error' };
  }
  if (/worker_crash|worker_timeout/.test(line)) {
    const w = line.match(/worker=(\d+)/);
    return { text: `Worker ${w?w[1]:'?'} ${/crash/.test(line)?'crashed':'timed out'}`, cls: 'event-error' };
  }
  if (/init_output/.test(line)) {
    const msg = line.replace(/.*init_output\s+/, '');
    return { text: `Init: ${msg}`, cls: 'event-line' };
  }
  return { text: line, cls: 'event-line' };
}

function renderEvents(data) {
  const inner = document.getElementById('events-inner');
  const events = data.debug_events || [];
  if (!events.length) {
    inner.innerHTML = '<div class="waiting">Waiting for events...</div>';
    return;
  }
  inner.innerHTML = events.map(line => {
    const { text, cls } = humanEvent(line);
    return `<div class="${cls}" style="padding:2px 0;border-bottom:1px solid #161b22">${esc(text)}</div>`;
  }).join('');
  inner.scrollTop = inner.scrollHeight;
}

function update(data) {
  document.getElementById('hd-initiative').textContent = data.initiative || '—';
  const rnd = data.max_rounds ? `round ${data.round_num}/${data.max_rounds}` : `round ${data.round_num}`;
  document.getElementById('hd-round').textContent = rnd;
  if (data.best_doc_path) _bestDocPath = data.best_doc_path;
  document.getElementById('hd-best').textContent = data.best_score != null ? data.best_score.toFixed(2) : '—';
  document.getElementById('hd-cost').textContent = `$${(data.total_cost||0).toFixed(2)}`;
  document.getElementById('sb-strategy').textContent = data.strategy ? `strategy: ${data.strategy}` : '';
  document.getElementById('sb-eval').textContent = data.eval_mode ? `eval: ${data.eval_mode}` : '';
  document.getElementById('sb-parallelism').textContent = data.parallelism ? `parallelism: ${data.parallelism}` : '';
  document.getElementById('sb-experiments').textContent = data.experiment_count ? `experiments: ${data.experiment_count}` : '';
  document.getElementById('sb-streak').textContent = data.discard_streak ? `discard_streak: ${data.discard_streak}` : '';
  document.getElementById('sb-branch').textContent = data.branch ? `branch: ${data.branch}` : '';
  renderWorkers(data);
  renderLog(data);
  renderEvents(data);
}

// Event delegation for file links (works on dynamically injected HTML)
document.addEventListener('click', e => {
  const el = e.target.closest('[data-file]');
  if (el) openFile(el.getAttribute('data-file'));
});

// Poll every second via SSE
const evtSource = new EventSource('/stream');
evtSource.onmessage = (e) => {
  try { update(JSON.parse(e.data)); } catch(ex) { console.error(ex); }
};
evtSource.onerror = () => {
  document.getElementById('pulse').style.background = '#f85149';
};
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    poller: "Poller" = None
    initiative: str = ""

    def log_message(self, format, *args):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    data = self.poller.get_snapshot()
                    data["initiative"] = self.initiative
                    payload = json.dumps(data)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == "/state":
            data = self.poller.get_snapshot()
            data["initiative"] = self.initiative
            body = json.dumps(data, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/file?"):
            from urllib.parse import urlparse, parse_qs, unquote
            qs = parse_qs(urlparse(self.path).query)
            raw_path = unquote(qs.get("path", [""])[0])
            if not raw_path:
                body = b"(no path provided)"
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                return
            file_path = Path(raw_path)
            if not file_path.exists():
                body = b"(file not found)"
                self.send_response(404)
            else:
                try:
                    content = file_path.read_text(errors="replace")
                    body = content.encode()
                    self.send_response(200)
                except Exception as ex:
                    body = f"(error reading file: {ex})".encode()
                    self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()


def main():
    parser = argparse.ArgumentParser(description="Autoresearch web monitor")
    parser.add_argument("project_dir", help="Path to project directory")
    parser.add_argument("initiative", help="Initiative name under autoresearch/")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        print(f"ERROR: project_dir does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    poller = Poller(project_dir=project_dir, initiative=args.initiative)
    poll_thread = threading.Thread(target=poller.run, daemon=True)
    poll_thread.start()

    Handler.poller = poller
    Handler.initiative = args.initiative

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Monitor running at http://localhost:{args.port}")
    print(f"Watching: {project_dir}/autoresearch/{args.initiative}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()


if __name__ == "__main__":
    main()
