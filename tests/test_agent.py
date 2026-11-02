"""Testa o loop do agente com um cliente falso (sem chamar a API)."""

from datetime import datetime
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock

from emporio import config, storage
from emporio.agent import EmporioAgent


class FakeMessages:
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
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def resp(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


def text(t):
    return BetaTextBlock(type="text", text=t)


def tool(name, args, id_="toolu_1"):
    return BetaToolUseBlock(type="tool_use", id=id_, name=name, input=args)


@pytest.fixture
def agent_factory(toolbox):
    def make(responses):
        client, calls = fake_client(responses)
        agent = EmporioAgent(client=client, toolbox=toolbox, clock=lambda: datetime(2026, 3, 25, 10, 0))
        return agent, calls

    return make


def test_resposta_direta(agent_factory):
    agent, calls = agent_factory([resp(text("Oi! Como posso ajudar?"))])
    reply = agent.send("oi")
    assert reply.text == "Oi! Como posso ajudar?"
    req = calls.calls[0]
    assert req["model"] == config.MODEL
    assert req["output_config"] == {"effort": config.EFFORT}
    # usuário + nota de hora como mensagem de sistema no meio da conversa
    assert [m["role"] for m in req["messages"]] == ["user", "system"]
    assert "quarta-feira, 25/03/2026 10:00" in req["messages"][1]["content"]


def test_executa_ferramenta_e_devolve_resultado(agent_factory):
    agent, calls = agent_factory(
        [
            resp(tool("buscar_produtos", {"termo": "Takamine GD20"}), stop="tool_use"),
            resp(text("O Takamine GD20 sai por R$ 2.199,00.")),
        ]
    )
    reply = agent.send("quanto custa o takamine gd20?")
    assert [c.name for c in reply.tool_calls] == ["buscar_produtos"]
    second = calls.calls[1]["messages"]
    tool_result = second[-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert "R$ 2.199,00" in tool_result["content"]
    assert agent.messages[-1]["role"] == "assistant"


def test_erro_de_ferramenta_vira_is_error(agent_factory):
    agent, calls = agent_factory(
        [
            resp(tool("detalhes_produto", {"produto_id": 9999}), stop="tool_use"),
            resp(text("Não encontrei esse produto.")),
        ]
    )
    reply = agent.send("produto 9999")
    assert reply.tool_calls[0].is_error
    assert calls.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_limite_de_rodadas(agent_factory, monkeypatch):
    monkeypatch.setattr(config, "MAX_TOOL_ROUNDS", 1)
    loop = resp(tool("listar_promocoes_ativas", {}), stop="tool_use")
    agent, _ = agent_factory([loop, loop])
    reply = agent.send("promo?")
    assert reply.stop_reason == "max_tool_rounds"


def test_erro_de_api_desfaz_turno(agent_factory):
    erro = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    agent, _ = agent_factory([erro])
    with pytest.raises(anthropic.APIConnectionError):
        agent.send("oi")
    assert agent.messages == []


def test_historico_persiste_e_reexibe(agent_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path)
    agent, _ = agent_factory([resp(text("Olá!"))])
    agent.send("oi")
    storage.save("teste", agent.messages)
    restored = storage.load("teste")
    assert restored == agent.messages
    assert storage.visible_turns(restored) == [("cliente", "oi"), ("lia", "Olá!")]
    with pytest.raises(ValueError):
        storage.save("../fora", [])
