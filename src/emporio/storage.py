"""Persistência simples do histórico de conversa em JSON (uma sessão por arquivo).

Permite retomar o atendimento de onde parou (ex.: cliente volta mais tarde
para saber do chamado). O histórico é salvo exatamente como enviado à API,
incluindo blocos de ferramenta, para ser reenviado sem alterações.
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
        raise ValueError("ID de sessão inválido (use letras, números, _ ou -).")
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
    """Extrai só as falas (cliente/Lia) do histórico, para reexibir ao retomar."""
    turns = []
    for m in messages:
        content = m["content"]
        if m["role"] == "user" and isinstance(content, str):
            turns.append(("cliente", content))
        elif m["role"] == "assistant":
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if text:
                turns.append(("lia", text))
    return turns
