from emporio.policies import SECTION_KEYS, get_sections, load_policies


def test_all_sections_extracted():
    policies = load_policies()
    assert set(policies) == set(SECTION_KEYS.values())
    assert "09:00 às 18:00" in policies["opening_hours"].text
    assert "7 (sete) dias corridos" in policies["returns_and_exchanges"].text
    assert "Rua 14 de Maio, 3200" in policies["about_the_store"].text


def test_sections_do_not_leak_into_each_other():
    policies = load_policies()
    assert "Garantia Legal" not in policies["customer_service_guidelines"].text
    assert "Saudação" in policies["customer_service_guidelines"].text  # list 1..5 stays in section 7


def test_interpretation_notes_attached():
    text = get_sections(["payment_methods"])
    assert "Internal interpretation note" in text
    assert "R$ 50,00" in text


def test_unknown_topic_does_not_break():
    assert "unknown topic" in get_sections(["xyz"])
