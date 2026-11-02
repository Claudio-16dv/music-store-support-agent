"""Central agent configuration (read from environment variables / .env)."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.getenv("EMPORIO_DATA_DIR", ROOT_DIR / "data"))
POLICIES_PDF = DATA_DIR / "store_policies.pdf"
RUNTIME_DIR = Path(os.getenv("EMPORIO_RUNTIME_DIR", ROOT_DIR / ".runtime"))
SESSIONS_DIR = RUNTIME_DIR / "sessions"
TICKETS_FILE = RUNTIME_DIR / "tickets.jsonl"

MODEL = os.getenv("EMPORIO_MODEL", "gpt-4.1-mini")
# Reasoning models only (e.g. gpt-5 / o-series): low | medium | high.
# Empty = the parameter is not sent (models like gpt-4.1 reject it).
REASONING_EFFORT = os.getenv("EMPORIO_REASONING_EFFORT", "")
MAX_TOKENS = int(os.getenv("EMPORIO_MAX_TOKENS", "2000"))
# Max tool-calling rounds per customer message (guards against loops).
MAX_TOOL_ROUNDS = int(os.getenv("EMPORIO_MAX_TOOL_ROUNDS", "8"))

# Campo Grande/MS has no daylight saving time: UTC-4 all year.
TIMEZONE = ZoneInfo("America/Campo_Grande")
