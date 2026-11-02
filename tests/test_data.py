from emporio.data import DESCONTINUADO, DISPONIVEL, EM_BREVE, ESGOTADO, normalize


def test_carrega_todas_as_tabelas(store):
    assert len(store.products) == 65
    assert len(store.categories) == 9
    assert len(store.orders) == 20
    assert sum(len(o.items) for o in store.orders.values()) == 22


def test_situacao_derivada_de_status_e_estoque(store):
    assert store.products[95].situacao == DISPONIVEL
    assert store.products[96].situacao == ESGOTADO  # active, estoque 0
    assert store.products[136].situacao == DESCONTINUADO  # descontinuado mesmo com estoque
    assert store.products[130].situacao == EM_BREVE


def test_promocao_ativa_e_preco_promocional(store):
    p = store.products[121]
    assert p.active_promotion.discount_percent == 20
    assert p.promo_price == 439.20
    assert store.products[102].active_promotion is None  # Black Friday inativa


def test_busca_ignora_acentos_e_espacos_no_modelo(store):
    for termo in ["Takamine GD20", "takamine gd 20", "TAKAMINE gd-20"]:
        found, aproximado = store.search_products(termo)
        assert [p.id for p in found] == [95]
        assert not aproximado


def test_busca_por_categoria_e_preco_final(store):
    found, _ = store.search_products(category="Violões", max_price=1000)
    assert found and all(p.final_price <= 1000 and p.category.name == "Violões" for p in found)
    assert all(p.situacao == DISPONIVEL for p in found)


def test_busca_sem_correspondencia_total_e_aproximada(store):
    _, aproximado = store.search_products("cordas de guitarra")
    assert aproximado


def test_verificacao_de_identidade(store):
    cliente = store.orders[8].customer  # Ana Carolina
    assert store.identity_matches(cliente, "anacarol.ferreira@coldmail.com")
    assert store.identity_matches(cliente, "ANACAROL.FERREIRA@COLDMAIL.COM ")
    assert store.identity_matches(cliente, "(67) 99654-7821")
    assert store.identity_matches(cliente, "+55 67 996547821")
    assert not store.identity_matches(cliente, "outra@pessoa.com")
    assert not store.identity_matches(cliente, "7821")


def test_normalize():
    assert normalize("  Violões   Elétricos ") == "violoes eletricos"
