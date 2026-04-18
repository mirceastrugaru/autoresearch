"""Session management for Autoresearch API.

Maps ULID-based session IDs to initiative directories on disk.
Registry stored as <data_root>/sessions.json.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SessionManager:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.registry_path = data_root / "sessions.json"
        self._sessions: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.registry_path.exists():
            self._sessions = json.loads(self.registry_path.read_text())
        else:
            self._sessions = {}

    def _save(self):
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(self._sessions, indent=2))

    def create(self, thesis: str) -> dict:
        """Create a new session with scaffolded initiative directory."""
        session_id = str(ULID()).lower()
        name = self._slugify(thesis)
        ar_dir = self.data_root / "autoresearch" / name

        # Don't clobber existing initiative
        if ar_dir.exists():
            name = f"{name}-{session_id[:8]}"
            ar_dir = self.data_root / "autoresearch" / name

        ar_dir.mkdir(parents=True, exist_ok=True)

        # Scaffold program.md
        program_md = f"""# Research Program

## Target
{thesis}

## Metric
Quality and depth of evidence gathered for both sides, scored by rubric.

## Strategy
collaborative

## Measurement
qualitative

## Direction
maximize

## Parallelism
2

## Editable files
- autoresearch/{name}/analysis.md

## Directions to prove

## Directions to disprove

## Rubric

Hard gates (fail any = score 0):
- correctness: no factual errors — every specific claim backed by a named, plausible, verifiable source
- evidence: every non-trivial claim has a specific, named, non-marketing source

Soft gates (each pass = +1 point):
- technical_specificity: concrete details (numbers, versions, measurements), not generalizations
- analytical_reasoning: connects facts into arguments with stated conclusions
- causal_implications: traces cause → effect → consequence with evidence
- investigative_effort: evidence of real digging (source code, commits, APIs, configs) not just summarizing docs pages

Score: 0 (hard gate fail) or 0-N (soft gate count).
"""
        (ar_dir / "program.md").write_text(program_md)

        # Scaffold empty analysis
        (ar_dir / "analysis.md").write_text(f"# {thesis}\n\n*Investigation pending.*\n")

        # Scaffold lockfile
        (ar_dir / "lockfile.txt").write_text("program.md\neval.sh\nlockfile.txt\n")

        # Scaffold eval.sh
        eval_sh = f"""#!/usr/bin/env bash
set -euo pipefail
WORKER_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
/opt/homebrew/bin/python3.13 "$SCRIPT_DIR/../../bin/eval_qualitative.py" "$WORKER_DIR" "$SCRIPT_DIR"
"""
        eval_path = ar_dir / "eval.sh"
        eval_path.write_text(eval_sh)
        eval_path.chmod(0o755)

        now = _now_iso()
        session = {
            "id": session_id,
            "thesis": thesis,
            "initiative": name,
            "ar_dir": str(ar_dir),
            "stage": "design",
            "createdAt": now,
            "updatedAt": now,
        }
        self._sessions[session_id] = session
        self._save()
        return session

    def register_existing(self, ar_dir: Path, thesis: str | None = None) -> dict:
        """Register an existing initiative directory as a session."""
        from bin.program_parser import read_target, infer_stage

        session_id = str(ULID()).lower()
        name = ar_dir.name

        if thesis is None:
            thesis = read_target(ar_dir) or name

        stage = infer_stage(ar_dir)
        now = _now_iso()

        session = {
            "id": session_id,
            "thesis": thesis,
            "initiative": name,
            "ar_dir": str(ar_dir),
            "stage": stage,
            "createdAt": now,
            "updatedAt": now,
        }
        self._sessions[session_id] = session
        self._save()
        return session

    def get(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list_sessions(self, cursor: str | None = None, limit: int = 20) -> tuple[list[dict], str | None]:
        """List sessions, newest first. Returns (items, nextCursor)."""
        all_sessions = sorted(self._sessions.values(), key=lambda s: s["updatedAt"], reverse=True)

        start = 0
        if cursor:
            for i, s in enumerate(all_sessions):
                if s["id"] == cursor:
                    start = i + 1
                    break

        page = all_sessions[start:start + limit]
        next_cursor = page[-1]["id"] if len(page) == limit and start + limit < len(all_sessions) else None
        return page, next_cursor

    def delete(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        self._save()
        return True

    def update(self, session_id: str, **fields) -> dict | None:
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.update(fields)
        session["updatedAt"] = _now_iso()
        self._save()
        return session

    def get_ar_dir(self, session_id: str) -> Path | None:
        session = self.get(session_id)
        if not session:
            return None
        return Path(session["ar_dir"])

    def _slugify(self, text: str) -> str:
        import re
        slug = text.lower().strip()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s]+', '-', slug)
        slug = slug[:60].rstrip('-')
        return slug or "untitled"
