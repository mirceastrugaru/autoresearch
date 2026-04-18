"""Shared parsing functions for autoresearch program.md and related files.

Extracted from orchestrator.py so the API server can import them without
triggering orchestrator preflight checks or importing the Agent SDK.
"""

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ── program.md section parsers ──────────────────────────────────────────────


def read_or(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return default


def _read_program(ar_dir: Path) -> str:
    return (ar_dir / "program.md").read_text()


def parse_editable_files(ar_dir: Path) -> list[str]:
    text = _read_program(ar_dir)
    m = re.search(r"## Editable files\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if not m:
        return []
    return [
        line.strip().lstrip("- ")
        for line in m.group(1).strip().splitlines()
        if line.strip()
    ]


def read_eval_mode(ar_dir: Path) -> str:
    text = _read_program(ar_dir)
    # Try ## Measurement first (current format), fall back to ## Mode (legacy)
    m = re.search(r"## Measurement\s*\n(\w+)", text)
    if not m:
        m = re.search(r"## Mode\s*\n(\w+)", text)
    return m.group(1) if m else "quantitative"


def read_parallelism(ar_dir: Path) -> int:
    text = _read_program(ar_dir)
    m = re.search(r"## Parallelism\s*\n(\d+)", text)
    n = int(m.group(1)) if m else 2
    if n < 2:
        print("ERROR: Parallelism must be at least 2 (1 supportive + 1 adversarial).")
        sys.exit(1)
    if n % 2 != 0:
        print(f"ERROR: Parallelism must be even (got {n}). Supportive/adversarial requires equal split.")
        sys.exit(1)
    return n


def read_direction(ar_dir: Path) -> str:
    text = _read_program(ar_dir)
    m = re.search(r"## Direction\s*\n(\w+)", text)
    return m.group(1).lower() if m else "maximize"


def read_strategy(ar_dir: Path) -> str:
    text = _read_program(ar_dir)
    m = re.search(r"## Strategy\s*\n(\w+)", text)
    if m:
        return m.group(1).lower()
    mode = read_eval_mode(ar_dir)
    return "collaborative" if mode == "qualitative" else "competitive"


def read_target(ar_dir: Path) -> str:
    text = _read_program(ar_dir)
    m = re.search(r"## Target\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def read_metric(ar_dir: Path) -> str:
    text = _read_program(ar_dir)
    m = re.search(r"## Metric\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


# ── Rubric parsing ──────────────────────────────────────────────────────────

REQUIRED_HARD_GATES = {"correctness", "evidence"}
UNIVERSAL_SOFT_GATES = {"technical_specificity", "analytical_reasoning", "causal_implications", "investigative_effort"}


def parse_rubric(ar_dir: Path) -> dict | None:
    """Parse rubric from program.md. Returns {hardGates: [...], softGates: {name: weight}} or None."""
    text = _read_program(ar_dir)
    m = re.search(r"## Rubric\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if not m:
        return None

    rubric_text = m.group(1)

    hard_gates = []
    hard_section = re.search(r"Hard gates.*?:\s*\n(.*?)(?=\nSoft gates|\Z)", rubric_text, re.DOTALL)
    if hard_section:
        for line in hard_section.group(1).strip().splitlines():
            line = line.strip()
            gate_m = re.match(r"-\s*(\w+):\s*(.*)", line)
            if gate_m:
                hard_gates.append(f"{gate_m.group(1)}: {gate_m.group(2)}")

    soft_gates = {}
    soft_section = re.search(r"Soft gates.*?:\s*\n(.*?)(?=\nScore:|\Z)", rubric_text, re.DOTALL)
    if soft_section:
        for line in soft_section.group(1).strip().splitlines():
            line = line.strip()
            gate_m = re.match(r"-\s*(\w+):\s*(.*)", line)
            if gate_m:
                soft_gates[gate_m.group(1)] = gate_m.group(2)

    return {"hardGates": hard_gates, "softGates": soft_gates}


def validate_rubric(ar_dir: Path):
    """Enforce rubric structure. Raises SystemExit if invalid."""
    text = _read_program(ar_dir)
    m = re.search(r"## Rubric\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if not m:
        print("ERROR: program.md has no ## Rubric section (required for qualitative measurement).")
        sys.exit(1)

    rubric = m.group(1)

    hard_section = re.search(r"Hard gates.*?:\s*\n(.*?)(?=\nSoft gates|\Z)", rubric, re.DOTALL)
    if not hard_section:
        print("ERROR: Rubric missing 'Hard gates' section.")
        sys.exit(1)
    hard_gates = set(re.findall(r"-\s*(\w+):", hard_section.group(1)))

    extra = hard_gates - REQUIRED_HARD_GATES
    missing = REQUIRED_HARD_GATES - hard_gates
    if extra:
        print(f"ERROR: Rubric contains unauthorized hard gates: {extra}")
        print(f"  Only allowed: {REQUIRED_HARD_GATES}")
        sys.exit(1)
    if missing:
        print(f"ERROR: Rubric missing required hard gates: {missing}")
        sys.exit(1)

    soft_section = re.search(r"Soft gates.*?:\s*\n(.*?)(?=\nScore:|\Z)", rubric, re.DOTALL)
    if not soft_section:
        print("ERROR: Rubric missing 'Soft gates' section.")
        sys.exit(1)
    soft_gates = set(re.findall(r"-\s*(\w+):", soft_section.group(1)))
    missing_soft = UNIVERSAL_SOFT_GATES - soft_gates
    if missing_soft:
        print(f"ERROR: Rubric missing universal soft gates: {missing_soft}")
        sys.exit(1)


# ── Roadmap parsing ─────────────────────────────────────────────────────────


def _make_direction_id() -> str:
    """Generate a short unique direction ID."""
    raw = hashlib.md5(f"{time.time()}{id(object())}".encode()).hexdigest()[:6]
    return f"d-{raw}"


def parse_roadmap(ar_dir: Path) -> list[dict]:
    """Parse roadmap.md into a list of directions.
    Returns [{"id": "d-xxxx", "title": "...", "priority": N}].
    Lines with [d-xxxx] prefix preserve their ID. Lines without get looked up
    in the registry or assigned a new ID."""
    roadmap_path = ar_dir / "roadmap.md"
    if not roadmap_path.exists():
        return []
    text = roadmap_path.read_text()
    registry = read_direction_registry(ar_dir)
    registry_by_id = {d["id"]: d for d in registry}

    directions = []
    priority = 0
    in_directions = False
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("## directions") or line.lower().startswith("# roadmap"):
            in_directions = True
            continue
        if line.startswith("## ") and in_directions:
            break
        if not in_directions:
            continue

        # Extract the direction text from numbered or bulleted lines
        title = None
        if re.match(r"^\d+\.\s+", line):
            title = re.sub(r"^\d+\.\s+", "", line).strip()
        elif line.startswith("- "):
            title = line.lstrip("- ").strip()
        if title is None:
            continue

        priority += 1
        if title.startswith("[FLAGGED FOR REVIEW]"):
            title = title.replace("[FLAGGED FOR REVIEW]", "").strip()

        # Extract inline ID if present: [d-xxxx] Title text
        id_match = re.match(r"\[([d]-[a-f0-9]+)\]\s*(.*)", title)
        if id_match:
            dir_id = id_match.group(1)
            title = id_match.group(2).strip()
        else:
            dir_id = None

        # If no inline ID, check if this direction is already registered by title
        if not dir_id:
            for reg in registry:
                if reg["title"].lower() == title.lower():
                    dir_id = reg["id"]
                    break

        if not dir_id:
            dir_id = _make_direction_id()

        directions.append({
            "id": dir_id,
            "title": title,
            "priority": priority,
        })

    return directions


def read_direction_registry(ar_dir: Path) -> list[dict]:
    """Read directions.jsonl registry."""
    path = ar_dir / "directions.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def register_direction(ar_dir: Path, dir_id: str, title: str,
                       parent_id: str | None = None,
                       source: str = "") -> dict:
    """Register a new direction in directions.jsonl. Returns the entry."""
    entry = {
        "id": dir_id,
        "title": title,
        "parent_id": parent_id,
        "source": source,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active",
    }
    with open(ar_dir / "directions.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def sync_directions_from_roadmap(ar_dir: Path, directions: list[dict],
                                  parent_map: dict[str, str] | None = None,
                                  source: str = ""):
    """Ensure all directions from the roadmap are registered.
    parent_map: {dir_id: parent_dir_id} for newly discovered directions."""
    registry = read_direction_registry(ar_dir)
    known_ids = {d["id"] for d in registry}
    parent_map = parent_map or {}
    for d in directions:
        if d["id"] not in known_ids:
            register_direction(
                ar_dir, d["id"], d["title"],
                parent_id=parent_map.get(d["id"]),
                source=source,
            )


def parse_program_directions(ar_dir: Path) -> list[dict]:
    """Parse directions from program.md (## Directions section).
    Each direction gets a stable ID generated once."""
    text = _read_program(ar_dir)
    directions = []

    m = re.search(r"## Directions\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if not m:
        return []
    priority = 0
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        if line.startswith("- "):
            priority += 1
            title = line.lstrip("- ").strip()
            short_title = title.split(" — ")[0] if " — " in title else title
            directions.append({
                "id": _make_direction_id(),
                "text": short_title,
                "fullText": title,
                "priority": priority,
            })
    return directions


# ── Coverage matrix ─────────────────────────────────────────────────────────


def build_coverage_matrix(ar_dir: Path, directions: list[dict]) -> dict[str, int]:
    """Build coverage counts: {direction_id: times_assigned}."""
    matrix = {d["id"]: 0 for d in directions}
    log_path = ar_dir / "log.jsonl"
    if not log_path.exists():
        return matrix
    for line in log_path.read_text().strip().splitlines():
        try:
            entry = json.loads(line)
            did = entry.get("assigned_direction")
            if did and did in matrix:
                matrix[did] += 1
        except (json.JSONDecodeError, KeyError):
            continue
    return matrix


# ── State management ────────────────────────────────────────────────────────


def read_state(ar_dir: Path) -> dict:
    with open(ar_dir / "state.json") as f:
        return json.load(f)


def write_state(ar_dir: Path, state: dict):
    with open(ar_dir / "state.json", "w") as f:
        json.dump(state, f, indent=2)


def read_full_log(ar_dir: Path) -> str:
    p = ar_dir / "log.jsonl"
    if not p.exists():
        return "none yet"
    text = p.read_text().strip()
    return text if text else "none yet"


def read_log_entries(ar_dir: Path) -> list[dict]:
    """Read log.jsonl as a list of parsed dicts."""
    p = ar_dir / "log.jsonl"
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def infer_stage(ar_dir: Path) -> str:
    """Infer the current stage from file-based state."""
    state_path = ar_dir / "state.json"
    if not state_path.exists():
        return "design"

    state = read_state(ar_dir)
    round_num = state.get("round", 0)
    experiment_count = state.get("experiment_count", 0)

    if round_num == 0 and experiment_count == 0:
        return "design"

    # Check if a run is currently active (debug.log has round_start without matching run_complete)
    debug_path = ar_dir / "debug.log"
    if debug_path.exists():
        last_section = None
        for line in debug_path.read_text().strip().splitlines():
            try:
                entry = json.loads(line)
                last_section = entry.get("section")
            except json.JSONDecodeError:
                continue
        if last_section in ("round_start", "worker_launch", "worker_result", "judge_start"):
            return "run"

    # Has experiments completed → review or roadmap
    if experiment_count > 0:
        return "review"

    return "design"
