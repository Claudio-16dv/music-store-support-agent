"""Reading the policy manual (PDF) and retrieving it by section.

The manual has 8 pages and 10 well-delimited sections. Instead of embeddings +
a vector store, the PDF is split along its own numbered sections and the
model picks which sections to read (topic routing via tool calling). For a
document this size that is more accurate, deterministic and cheaper than
vector search — see the README.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import config

# Numbered manual section -> topic key used by the tool.
SECTION_KEYS = {
    1: "about_the_store",
    2: "opening_hours",
    3: "payment_methods",
    4: "returns_and_exchanges",
    5: "shipping_and_delivery",
    6: "promotions",
    7: "customer_service_guidelines",
    8: "warranty",
    9: "data_privacy",
    10: "final_provisions",
}

# The manual contradicts itself in a few places. The interpretations adopted
# are attached to the matching section so the agent always answers the same way.
INTERPRETATION_NOTES = {
    "about_the_store": (
        "Official contact: phone/WhatsApp (67) 3341-4444 and e-mail "
        "contato@emporiodamusica.com.br (no accent — the accent in the table is a typo; "
        "the cover has the correct address). The number (67) 3321-4500 mentioned in "
        "section 7 contradicts the cover and the company data table; use (67) 3341-4444."
    ),
    "payment_methods": (
        "The table says 'parcela mínima de R$ 100,00' (minimum installment) for credit, but "
        "section 3.1 details tiers. The more specific rule (3.1) prevails: 1x to 3x with a "
        "minimum installment of R$ 50,00; 4x to 6x with a minimum of R$ 80,00; 7x to 12x with "
        "a minimum of R$ 100,00. Use the simulate_payment tool to compute the options for an amount."
    ),
    "returns_and_exchanges": (
        "Section 4.2 says that after 30 days the customer must go to the manufacturer, but section "
        "8.1 (Consumer Defense Code) gives a 90-day legal warranty from receipt. Interpretation: "
        "within those 90 days the store handles manufacturing defects (open a ticket for the team); "
        "after that, the manufacturer's warranty applies and the store can mediate."
    ),
    "customer_service_guidelines": (
        "The official WhatsApp number is (67) 3341-4444 (see about_the_store)."
    ),
}


@dataclass(frozen=True)
class PolicySection:
    number: int
    key: str
    title: str
    text: str


def _clean_page(text: str) -> str:
    # pypdf returns one word per line for this PDF; join everything into running text.
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"(\d)\s+-\s*(\d)", r"\1-\2", text)  # "3341 - 4444" -> "3341-4444"
    text = text.replace("​", "")
    text = re.sub(r"Empório da Música Manual de Políticas e Procedimentos", " ", text)
    text = re.sub(r"Página \d+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _split_sections(full_text: str) -> list[PolicySection]:
    """Cuts the text at the known section titles ("N. Title"), in order.

    Looking the titles up in sequence avoids mistaking subsections ("3.1") or
    numbered lists inside a section ("1. Saudação") for section titles.
    """
    starts: list[int] = []
    pos = 0
    for n, title in _TITLES.items():
        idx = full_text.find(f"{n}. {title}", pos)
        if idx < 0:
            raise ValueError(f"Section '{n}. {title}' not found in the policy manual")
        starts.append(idx)
        pos = idx + 1
    starts.append(len(full_text))

    return [
        PolicySection(n, SECTION_KEYS[n], title, full_text[starts[i] : starts[i + 1]].strip())
        for i, (n, title) in enumerate(_TITLES.items())
    ]


# Section titles exactly as they appear in the (Portuguese) manual.
_TITLES = {
    1: "Sobre a Empório da Música",
    2: "Horário de Funcionamento",
    3: "Formas de Pagamento",
    4: "Política de Trocas e Devoluções",
    5: "Política de Frete e Entregas",
    6: "Promoções e Descontos",
    7: "Atendimento via WhatsApp",
    8: "Garantia",
    9: "Privacidade e Proteção de Dados",
    10: "Disposições Finais",
}


@lru_cache(maxsize=1)
def load_policies(pdf_path: Path = config.POLICIES_PDF) -> dict[str, PolicySection]:
    reader = PdfReader(str(pdf_path))
    pages = [_clean_page(p.extract_text() or "") for p in reader.pages]
    cover, body = pages[0], " ".join(pages[1:])
    sections = _split_sections(body)
    result = {s.key: s for s in sections}
    # The cover has the address/phone/e-mail: attach it to the "about the store" section.
    about = result["about_the_store"]
    result["about_the_store"] = PolicySection(
        about.number, about.key, about.title, f"{about.text} Manual cover: {cover}"
    )
    return result


def get_sections(keys: list[str]) -> str:
    policies = load_policies()
    if "all" in keys:
        keys = list(SECTION_KEYS.values())
    parts = []
    for key in dict.fromkeys(keys):  # dedupe, keeping order
        section = policies.get(key)
        if section is None:
            parts.append(f"[{key}] unknown topic. Valid topics: {', '.join(SECTION_KEYS.values())}")
            continue
        text = f"## {section.number}. {section.title}\n{section.text}"
        if key in INTERPRETATION_NOTES:
            text += f"\n[Internal interpretation note] {INTERPRETATION_NOTES[key]}"
        parts.append(text)
    return "\n\n".join(parts)
