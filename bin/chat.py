"""Chat engine for Autoresearch API.

Uses Claude Code (Agent SDK) for tool-calling responses.
Conversation history stored in ar_dir/chat_history.jsonl.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from ulid import ULID


CHAT_MODEL = os.environ.get("AUTORESEARCH_CHAT_MODEL", "claude-sonnet-4-6")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class ChatEngine:
    def __init__(self, session_mgr, run_mgr):
        self.session_mgr = session_mgr
        self.run_mgr = run_mgr

    async def send_message(self, session_id: str, text: str) -> AsyncIterator[str]:
        """Send a user message and stream the assistant's response as SSE events."""
        session = self.session_mgr.get(session_id)
        if not session:
            yield _sse("error", {"code": "not_found", "message": "Session not found"})
            return

        ar_dir = Path(session["ar_dir"])
        stage = session.get("stage", "design")

        # Save user message
        self._save_message(ar_dir, "user", text, stage)

        # Build the prompt with conversation context
        system_prompt = self._build_system_prompt(ar_dir, session)
        history = self._load_history(ar_dir)
        user_prompt = self._format_history_prompt(history, text)

        msg_id = str(ULID()).lower()
        yield _sse("message.start", {"id": msg_id, "role": "assistant"})

        full_text = ""
        tool_calls = []

        try:
            async for msg in query(
                prompt=user_prompt,
                options=ClaudeAgentOptions(
                    model=CHAT_MODEL,
                    system_prompt=system_prompt,
                    permission_mode="bypassPermissions",
                    cwd=str(ar_dir),
                    extra_args={"no-session-persistence": None},
                ),
            ):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            full_text += block.text
                            yield _sse("message.delta", {"textDelta": block.text})
                        elif isinstance(block, ToolUseBlock):
                            tool_calls.append({
                                "name": block.name,
                                "args": block.input if isinstance(block.input, dict) else {},
                            })
                            yield _sse("tool.call", {"name": block.name, "args": block.input})

                elif isinstance(msg, ToolResultBlock):
                    content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                    if tool_calls:
                        tool_calls[-1]["result"] = content
                    yield _sse("tool.result", {"result": content[:2000]})

                elif isinstance(msg, ResultMessage):
                    pass

        except Exception as e:
            error_text = f"Error: {e}"
            full_text += error_text
            yield _sse("message.delta", {"textDelta": error_text})

        # Save assistant message
        self._save_message(ar_dir, "assistant", full_text, stage, tool_calls)

        yield _sse("message.complete", {
            "id": msg_id,
            "fullText": full_text,
            "toolCalls": tool_calls,
        })

    def get_history(self, ar_dir: Path, cursor: str | None = None, limit: int = 50) -> tuple[list[dict], str | None]:
        """Get paginated chat history."""
        history_path = ar_dir / "chat_history.jsonl"
        if not history_path.exists():
            return [], None

        messages = []
        for line in history_path.read_text().strip().splitlines():
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        messages.reverse()

        start = 0
        if cursor:
            for i, m in enumerate(messages):
                if m.get("id") == cursor:
                    start = i + 1
                    break

        page = messages[start:start + limit]
        next_cursor = page[-1]["id"] if len(page) == limit and start + limit < len(messages) else None
        return page, next_cursor

    def _load_history(self, ar_dir: Path) -> list[dict]:
        """Load recent conversation history."""
        history_path = ar_dir / "chat_history.jsonl"
        if not history_path.exists():
            return []

        messages = []
        for line in history_path.read_text().strip().splitlines():
            try:
                messages.append(json.loads(line))
            except (json.JSONDecodeError, KeyError):
                continue

        return messages[-20:]

    def _format_history_prompt(self, history: list[dict], current_text: str) -> str:
        """Format conversation history + current message into a single prompt."""
        parts = []
        for msg in history:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            if role == "user":
                parts.append(f"User: {text}")
            else:
                parts.append(f"Assistant: {text}")

        parts.append(f"User: {current_text}")
        parts.append("Respond to the user's latest message. Use tools when they ask you to take action.")
        return "\n\n".join(parts)

    def _save_message(self, ar_dir: Path, role: str, text: str, stage: str, tool_calls: list | None = None):
        """Append message to chat_history.jsonl."""
        msg = {
            "id": str(ULID()).lower(),
            "role": role,
            "stage": stage,
            "text": text,
            "toolCalls": tool_calls or [],
            "createdAt": _now_iso(),
        }
        with open(ar_dir / "chat_history.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")

    def _build_system_prompt(self, ar_dir: Path, session: dict) -> str:
        """Build system prompt with session context."""
        from bin.program_parser import read_or, read_target, parse_rubric, parse_roadmap

        thesis = read_target(ar_dir)
        rubric = parse_rubric(ar_dir)
        directions = parse_roadmap(ar_dir)
        stage = session.get("stage", "design")
        session_id = session.get("id", "")

        context = f"""You are an AI research assistant managing an autoresearch investigation.

Session ID: {session_id}
Thesis: {thesis}
Current stage: {stage}
Working directory: {ar_dir}

## What you can do

You have full shell access. Use it to read/modify files and call the API.

### File operations
Read and modify files in {ar_dir} directly:
- program.md: investigation config (thesis, directions, rubric, rounds, parallelism)
- roadmap.md: direction queue with coverage status
- state.json: current run state
- log.jsonl: experiment log
- best/: best document so far
- findings.md: synthesized findings
- verdict.json: final verdict

### API operations (use curl)
The API server runs at http://localhost:8000. Use these for actions:

Create a new session:
  curl -s -X POST http://localhost:8000/api/sessions -H 'Content-Type: application/json' -d '{{"thesis":"<thesis>"}}'

Start a run for THIS session:
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/run

Pause/resume/stop:
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/pause
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/resume
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/stop

Add a direction:
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/directions -H 'Content-Type: application/json' -d '{{"stance":"pro","text":"..."}}'

## Rules
- When asked to add a direction, call the API endpoint (not just edit files).
- When asked to start/run the investigation, call POST /run.
- When asked to create a NEW investigation on a different topic, call POST /sessions with the new thesis. Tell the user to switch to it in the sidebar.
- When asked about results, read the files directly.
- Be concise. Take action immediately when asked. Don't explain what you'll do — just do it.
- After taking an action, confirm what you did in one sentence.
"""

        if rubric:
            context += f"\nRubric: {len(rubric.get('hardGates', []))} hard gates, {len(rubric.get('softGates', {}))} soft gates"

        if directions:
            context += f"\nDirections: {len(directions)} configured"
            covered = sum(1 for d in directions if d.get("coverage", 0) > 0)
            if covered:
                context += f" ({covered} covered)"

        if stage in ("review", "roadmap"):
            findings_text = read_or(ar_dir / "findings.md", "")
            if findings_text and len(findings_text) > 50:
                context += f"\n\nFindings summary:\n{findings_text[:500]}"

        return context
