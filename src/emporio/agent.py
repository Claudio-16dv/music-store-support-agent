"""Agent loop: OpenAI model (Chat Completions) + function calling.

A manual loop gives explicit control over: the tool-round limit, recording
the calls (debug mode and example generation), finish_reason handling and
history persistence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import holidays
import openai

from . import config
from .data import StoreData
from .prompts import SYSTEM_PROMPT, current_time_note
from .tools import ToolError, Toolbox

log = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Shown to the customer, so it stays in Portuguese.
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


# National + Mato Grosso do Sul holidays, plus Campo Grande's municipal holiday
# (city anniversary). The manual says the store is closed on holidays.
_HOLIDAYS = holidays.Brazil(subdiv="MS")
CITY_HOLIDAYS = {(8, 26): "Campo Grande anniversary"}


def holiday_name(day: date) -> str | None:
    return CITY_HOLIDAYS.get((day.month, day.day)) or _HOLIDAYS.get(day)


def now_text(now: datetime | None = None) -> str:
    now = now or datetime.now(config.TIMEZONE)
    text = f"{WEEKDAYS[now.weekday()]}, {now:%Y-%m-%d %H:%M}"
    if name := holiday_name(now.date()):
        text += f" — public holiday ({name}): the store is closed all day today"
    return text


def _assistant_param(message: Any) -> dict:
    """Turns the SDK response message into a serializable dict (resending and history)."""
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
        # History without the system prompt (it is prepended to every request).
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
            # Fixed system prompt first: OpenAI automatically caches the repeated
            # prefix (tools + system + history) across turns.
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *self.messages],
            "tools": self._tools,
            "max_completion_tokens": config.MAX_TOKENS,
        }
        if config.REASONING_EFFORT:
            kwargs["reasoning_effort"] = config.REASONING_EFFORT
        else:
            # Non-reasoning models: low temperature for consistent answers.
            kwargs["temperature"] = 0.3
        return kwargs

    def _execute(self, tool_call: Any) -> tuple[dict, ToolCall]:
        name = tool_call.function.name
        args: dict = {}
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(args, dict):
                raise ToolError("Arguments must be a JSON object.")
            output = self.toolbox.run(name, args)
            is_error = False
        except json.JSONDecodeError:
            output, is_error = "Error: arguments are not valid JSON.", True
        except ToolError as e:
            output, is_error = f"Error: {e}", True
        except Exception:  # bug in a tool: don't kill the conversation
            log.exception("Tool %s failed", name)
            output, is_error = "Internal error while querying the system. Do not make up the information.", True
        result = {"role": "tool", "tool_call_id": tool_call.id, "content": output}
        return result, ToolCall(name, args, output, is_error)

    def send(self, user_text: str) -> AgentReply:
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        # The time goes in a system message next to the turn, not in the system
        # prompt, so the cached prefix is not invalidated.
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
                    text = FALLBACK_ERROR_REPLY
                else:
                    text = (message.content or "").strip()
                    if choice.finish_reason == "length":
                        text += "\n\n(Resposta interrompida por limite de tamanho.)"  # customer-facing
                    text = text or FALLBACK_ERROR_REPLY
                # Store what the customer actually saw: an assistant message with no content
                # and no tool calls would make every later request in the session fail.
                self.messages[-1]["content"] = text
                return AgentReply(text, calls, choice.finish_reason)

            # Close the turn with an assistant message so the saved history stays coherent.
            self.messages.append({"role": "assistant", "content": FALLBACK_ERROR_REPLY})
            return AgentReply(FALLBACK_ERROR_REPLY, calls, "max_tool_rounds")
        except openai.APIError:
            # Roll back the incomplete turn so the history stays valid.
            del self.messages[checkpoint:]
            raise
