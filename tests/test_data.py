from emporio.data import AVAILABLE, COMING_SOON, DISCONTINUED, OUT_OF_STOCK, normalize


def test_loads_all_tables(store):
    assert len(store.products) == 65
    assert len(store.categories) == 9
    assert len(store.orders) == 20
    assert sum(len(o.items) for o in store.orders.values()) == 22


def test_availability_derived_from_status_and_stock(store):
    assert store.products[95].availability == AVAILABLE
    assert store.products[96].availability == OUT_OF_STOCK  # active, stock 0
    assert store.products[136].availability == DISCONTINUED  # discontinued despite stock
    assert store.products[130].availability == COMING_SOON


def test_active_promotion_and_promo_price(store):
    p = store.products[121]
    assert p.active_promotion.discount_percent == 20
    assert p.promo_price == 439.20
    assert store.products[102].active_promotion is None  # Black Friday inactive


def test_search_ignores_accents_and_spacing_in_model(store):
    for query in ["Takamine GD20", "takamine gd 20", "TAKAMINE gd-20"]:
        found, approximate = store.search_products(query)
        assert [p.id for p in found] == [95]
        assert not approximate


def test_search_by_category_and_final_price(store):
    found, _ = store.search_products(category="Violões", max_price=1000)
    assert found and all(p.final_price <= 1000 and p.category.name == "Violões" for p in found)
    assert all(p.availability == AVAILABLE for p in found)


def test_search_without_full_match_is_approximate(store):
    _, approximate = store.search_products("cordas de guitarra")
    assert approximate


def test_identity_verification(store):
    customer = store.orders[8].customer  # Ana Carolina
    assert store.identity_matches(customer, "anacarol.ferreira@coldmail.com")
    assert store.identity_matches(customer, "ANACAROL.FERREIRA@COLDMAIL.COM ")
    assert store.identity_matches(customer, "(67) 99654-7821")
    assert store.identity_matches(customer, "+55 67 996547821")
    assert not store.identity_matches(customer, "someone@else.com")
    assert not store.identity_matches(customer, "7821")


def test_normalize():
    assert normalize("  Violões   Elétricos ") == "violoes eletricos"
