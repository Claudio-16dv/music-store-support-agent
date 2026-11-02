"""Roda conversas roteirizadas contra o agente real e salva em exemplos/*.md.

As respostas são geradas ao vivo pelo modelo (nada é editado à mão); as
chamadas de ferramenta ficam registradas em blocos <details> para mostrar
quando o agente consultou dados ou políticas.

Uso: python scripts/gerar_exemplos.py [nome_do_cenario ...]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emporio import config  # noqa: E402
from emporio.agent import EmporioAgent  # noqa: E402

SCENARIOS: dict[str, tuple[str, list[str]]] = {
    "01_catalogo_violoes": (
        "Consulta ao catálogo com filtro de preço e recomendação para iniciante.",
        [
            "Oi! Quais opções de violões vocês têm custando até R$1000?",
            "Sou iniciante e quero tocar MPB, qual você indica?",
        ],
    ),
    "02_preco_e_pagamento": (
        "Consulta de preço de um modelo específico e simulação de PIX/parcelamento pelas regras da loja.",
        [
            "Quanto custa o Takamine GD20?",
            "Se eu pagar no PIX fica quanto? E dá pra parcelar em quantas vezes?",
        ],
    ),
    "03_devolucao_arrependimento": (
        "Aplicação da política de trocas/devoluções a um pedido real, com verificação de identidade.",
        [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 7, meu e-mail é leticia.rocha@jmail.com",
            "Na verdade o ukulele começou a apresentar um chiado no braço, parece defeito. E agora?",
        ],
    ),
    "04_pedido_atrasado_lgpd": (
        "Status de pedido: primeiro com contato errado (LGPD), depois correto; pedido atrasado vira chamado.",
        [
            "Boa tarde, cadê meu pedido 8? Meu email é ana@gmail.com",
            "Ah desculpa, é o telefone (67) 99654-7821",
            "Já faz muito tempo! Quero registrar uma reclamação, pode me ligar nesse mesmo número.",
        ],
    ),
    "05_escopo_e_informacoes_gerais": (
        "Pedidos fora do escopo (acessórios e assunto não relacionado), promoção expirada e dados da loja.",
        [
            "Vocês vendem cordas e pedal de distorção?",
            "Beleza. Aproveitando, me ajuda a escrever uma redação sobre a Revolução Francesa?",
            "Haha ok. Vi que o Crafter CE-15 estava na Black Friday, ainda tá com desconto?",
            "Qual o endereço da loja e até que horas abre no sábado?",
        ],
    ),
}


def render(name: str, description: str, turns: list[tuple[str, object]]) -> str:
    now = datetime.now(config.TIMEZONE)
    lines = [
        f"# {name.split('_', 1)[1].replace('_', ' ').capitalize()}",
        "",
        f"> {description}",
        ">",
        f"> Gerado automaticamente por `scripts/gerar_exemplos.py` em {now:%d/%m/%Y %H:%M} "
        f"(horário de Campo Grande) com o modelo `{config.MODEL}` (OpenAI).",
        "",
    ]
    for user_text, reply in turns:
        lines += [f"**Cliente:** {user_text}", ""]
        if reply.tool_calls:
            lines += ["<details><summary>🔧 Ferramentas consultadas</summary>", ""]
            for call in reply.tool_calls:
                args = json.dumps(call.input, ensure_ascii=False)
                output = call.output if len(call.output) < 1500 else call.output[:1500] + " …"
                lines += [f"- `{call.name}({args})`", "", "  ```json", f"  {output}", "  ```", ""]
            lines += ["</details>", ""]
        body = reply.text.replace("\n", "  \n")
        lines += [f"**Lia:** {body}", "", "---", ""]
    return "\n".join(lines)


def main(selected: list[str]) -> None:
    out_dir = ROOT / "exemplos"
    out_dir.mkdir(exist_ok=True)
    for name, (description, messages) in SCENARIOS.items():
        if selected and name not in selected:
            continue
        agent = EmporioAgent()
        turns = []
        for msg in messages:
            reply = agent.send(msg)
            turns.append((msg, reply))
            print(f"[{name}] cliente: {msg}\n[{name}] lia: {reply.text}\n")
        (out_dir / f"{name}.md").write_text(render(name, description, turns), encoding="utf-8")
        print(f"→ exemplos/{name}.md")


if __name__ == "__main__":
    main(sys.argv[1:])
