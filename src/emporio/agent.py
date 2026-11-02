"""Loop do agente: Claude + function calling sobre as ferramentas da loja.

Usamos um loop manual (em vez do tool runner beta do SDK) para ter controle
explícito de: limite de rodadas de ferramenta, registro das chamadas (debug e
geração dos exemplos), tratamento de stop_reason e persistência do histórico.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic

from . import config
from .data import StoreData
from .prompts import SYSTEM_PROMPT, current_time_note
from .tools import ToolError, Toolbox

log = logging.getLogger(__name__)

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

FALLBACK_ERROR_REPLY = (
    "Poxa, tive um probleminha aqui pra concluir sua solicitação. 😕 Pode tentar de novo? "
    "Se preferir, fale com a nossa equipe pelo WhatsApp (67) 3341-4444."
)


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str
    is_error: bool = False


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None


def now_text(now: datetime | None = None) -> str:
    now = now or datetime.now(config.TIMEZONE)
    return f"{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M}"


def _to_param(block: Any) -> dict:
    """Converte um bloco de resposta do SDK em dict serializável (para reenviar e salvar)."""
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", exclude_none=True)


class EmporioAgent:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        store: StoreData | None = None,
        toolbox: Toolbox | None = None,
        messages: list[dict] | None = None,
        clock=None,
    ):
        self.client = client or anthropic.Anthropic()
        self.toolbox = toolbox or Toolbox(store or StoreData())
        self.messages: list[dict] = messages if messages is not None else []
        self.clock = clock or (lambda: datetime.now(config.TIMEZONE))

    def _request_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {
            "model": config.MODEL,
            "max_tokens": config.MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "tools": self.toolbox.schemas,
            "messages": self.messages,
            "output_config": {"effort": config.EFFORT},
            # Cache automático do prefixo (ferramentas + sistema + histórico).
            "cache_control": {"type": "ephemeral"},
        }
        if config.USE_FALLBACK:
            # Se o classificador de segurança recusar, a API refaz no modelo de fallback.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _execute(self, block: Any) -> tuple[dict, ToolCall]:
        try:
            output = self.toolbox.run(block.name, dict(block.input or {}))
            is_error = False
        except ToolError as e:
            output, is_error = f"Erro: {e}", True
        except Exception:  # bug na ferramenta: não derruba a conversa
            log.exception("Falha ao executar ferramenta %s", block.name)
            output, is_error = "Erro interno ao consultar o sistema. Não invente a informação.", True
        result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
        if is_error:
            result["is_error"] = True
        return result, ToolCall(block.name, dict(block.input or {}), output, is_error)

    def send(self, user_text: str) -> AgentReply:
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        # Mensagem de sistema no meio da conversa: informa a hora sem mexer no
        # prompt de sistema (que fica em cache).
        self.messages.append({"role": "system", "content": current_time_note(now_text(self.clock()))})

        calls: list[ToolCall] = []
        try:
            for _ in range(config.MAX_TOOL_ROUNDS + 1):
                response = self.client.beta.messages.create(**self._request_kwargs())
                self.messages.append(
                    {"role": "assistant", "content": [_to_param(b) for b in response.content]}
                )

                if response.stop_reason == "refusal":
                    return AgentReply(FALLBACK_ERROR_REPLY, calls, "refusal")

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason == "tool_use" and tool_uses:
                    results = []
                    for block in tool_uses:
                        result, call = self._execute(block)
                        results.append(result)
                        calls.append(call)
                        log.debug("tool %s(%s) -> %s", call.name, json.dumps(call.input, ensure_ascii=False), call.output[:300])
                    # Todos os resultados num único turno de usuário (mantém chamadas paralelas).
                    self.messages.append({"role": "user", "content": results})
                    continue

                text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += "\n\n(Resposta interrompida por limite de tamanho.)"
                return AgentReply(text or FALLBACK_ERROR_REPLY, calls, response.stop_reason)

            return AgentReply(FALLBACK_ERROR_REPLY, calls, "max_tool_rounds")
        except anthropic.APIError:
            # Desfaz o turno incompleto para o histórico continuar válido.
            del self.messages[checkpoint:]
            raise
