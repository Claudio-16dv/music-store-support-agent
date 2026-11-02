from emporio.policies import SECTION_KEYS, get_sections, load_policies


def test_todas_as_secoes_extraidas():
    policies = load_policies()
    assert set(policies) == set(SECTION_KEYS.values())
    assert "09:00 às 18:00" in policies["horario_funcionamento"].text
    assert "7 (sete) dias corridos" in policies["trocas_devolucoes"].text
    assert "Rua 14 de Maio, 3200" in policies["sobre_a_loja"].text


def test_secoes_nao_vazam_umas_nas_outras():
    policies = load_policies()
    assert "Garantia Legal" not in policies["diretrizes_atendimento"].text
    assert "Saudação" in policies["diretrizes_atendimento"].text  # lista 1..5 fica na seção 7


def test_notas_de_interpretacao_anexadas():
    texto = get_sections(["formas_pagamento"])
    assert "Nota de interpretação interna" in texto
    assert "R$ 50,00" in texto


def test_topico_invalido_nao_quebra():
    assert "tópico inexistente" in get_sections(["xpto"])
