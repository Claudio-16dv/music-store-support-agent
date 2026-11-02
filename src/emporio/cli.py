"""Interface de linha de comando para conversar com a Lia.

Uso:
    python -m emporio.cli                 # nova conversa
    python -m emporio.cli --sessao ID     # retoma (ou cria) a sessão ID
    python -m emporio.cli --debug         # mostra as ferramentas chamadas
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import openai

from . import config, storage
from .agent import AgentReply, EmporioAgent

BOLD, DIM, CYAN, RESET = "\033[1m", "\033[2m", "\033[36m", "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = CYAN = RESET = ""

HELP = "Comandos: /nova (nova conversa), /debug (liga/desliga ferramentas), /sair"


def print_reply(reply: AgentReply, debug: bool) -> None:
    if debug:
        for call in reply.tool_calls:
            args = json.dumps(call.input, ensure_ascii=False)
            flag = " [erro]" if call.is_error else ""
            print(f"{DIM}  ↳ {call.name}({args}){flag}\n    {call.output[:400]}{RESET}")
    print(f"{CYAN}{BOLD}Lia:{RESET} {reply.text}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atendimento Empório da Música (CLI)")
    parser.add_argument("--sessao", help="ID da sessão para retomar/salvar a conversa")
    parser.add_argument("--debug", action="store_true", help="mostra as chamadas de ferramenta")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    session_id = args.sessao or storage.new_session_id()
    messages = storage.load(session_id)
    agent = EmporioAgent(messages=messages)
    debug = args.debug

    print(f"{BOLD}🎸 Empório da Música — atendimento virtual{RESET}")
    print(f"{DIM}Sessão: {session_id} · modelo: {config.MODEL} · {HELP}{RESET}\n")
    for who, text in storage.visible_turns(messages):
        label = "Você" if who == "cliente" else "Lia"
        print(f"{DIM}{label}: {text}{RESET}\n")

    while True:
        try:
            user_text = input(f"{BOLD}Você:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text == "/sair":
            break
        if user_text == "/debug":
            debug = not debug
            print(f"{DIM}debug {'ligado' if debug else 'desligado'}{RESET}\n")
            continue
        if user_text == "/nova":
            session_id = storage.new_session_id()
            agent = EmporioAgent(client=agent.client, toolbox=agent.toolbox)
            print(f"{DIM}Nova sessão: {session_id}{RESET}\n")
            continue

        try:
            reply = agent.send(user_text)
        except openai.AuthenticationError:
            print("Erro: chave da API inválida ou ausente. Configure OPENAI_API_KEY no .env.")
            return 1
        except openai.RateLimitError:
            print(f"{DIM}Muitas requisições agora; aguarde alguns segundos e tente de novo.{RESET}\n")
            continue
        except openai.APIConnectionError:
            print(f"{DIM}Sem conexão com a API. Verifique a internet e tente de novo.{RESET}\n")
            continue
        except openai.APIStatusError as e:
            print(f"{DIM}Erro da API ({e.status_code}): {e.message}{RESET}\n")
            continue
        storage.save(session_id, agent.messages)
        print_reply(reply, debug)

    print(f"{DIM}Conversa salva. Para retomar: python -m emporio.cli --sessao {session_id}{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
