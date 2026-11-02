"""Tools (function calling) exposed to the model.

Each tool has a JSON schema (sent to the API) and a Python implementation that
returns a JSON string. Invalid input raises ToolError, which the agent loop
sends back to the model as an error tool result.

Tool outputs are in English (they are read by the model, not the customer);
catalog data and policy text stay in Portuguese, as in the source files.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import config
from .data import (
    AVAILABLE,
    COMING_SOON,
    DISCONTINUED,
    ORDER_STATUS_LABELS,
    OUT_OF_STOCK,
    Product,
    StoreData,
    only_digits,
    payment_method_label,
)
from .policies import SECTION_KEYS, get_sections

WITHDRAWAL_DAYS = 7  # right of withdrawal (arrependimento)
PREFERENCE_EXCHANGE_DAYS = 7  # exchange for another color/model/size (§4.3)
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90
PIX_DISCOUNT = 0.05
# (up to N installments, minimum installment) — section 3.1 of the manual.
INSTALLMENT_TIERS = [(3, 50.0), (6, 80.0), (12, 100.0)]
SPLIT_PAYMENT_MINIMUM = 2000.0


class ToolError(Exception):
    """Invalid input or impossible query; the message is sent to the model."""


def brl(value: float) -> str:
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


def _product_summary(p: Product) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "category": p.category.name,
        "availability": p.availability,
        "price": brl(p.price),
    }
    if p.active_promotion:
        item["promotion"] = {
            "campaign": p.active_promotion.description,
            "discount": f"{p.active_promotion.discount_percent:g}%",
            "promo_price": brl(p.promo_price),
        }
    if p.availability == AVAILABLE:
        item["stock"] = p.stock
    return item


class Toolbox:
    def __init__(self, store: StoreData, clock: Callable[[], date] = today):
        self.store = store
        self.clock = clock
        self._handlers: dict[str, Callable[..., Any]] = {
            "search_products": self.search_products,
            "product_details": self.product_details,
            "list_active_promotions": self.list_active_promotions,
            "lookup_order": self.lookup_order,
            "get_policies": self.get_policies,
            "simulate_payment": self.simulate_payment,
            "create_ticket": self.create_ticket,
        }

    # ----------------------------------------------------------------- schemas

    @property
    def schemas(self) -> list[dict]:
        categories = [c.name for c in self.store.categories.values()]
        return [
            {
                "name": "search_products",
                "description": (
                    "Searches the store's instrument catalog with current price, active promotion and "
                    "stock status. Use it for any question about products, prices, models, brands or "
                    "availability — never state a price or stock level without checking. By default "
                    "it returns only items available for purchase; to check a specific model that may "
                    "be out of stock/discontinued, set include_unavailable=true. Price filters use the "
                    "final price (promotion applied, no PIX discount)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keywords in Portuguese, as in the catalog: brand, model, type (e.g. 'Takamine GD20', 'nylon', 'elétrico', 'tenor'). Empty to list the whole category.",
                        },
                        "category": {"type": "string", "enum": categories},
                        "min_price": {"type": "number", "description": "Minimum price in BRL."},
                        "max_price": {"type": "number", "description": "Maximum price in BRL."},
                        "include_unavailable": {"type": "boolean"},
                        "limit": {"type": "integer", "description": "Maximum number of items (default 15)."},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "product_details",
                "description": (
                    "Full product sheet by id (description, technical specs, price, promotion, stock) "
                    "and, if it is not available, similar alternatives that are in stock."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_active_promotions",
                "description": (
                    "Lists the promotions running now, with original price, discount and promotional "
                    "price. For a specific product, use search_products instead: it also returns the "
                    "promotions that have ended and the current price."
                ),
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "lookup_order",
                "description": (
                    "Looks up an order's status, items, tracking, delivery estimate and return/exchange "
                    "deadlines. Needs two things: the order number and ONE customer contact (e-mail OR "
                    "phone — either one is enough; do not ask for both). The tool itself checks whether "
                    "the contact matches the customer record (LGPD): call it as soon as you have both, "
                    "without judging beforehand whether the contact is right."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {"type": "integer"},
                        "email_or_phone": {
                            "type": "string",
                            "description": "E-mail or phone given by the customer to confirm ownership.",
                        },
                    },
                    "required": ["order_number", "email_or_phone"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_policies",
                "description": (
                    "Returns the official text of the store's policy manual (in Portuguese) for the "
                    "requested topics. Check it before answering about address/contact, opening hours, "
                    "payment and installments, returns and exchanges, shipping and delivery times, "
                    "promotion rules, warranty or data privacy. Several topics can be requested at once."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topics": {
                            "type": "array",
                            "items": {"type": "string", "enum": [*SECTION_KEYS.values(), "all"]},
                            "minItems": 1,
                        }
                    },
                    "required": ["topics"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "simulate_payment",
                "description": (
                    "Computes the payment conditions for a purchase amount following the store's rules: "
                    "PIX price (5% discount, which does not apply to promotional prices), interest-free "
                    "installment options respecting the minimum installments, and whether payment "
                    "methods can be combined. Use it instead of doing the math yourself."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number", "description": "Total purchase amount in BRL."},
                        "is_promotional_price": {
                            "type": "boolean",
                            "description": "true if the amount is already a promotional price (so there is no PIX discount).",
                        },
                    },
                    "required": ["amount", "is_promotional_price"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "create_ticket",
                "description": (
                    "Opens a ticket for the human team: complaint, order problem (delay, damage, "
                    "return/exchange to be carried out), data deletion request, or when the customer "
                    "asks to talk to a person. Confirm the summary and a contact with the customer "
                    "before opening it. Returns the protocol number."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["complaint", "return_exchange", "delivery_delay", "privacy", "talk_to_agent", "other"],
                        },
                        "summary": {"type": "string"},
                        "customer_name": {"type": "string"},
                        "contact": {"type": "string", "description": "Phone or e-mail for the follow-up."},
                        "order_number": {"type": "integer"},
                    },
                    "required": ["type", "summary", "contact"],
                    "additionalProperties": False,
                },
            },
        ]

    # --------------------------------------------------------------- execution

    def run(self, name: str, args: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            result = handler(**args)
        except TypeError as e:  # missing/unexpected argument
            raise ToolError(f"Invalid arguments for {name}: {e}") from e
        return json.dumps(result, ensure_ascii=False)

    # ------------------------------------------------------------------- tools

    def search_products(
        self,
        query: str = "",
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        include_unavailable: bool = False,
        limit: int = 15,
    ) -> dict:
        if category and not self.store.category_by_name(category):
            raise ToolError(f"Unknown category: {category}")
        found, approximate = self.store.search_products(
            query, category, min_price, max_price, include_unavailable
        )
        # A customer asking for a specific model that is out of stock, discontinued or
        # coming soon must hear that, not "we don't have it": look among those too.
        only_unavailable = False
        if query and (approximate or not found) and not include_unavailable:
            unavailable, approx_unavailable = self.store.search_products(
                query, category, min_price, max_price, include_unavailable=True
            )
            if unavailable and not approx_unavailable:
                found, approximate, only_unavailable = unavailable, False, True
        limit = max(1, min(int(limit or 15), 20))
        result: dict[str, Any] = {
            "total_found": len(found),
            "products": [self._summary_with_ended_promotions(p) for p in found[:limit]],
        }
        if only_unavailable:
            result["note"] = (
                "The requested model exists but is NOT available for purchase. Tell the customer "
                "the real situation (out_of_stock: temporarily unavailable; discontinued: no longer "
                "in the catalog; coming_soon: not on sale yet, no date) and use product_details to "
                "suggest available alternatives."
            )
        elif approximate:
            result["note"] = (
                "No product contains all the terms; these are APPROXIMATE results (they match only "
                "some of the terms). Do not present them as the requested item. Remember the store "
                "does not sell accessories."
            )
        elif len(found) > limit:
            result["note"] = f"Showing the {limit} cheapest; refine the search to see others."
        if not found:
            result["note"] = (
                "No products found with these criteria. The store sells musical instruments only "
                "(no accessories). Try other terms, another category or include_unavailable=true."
            )
        return result

    def _summary_with_ended_promotions(self, p: Product) -> dict:
        """Product summary plus promotions that have ended, so Lia can say so when asked."""
        item = _product_summary(p)
        expired = self.store.inactive_promotions_for(p.id)
        if expired and not p.active_promotion:
            item["ended_promotions"] = sorted({pr.description for pr in expired})
        return item

    def product_details(self, product_id: int) -> dict:
        p = self.store.products.get(int(product_id))
        if p is None:
            raise ToolError(f"Product {product_id} does not exist in the catalog.")
        result = self._summary_with_ended_promotions(p)
        if p.description_conflict:
            result["data_note"] = (
                "The catalog description of this product names another brand/model (data error), "
                "so it is omitted. Describe the product only by its name and specs."
            )
        else:
            result["description"] = p.description
        result["specs"] = p.specs
        guidance = {
            OUT_OF_STOCK: "Temporarily out of stock: say so and suggest the alternatives.",
            DISCONTINUED: "No longer part of the catalog: offer equivalent models.",
            COMING_SOON: "Upcoming release not yet on sale: do not confirm a purchase or a date.",
        }.get(p.availability)
        if guidance:
            result["guidance"] = guidance
            result["available_alternatives"] = [_product_summary(a) for a in self.store.similar_available(p)]
        return result

    def list_active_promotions(self) -> dict:
        return {
            "active_promotions": [_product_summary(p) for p in self.store.active_promotions()],
            "rules": "Promotions do not stack and the PIX discount does not apply to promotional prices.",
        }

    def lookup_order(self, order_number: int, email_or_phone: str) -> dict:
        order = self.store.get_order(int(order_number))
        denied = {
            "verified": False,
            "message": (
                "Could not confirm the order with the details provided. Ask the customer to check "
                "the order number and the e-mail/phone used for the purchase. Do not reveal whether "
                "the order exists or any third-party data."
            ),
        }
        if order is None or order.customer is None:
            return denied
        if not self.store.identity_matches(order.customer, email_or_phone=email_or_phone):
            return denied
        if "@" in email_or_phone and self.store.email_is_shared(email_or_phone):
            return {
                "verified": False,
                "message": (
                    "This e-mail is linked to more than one customer record, so it cannot confirm "
                    "ownership. Ask for the phone number used in the purchase instead."
                ),
            }

        today_ = self.clock()
        days_since_purchase = (today_ - order.order_date).days
        result: dict[str, Any] = {
            "verified": True,
            "customer_first_name": order.customer.first_name,
            "order": order.id,
            "order_date": order.order_date.isoformat(),
            "status": ORDER_STATUS_LABELS.get(order.status, order.status),
            "items": [
                {
                    "product": i.product.name if i.product else f"product #{i.product_id}",
                    "quantity": i.quantity,
                }
                for i in order.items
            ],
            "total_paid": brl(order.total),
            "payment_method": payment_method_label(order.payment_method),
            "today": today_.isoformat(),
        }
        if order.tracking_code:
            result["tracking_code"] = order.tracking_code
        if order.estimated_delivery:
            result["estimated_delivery"] = order.estimated_delivery.isoformat()
        if order.notes:
            result["notes"] = order.notes

        alerts = []
        if order.status == "shipped" and order.estimated_delivery and order.estimated_delivery < today_:
            delay = (today_ - order.estimated_delivery).days
            alerts.append(
                f"Delivery estimate passed {delay} days ago. Apologize, share the tracking code and "
                "offer to open a delivery-delay ticket for the team."
            )
        if order.status in ("pending", "confirmed") and days_since_purchase > 15:
            alerts.append(
                f"Order has not moved for {days_since_purchase} days (unusual). Do not make up a reason: "
                "offer to open a ticket for the team to check."
            )
        if order.status == "delivered":
            # There is no actual receipt date; the delivery estimate is used as the reference.
            received = order.estimated_delivery or order.order_date
            days_since_receipt = (today_ - received).days
            legal_until = (received + timedelta(days=LEGAL_WARRANTY_DAYS)).isoformat()
            result["deadlines"] = {
                "receipt_reference": f"{received.isoformat()} (delivery estimate; the actual receipt date is not in the system)",
                "withdrawal_7_days_after_receipt": "within the deadline" if days_since_receipt <= WITHDRAWAL_DAYS else f"expired ({days_since_receipt} days since receipt)",
                "preference_exchange_7_days_after_receipt": "within the deadline (subject to availability of the desired product)" if days_since_receipt <= PREFERENCE_EXCHANGE_DAYS else f"expired ({days_since_receipt} days since receipt)",
                "defect_exchange_30_days_after_purchase": "within the deadline" if days_since_purchase <= DEFECT_EXCHANGE_DAYS else f"expired ({days_since_purchase} days since purchase)",
                # §4.2 sends defects to the manufacturer after 30 days, but §8.1 (CDC) gives a
                # 90-day legal warranty from receipt: within it, the store handles the defect.
                "legal_warranty_90_days_after_receipt": (
                    f"active until {legal_until}: the store handles manufacturing defects (open a ticket for the team)"
                    if days_since_receipt <= LEGAL_WARRANTY_DAYS
                    else f"ended on {legal_until}: defects go to the manufacturer's warranty (6 months to 2 years); the store can mediate"
                ),
                "note": (
                    "Deadlines are counted from the estimated delivery date. Do not present it as the "
                    "actual delivery date; if the customer received it later, take that into account "
                    "before saying a deadline has expired."
                ),
            }
        if alerts:
            result["alerts"] = alerts
        return result

    def get_policies(self, topics: list[str]) -> dict:
        if not topics:
            raise ToolError("Provide at least one topic.")
        return {"policies": get_sections(topics)}

    def simulate_payment(self, amount: float, is_promotional_price: bool) -> dict:
        amount = float(amount)
        if amount <= 0:
            raise ToolError("The amount must be positive.")
        options = []
        for n in range(1, 13):
            minimum = next(m for up_to, m in INSTALLMENT_TIERS if n <= up_to)
            # A purchase under R$ 50 can still be paid in 1x.
            if n == 1 or amount / n >= minimum:
                options.append(n)
        max_installments = max(options)
        return {
            "amount": brl(amount),
            "pix": (
                brl(amount) + " (no extra discount: the amount is already promotional)"
                if is_promotional_price
                else f"{brl(amount * (1 - PIX_DISCOUNT))} (5% discount)"
            ),
            "debit_or_boleto": f"{brl(amount)} upfront (boleto clears in up to 3 business days)",
            "interest_free_credit": f"up to {max_installments}x of {brl(round(amount / max_installments, 2))}",
            "possible_installments": options,
            "can_combine_payment_methods": amount > SPLIT_PAYMENT_MINIMUM,
        }

    def create_ticket(
        self,
        type: str,
        summary: str,
        contact: str,
        customer_name: str = "",
        order_number: int | None = None,
    ) -> dict:
        if "@" not in contact and len(only_digits(contact)) < 8:
            raise ToolError(
                "A valid phone number or e-mail is required: ask the customer for one before opening the ticket."
            )
        protocol = f"EM-{datetime.now(config.TIMEZONE):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        record = {
            "protocol": protocol,
            "created_at": datetime.now(config.TIMEZONE).isoformat(timespec="seconds"),
            "type": type,
            "summary": summary,
            "customer_name": customer_name,
            "contact": contact,
            "order_number": order_number,
        }
        config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with config.TICKETS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {
            "protocol": protocol,
            "response_time": "within 24 business hours",
            "message": "Ticket created and forwarded to the responsible team.",
        }
