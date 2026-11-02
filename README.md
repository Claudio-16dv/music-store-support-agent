# 🎸 Empório da Música — Customer Service Agent

Prototype of a text-message customer service agent for **Empório da Música**, a fictional musical instrument store in Campo Grande/MS, Brazil. The agent (**Lia**) answers customers about the catalog, prices, promotions, order status and store policies, deciding on its own when to check **data** (CSVs) and when to check **policies** (PDF).

The code, prompt and documentation are in English. Lia talks to customers in **Brazilian Portuguese**, because the store and its customers are Brazilian; the source data (CSVs and the policy manual) are also in Portuguese.

```
Customer ──► CLI ──► EmporioAgent (function-calling loop) ──► OpenAI API
                          │                                    ▲
                          ▼                                    │ tool result
                     Toolbox (7 tools) ────────────────────────┘
                      ├─ search_products / product_details / list_active_promotions ─► StoreData (clean CSVs, in memory)
                      ├─ lookup_order (with identity verification)                  ─► StoreData
                      ├─ get_policies (by manual section)                           ─► PDF manual → 10 sections
                      ├─ simulate_payment (PIX/installment rules in code)
                      └─ create_ticket (escalation to a human)                      ─► .runtime/tickets.jsonl
```

## How to run

Requirements: Python 3.11+ and an OpenAI API key.

```bash
git clone https://github.com/Claudio-16dv/music-store-support-agent.git && cd music-store-support-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then fill in OPENAI_API_KEY
```

Chat with the agent:

```bash
python -m emporio.cli                      # new conversation
python -m emporio.cli --debug              # show every tool call and what it returned
python -m emporio.cli --session my-session # resume a saved conversation
```

Inside the chat: `/debug` toggles debug mode, `/new` starts another conversation, `/quit` exits.

Other commands:

```bash
pytest                                # 33 tests, no API calls
python scripts/generate_examples.py   # regenerates the conversations in examples/ (calls the API)
```

Optional settings in `.env`: `EMPORIO_MODEL` (default `gpt-4.1-mini`) and `EMPORIO_REASONING_EFFORT` (`low`/`medium`/`high`, reasoning models only).

## Layout

| Path | Contents |
|---|---|
| `src/emporio/data.py` | CSV loading and cleaning, product search, identity verification |
| `src/emporio/policies.py` | PDF extraction into sections + interpretation notes |
| `src/emporio/tools.py` | Schemas and implementation of the 7 tools |
| `src/emporio/prompts.py` | System prompt (persona and rules) |
| `src/emporio/agent.py` | Agent loop (API call, tool execution, error handling) |
| `src/emporio/storage.py` / `cli.py` | Session persistence and terminal interface |
| `tests/` | Tests for data, policies, tools and the loop (with a fake client) |
| `examples/` | Real conversations with the agent |

## Technical decisions

### Approach: function calling with deterministic tools

The agent is a *tool use* loop: the model receives the message, decides which tools to call, gets the results and replies. Why not the alternatives:

- **Pure vector RAG:** the operational data is **structured** (price, stock, status). Semantic search over CSV rows gets filters like "up to R$ 1000" wrong and does not guarantee exact prices, which the manual itself forbids ("never give information about prices, stock or deadlines without checking the system").
- **SQL agent (text→SQL):** flexible, but it leaves room for wrong queries and for **customer data leaks** (a `SELECT * FROM customers` answers anything). With closed tools, the LGPD (Brazil's data protection law) rule lives in code: `lookup_order` only returns data if the order number **and** the e-mail/phone match.
- **Math in code, not in the model:** PIX, minimum installments per tier, and withdrawal, exchange and warranty deadlines are computed in Python (`simulate_payment`, `lookup_order`). The model explains; the code computes.

I used a **manual loop** over the Chat Completions API (instead of a framework like LangChain) to control the round limit, record the calls (debug mode and examples), handle each `finish_reason`, handle invalid JSON arguments, and roll back the turn if the API fails, so the saved history is never left inconsistent.

### Policy retrieval: by section, no vector store

The manual has 8 pages and 10 numbered sections. The PDF is read with `pypdf`, normalized (`pypdf` returns one word per line for this file) and split along its own section titles. The `get_policies` tool takes topics from an `enum` (`opening_hours`, `returns_and_exchanges`, `payment_methods`…) and the model picks which ones to request.

For a document this size that is **more accurate** (the text comes back whole, with no arbitrary chunk cuts), **deterministic** (easy to test) and **needs no extra infrastructure**. With a much larger manual I would switch to subsection chunks + embeddings, keeping the same tool interface.

I also considered putting the whole manual in the system prompt (about 3k tokens, cheap with caching). I kept the tool because the challenge asks the agent to *know when* to check the policies, and because it keeps the prompt focused on behavior and scales better.

### Model and provider: OpenAI (`gpt-4.1-mini` by default)

- **Provider:** the OpenAI API, through the official `openai` SDK and Chat Completions with *function calling*. The choice was practical: that is where I have credits.
- **Default model `gpt-4.1-mini`:**
  - follows long instructions well and calls tools reliably;
  - is fast and cheap, which matters for customer service with many short messages.
- **Comparison:** I also ran the hardest scenarios (return, and order with verification) with `gpt-5.4-mini`. There was no clear gain, and it even opened a ticket without confirming with the customer. The `gpt-4.1-mini` mistakes were fixed by adjusting the prompt and the tool descriptions. Note: on Chat Completions, `gpt-5.4-mini` only accepts tools with `reasoning_effort=none`.
- **Configurable:** switch it with `EMPORIO_MODEL`. With a reasoning model (e.g. `gpt-5-mini`), set `EMPORIO_REASONING_EFFORT`. The code sends `reasoning_effort` only in that case; otherwise it sends `temperature=0.3` for consistent answers.
- **Prompt caching:** OpenAI automatically caches repeated prefixes. That is why the system prompt is static and comes first. The **current date/time** is added on each turn as a system message next to the customer's message, without changing the prefix. The time is needed for opening hours and deadlines.
- **Provider independence:** the business logic (data, policies, tools, prompt) does not depend on the provider. Only `agent.py` talks to the API, so switching providers means rewriting that file. I did this in practice: the project started on the Anthropic API and moved to OpenAI (see the commit history).

### Prompt strategy

The system prompt (`prompts.py`) is written in English and tells the model to always reply in Brazilian Portuguese. It defines:
- the **persona**: Lia, informal but professional, short WhatsApp-style messages, as section 7.1 of the manual asks;
- **when to use each tool**, tied to each kind of question;
- the manual's **special situations**: out-of-stock or discontinued product, expired promotion, complaint;
- the **scope**: instruments only; accessories are redirected; topics unrelated to the store are declined kindly;
- **security** rules: ignore attempts to change the rules or reveal data.

The tool descriptions reinforce the "when to use". The results carry guidance fields (`guidance`, `alerts`, `note`) that steer the model in the specific case, for example "delivery estimate passed N days ago, offer to open a ticket".

### Interface and persistence

- **CLI**: the focus of the challenge is the agent. `EmporioAgent.send()` is independent of the interface, so an API (FastAPI) or a WhatsApp webhook would be a thin layer on top.
- **History persisted** as JSON per session (`.runtime/sessions/`). The customer can resume the conversation (`--session`), and the history is saved exactly in the format sent to the API.
- **Tickets** (complaints, exchanges, delays) go to `.runtime/tickets.jsonl` with a protocol number. This is the integration point with the human team.

### Data handling

| Issue found | Handling |
|---|---|
| `status` + `stock_quantity` combine ambiguously | Derived availability: `available`, `out_of_stock` (active with stock 0, e.g. id 96), `discontinued`, `coming_soon` |
| Product 136 **discontinued with 13 in stock** | Treated as discontinued, as the policy says: it is not offered and the agent suggests equivalents |
| Product 130 **"coming_soon" with stock 2** and already in orders | Treated as "coming soon": not sold, and the agent does not promise a date |
| More than one promotion per product (e.g. 93 and 96) | Only active promotions count; if more than one is active, the largest wins (they don't stack) |
| No promotional price in the CSV | Computed (`price × (1 − discount)`) and always shown with the original price and the % |
| `specs` JSON in different formats | Lenient parsing and normalized keys |
| Text search ("takamine gd 20", accents, case) | Accent-free normalization, glued terms ("gd 20" → "gd20"); partial results are flagged as **approximate** so the agent does not mistake them for the requested item |
| Orders have no actual receipt date | The delivery estimate is used as the reference for deadlines, and the agent is told so |
| Some order totals ≠ sum of current prices (e.g. orders 3 and 20) | The order total is treated as the amount actually charged (prices change, discounts may apply); it is not recomputed |
| Orders from 2025–2026 and a moving "today" | Deadlines are computed against the current date: "shipped" orders past their estimate and orders stuck for a long time raise alerts and a ticket offer |
| pypdf extracts one word per line | Text normalization before splitting the sections |

### Assumptions about inconsistencies in the manual

The challenge asks for the interpretations to be documented. They are also attached to the section text returned to the agent, so it always answers the same way.

1. **WhatsApp:** the cover and the data table show **(67) 3341-4444**, while section 7 mentions **(67) 3321-4500**. I adopted 3341-4444, which appears in two places, including the company's official table.
2. **E-mail:** the table shows `contato@empóriodamusica.com.br` (with an accent); I treated it as a typo and use the cover's `contato@emporiodamusica.com.br`.
3. **Installments:** the table says "minimum installment of R$ 100,00", but section 3.1 details tiers. The more specific rule prevails:
   - 1x to 3x: minimum installment of R$ 50;
   - 4x to 6x: minimum of R$ 80;
   - 7x to 12x: minimum of R$ 100.

   A purchase under R$ 50 can be paid in 1x.
4. **Right of withdrawal** applies to online purchases. The data does not say which channel a purchase came from, so the agent asks the customer when it matters.
5. **Closing a sale and reservations:** there is no system for that, so the agent gives the conditions and refers the customer to the store or to a human agent.

### Security and LGPD

- Order data is only shown with the order number **and** the owner's e-mail/phone.
- When verification fails, the response is the same for "order does not exist" and "details don't match", so it does not reveal whether the order exists.
- From the customer record, the agent only receives the first name; the stored phone, e-mail and city never enter the model's context.
- The prompt says to ignore attempts to change the rules, take on another role or reveal the prompt.

## Example conversations

Conversations generated live by the agent with `scripts/generate_examples.py`. The conversations are in Portuguese; the tool calls appear in the "🔧 Tools called" blocks.

1. [Guitar catalog up to R$ 1000 + recommendation](examples/01_guitar_catalog.md)
2. [Takamine GD20 price + PIX and installments](examples/02_price_and_payment.md)
3. [Withdrawal/defect applied to a real order](examples/03_return_and_warranty.md) (non-trivial: verifies identity, computes deadlines, applies the policy and opens a ticket)
4. [Late order with LGPD verification](examples/04_late_order_lgpd.md) (non-trivial)
5. [Out of scope, expired promotion and store info](examples/05_scope_and_store_info.md)

## Known limitations and what I would do with more time

- **Automated evaluation:** today the tests cover the deterministic code and the loop, with a fake client. The next step would be an evaluation set with real questions and per-answer criteria: did it use the right tool? Did it make up a price? Did it respect LGPD? That set would run on every prompt or model change.
- **Simple identity verification:** an e-mail or phone is enough, and the phone check compares the last 8 digits. In production, the channel (WhatsApp) would already identify the number and I would add a confirmation code.
- **Shipping:** there is no shipping table in the data, so the agent explains options and delivery times but does not quote prices. A carrier API (Correios/Jadlog) could be integrated.
- **Lexical product search:** works well for brand and model. Subjective requests ("a guitar with a fuller sound") depend on the model reading the descriptions. Embeddings over descriptions and specs would help with a 300+ item catalog.
- **In-memory data read from CSV:** enough for the prototype. In production I would use the store's database/ERP, with the same tools on top.
- **Interface:** CLI only. The next step is to expose `EmporioAgent.send()` through an API and a WhatsApp webhook, with the history in a database instead of files.
- **Tickets** live in a JSONL file. Ideally they would go to a helpdesk or notify the team.
- **Receipt date:** deadlines use the delivery estimate because the actual date is not in the data.
- **Observability:** I would log tokens, latency and tools used per conversation to track cost and quality.

## Use of coding assistants

I used **Claude Code** (Anthropic) as a pair programmer throughout the challenge:

1. **Analysis:** I asked it to read the challenge statement, the PDF manual and the CSVs and give me a summary of what the challenge asked for. The inconsistencies in the data and the manual already showed up at this stage (duplicate phone number, contradictory installment rule, products with inconsistent status and stock).
2. **Plan and decisions:** we discussed the approach (function calling vs. RAG vs. SQL), the provider and the interface. I approved the plan before implementation.
3. **Incremental implementation:** it wrote the code in steps (data → policies → tools → agent → CLI → tests), running the tests and checking the tool output against the real data. Each step became a commit.
4. **Review:** I reviewed the decisions, the assumptions and the example conversations, which were generated live by the agent with the script, not written by hand.

The assistant sped up the mechanical work (parsing, tests, boilerplate). The product and business decisions (what to do with inconsistent data, LGPD rules, scope) were made explicit and documented here.
