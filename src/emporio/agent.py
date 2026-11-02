"""Loop do agente: modelo da OpenAI (Chat Completions) + function calling.

Usamos um loop manual para ter controle explícito de: limite de rodadas de
ferramenta, registro das chamadas (debug e geração dos exemplos), tratamento
de finish_reason e persistência do histórico.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import openai

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


def _assistant_param(message: Any) -> dict:
    """Converte a mensagem de resposta do SDK em dict serializável (reenvio e histórico)."""
    param: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        param["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]
    return param


class EmporioAgent:
    def __init__(
        self,
        client: openai.OpenAI | None = None,
        store: StoreData | None = None,
        toolbox: Toolbox | None = None,
        messages: list[dict] | None = None,
        clock=None,
    ):
        self.client = client or openai.OpenAI()
        self.toolbox = toolbox or Toolbox(store or StoreData())
        # Histórico sem o prompt de sistema (ele é prefixado a cada requisição).
        self.messages: list[dict] = messages if messages is not None else []
        self.clock = clock or (lambda: datetime.now(config.TIMEZONE))
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["parameters"],
                },
            }
            for s in self.toolbox.schemas
        ]

    def _request_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {
            "model": config.MODEL,
            # Prompt de sistema fixo no início: a OpenAI faz cache automático do
            # prefixo repetido (ferramentas + sistema + histórico) entre turnos.
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *self.messages],
            "tools": self._tools,
            "max_completion_tokens": config.MAX_TOKENS,
        }
        if config.REASONING_EFFORT:
            kwargs["reasoning_effort"] = config.REASONING_EFFORT
        else:
            # Modelos sem raciocínio: temperatura baixa para respostas consistentes.
            kwargs["temperature"] = 0.3
        return kwargs

    def _execute(self, tool_call: Any) -> tuple[dict, ToolCall]:
        name = tool_call.function.name
        args: dict = {}
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(args, dict):
                raise ToolError("Argumentos devem ser um objeto JSON.")
            output = self.toolbox.run(name, args)
            is_error = False
        except json.JSONDecodeError:
            output, is_error = "Erro: argumentos não são JSON válido.", True
        except ToolError as e:
            output, is_error = f"Erro: {e}", True
        except Exception:  # bug na ferramenta: não derruba a conversa
            log.exception("Falha ao executar ferramenta %s", name)
            output, is_error = "Erro interno ao consultar o sistema. Não invente a informação.", True
        result = {"role": "tool", "tool_call_id": tool_call.id, "content": output}
        return result, ToolCall(name, args, output, is_error)

    def send(self, user_text: str) -> AgentReply:
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        # A hora vai numa mensagem de sistema junto do turno, e não no prompt de
        # sistema, para não invalidar o cache do prefixo.
        self.messages.append({"role": "system", "content": current_time_note(now_text(self.clock()))})

        calls: list[ToolCall] = []
        try:
            for _ in range(config.MAX_TOOL_ROUNDS + 1):
                response = self.client.chat.completions.create(**self._request_kwargs())
                choice = response.choices[0]
                message = choice.message
                self.messages.append(_assistant_param(message))

                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        result, call = self._execute(tool_call)
                        self.messages.append(result)
                        calls.append(call)
                        log.debug("tool %s(%s) -> %s", call.name, json.dumps(call.input, ensure_ascii=False), call.output[:300])
                    continue

                if choice.finish_reason == "content_filter":
                    return AgentReply(FALLBACK_ERROR_REPLY, calls, "content_filter")
                text = (message.content or "").strip()
                if choice.finish_reason == "length":
                    text += "\n\n(Resposta interrompida por limite de tamanho.)"
                return AgentReply(text or FALLBACK_ERROR_REPLY, calls, choice.finish_reason)

            return AgentReply(FALLBACK_ERROR_REPLY, calls, "max_tool_rounds")
        except openai.APIError:
            # Desfaz o turno incompleto para o histórico continuar válido.
            del self.messages[checkpoint:]
            raise
