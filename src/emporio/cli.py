"""Command-line interface to chat with Lia.

Usage:
    python -m emporio.cli                  # new conversation
    python -m emporio.cli --session ID     # resume (or create) session ID
    python -m emporio.cli --debug          # show the tool calls
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

HELP = "Commands: /new (new conversation), /debug (toggle tool output), /quit"


def print_reply(reply: AgentReply, debug: bool) -> None:
    if debug:
        for call in reply.tool_calls:
            args = json.dumps(call.input, ensure_ascii=False)
            flag = " [error]" if call.is_error else ""
            print(f"{DIM}  ↳ {call.name}({args}){flag}\n    {call.output[:400]}{RESET}")
    print(f"{CYAN}{BOLD}Lia:{RESET} {reply.text}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Empório da Música customer service (CLI)")
    parser.add_argument("--session", help="session ID to resume/save the conversation")
    parser.add_argument("--debug", action="store_true", help="show the tool calls")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    session_id = args.session or storage.new_session_id()
    messages = storage.load(session_id)
    try:
        agent = EmporioAgent(messages=messages)
    except openai.OpenAIError:  # raised by the client when no API key is configured
        print("Error: OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return 1
    debug = args.debug

    print(f"{BOLD}🎸 Empório da Música — virtual assistant{RESET}")
    print(f"{DIM}Session: {session_id} · model: {config.MODEL} · {HELP}{RESET}\n")
    for who, text in storage.visible_turns(messages):
        label = "You" if who == "customer" else "Lia"
        print(f"{DIM}{label}: {text}{RESET}\n")

    while True:
        try:
            user_text = input(f"{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text == "/quit":
            break
        if user_text == "/debug":
            debug = not debug
            print(f"{DIM}debug {'on' if debug else 'off'}{RESET}\n")
            continue
        if user_text == "/new":
            session_id = storage.new_session_id()
            agent = EmporioAgent(client=agent.client, toolbox=agent.toolbox)
            print(f"{DIM}New session: {session_id}{RESET}\n")
            continue

        try:
            reply = agent.send(user_text)
        except openai.AuthenticationError:
            print("Error: missing or invalid API key. Set OPENAI_API_KEY in .env.")
            return 1
        except openai.RateLimitError:
            print(f"{DIM}Too many requests right now; wait a few seconds and try again.{RESET}\n")
            continue
        except openai.APIConnectionError:
            print(f"{DIM}Could not reach the API. Check your connection and try again.{RESET}\n")
            continue
        except openai.APIStatusError as e:
            print(f"{DIM}API error ({e.status_code}): {e.message}{RESET}\n")
            continue
        storage.save(session_id, agent.messages)
        print_reply(reply, debug)

    print(f"{DIM}Conversation saved. To resume: python -m emporio.cli --session {session_id}{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
