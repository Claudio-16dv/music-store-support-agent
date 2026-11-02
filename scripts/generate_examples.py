"""Runs scripted conversations against the real agent and saves them to examples/*.md.

The replies are generated live by the model (nothing is hand-edited); the tool
calls are recorded in <details> blocks to show when the agent checked data or
policies. The customer messages are in Portuguese, like the store's customers.

Usage: python scripts/generate_examples.py [scenario_name ...]
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

SCENARIOS: dict[str, tuple[str, str, list[str]]] = {
    "01_guitar_catalog": (
        "Guitar catalog",
        "Catalog lookup with a price filter and a recommendation for a beginner.",
        [
            "Oi! Quais opções de violões vocês têm custando até R$1000?",
            "Sou iniciante e quero tocar MPB, qual você indica?",
        ],
    ),
    "02_price_and_payment": (
        "Price and payment",
        "Price of a specific model and a PIX/installment simulation following the store's rules.",
        [
            "Quanto custa o Takamine GD20?",
            "Se eu pagar no PIX fica quanto? E dá pra parcelar em quantas vezes?",
        ],
    ),
    "03_return_and_warranty": (
        "Return and warranty",
        "Return/exchange policy applied to a real order, with identity verification.",
        [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 7, meu e-mail é leticia.rocha@jmail.com",
            "Na verdade o ukulele começou a apresentar um chiado no braço, parece defeito. E agora?",
            "Pode registrar sim, usa o mesmo e-mail.",
        ],
    ),
    "04_late_order_lgpd": (
        "Late order with LGPD verification",
        "Order status: first with a wrong contact (LGPD), then the right one; the late order becomes a ticket.",
        [
            "Boa tarde, cadê meu pedido 8? Meu email é ana@gmail.com",
            "Ah desculpa, é o telefone (67) 99654-7821",
            "Já faz muito tempo! Quero registrar uma reclamação, pode me ligar nesse mesmo número.",
        ],
    ),
    "05_scope_and_store_info": (
        "Scope and store info",
        "Out-of-scope requests (accessories and an unrelated topic), an expired promotion and store details.",
        [
            "Vocês vendem cordas e pedal de distorção?",
            "Beleza. Aproveitando, me ajuda a escrever uma redação sobre a Revolução Francesa?",
            "Haha ok. Vi que o Crafter CE-15 estava na Black Friday, ainda tá com desconto?",
            "Qual o endereço da loja e até que horas abre no sábado?",
        ],
    ),
}


def render(title: str, description: str, turns: list[tuple[str, object]]) -> str:
    now = datetime.now(config.TIMEZONE)
    lines = [
        f"# {title}",
        "",
        f"> {description}",
        ">",
        f"> Generated automatically by `scripts/generate_examples.py` on {now:%Y-%m-%d %H:%M} "
        f"(Campo Grande time) with the `{config.MODEL}` model (OpenAI). The conversation is in "
        "Portuguese, as with the store's real customers.",
        "",
    ]
    for user_text, reply in turns:
        lines += [f"**Customer:** {user_text}", ""]
        if reply.tool_calls:
            lines += ["<details><summary>🔧 Tools called</summary>", ""]
            for call in reply.tool_calls:
                args = json.dumps(call.input, ensure_ascii=False)
                output = call.output if len(call.output) < 1500 else call.output[:1500] + " …"
                lines += [f"- `{call.name}({args})`", "", "  ```json", f"  {output}", "  ```", ""]
            lines += ["</details>", ""]
        body = reply.text.replace("\n", "  \n")
        lines += [f"**Lia:** {body}", "", "---", ""]
    return "\n".join(lines)


def main(selected: list[str]) -> None:
    out_dir = ROOT / "examples"
    out_dir.mkdir(exist_ok=True)
    for name, (title, description, messages) in SCENARIOS.items():
        if selected and name not in selected:
            continue
        agent = EmporioAgent()
        turns = []
        for msg in messages:
            reply = agent.send(msg)
            turns.append((msg, reply))
            print(f"[{name}] customer: {msg}\n[{name}] lia: {reply.text}\n")
        (out_dir / f"{name}.md").write_text(render(title, description, turns), encoding="utf-8")
        print(f"→ examples/{name}.md")


if __name__ == "__main__":
    main(sys.argv[1:])
