import json

import pytest

from emporio import config
from emporio.tools import ToolError


def run(toolbox, name, **args):
    return json.loads(toolbox.run(name, args))


def test_schemas_validos(toolbox):
    names = {s["name"] for s in toolbox.schemas}
    assert names == set(toolbox._handlers)
    for s in toolbox.schemas:
        assert s["parameters"]["type"] == "object"


def test_buscar_violoes_ate_1000(toolbox):
    r = run(toolbox, "buscar_produtos", categoria="Violões", preco_max=1000, limite=20)
    assert r["total_encontrado"] == len(r["produtos"]) == 12


def test_produto_esgotado_sugere_alternativas(toolbox):
    r = run(toolbox, "detalhes_produto", produto_id=96)
    assert r["situacao"] == "esgotado"
    assert r["alternativas_disponiveis"]
    assert all(a["situacao"] == "disponivel" for a in r["alternativas_disponiveis"])
    assert r["promocoes_encerradas"] == ["Semana do Músico"]


def test_pedido_exige_identidade(toolbox):
    r = run(toolbox, "consultar_pedido", numero_pedido=8, email_ou_telefone="intruso@x.com")
    assert r["verificado"] is False
    assert "Kala" not in json.dumps(r)
    r = run(toolbox, "consultar_pedido", numero_pedido=999, email_ou_telefone="a@b.com")
    assert r["verificado"] is False


def test_pedido_entregue_calcula_prazos(toolbox):
    # Pedido 7: entregue com previsão 2026-02-17; "hoje" nos testes = 2026-03-25.
    r = run(toolbox, "consultar_pedido", numero_pedido=7, email_ou_telefone=_email(toolbox, 7))
    assert r["status"] == "entregue"
    assert r["prazos"]["arrependimento_7_dias_apos_recebimento"].startswith("expirado")
    assert r["prazos"]["troca_por_defeito_30_dias_apos_compra"].startswith("expirado")
    assert r["prazos"]["garantia_legal_90_dias_apos_recebimento"] == "vigente"


def test_pedido_enviado_atrasado_gera_alerta(toolbox):
    r = run(toolbox, "consultar_pedido", numero_pedido=8, email_ou_telefone=_email(toolbox, 8))
    assert r["codigo_rastreio"] == "BRJL5544332BR"
    assert "vencida" in r["alertas"][0]


def test_pedido_cancelado_mostra_motivo(toolbox):
    r = run(toolbox, "consultar_pedido", numero_pedido=18, email_ou_telefone=_email(toolbox, 18))
    assert r["status"] == "cancelado"
    assert "fora de estoque" in r["observacao"]


@pytest.mark.parametrize(
    "valor,promo,max_parcelas,pix",
    [
        (2199, False, 12, "R$ 2.089,05 (5% de desconto)"),
        (159.9, False, 3, "R$ 151,91 (5% de desconto)"),
        (439.2, True, 5, "R$ 439,20 (sem desconto adicional: valor já é promocional)"),
        (40, False, 1, "R$ 38,00 (5% de desconto)"),
    ],
)
def test_simular_pagamento(toolbox, valor, promo, max_parcelas, pix):
    r = run(toolbox, "simular_pagamento", valor=valor, valor_ja_promocional=promo)
    assert max(r["parcelas_possiveis"]) == max_parcelas
    assert r["pix"] == pix
    assert r["combinar_formas_pagamento"] is (valor > 2000)


def test_registrar_chamado_grava_arquivo(toolbox):
    r = run(toolbox, "registrar_chamado", tipo="reclamacao", resumo="teste", contato="a@b.com")
    assert r["protocolo"].startswith("EM-")
    linhas = config.TICKETS_FILE.read_text(encoding="utf-8").splitlines()
    assert json.loads(linhas[-1])["protocolo"] == r["protocolo"]


def test_erros_de_entrada(toolbox):
    with pytest.raises(ToolError):
        toolbox.run("nao_existe", {})
    with pytest.raises(ToolError):
        toolbox.run("buscar_produtos", {"categoria": "Acessórios"})
    with pytest.raises(ToolError):
        toolbox.run("detalhes_produto", {})


def _email(toolbox, order_id):
    return toolbox.store.orders[order_id].customer.email
