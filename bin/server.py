"""Autoresearch API server — FastAPI wrapper around file-based orchestrator state."""

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Add parent dir to path so we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from bin.program_parser import (
    parse_editable_files,
    parse_roadmap,
    parse_program_directions,
    parse_rubric,
    read_eval_mode,
    read_parallelism,
    read_direction,
    read_strategy,
    read_target,
    read_metric,
    read_or,
    read_state,
    write_state,
    read_log_entries,
    build_coverage_matrix,
    infer_stage,
)
from bin.sessions import SessionManager
from bin.models import (
    SessionCreate,
    ConfigUpdate,
    DirectionCreate,
    DirectionUpdate,
    RubricUpdate,
    EstimateResponse,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_direction_text(text: str) -> str:
    """Strip markdown formatting and tags from direction text."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^\[(REJECTED|RETRY|FLAGGED FOR REVIEW)\]\s*', '', text.strip())
    text = re.sub(r'^\[(REJECTED|RETRY|FLAGGED FOR REVIEW)\]\s*', '', text.strip())
    return text.strip()


# ── App setup ───────────────────────────────────────────────────────────────

DATA_ROOT = Path(os.environ.get("AUTORESEARCH_DATA_ROOT", "/tmp/autoresearch-server"))

_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _get_file_lock(path: str) -> threading.Lock:
    with _file_locks_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]
DATA_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Autoresearch API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

session_mgr = SessionManager(DATA_ROOT)

from bin.run_manager import RunManager, stream_events, _build_workers_snapshot
from bin.chat import ChatEngine

run_mgr = RunManager()
chat_engine = ChatEngine(session_mgr, run_mgr)


def _get_ar_dir(session_id: str) -> Path:
    ar_dir = session_mgr.get_ar_dir(session_id)
    if not ar_dir or not ar_dir.exists():
        raise HTTPException(404, f"Session {session_id} not found")
    return ar_dir


# ── 1. Sessions ─────────────────────────────────────────────────────────────


@app.post("/api/sessions")
def create_session(body: SessionCreate):
    session = session_mgr.create(body.thesis)
    return {
        "id": session["id"],
        "thesis": session["thesis"],
        "stage": session["stage"],
        "createdAt": session["createdAt"],
    }


@app.get("/api/sessions")
def list_sessions(cursor: str | None = None, limit: int = Query(20, le=100)):
    items, next_cursor = session_mgr.list_sessions(cursor, limit)
    return {
        "items": [
            {"id": s["id"], "thesis": s["thesis"], "stage": s.get("stage", "design"), "updatedAt": s["updatedAt"]}
            for s in items
        ],
        "nextCursor": next_cursor,
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    session = session_mgr.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    ar_dir = Path(session["ar_dir"])
    stage = infer_stage(ar_dir) if ar_dir.exists() else "design"

    # Update cached stage
    if stage != session.get("stage"):
        session_mgr.update(session_id, stage=stage)

    config = _build_config(ar_dir) if ar_dir.exists() else None

    run_state = None
    state_path = ar_dir / "state.json"
    if state_path.exists():
        run_state = json.loads(state_path.read_text())

    verdict = None
    verdict_path = ar_dir / "verdict.json"
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text())

    return {
        "id": session["id"],
        "thesis": session["thesis"],
        "stage": stage,
        "config": config,
        "run": run_state,
        "verdict": verdict,
        "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"],
    }


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    if not session_mgr.delete(session_id):
        raise HTTPException(404, "Session not found")
    return Response(status_code=204)


# ── 2. Design stage — config, directions, rubric ───────────────────────────


def _build_config(ar_dir: Path) -> dict:
    """Build config dict from program.md + roadmap."""
    directions = _build_directions_list(ar_dir)
    rubric = parse_rubric(ar_dir)

    return {
        "thesis": read_target(ar_dir),
        "directions": directions,
        "rubric": rubric,
        "rounds": _read_rounds(ar_dir),
        "workersPerRound": read_parallelism(ar_dir),
        "costCap": None,
    }


def _read_rounds(ar_dir: Path) -> int:
    """Read rounds from state.json or default to 10."""
    state_path = ar_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            return state.get("max_rounds", 10)
        except (json.JSONDecodeError, KeyError):
            pass
    return 10


def _build_directions_list(ar_dir: Path) -> list[dict]:
    """Build unified direction list from roadmap.md with coverage data."""
    roadmap_dirs = parse_roadmap(ar_dir)
    program_dirs = parse_program_directions(ar_dir)

    # Use roadmap if available (it's the live version), else program.md
    if roadmap_dirs:
        dirs = roadmap_dirs
    elif program_dirs:
        dirs = program_dirs
    else:
        return []

    # Build coverage matrix
    coverage = build_coverage_matrix(ar_dir, dirs)

    # Determine status from log entries
    log_entries = read_log_entries(ar_dir)
    covered_directions = set()
    for entry in log_entries:
        d_id = entry.get("assigned_direction")
        if d_id and entry.get("status") in ("keep", "discard"):
            covered_directions.add(d_id)

    result = []
    for d in dirs:
        d_id = d["id"]
        stance_map = {"prove": "pro", "disprove": "con"}
        stance = stance_map.get(d.get("stance", ""), d.get("stance", ""))

        status = "queued"
        if d_id in covered_directions:
            status = "covered"

        score = None
        # Find best score for this direction
        for entry in log_entries:
            if entry.get("assigned_direction") == d_id and entry.get("score") is not None:
                s = entry["score"]
                if score is None or s > score:
                    score = s

        raw_text = d.get("title", d.get("text", ""))
        clean_text = _clean_direction_text(raw_text)

        result.append({
            "id": d_id,
            "stance": stance,
            "text": clean_text,
            "status": status,
            "score": score,
            "coverage": coverage.get(d_id, 0),
        })

    return result


@app.get("/api/sessions/{session_id}/config")
def get_config(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    return _build_config(ar_dir)


@app.patch("/api/sessions/{session_id}/config")
def update_config(session_id: str, body: ConfigUpdate):
    ar_dir = _get_ar_dir(session_id)
    program_path = ar_dir / "program.md"
    text = program_path.read_text()

    if body.thesis is not None:
        text = re.sub(r"(## Target\s*\n).*?(\n##)", rf"\g<1>{body.thesis}\n\n\2", text, flags=re.DOTALL)

    if body.workersPerRound is not None:
        text = re.sub(r"(## Parallelism\s*\n)\d+", rf"\g<1>{body.workersPerRound}", text)

    program_path.write_text(text)

    if body.rounds is not None:
        state_path = ar_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            state["max_rounds"] = body.rounds
            state_path.write_text(json.dumps(state, indent=2))

    return _build_config(ar_dir)


@app.post("/api/sessions/{session_id}/directions")
def add_direction(session_id: str, body: DirectionCreate):
    ar_dir = _get_ar_dir(session_id)
    program_path = ar_dir / "program.md"
    lock = _get_file_lock(str(program_path))
    lock.acquire()
    try:
        return _add_direction_locked(ar_dir, program_path, body)
    finally:
        lock.release()


def _add_direction_locked(ar_dir: Path, program_path: Path, body: DirectionCreate):
    text = program_path.read_text()

    # Map stance to section header
    if body.stance in ("pro", "prove"):
        section = "## Directions to prove"
    else:
        section = "## Directions to disprove"

    # Find section and append
    idx = text.find(section)
    if idx == -1:
        text += f"\n{section}\n- {body.text}\n"
    else:
        # Find end of section (next ## or end)
        next_section = text.find("\n##", idx + len(section))
        if next_section == -1:
            text += f"- {body.text}\n"
        else:
            text = text[:next_section] + f"- {body.text}\n" + text[next_section:]

    program_path.write_text(text)

    # Also update roadmap.md if it exists
    roadmap_path = ar_dir / "roadmap.md"
    if roadmap_path.exists():
        roadmap_text = roadmap_path.read_text()
        stance_header = "## Prove" if body.stance in ("pro", "prove") else "## Disprove"
        idx = roadmap_text.find(stance_header)
        if idx != -1:
            next_section = roadmap_text.find("\n##", idx + len(stance_header))
            if next_section == -1:
                roadmap_text += f"\n- {body.text}\n"
            else:
                roadmap_text = roadmap_text[:next_section] + f"- {body.text}\n" + roadmap_text[next_section:]
            roadmap_path.write_text(roadmap_text)

    # Return the new direction
    dirs = _build_directions_list(ar_dir)
    # Find the one we just added
    for d in reversed(dirs):
        if d["text"] == body.text:
            return d

    return {"id": "new", "stance": body.stance, "text": body.text, "status": "queued", "score": None, "coverage": 0}


@app.patch("/api/sessions/{session_id}/directions/{dir_id}")
def update_direction(session_id: str, dir_id: str, body: DirectionUpdate):
    ar_dir = _get_ar_dir(session_id)
    # Parse current directions to find the one to update
    dirs = parse_roadmap(ar_dir)
    target = None
    for d in dirs:
        if d["id"] == dir_id:
            target = d
            break

    if not target:
        raise HTTPException(404, f"Direction {dir_id} not found")

    # Rewrite roadmap.md with updated direction
    roadmap_path = ar_dir / "roadmap.md"
    if roadmap_path.exists():
        text = roadmap_path.read_text()
        old_title = target["title"]
        new_title = body.text if body.text else old_title
        text = text.replace(old_title, new_title)
        roadmap_path.write_text(text)

    return {"id": dir_id, "text": body.text or target["title"], "stance": body.stance or target["stance"]}


@app.delete("/api/sessions/{session_id}/directions/{dir_id}", status_code=204)
def delete_direction(session_id: str, dir_id: str):
    ar_dir = _get_ar_dir(session_id)
    dirs = parse_roadmap(ar_dir)
    target = None
    for d in dirs:
        if d["id"] == dir_id:
            target = d
            break

    if not target:
        raise HTTPException(404, f"Direction {dir_id} not found")

    # Remove from roadmap.md
    roadmap_path = ar_dir / "roadmap.md"
    if roadmap_path.exists():
        lines = roadmap_path.read_text().splitlines()
        new_lines = [l for l in lines if target["title"] not in l]
        roadmap_path.write_text("\n".join(new_lines) + "\n")

    return Response(status_code=204)


@app.post("/api/sessions/{session_id}/directions/suggest")
def suggest_directions(session_id: str):
    # Placeholder — will be wired to Claude in M5
    ar_dir = _get_ar_dir(session_id)
    thesis = read_target(ar_dir)
    return {
        "suggested": [
            {"stance": "pro", "text": f"Evidence supporting: {thesis[:50]}...", "rationale": "Core thesis exploration"},
            {"stance": "con", "text": f"Evidence against: {thesis[:50]}...", "rationale": "Counter-argument exploration"},
        ]
    }


@app.patch("/api/sessions/{session_id}/rubric")
def update_rubric(session_id: str, body: RubricUpdate):
    ar_dir = _get_ar_dir(session_id)
    program_path = ar_dir / "program.md"
    text = program_path.read_text()

    # Rebuild rubric section
    rubric_start = text.find("## Rubric")
    if rubric_start == -1:
        raise HTTPException(400, "No rubric section in program.md")

    rubric_end = text.find("\n##", rubric_start + 10)
    if rubric_end == -1:
        rubric_end = len(text)

    current = parse_rubric(ar_dir)
    if not current:
        raise HTTPException(400, "Could not parse current rubric")

    hard = body.hardGates if body.hardGates is not None else current["hardGates"]
    soft = body.softGates if body.softGates is not None else current["softGates"]

    rubric_text = "## Rubric\n\nHard gates (fail any = score 0):\n"
    for gate in hard:
        rubric_text += f"- {gate}\n"
    rubric_text += "\nSoft gates (each pass = +1 point):\n"
    for name, desc in soft.items():
        rubric_text += f"- {name}: {desc}\n"
    rubric_text += "\nScore: 0 (hard gate fail) or 0-N (soft gate count).\n"

    text = text[:rubric_start] + rubric_text + text[rubric_end:]
    program_path.write_text(text)

    return parse_rubric(ar_dir)


@app.post("/api/sessions/{session_id}/estimate")
def estimate(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    rounds = _read_rounds(ar_dir)
    workers = read_parallelism(ar_dir)
    cost_per_worker = 0.50
    estimated_cost = rounds * workers * cost_per_worker
    estimated_tokens = rounds * workers * 50000
    estimated_duration = rounds * 180  # ~3 min per round

    return EstimateResponse(
        estimatedCost=estimated_cost,
        estimatedTokens=estimated_tokens,
        estimatedDurationSec=estimated_duration,
    )


# ── 4. Review stage — verdict, writeups, documents ─────────────────────────


@app.get("/api/sessions/{session_id}/verdict")
def get_verdict(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    verdict_path = ar_dir / "verdict.json"
    if verdict_path.exists():
        return json.loads(verdict_path.read_text())

    # Generate on-demand for completed runs
    from bin.verdict import generate_verdict
    log_entries = read_log_entries(ar_dir)
    if not log_entries:
        raise HTTPException(404, "No experiments completed yet")
    return generate_verdict(ar_dir)


@app.get("/api/sessions/{session_id}/findings")
def get_findings(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    verdict_path = ar_dir / "verdict.json"
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text())
        return {"items": verdict.get("findings", [])}

    from bin.verdict import generate_verdict
    verdict = generate_verdict(ar_dir)
    return {"items": verdict.get("findings", [])}


@app.get("/api/sessions/{session_id}/arguments")
def get_arguments(session_id: str, stance: str | None = None):
    ar_dir = _get_ar_dir(session_id)
    verdict_path = ar_dir / "verdict.json"
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text())
    else:
        from bin.verdict import generate_verdict
        verdict = generate_verdict(ar_dir)

    args = verdict.get("arguments", {"pro": [], "con": []})
    if stance:
        return {"items": args.get(stance, [])}
    return {"items": args}


@app.get("/api/sessions/{session_id}/next-actions")
def get_next_actions(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    verdict_path = ar_dir / "verdict.json"
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text())
        return {"items": verdict.get("nextActions", [])}

    from bin.verdict import generate_verdict
    verdict = generate_verdict(ar_dir)
    return {"items": verdict.get("nextActions", [])}


@app.get("/api/sessions/{session_id}/writeups")
def list_writeups(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    from bin.writeup_store import list_writeups as _list_writeups
    return {"items": _list_writeups(ar_dir)}


@app.get("/api/sessions/{session_id}/writeups/{writeup_id}")
def get_writeup(session_id: str, writeup_id: str):
    ar_dir = _get_ar_dir(session_id)
    from bin.writeup_store import get_writeup as _get_writeup
    wp = _get_writeup(ar_dir, writeup_id)
    if not wp:
        raise HTTPException(404, f"Writeup {writeup_id} not found")
    return wp


@app.get("/api/sessions/{session_id}/main.md")
def get_main_doc(session_id: str, round: int | None = None):
    ar_dir = _get_ar_dir(session_id)
    editable = parse_editable_files(ar_dir)
    for f in editable:
        best_path = ar_dir / "best" / f
        if best_path.exists():
            content = best_path.read_text()
            return Response(content=content, media_type="text/markdown")
    raise HTTPException(404, "No main document found")


@app.get("/api/sessions/{session_id}/meta.md")
def get_meta_doc(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    meta_path = ar_dir / "meta.md"
    if not meta_path.exists():
        raise HTTPException(404, "No meta document found")
    return Response(content=meta_path.read_text(), media_type="text/markdown")


@app.get("/api/sessions/{session_id}/export")
def export_report(session_id: str, format: str = "md"):
    ar_dir = _get_ar_dir(session_id)
    editable = parse_editable_files(ar_dir)
    for f in editable:
        best_path = ar_dir / "best" / f
        if best_path.exists():
            content = best_path.read_text()
            filename = f"autoresearch-report.{format}"
            return Response(
                content=content,
                media_type="text/markdown",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
    raise HTTPException(404, "No report to export")


# ── 5. Roadmap stage ───────────────────────────────────────────────────────


@app.get("/api/sessions/{session_id}/directions")
def get_directions(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    return {"items": _build_directions_list(ar_dir)}


@app.post("/api/sessions/{session_id}/directions/rerank")
def rerank_directions(session_id: str):
    # Placeholder — will be wired to Claude judge in M5
    ar_dir = _get_ar_dir(session_id)
    return {"items": _build_directions_list(ar_dir)}


@app.post("/api/sessions/{session_id}/directions/{dir_id}/promote")
def promote_direction(session_id: str, dir_id: str):
    ar_dir = _get_ar_dir(session_id)
    roadmap_path = ar_dir / "roadmap.md"
    if not roadmap_path.exists():
        raise HTTPException(404, "No roadmap found")

    # Find direction in roadmap
    dirs = parse_roadmap(ar_dir)
    target = None
    for d in dirs:
        if d["id"] == dir_id:
            target = d
            break
    if not target:
        raise HTTPException(404, f"Direction {dir_id} not found")

    return {"id": dir_id, "status": "queued"}


@app.post("/api/sessions/{session_id}/directions/{dir_id}/reject")
def reject_direction(session_id: str, dir_id: str):
    ar_dir = _get_ar_dir(session_id)
    roadmap_path = ar_dir / "roadmap.md"
    if not roadmap_path.exists():
        raise HTTPException(404, "No roadmap found")

    # Mark as rejected by prepending [REJECTED] in roadmap.md
    dirs = parse_roadmap(ar_dir)
    target = None
    for d in dirs:
        if d["id"] == dir_id:
            target = d
            break
    if not target:
        raise HTTPException(404, f"Direction {dir_id} not found")

    text = roadmap_path.read_text()
    text = text.replace(target["title"], f"[REJECTED] {target['title']}")
    roadmap_path.write_text(text)

    return {"id": dir_id, "status": "rejected"}


@app.get("/api/sessions/{session_id}/burndown")
def get_burndown(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    from bin.burndown import compute_burndown
    return compute_burndown(ar_dir)


@app.post("/api/sessions/{session_id}/rounds")
def add_rounds(session_id: str, body: dict):
    ar_dir = _get_ar_dir(session_id)
    count = body.get("count", 1)
    state_path = ar_dir / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        state["max_rounds"] = state.get("max_rounds", 10) + count
        state_path.write_text(json.dumps(state, indent=2))
    return _build_config(ar_dir)


# ── 3. Execution — control + live stream ───────────────────────────────────


@app.post("/api/sessions/{session_id}/run")
def start_run(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    if run_mgr.is_running(session_id):
        raise HTTPException(409, "Run already in progress")

    config = _build_config(ar_dir)
    result = run_mgr.start_run(
        session_id, ar_dir,
        rounds=config.get("rounds", 10) if isinstance(config, dict) else 10,
        workers=config.get("workersPerRound") if isinstance(config, dict) else None,
    )
    if "error" in result:
        raise HTTPException(result.get("status", 500), result["error"])

    session_mgr.update(session_id, stage="run")
    return result


@app.post("/api/sessions/{session_id}/pause")
def pause_run(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    if not run_mgr.pause_run(session_id):
        # Create sentinel directly even if not tracking the process
        (ar_dir / "pause_requested").write_text("paused")
    return {"status": "pausing"}


@app.post("/api/sessions/{session_id}/resume")
def resume_run(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    run_mgr.resume_run(session_id)
    sentinel = ar_dir / "pause_requested"
    if sentinel.exists():
        sentinel.unlink()
    return {"status": "resumed"}


@app.post("/api/sessions/{session_id}/stop")
def stop_run(session_id: str):
    if not run_mgr.stop_run(session_id):
        raise HTTPException(400, "No active run to stop")
    session_mgr.update(session_id, stage="review")
    return {"status": "stopped"}


@app.get("/api/sessions/{session_id}/stream")
async def stream(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    return StreamingResponse(
        stream_events(ar_dir),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/sessions/{session_id}/workers")
def get_workers(session_id: str):
    ar_dir = _get_ar_dir(session_id)
    return _build_workers_snapshot(ar_dir)


@app.get("/api/sessions/{session_id}/activity")
def get_activity(session_id: str, cursor: str | None = None, limit: int = Query(100, le=500)):
    ar_dir = _get_ar_dir(session_id)
    debug_path = ar_dir / "debug.log"
    if not debug_path.exists():
        return {"items": [], "nextCursor": None}

    items = []
    for line in debug_path.read_text().strip().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        section = e.get("section", "")
        ts = e.get("ts", "")[:19].replace("T", " ")

        if section == "worker_launch":
            items.append({
                "t": ts, "who": f"w{e.get('worker')}", "stance": e.get("stance", ""),
                "msg": f"Started experiment {e.get('exp_id', '')}",
            })
        elif section == "worker_result":
            items.append({
                "t": ts, "who": f"w{e.get('worker')}", "stance": e.get("stance", ""),
                "msg": f"Completed (score={e.get('score', '?')})",
            })
        elif section == "judge_start":
            items.append({"t": ts, "who": "judge", "msg": "Scoring write-ups"})
        elif section == "round_start":
            items.append({"t": ts, "who": "system", "msg": f"Round {e.get('round')} started"})

    # Newest first
    items.reverse()
    return {"items": items[:limit], "nextCursor": None}


# ── Register existing initiatives ───────────────────────────────────────────


@app.post("/api/sessions/register")
def register_existing(ar_dir: str, thesis: str | None = None):
    """Register an existing initiative directory as a session."""
    path = Path(ar_dir)
    if not path.exists() or not (path / "program.md").exists():
        raise HTTPException(400, f"Not a valid initiative directory: {ar_dir}")
    session = session_mgr.register_existing(path, thesis)
    return {
        "id": session["id"],
        "thesis": session["thesis"],
        "stage": session["stage"],
        "createdAt": session["createdAt"],
    }


# ── 6. Chat ─────────────────────────────────────────────────────────────────


@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str, cursor: str | None = None, limit: int = Query(50, le=200)):
    ar_dir = _get_ar_dir(session_id)
    items, next_cursor = chat_engine.get_history(ar_dir, cursor, limit)
    return {"items": items, "nextCursor": next_cursor}


@app.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, body: dict):
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "Message text required")

    return StreamingResponse(
        chat_engine.send_message(session_id, text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f"Starting Autoresearch API server on port {port}")
    print(f"Data root: {DATA_ROOT}")
    uvicorn.run(app, host="0.0.0.0", port=port)
