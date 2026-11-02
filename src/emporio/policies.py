"""Leitura do manual de políticas (PDF) e recuperação por seção.

O manual tem 8 páginas e 10 seções bem delimitadas. Em vez de embeddings +
banco vetorial, o PDF é dividido nas suas próprias seções numeradas e o
modelo escolhe quais seções consultar (roteamento por tópico via tool
calling). Para um documento desse tamanho isso é mais preciso, determinístico
e barato que busca vetorial — ver README.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import config

# Seção numerada do manual -> chave de tópico usada pela ferramenta.
SECTION_KEYS = {
    1: "sobre_a_loja",
    2: "horario_funcionamento",
    3: "formas_pagamento",
    4: "trocas_devolucoes",
    5: "frete_entregas",
    6: "promocoes",
    7: "diretrizes_atendimento",
    8: "garantia",
    9: "privacidade_dados",
    10: "disposicoes_finais",
}

# O manual tem inconsistências internas. As interpretações adotadas ficam
# anexadas à seção correspondente, para o agente sempre respondê-las igual.
INTERPRETATION_NOTES = {
    "sobre_a_loja": (
        "Contato oficial: telefone/WhatsApp (67) 3341-4444 e e-mail "
        "contato@emporiodamusica.com.br (sem acento — o acento na tabela é erro de "
        "digitação; a capa traz o endereço correto). O número (67) 3321-4500 citado na "
        "seção 7 diverge da capa e da tabela de dados da empresa; usamos (67) 3341-4444."
    ),
    "formas_pagamento": (
        "A tabela diz 'parcela mínima de R$ 100,00' para crédito, mas a seção 3.1 detalha "
        "as faixas. Prevalece a regra mais específica (3.1): 1x a 3x com parcela mínima de "
        "R$ 50,00; 4x a 6x com mínima de R$ 80,00; 7x a 12x com mínima de R$ 100,00. "
        "Use a ferramenta simular_pagamento para calcular as opções de um valor."
    ),
    "diretrizes_atendimento": (
        "O WhatsApp oficial considerado é (67) 3341-4444 (ver sobre_a_loja)."
    ),
}


@dataclass(frozen=True)
class PolicySection:
    number: int
    key: str
    title: str
    text: str


def _clean_page(text: str) -> str:
    # pypdf devolve uma palavra por linha neste PDF; juntamos tudo em texto corrido.
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"(\d)\s+-\s*(\d)", r"\1-\2", text)  # "3341 - 4444" -> "3341-4444"
    text = text.replace("​", "")
    text = re.sub(r"Empório da Música Manual de Políticas e Procedimentos", " ", text)
    text = re.sub(r"Página \d+", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _split_sections(full_text: str) -> list[PolicySection]:
    """Corta o texto nos títulos de seção conhecidos ("N. Título"), em ordem.

    Buscar os títulos em sequência evita confundir subseções ("3.1") ou listas
    numeradas dentro de uma seção ("1. Saudação") com títulos de seção.
    """
    starts: list[int] = []
    pos = 0
    for n, title in _TITLES.items():
        idx = full_text.find(f"{n}. {title}", pos)
        if idx < 0:
            raise ValueError(f"Seção '{n}. {title}' não encontrada no manual de políticas")
        starts.append(idx)
        pos = idx + 1
    starts.append(len(full_text))

    return [
        PolicySection(n, SECTION_KEYS[n], title, full_text[starts[i] : starts[i + 1]].strip())
        for i, (n, title) in enumerate(_TITLES.items())
    ]


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
    # A capa traz endereço/telefone/e-mail: anexamos à seção "sobre a loja".
    about = result["sobre_a_loja"]
    result["sobre_a_loja"] = PolicySection(
        about.number, about.key, about.title, f"{about.text} Capa do manual: {cover}"
    )
    return result


def get_sections(keys: list[str]) -> str:
    policies = load_policies()
    if "todas" in keys:
        keys = list(SECTION_KEYS.values())
    parts = []
    for key in dict.fromkeys(keys):  # remove duplicadas preservando ordem
        section = policies.get(key)
        if section is None:
            parts.append(f"[{key}] tópico inexistente. Tópicos válidos: {', '.join(SECTION_KEYS.values())}")
            continue
        text = f"## {section.number}. {section.title}\n{section.text}"
        if key in INTERPRETATION_NOTES:
            text += f"\n[Nota de interpretação interna] {INTERPRETATION_NOTES[key]}"
        parts.append(text)
    return "\n\n".join(parts)
