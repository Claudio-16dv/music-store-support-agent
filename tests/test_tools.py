import json

import pytest

from emporio import config
from emporio.tools import ToolError


def run(toolbox, name, **args):
    return json.loads(toolbox.run(name, args))


def test_valid_schemas(toolbox):
    names = {s["name"] for s in toolbox.schemas}
    assert names == set(toolbox._handlers)
    for s in toolbox.schemas:
        assert s["parameters"]["type"] == "object"


def test_search_acoustic_guitars_up_to_1000(toolbox):
    r = run(toolbox, "search_products", category="Violões", max_price=1000, limit=20)
    assert r["total_found"] == len(r["products"]) == 12


def test_out_of_stock_product_suggests_alternatives(toolbox):
    r = run(toolbox, "product_details", product_id=96)
    assert r["availability"] == "out_of_stock"
    assert r["available_alternatives"]
    assert all(a["availability"] == "available" for a in r["available_alternatives"])
    assert r["ended_promotions"] == ["Semana do Músico"]


def test_order_requires_identity(toolbox):
    r = run(toolbox, "lookup_order", order_number=8, email_or_phone="intruder@x.com")
    assert r["verified"] is False
    assert "Kala" not in json.dumps(r)
    r = run(toolbox, "lookup_order", order_number=999, email_or_phone="a@b.com")
    assert r["verified"] is False


def test_delivered_order_computes_deadlines(toolbox):
    # Order 7: delivered, estimate 2026-02-17; "today" in the tests = 2026-03-25.
    r = run(toolbox, "lookup_order", order_number=7, email_or_phone=_email(toolbox, 7))
    assert r["status"] == "delivered"
    assert r["deadlines"]["withdrawal_7_days_after_receipt"].startswith("expired")
    assert r["deadlines"]["defect_exchange_30_days_after_purchase"].startswith("expired")
    assert r["deadlines"]["legal_warranty_90_days_after_receipt"] == "active"


def test_late_shipped_order_raises_alert(toolbox):
    r = run(toolbox, "lookup_order", order_number=8, email_or_phone=_email(toolbox, 8))
    assert r["tracking_code"] == "BRJL5544332BR"
    assert "passed" in r["alerts"][0]


def test_cancelled_order_shows_reason(toolbox):
    r = run(toolbox, "lookup_order", order_number=18, email_or_phone=_email(toolbox, 18))
    assert r["status"] == "cancelled"
    assert "fora de estoque" in r["notes"]


@pytest.mark.parametrize(
    "amount,promo,max_installments,pix",
    [
        (2199, False, 12, "R$ 2.089,05 (5% discount)"),
        (159.9, False, 3, "R$ 151,91 (5% discount)"),
        (439.2, True, 5, "R$ 439,20 (no extra discount: the amount is already promotional)"),
        (40, False, 1, "R$ 38,00 (5% discount)"),
    ],
)
def test_simulate_payment(toolbox, amount, promo, max_installments, pix):
    r = run(toolbox, "simulate_payment", amount=amount, is_promotional_price=promo)
    assert max(r["possible_installments"]) == max_installments
    assert r["pix"] == pix
    assert r["can_combine_payment_methods"] is (amount > 2000)


def test_create_ticket_writes_file(toolbox):
    r = run(toolbox, "create_ticket", type="complaint", summary="test", contact="a@b.com")
    assert r["protocol"].startswith("EM-")
    lines = config.TICKETS_FILE.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["protocol"] == r["protocol"]


def test_input_errors(toolbox):
    with pytest.raises(ToolError):
        toolbox.run("does_not_exist", {})
    with pytest.raises(ToolError):
        toolbox.run("search_products", {"category": "Acessórios"})
    with pytest.raises(ToolError):
        toolbox.run("product_details", {})


def _email(toolbox, order_id):
    return toolbox.store.orders[order_id].customer.email
