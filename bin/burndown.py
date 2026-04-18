"""Burndown data aggregation for Autoresearch.

Computes direction coverage per round from log.jsonl and roadmap.md.
"""

import json
import math
from pathlib import Path

from bin.program_parser import parse_roadmap, read_log_entries, read_state


def compute_burndown(ar_dir: Path) -> dict:
    """Compute burndown chart data from log.jsonl and roadmap.md."""
    directions = parse_roadmap(ar_dir)
    entries = read_log_entries(ar_dir)

    if not directions:
        return {
            "rounds": [],
            "velocity": 0,
            "projection": "No directions configured.",
        }

    total_directions = len(directions)

    # Group entries by round
    rounds_data: dict[int, list[dict]] = {}
    for entry in entries:
        r = _infer_round(entry)
        if r not in rounds_data:
            rounds_data[r] = []
        rounds_data[r].append(entry)

    # Track cumulative coverage
    covered_ids: set[str] = set()
    proposed_ids: set[str] = set()

    # Check for proposed directions (those not in original roadmap)
    roadmap_ids = {d["id"] for d in directions}

    # Determine current round
    state_path = ar_dir / "state.json"
    current_round = 0
    if state_path.exists():
        try:
            state = read_state(ar_dir)
            current_round = state.get("round", 0)
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    max_round = max(rounds_data.keys()) if rounds_data else 0

    # Build round-by-round data
    result_rounds = []

    # Start point (round 0)
    result_rounds.append({
        "r": 0,
        "covered": 0,
        "inProgress": 0,
        "queued": total_directions,
        "proposed": 0,
    })

    for r in range(1, max_round + 1):
        r_entries = rounds_data.get(r, [])

        # Mark directions covered this round
        for entry in r_entries:
            d_id = entry.get("assigned_direction", "")
            if d_id:
                covered_ids.add(d_id)

        covered = len(covered_ids & roadmap_ids)
        in_progress = 0  # Can't know for historical data
        queued = total_directions - covered
        proposed = len(proposed_ids)

        round_data = {
            "r": r,
            "covered": covered,
            "inProgress": in_progress,
            "queued": max(0, queued),
            "proposed": proposed,
        }

        if r == current_round:
            round_data["isNow"] = True

        result_rounds.append(round_data)

    # Calculate velocity
    completed_rounds = max_round if max_round > 0 else 1
    velocity = len(covered_ids & roadmap_ids) / completed_rounds if completed_rounds else 0

    # Project one round ahead
    if velocity > 0 and max_round > 0:
        projected_covered = min(total_directions, len(covered_ids & roadmap_ids) + round(velocity))
        remaining = total_directions - projected_covered
        projected_round = max_round + 1

        result_rounds.append({
            "r": projected_round,
            "covered": projected_covered,
            "inProgress": 0,
            "queued": max(0, remaining),
            "proposed": len(proposed_ids),
            "projected": True,
        })

        if remaining <= 0:
            rounds_to_close = 0
        else:
            rounds_to_close = math.ceil(remaining / velocity)
        close_round = max_round + rounds_to_close

        if remaining <= 0:
            projection = f"All {total_directions} directions covered. Investigation complete."
        else:
            projection = f"At current velocity ({velocity:.1f}/round), the {remaining} remaining directions close out by end of round {close_round}. No pivot needed."
    else:
        projection = "No data yet to project velocity."

    return {
        "rounds": result_rounds,
        "velocity": round(velocity, 1),
        "projection": projection,
    }


def _infer_round(entry: dict) -> int:
    """Infer round number from experiment ID or position."""
    exp_id = str(entry.get("experiment_id", ""))

    # Try exp-R-W-hash format
    parts = exp_id.split("-")
    if len(parts) >= 3 and parts[0] == "exp":
        try:
            return int(parts[1])
        except ValueError:
            pass

    # For numeric IDs, estimate: round = ceil(id / 2) assuming parallelism=2
    try:
        eid = int(exp_id)
        return (eid + 1) // 2
    except (ValueError, TypeError):
        return 0
