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

MODEL = os.getenv("EMPORIO_MODEL", "gpt-4.1-mini")
# Só para modelos de raciocínio (ex.: família gpt-5/o-series): low | medium | high.
# Vazio = não envia o parâmetro (modelos como gpt-4.1 não o aceitam).
REASONING_EFFORT = os.getenv("EMPORIO_REASONING_EFFORT", "")
MAX_TOKENS = int(os.getenv("EMPORIO_MAX_TOKENS", "2000"))
# Limite de chamadas de ferramenta por mensagem do cliente (proteção contra loop).
MAX_TOOL_ROUNDS = int(os.getenv("EMPORIO_MAX_TOOL_ROUNDS", "8"))

# Campo Grande/MS não tem horário de verão: UTC-4 o ano todo.
TIMEZONE = ZoneInfo("America/Campo_Grande")
