"""Configuração central do agente (lida de variáveis de ambiente / .env)."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.getenv("EMPORIO_DATA_DIR", ROOT_DIR / "data"))
POLICIES_PDF = DATA_DIR / "políticas_da_loja.pdf"
RUNTIME_DIR = Path(os.getenv("EMPORIO_RUNTIME_DIR", ROOT_DIR / ".runtime"))
SESSIONS_DIR = RUNTIME_DIR / "sessoes"
TICKETS_FILE = RUNTIME_DIR / "chamados.jsonl"

MODEL = os.getenv("EMPORIO_MODEL", "claude-opus-5-5")
# Atendimento é conversa curta + consultas simples: "low" já resolve bem e
# reduz latência/custo. Suba para "medium"/"high" se notar raciocínio raso.
EFFORT = os.getenv("EMPORIO_EFFORT", "low")
MAX_TOKENS = int(os.getenv("EMPORIO_MAX_TOKENS", "8000"))
# Fallback server-side em caso de recusa do classificador de segurança.
USE_FALLBACK = os.getenv("EMPORIO_FALLBACK", "1") == "1"
# Limite de chamadas de ferramenta por mensagem do cliente (proteção contra loop).
MAX_TOOL_ROUNDS = int(os.getenv("EMPORIO_MAX_TOOL_ROUNDS", "8"))

# Campo Grande/MS não tem horário de verão: UTC-4 o ano todo.
TIMEZONE = ZoneInfo("America/Campo_Grande")
