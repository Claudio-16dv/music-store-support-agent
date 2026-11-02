"""Simple JSON persistence of the conversation history (one session per file).

Lets a conversation be resumed where it stopped (e.g. the customer comes back
later to ask about a ticket). The history is saved exactly as sent to the API,
tool messages included, so it can be resent unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import config


def _path(session_id: str) -> Path:
    if not re.fullmatch(r"[\w-]{1,64}", session_id):
        raise ValueError("Invalid session ID (use letters, digits, _ or -).")
    return config.SESSIONS_DIR / f"{session_id}.json"


def new_session_id() -> str:
    return f"{datetime.now(config.TIMEZONE):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def load(session_id: str) -> list[dict]:
    path = _path(session_id)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["messages"]


def save(session_id: str, messages: list[dict]) -> Path:
    path = _path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "updated_at": datetime.now(config.TIMEZONE).isoformat(timespec="seconds"),
        "model": config.MODEL,
        "messages": messages,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def visible_turns(messages: list[dict]) -> list[tuple[str, str]]:
    """Extracts only the spoken turns (customer/Lia) from the history, to replay on resume."""
    turns = []
    for m in messages:
        content = m.get("content") or ""
        if m["role"] == "user":
            turns.append(("customer", content))
        elif m["role"] == "assistant" and not m.get("tool_calls") and content.strip():
            turns.append(("lia", content.strip()))
    return turns
