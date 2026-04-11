#!/usr/bin/env python3
"""Autoresearch orchestrator — Claude Agent SDK with parallel workers and prompt caching."""

import asyncio
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

    # API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        errors.append(
            "ANTHROPIC_API_KEY not set.\n"
            "  Get one at: https://console.anthropic.com/settings/keys\n"
            "  Then: export ANTHROPIC_API_KEY=sk-ant-api03-..."
        )

    # Prompt templates
    prompts_dir = Path(__file__).parent.parent / "prompts"
    for name in ("init.md", "experiment.md", "summarize.md"):
        if not (prompts_dir / name).exists():
            errors.append(f"Missing prompt template: {prompts_dir / name}")

    # Project config — skip detailed checks here, main() handles initiative discovery

    if errors:
        print("PREFLIGHT FAILED:\n")
        for i, e in enumerate(errors, 1):
            print(f"  {i}. {e}\n")
        sys.exit(1)


preflight()

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

# ── Constants ────────────────────────────────────────────────────────────────

MODEL = os.environ.get("AUTORESEARCH_MODEL", "claude-sonnet-4-5-20250929")
SUMMARIZE_EVERY = 5
DISCARD_STREAK_WARN = 3
DISCARD_STREAK_PIVOT = 5
PLATEAU_THRESHOLD = 8
REVALIDATE_EVERY = 10
NOISE_THRESHOLD = 0.01
LOG_TAIL_SIZE = 10

# ── Agent runner ─────────────────────────────────────────────────────────────


async def run_agent(
    system_prompt: str,
    user_prompt: str,
    cwd: str | Path,
    name: str = "agent",
) -> tuple[str, ResultMessage | None]:
    """Run an agent to completion. Returns (result_text, result_message)."""
    result_msg = None
    try:
        async for msg in query(
            prompt=user_prompt,
            options=ClaudeAgentOptions(
                model=MODEL,
                system_prompt=system_prompt,
                permission_mode="bypassPermissions",
                cwd=str(cwd),
                max_turns=50,
                extra_args={"no-session-persistence": None},
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_msg = msg
    except Exception as e:
        print(f"    [{name}] ERROR: {e}")
        return f"Agent error: {e}", None

    result_text = result_msg.result if result_msg and result_msg.result else ""
    cost = result_msg.total_cost_usd if result_msg else 0
    duration = result_msg.duration_ms if result_msg else 0
    print(f"    [{name}] done ({duration}ms, ${cost:.4f})")
    return result_text, result_msg


# ── Program.md parsing ───────────────────────────────────────────────────────


def parse_editable_files(ar_dir: Path) -> list[str]:
    text = (ar_dir / "program.md").read_text()
    m = re.search(r"## Editable files\s*\n(.*?)(\n##|\Z)", text, re.DOTALL)
    if not m:
        return []
    return [
        line.strip().lstrip("- ")
        for line in m.group(1).strip().splitlines()
        if line.strip()
    ]


def read_eval_mode(ar_dir: Path) -> str:
    text = (ar_dir / "program.md").read_text()
    m = re.search(r"## Mode\s*\n(\w+)", text)
    return m.group(1) if m else "quantitative"


def read_parallelism(ar_dir: Path) -> int:
    text = (ar_dir / "program.md").read_text()
    m = re.search(r"## Parallelism\s*\n(\d+)", text)
    return int(m.group(1)) if m else 3


def read_direction(ar_dir: Path) -> str:
    """Read optimization direction from program.md. Returns 'maximize' or 'minimize'."""
    text = (ar_dir / "program.md").read_text()
    m = re.search(r"## Direction\s*\n(\w+)", text)
    return m.group(1).lower() if m else "maximize"


# ── File helpers ─────────────────────────────────────────────────────────────


def read_or(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return default


def read_log_tail(ar_dir: Path, n: int) -> str:
    p = ar_dir / "log.jsonl"
    if not p.exists():
        return "none yet"
    lines = p.read_text().strip().splitlines()
    return "\n".join(lines[-n:]) if lines else "none yet"


# ── State management ─────────────────────────────────────────────────────────


def read_state(ar_dir: Path) -> dict:
    with open(ar_dir / "state.json") as f:
        return json.load(f)


def write_state(ar_dir: Path, state: dict):
    with open(ar_dir / "state.json", "w") as f:
        json.dump(state, f, indent=2)


def append_log(ar_dir: Path, entry: dict):
    entry["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with open(ar_dir / "log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def append_branch(ar_dir: Path, entry: dict):
    with open(ar_dir / "branches.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Critique checks (pure Python, no LLM) ───────────────────────────────────


def check_lockfile_violation(diff_text: str, ar_dir: Path) -> bool:
    lf = ar_dir / "lockfile.txt"
    if not lf.exists():
        return False
    locked = [l.strip() for l in lf.read_text().splitlines() if l.strip()]
    changed = re.findall(r"^[+-]{3} (?:a/|b/)?(.+)", diff_text, re.MULTILINE)
    changed += re.findall(r"^File: (.+)", diff_text, re.MULTILINE)
    for c in changed:
        c = c.strip()
        for l in locked:
            if c == l or c.endswith("/" + l):
                return True
    return False


def check_safety_violation(diff_text: str) -> bool:
    forbidden = [
        "eval.sh", "lockfile.txt", "program.md", "best_score.txt",
        "state.json", "log.jsonl", "branches.jsonl",
    ]
    changed = re.findall(r"^[+-]{3} (?:a/|b/)?(.+)", diff_text, re.MULTILINE)
    changed += re.findall(r"^File: (.+)", diff_text, re.MULTILINE)
    for c in changed:
        c = c.strip()
        for f in forbidden:
            if c == f or c.endswith("/" + f):
                return True
    return False


def check_noise(new_score: float, best_score: float, direction: str = "maximize") -> bool:
    if best_score == 0:
        return new_score != 0
    delta = (new_score - best_score) / abs(best_score)
    if direction == "minimize":
        return delta < -NOISE_THRESHOLD
    return delta > NOISE_THRESHOLD


# ── Worker management ────────────────────────────────────────────────────────


def prepare_workers(ar_dir: Path, active_branch: str, parallelism: int):
    workers = ar_dir / "workers"
    if workers.exists():
        shutil.rmtree(workers)
    branch_dir = ar_dir / "branches" / active_branch
    for i in range(1, parallelism + 1):
        wdir = workers / f"worker-{i}"
        wdir.mkdir(parents=True)
        if branch_dir.exists():
            for item in branch_dir.iterdir():
                dest = wdir / item.name
                if item.is_file():
                    shutil.copy2(item, dest)
                elif item.is_dir():
                    shutil.copytree(item, dest)


# Files created by the orchestrator/experiment protocol — not project code
WORKER_META_FILES = {
    "experiment_id.txt", "experiment_id_output.txt",
    "latest_score.txt", "latest_status.txt", "latest_hypothesis.txt",
    "latest_diff.txt", "latest_parent.txt", "eval_scores.json",
}


def promote_worker(wdir: Path, ar_dir: Path, active_branch: str):
    """Copy all project files from worker to best/ and branch/, skipping orchestrator metadata."""
    for src in wdir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(wdir)
        if rel.name in WORKER_META_FILES:
            continue
        for dest_base in [ar_dir / "best", ar_dir / "branches" / active_branch]:
            dest = dest_base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def cleanup_workers(ar_dir: Path):
    w = ar_dir / "workers"
    if w.exists():
        shutil.rmtree(w)


# ── Convergence ──────────────────────────────────────────────────────────────


def force_pivot(state: dict, ar_dir: Path, project_dir: Path):
    new_branch = f"pivot-{state['experiment_count']}"
    print(f"\n=== FORCED PIVOT: '{new_branch}' from baseline ===")

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


# ── Main ─────────────────────────────────────────────────────────────────────


async def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("Usage: orchestrator.py [rounds] [project-dir] [initiative-name]")
        print()
        print("  rounds           Number of experiment rounds (default: 10)")
        print("                   Each round runs N parallel experiments (default N=3)")
        print("  project-dir      Path to project with autoresearch/ config (default: cwd)")
        print("  initiative-name  Name of the research initiative (default: auto-detect)")
        print("                   Each initiative lives in autoresearch/<name>/")
        print()
        print("Environment:")
        print("  ANTHROPIC_API_KEY     Required. Get from console.anthropic.com/settings/keys")
        print("  AUTORESEARCH_MODEL    Model to use (default: claude-sonnet-4-5-20250929)")
        print()
        print("Setup: run /autoresearch:design in Claude Code first to create config files.")
        sys.exit(0)

    max_rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    project_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()
    initiative_name = sys.argv[3] if len(sys.argv) > 3 else None

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
    init_skill = (prompts_dir / "init.md").read_text()
    experiment_skill = (prompts_dir / "experiment.md").read_text()
    summarize_skill = (prompts_dir / "summarize.md").read_text()

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
        state["parallelism"] = read_parallelism(ar_dir)
        state["direction"] = read_direction(ar_dir)
        print(f"  Round: {state['round']} / Experiments: {state['experiment_count']} / Best: {state['best_score']}")
        print(f"  Branch: {state['active_branch']} / Discard streak: {state['discard_streak']}")
    else:
        eval_mode = read_eval_mode(ar_dir)
        parallelism = read_parallelism(ar_dir)
        direction = read_direction(ar_dir)
        print(f"Eval mode: {eval_mode} / Parallelism: {parallelism} / Direction: {direction}")
        print("\n--- INIT ---")

        output, _ = await run_agent(
            system_prompt=init_skill,
            user_prompt=(
                f"Initialize the autoresearch project.\n"
                f"Project directory: {project_dir}\n"
                f"Autoresearch directory: {ar_dir}\n"
                f"Eval mode: {eval_mode}\n"
                f"Parallelism: {parallelism}"
            ),
            cwd=project_dir,
            name="init",
        )
        print(output)

        if not state_file.exists():
            print("INIT FAILED: state.json not created. Aborting.")
            sys.exit(1)

        state = read_state(ar_dir)
        state["direction"] = direction
        print(f"Baseline score: {state['best_score']}")

    # ── Phase 2: Experiment loop ──

    round_num = state["round"]
    total_cost = 0.0

    while round_num < max_rounds:
        round_num += 1
        state["round"] = round_num
        parallelism = state["parallelism"]

        print(f"\n{'=' * 50}")
        print(f"  ROUND {round_num}/{max_rounds}  (experiments: {state['experiment_count']}, best: {state['best_score']:.2f})")
        print(f"{'=' * 50}")

        # Convergence
        if state["discard_streak"] >= DISCARD_STREAK_PIVOT:
            force_pivot(state, ar_dir, project_dir)
        elif state["best_unchanged_count"] >= PLATEAU_THRESHOLD:
            force_pivot(state, ar_dir, project_dir)

        if state["experiment_count"] > 0 and state["experiment_count"] % REVALIDATE_EVERY == 0:
            revalidate_best(ar_dir, state)

        # Prepare workers
        prepare_workers(ar_dir, state["active_branch"], parallelism)

        # Build guardrail message if needed
        guardrail_msg = ""
        if state["discard_streak"] >= DISCARD_STREAK_PIVOT:
            guardrail_msg = (
                f"\nCRITICAL: {state['discard_streak']} consecutive rounds with no improvement. Strategy pivot forced.\n"
                f"You are on a new branch forked from baseline. You MUST:\n"
                f"1. List the assumptions the previous strategy was based on.\n"
                f"2. INVERT at least one core assumption as your hypothesis.\n"
                f"3. Check parking_lot.md for deferred ideas.\n"
                f"Do NOT try minor variants of what already failed."
            )
        elif state["discard_streak"] >= DISCARD_STREAK_WARN:
            guardrail_msg = (
                f"\nWARNING: {state['discard_streak']} consecutive rounds with no improvement.\n"
                f"Before your next hypothesis, write an assumptions list: what does the current approach assume?\n"
                f"Try inverting an assumption, or pick an idea from parking_lot.md."
            )

        # Launch parallel workers
        tasks = []
        exp_ids = []
        for i in range(1, parallelism + 1):
            wdir = ar_dir / "workers" / f"worker-{i}"
            exp_num = state["experiment_count"] + i
            exp_id = f"exp-{round_num}-{i}-{hashlib.md5(f'{time.time()}{i}'.encode()).hexdigest()[:8]}"
            exp_ids.append(exp_id)
            (wdir / "experiment_id.txt").write_text(exp_id)

            # Determine parent experiment (the last promoted experiment, or 0 for baseline)
            parent_exp = state.get("last_promoted_experiment", 0)

            user_msg = (
                f"Run experiment {exp_num} (ID: {exp_id}).\n"
                f"Worker directory: {wdir}\n"
                f"Autoresearch directory: {ar_dir}\n"
                f"Eval command: bash {ar_dir}/eval.sh {wdir}\n"
                f"Active branch: {state['active_branch']}\n"
                f"Current best score: {state['best_score']}\n"
                f"Parent experiment: #{parent_exp}\n"
                f"{guardrail_msg}\n\n"
                f"Read {ar_dir}/program.md for research directions and editable files.\n"
                f"Read {ar_dir}/log.jsonl (last 10 lines) for recent experiment history.\n"
                f"Read {ar_dir}/findings.md for summary of what's been tried.\n"
                f"Read {ar_dir}/parking_lot.md for deferred ideas (if it exists).\n\n"
                f"CRITICAL: Write '{exp_id}' to {wdir}/experiment_id_output.txt as your LAST action."
            )

            print(f"  Launching worker-{i} (experiment {exp_num})...")
            tasks.append(
                run_agent(
                    system_prompt=experiment_skill,
                    user_prompt=user_msg,
                    cwd=wdir,
                    name=f"worker-{i}",
                )
            )

        print(f"  Waiting for {parallelism} workers...")
        t0 = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - t0
        print(f"  All workers done. ({elapsed:.1f}s)")

        # Track costs
        for r in results:
            if not isinstance(r, Exception) and r[1] is not None:
                total_cost += r[1].total_cost_usd or 0

        # Collect results
        best_worker = None
        best_worker_score = None
        round_had_improvement = False

        for i in range(1, parallelism + 1):
            wdir = ar_dir / "workers" / f"worker-{i}"
            exp_num = state["experiment_count"] + i

            # Agent crashed?
            if isinstance(results[i - 1], Exception):
                print(f"  worker-{i}: CRASH ({results[i - 1]})")
                append_log(ar_dir, {
                    "experiment_id": exp_num, "branch": state["active_branch"],
                    "worker": i, "status": "crash",
                    "hypothesis": f"Agent error: {results[i - 1]}", "diff": "",
                    "score": 0, "best_score_at_time": state["best_score"],
                    "improved": False,
                })
                continue

            # Stale-file check
            expected = read_or(wdir / "experiment_id.txt", "NONE").strip()
            actual = read_or(wdir / "experiment_id_output.txt", "MISSING").strip()
            if expected != actual:
                print(f"  worker-{i}: STALE (expected {expected}, got {actual})")
                append_log(ar_dir, {
                    "experiment_id": exp_num, "branch": state["active_branch"],
                    "worker": i, "status": "crash",
                    "hypothesis": "Experiment ID mismatch", "diff": "",
                    "score": 0, "best_score_at_time": state["best_score"],
                    "improved": False,
                })
                continue

            # Thought experiment?
            status = read_or(wdir / "latest_status.txt", "real").strip()
            hypothesis = read_or(wdir / "latest_hypothesis.txt", "").strip()

            if status == "thought":
                print(f"  worker-{i}: THOUGHT — {hypothesis[:80]}")
                append_log(ar_dir, {
                    "experiment_id": exp_num, "branch": state["active_branch"],
                    "worker": i, "status": "thought",
                    "hypothesis": hypothesis, "diff": "",
                    "score": 0, "best_score_at_time": state["best_score"],
                    "improved": False,
                })
                continue

            # Score + diff
            score_str = read_or(wdir / "latest_score.txt", "0").strip()
            try:
                worker_score = float(score_str)
            except ValueError:
                worker_score = 0.0
            diff_text = read_or(wdir / "latest_diff.txt", "").strip()

            print(f"  worker-{i}: score={worker_score:.2f} (best={state['best_score']:.2f})")

            # Mechanical critique
            skip = False
            if diff_text:
                if check_lockfile_violation(diff_text, ar_dir):
                    print(f"  worker-{i}: REJECTED (lockfile)")
                    skip = True
                if check_safety_violation(diff_text):
                    print(f"  worker-{i}: REJECTED (safety)")
                    skip = True
            if not hypothesis or not diff_text:
                print(f"  worker-{i}: REJECTED (empty)")
                skip = True

            improved = False if skip else check_noise(worker_score, state["best_score"], state.get("direction", "maximize"))

            # Read parent from worker (the experiment writes it) or use the state default
            parent = read_or(wdir / "latest_parent.txt", str(parent_exp)).strip()

            append_log(ar_dir, {
                "experiment_id": exp_num, "branch": state["active_branch"],
                "parent": parent, "worker": i,
                "status": "keep" if improved else "discard",
                "hypothesis": hypothesis, "diff": diff_text,
                "score": worker_score, "best_score_at_time": state["best_score"],
                "improved": improved,
            })

            if improved:
                round_had_improvement = True
                direction = state.get("direction", "maximize")
                if best_worker_score is None or (
                    worker_score < best_worker_score if direction == "minimize" else worker_score > best_worker_score
                ):
                    best_worker = i
                    best_worker_score = worker_score

        # Ratchet
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
        else:
            state["discard_streak"] += 1
            state["best_unchanged_count"] += parallelism
            print(f"\n  No improvement. Discard streak: {state['discard_streak']}")

        state["experiment_count"] += parallelism
        write_state(ar_dir, state)
        cleanup_workers(ar_dir)

        # Periodic summarize
        if round_num % SUMMARIZE_EVERY == 0:
            print(f"\n--- SUMMARIZE (round {round_num}) ---")
            log20 = read_log_tail(ar_dir, 20)
            findings = read_or(ar_dir / "findings.md", "none")
            branches_text = read_or(ar_dir / "branches.jsonl", "none")
            output, _ = await run_agent(
                system_prompt=summarize_skill,
                user_prompt=(
                    f"Summarize the experiment log. Autoresearch directory: {ar_dir}\n"
                    f"Recent log entries (last 20): {log20}\n"
                    f"Existing findings: {findings}\n"
                    f"Branch registry: {branches_text}"
                ),
                cwd=project_dir,
                name="summarize",
            )
            print(output)

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
