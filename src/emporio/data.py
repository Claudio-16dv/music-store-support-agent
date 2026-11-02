"""Loading, cleaning and querying of the store's operational data (CSVs).

The CSVs are small (tens of rows), so everything is loaded into memory at
startup. Cleaning/interpretation rules live here so the agent's tools always
receive consistent data.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import config

# Product status in the CSV -> sales availability exposed to the agent.
AVAILABLE = "available"
OUT_OF_STOCK = "out_of_stock"
DISCONTINUED = "discontinued"
COMING_SOON = "coming_soon"

ORDER_STATUS_LABELS = {
    "pending": "awaiting payment",
    "confirmed": "payment confirmed, being prepared",
    "shipped": "shipped",
    "delivered": "delivered",
    "cancelled": "cancelled",
}

# Customers (and the catalog) write in Portuguese, so the stopwords are Portuguese.
STOPWORDS = {"de", "da", "do", "das", "dos", "para", "com", "sem", "e", "o", "a", "os", "as", "um", "uma", "em", "no", "na"}

PAYMENT_METHOD_LABELS = {
    "pix": "PIX",
    "debit": "debit card",
    "boleto": "boleto (bank slip)",
}


def normalize(text: str) -> str:
    """Lowercase, accent-free, single-spaced — the basis of all text search."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def only_digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def payment_method_label(code: str) -> str:
    if code.startswith("credit_"):
        return f"credit card in {code.removeprefix('credit_')} installments"
    return PAYMENT_METHOD_LABELS.get(code, code)


@dataclass
class Category:
    id: int
    name: str
    description: str


@dataclass
class Promotion:
    id: int
    product_id: int
    discount_percent: float
    description: str
    is_active: bool


@dataclass
class Product:
    id: int
    name: str
    price: float
    category: Category
    description: str
    stock: int
    raw_status: str
    specs: dict
    created_at: str
    active_promotion: Promotion | None = None
    _search_text: str = field(default="", repr=False)

    @property
    def availability(self) -> str:
        if self.raw_status == "discontinued":
            return DISCONTINUED
        if self.raw_status == "coming_soon":
            return COMING_SOON
        return AVAILABLE if self.stock > 0 else OUT_OF_STOCK

    @property
    def promo_price(self) -> float | None:
        if not self.active_promotion:
            return None
        return round(self.price * (1 - self.active_promotion.discount_percent / 100), 2)

    @property
    def final_price(self) -> float:
        return self.promo_price if self.promo_price is not None else self.price


@dataclass
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


@dataclass
class OrderItem:
    product: Product | None
    product_id: int
    quantity: int


@dataclass
class Order:
    id: int
    customer: Customer | None
    order_date: date
    status: str
    total: float
    payment_method: str
    tracking_code: str
    estimated_delivery: date | None
    notes: str
    items: list[OrderItem] = field(default_factory=list)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_specs(raw: str) -> dict:
    try:
        specs = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    # Some products have keys/values with extra spaces; normalize them.
    return {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in specs.items()}


class StoreData:
    """In-memory repository with the queries the agent needs."""

    def __init__(self, data_dir: Path = config.DATA_DIR):
        self.categories = {
            int(r["category_id"]): Category(int(r["category_id"]), r["name"], r["description"])
            for r in _read_csv(data_dir / "categories.csv")
        }

        self.products: dict[int, Product] = {}
        for r in _read_csv(data_dir / "products.csv"):
            p = Product(
                id=int(r["product_id"]),
                name=r["name"],
                price=float(r["price_brl"]),
                category=self.categories[int(r["category_id"])],
                description=r["description"],
                stock=int(r["stock_quantity"] or 0),
                raw_status=r["status"].lower(),
                specs=_parse_specs(r["specs"]),
                created_at=r["created_at"],
            )
            p._search_text = normalize(
                " ".join([p.name, p.category.name, p.description, *map(str, p.specs.values())])
            )
            self.products[p.id] = p

        self.promotions = [
            Promotion(
                id=int(r["promotion_id"]),
                product_id=int(r["product_id"]),
                discount_percent=float(r["discount_percent"]),
                description=r["description"],
                is_active=r["is_active"] == "1",
            )
            for r in _read_csv(data_dir / "promotions.csv")
        ]
        for promo in self.promotions:
            product = self.products.get(promo.product_id)
            if not promo.is_active or product is None:
                continue
            # Promotions don't stack: if more than one is active, the largest wins.
            current = product.active_promotion
            if current is None or promo.discount_percent > current.discount_percent:
                product.active_promotion = promo

        self.customers = {
            int(r["customer_id"]): Customer(
                int(r["customer_id"]), r["name"], r["phone"], r["email"], r["city"]
            )
            for r in _read_csv(data_dir / "customers.csv")
        }

        self.orders: dict[int, Order] = {}
        for r in _read_csv(data_dir / "orders.csv"):
            o = Order(
                id=int(r["order_id"]),
                customer=self.customers.get(int(r["customer_id"])),
                order_date=date.fromisoformat(r["order_date"]),
                status=r["status"].lower(),
                total=float(r["total_brl"]),
                payment_method=r["payment_method"],
                tracking_code=r["tracking_code"],
                estimated_delivery=_parse_date(r["estimated_delivery"]),
                notes=r["notes"],
            )
            self.orders[o.id] = o
        for r in _read_csv(data_dir / "order_items.csv"):
            order = self.orders.get(int(r["order_id"]))
            if order is None:
                continue
            pid = int(r["product_id"])
            order.items.append(OrderItem(self.products.get(pid), pid, int(r["quantity"])))

    # ------------------------------------------------------------------ products

    def category_by_name(self, name: str) -> Category | None:
        target = normalize(name)
        for c in self.categories.values():
            if normalize(c.name) == target:
                return c
        return None

    def search_products(
        self,
        query: str = "",
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        include_unavailable: bool = False,
    ) -> tuple[list[Product], bool]:
        """Text search + filters. Price filters use the final (promotional) price.

        Every term must appear in the product; if nothing matches, it tries
        gluing the terms together ("takamine gd 20" -> GD20) and finally falls
        back to partial matching. Returns (products, approximate) —
        approximate=True means not all terms were found.
        """
        candidates = list(self.products.values())
        if category:
            cat = self.category_by_name(category)
            candidates = [p for p in candidates if cat and p.category.id == cat.id]
        if not include_unavailable:
            candidates = [p for p in candidates if p.availability == AVAILABLE]
        if min_price is not None:
            candidates = [p for p in candidates if p.final_price >= min_price]
        if max_price is not None:
            candidates = [p for p in candidates if p.final_price <= max_price]

        terms = [t for t in normalize(query).split() if len(t) > 1 and t not in STOPWORDS]
        if not terms:
            return sorted(candidates, key=lambda p: p.final_price), False

        def score(p: Product) -> int:
            compact = p._search_text.replace(" ", "").replace("-", "")
            return sum(1 for t in terms if t in p._search_text or t.replace("-", "") in compact)

        exact = [p for p in candidates if score(p) == len(terms)]
        if exact:
            return sorted(exact, key=lambda p: p.final_price), False
        # Glue neighbouring terms ("gd 20" -> "gd20") before falling back to partial matching.
        joined = "".join(terms)
        glued = [p for p in candidates if joined in p._search_text.replace(" ", "").replace("-", "")]
        if glued:
            return sorted(glued, key=lambda p: p.final_price), False
        partial = [(score(p), p) for p in candidates if score(p) > 0]
        partial.sort(key=lambda sp: (-sp[0], sp[1].final_price))
        return [p for _, p in partial], True

    def similar_available(self, product: Product, limit: int = 3) -> list[Product]:
        """Available alternatives from the same category, closest in price."""
        same_cat = [
            p
            for p in self.products.values()
            if p.category.id == product.category.id and p.id != product.id and p.availability == AVAILABLE
        ]
        same_cat.sort(key=lambda p: abs(p.final_price - product.final_price))
        return same_cat[:limit]

    def active_promotions(self) -> list[Product]:
        return sorted(
            (p for p in self.products.values() if p.active_promotion),
            key=lambda p: -p.active_promotion.discount_percent,
        )

    def inactive_promotions_for(self, product_id: int) -> list[Promotion]:
        return [p for p in self.promotions if p.product_id == product_id and not p.is_active]

    # ------------------------------------------------------------------ orders

    def get_order(self, order_id: int) -> Order | None:
        return self.orders.get(order_id)

    @staticmethod
    def identity_matches(customer: Customer, email_or_phone: str) -> bool:
        """Checks whether the given contact belongs to the order owner (LGPD)."""
        value = (email_or_phone or "").strip()
        if "@" in value:
            return value.casefold() == customer.email.casefold()
        digits = only_digits(value)
        # Accepts numbers with or without area/country code: compares the last
        # 8 digits and requires at least 8 digits.
        return len(digits) >= 8 and only_digits(customer.phone).endswith(digits[-8:])
