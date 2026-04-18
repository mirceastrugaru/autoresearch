Score each worker write-up against the rubric. Hard gate fail = score 0. Soft gates: count passes.

TARGET: {target}

RUBRIC:
{rubric}

WORKER WRITE-UPS THIS ROUND:
{writeups_json}

---

For each worker, evaluate every gate. Be strict — the rubric is a checklist, not a suggestion.

Respond ONLY with JSON:
{{
  "worker_id": {{
    "gates": {{
      "gate_name": {{"type": "hard|soft", "result": "pass|fail", "reason": "one sentence"}}
    }},
    "hard_gate_failed": true|false,
    "soft_gates_passed": N,
    "final_score": N
  }}
}}
