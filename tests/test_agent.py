"""Testa o loop do agente com um cliente falso (sem chamar a API)."""

import json
from datetime import datetime
from types import SimpleNamespace

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from emporio import config, storage
from emporio.agent import EmporioAgent


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_client(responses):
    completions = FakeCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def resp(content=None, tool_calls=None, finish="stop"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish = "tool_calls"
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": config.MODEL,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        }
    )


def tool(name, args, id_="call_1"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def agent_factory(toolbox):
    def make(responses):
        client, calls = fake_client(responses)
        agent = EmporioAgent(client=client, toolbox=toolbox, clock=lambda: datetime(2026, 3, 25, 10, 0))
        return agent, calls

    return make


def test_resposta_direta(agent_factory):
    agent, calls = agent_factory([resp("Oi! Como posso ajudar?")])
    reply = agent.send("oi")
    assert reply.text == "Oi! Como posso ajudar?"
    req = calls.calls[0]
    assert req["model"] == config.MODEL
    assert {t["function"]["name"] for t in req["tools"]} == set(agent.toolbox._handlers)
    # prompt de sistema fixo + usuário + nota de hora
    assert [m["role"] for m in req["messages"]] == ["system", "user", "system"]
    assert "quarta-feira, 25/03/2026 10:00" in req["messages"][2]["content"]
    # o prompt de sistema não é salvo no histórico
    assert agent.messages[0]["role"] == "user"


def test_executa_ferramentas_e_devolve_resultado(agent_factory):
    agent, calls = agent_factory(
        [
            resp(tool_calls=[
                tool("buscar_produtos", {"termo": "Takamine GD20"}, "call_1"),
                tool("consultar_politicas", {"topicos": ["formas_pagamento"]}, "call_2"),
            ]),
            resp("O Takamine GD20 sai por R$ 2.199,00."),
        ]
    )
    reply = agent.send("quanto custa o takamine gd20?")
    assert [c.name for c in reply.tool_calls] == ["buscar_produtos", "consultar_politicas"]
    second = calls.calls[1]["messages"]
    assert second[-3]["tool_calls"][0]["id"] == "call_1"
    assert [m["tool_call_id"] for m in second[-2:]] == ["call_1", "call_2"]
    assert "R$ 2.199,00" in second[-2]["content"]
    assert agent.messages[-1] == {"role": "assistant", "content": "O Takamine GD20 sai por R$ 2.199,00."}


def test_erro_de_ferramenta_vira_mensagem_de_erro(agent_factory):
    agent, calls = agent_factory(
        [resp(tool_calls=[tool("detalhes_produto", {"produto_id": 9999})]), resp("Não encontrei esse produto.")]
    )
    reply = agent.send("produto 9999")
    assert reply.tool_calls[0].is_error
    assert calls.calls[1]["messages"][-1]["content"].startswith("Erro:")


def test_argumentos_invalidos_nao_quebram(agent_factory):
    bad = {"id": "call_x", "type": "function", "function": {"name": "buscar_produtos", "arguments": "{oops"}}
    agent, _ = agent_factory([resp(tool_calls=[bad]), resp("Pode repetir?")])
    reply = agent.send("x")
    assert reply.tool_calls[0].is_error and reply.text == "Pode repetir?"


def test_limite_de_rodadas(agent_factory, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 1)
    loop = resp(tool_calls=[tool("listar_promocoes_ativas", {})])
    agent, _ = agent_factory([loop, loop])
    reply = agent.send("promo?")
    assert reply.stop_reason == "max_tool_rounds"


def test_parametros_de_modelo(agent_factory, monkeypatch):
    agent, calls = agent_factory([resp("a"), resp("b")])
    agent.send("x")
    assert "temperature" in calls.calls[0] and "reasoning_effort" not in calls.calls[0]
    monkeypatch.setattr(config, "REASONING_EFFORT", "low")
    agent.send("y")
    assert calls.calls[1]["reasoning_effort"] == "low" and "temperature" not in calls.calls[1]


def test_erro_de_api_desfaz_turno(agent_factory):
    erro = openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com"))
    agent, _ = agent_factory([erro])
    with pytest.raises(openai.APIConnectionError):
        agent.send("oi")
    assert agent.messages == []


def test_historico_persiste_e_reexibe(agent_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path)
    agent, _ = agent_factory([resp(tool_calls=[tool("listar_promocoes_ativas", {})]), resp("Olá!")])
    agent.send("oi")
    storage.save("teste", agent.messages)
    restored = storage.load("teste")
    assert restored == agent.messages
    assert storage.visible_turns(restored) == [("cliente", "oi"), ("lia", "Olá!")]
    with pytest.raises(ValueError):
        storage.save("../fora", [])
