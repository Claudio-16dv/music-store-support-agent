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
pytest                                # 49 tests, no API calls
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
- **Prompt caching:** OpenAI automatically caches repeated prefixes. That is why the system prompt is static and comes first. The **current date/time** is added on each turn as a system message next to the customer's message, without changing the prefix. The time is needed for opening hours and deadlines, and the note also flags public holidays, when the store is closed (national and Mato Grosso do Sul holidays from the `holidays` package, plus Campo Grande's anniversary on August 26).
- **Provider independence:** the business logic (data, policies, tools, prompt) does not depend on the provider. Only `agent.py` talks to the API, so switching providers means rewriting that file. I did this in practice: the project started on the Anthropic API and moved to OpenAI (see the commit history).

### Prompt strategy

The system prompt (`prompts.py`) is written in English and tells the model to always reply in Brazilian Portuguese. It defines:
- the **persona**: Lia, informal but professional, short WhatsApp-style messages, as section 7.1 of the manual asks;
- **when to use each tool**, tied to each kind of question;
- the manual's **special situations**: out-of-stock or discontinued product, expired promotion, complaint, a public holiday, an order marked as delivered that the customer says never arrived;
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
| Several promotions per product (93, 96, 99), all of them already ended | Only active promotions count; if more than one were active, the largest would win (they don't stack). Ended ones are returned as `ended_promotions`, so the agent can say a campaign is over and give the current price |
| No promotional price in the CSV | Computed (`price × (1 − discount)`) and always shown with the original price and the % |
| `specs` JSON in different formats | Lenient parsing and normalized keys |
| Text search ("takamine gd 20", "violões", accents, case) | Accent-free, whole-word matching with light plural/gender stemming; numbers are kept ("violão 7 cordas" only returns 7-string guitars); split model codes are glued only when the glued form exists ("gd 20" → "gd20"). Partial results are flagged as **approximate** so the agent does not mistake them for the requested item |
| A customer asks for a model that is out of stock, discontinued or coming soon | The default search only returns products for sale, so when the exact model exists only among unavailable ones, it is returned with its real situation and the agent explains it instead of saying "we don't have it" |
| **Descriptions that name another brand** (ids 135, 137, 139, 140, 142, 144; e.g. "Music Man Bass 1X" described as a "Fender Jazz Bass", "Korg" keyboard described as a Roland with 88 keys while the specs say 61) | Detected automatically (the description mentions a brand that is not in the name). The name and specs are treated as the source of truth: those descriptions are left out of the search index and of `product_details`, to avoid misleading information |
| Customers 11 and 43 share the same e-mail | A shared e-mail does not verify order ownership; the agent asks for the phone instead |
| Some past orders do not follow today's rules (PIX orders 1, 5, 10, 13 and 17 charged without the 5% discount; orders 9, 16 and 18 with installments below the minimum) | Historical orders are shown as recorded; the rules are only applied to new simulations |
| Orders have no actual receipt date | The delivery estimate is used as the reference for deadlines, and the agent is told so |
| Some order totals ≠ sum of current prices (e.g. orders 3 and 20) | The order total is treated as the amount actually charged (prices change, discounts may apply); it is not recomputed |
| Orders from 2025–2026 and a moving "today" | Deadlines are computed against the current date: "shipped" orders past their estimate and orders stuck for a long time raise alerts and a ticket offer |
| The manual mentions "more than 300 instruments", including wind and orchestral strings, but the CSV has 65 products and those three categories are empty | The data is the source of truth: the agent says those instruments are not available at the moment |
| pypdf extracts one word per line | Text normalization before splitting the sections |

### Assumptions about inconsistencies in the manual

The challenge asks for the interpretations to be documented. Assumptions 1–3, 6 and 9 are also attached to the section text returned to the agent (`INTERPRETATION_NOTES`), so it always answers the same way; 4, 5, 7 and 8 are in the system prompt and the tools.

1. **WhatsApp:** the cover and the data table show **(67) 3341-4444**, while section 7 mentions **(67) 3321-4500**. I adopted 3341-4444, which appears in two places, including the company's official table.
2. **E-mail:** the table shows `contato@empóriodamusica.com.br` (with an accent); I treated it as a typo and use the cover's `contato@emporiodamusica.com.br`.
3. **Installments:** the table says "minimum installment of R$ 100,00", but section 3.1 details tiers. The more specific rule prevails. Section 3.1 also says "up to 3x: no minimum installment (except below R$ 50,00)", which I read as a R$ 50 minimum installment for 1x–3x:
   - 1x to 3x: minimum installment of R$ 50;
   - 4x to 6x: minimum of R$ 80;
   - 7x to 12x: minimum of R$ 100.

   A purchase under R$ 50 can be paid in 1x.
4. **Right of withdrawal** applies to online purchases. The data does not say which channel a purchase came from, so the agent asks the customer when it matters.
5. **Closing a sale and reservations:** there is no system for that, so the agent gives the conditions and refers the customer to the store or to a human agent.
6. **Defects after 30 days:** section 4.2 says that after 30 days the customer must go to the manufacturer, but section 8.1 gives a 90-day legal warranty from receipt (Consumer Defense Code). Within those 90 days the store handles the defect (the agent opens a ticket); after that, the manufacturer's warranty applies and the store can mediate.
7. **Holidays:** the manual says the store is closed on holidays without listing them. I used the national and Mato Grosso do Sul holidays plus Campo Grande's anniversary (August 26). Dates I could not confirm as municipal holidays (Corpus Christi, June 13) are treated as regular days.
8. **Exchange for another color/model/size:** section 4.3 allows it "within 7 days" without saying from when. I count it from receipt, like the right of withdrawal.
9. **Shipping at exactly R$ 500,00:** the manual gives free shipping "above R$ 500,00" and R$ 35,00 "below R$ 500,00" in the Campo Grande area, but says nothing about exactly R$ 500,00. I went with the customer-friendly reading: free shipping.

### Security and LGPD

- Order data is only shown with the order number **and** the owner's e-mail/phone.
- When verification fails, the response is the same for "order does not exist" and "details don't match", so it does not reveal whether the order exists.
- From the customer record, the agent only receives the first name; the stored phone, e-mail and city never enter the model's context.
- An e-mail shared by more than one customer record does not verify ownership; the agent asks for the phone.
- The agent never gives a customer's contact, address or order details to a third party (e.g. someone claiming to be a courier), even if they know the order number.
- Tickets require a real phone or e-mail, so the team can always reach the customer back.
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
- **Holiday calendar:** national, state and the city anniversary only; special opening hours (the manual mentions extended hours on dates like Black Friday) are not modeled.
- **Conversation length:** the whole history is resent on every turn and is never trimmed or summarized. Fine for customer service chats; very long sessions would need a window or a summary.
- **Customer language:** Lia always answers in Brazilian Portuguese. I tried telling her to answer in the customer's language, but `gpt-4.1-mini` only did it in 1 of 3 test messages (English and Spanish), and an agent that switches language at random is worse than a predictable one. A language-detection step before the call, or a stronger model, would fix it.
- **Observability:** I would log tokens, latency and tools used per conversation to track cost and quality.

## Use of coding assistants

I used **Claude Code** (Anthropic), in the Claude desktop app, for this challenge. I worked with it the way I would with a fast pair programmer: I set the direction and made the calls, it did most of the typing, and nothing went in without a reason I agreed with.

How it went in practice:

- **Understanding the problem.** Before any code, I had it read the statement, the manual and the CSVs and summarize what was being asked. That brought the messy parts up early (two different phone numbers, conflicting installment rules, products whose status doesn't match their stock), and I agreed on how to handle each one before implementation started.
- **Choosing the approach.** It suggested function calling with closed tools instead of RAG over the CSVs or text-to-SQL, and splitting the PDF by section instead of a vector store. I went with it after we went through the trade-offs (the reasoning is in the sections above). The provider was my call: the project started on Anthropic's API and I switched it to OpenAI, where I had credits. Because only `agent.py` talks to the API, that was a one-file change. I also asked for the code and docs in English while keeping Lia in Portuguese for the customers.
- **Building it.** The code was written in small steps (data, policies, tools, agent loop, CLI, tests), each one tested and committed on its own, so the history shows how the project actually evolved.
- **Testing with real conversations.** Unit tests don't tell you whether the agent behaves well, so we ran real conversations against it. That's how we caught what the tests couldn't: Lia asking for e-mail *and* phone when one is enough, forgetting to give the ticket number, listing 8 of 12 guitars without saying there were more. Most of these were fixed in the prompt and the tool descriptions, not in code. We also compared `gpt-5.4-mini` on the hardest cases and kept `gpt-4.1-mini`.
- **Auditing before delivery.** At the end I asked for a full audit against the challenge statement: a clean install from GitHub, adversarial conversations (prompt injection, someone posing as a courier asking for a customer's address, out-of-stock models, a public holiday) and a second, independent review of every rule against the manual and every claim in this README against the data. It found real problems, like the agent telling a customer the store was open on a holiday, and each one was fixed in its own commit.

What I take from it: the assistant is very fast at the mechanical work (PDF parsing, tests, boilerplate) and good at spotting inconsistencies in data, but it can also be confidently wrong. What made the difference was asking for evidence, by running the agent and checking its answers against the CSVs and the manual, instead of trusting the first answer. That's also why the commits are co-authored with Claude: it's an honest picture of how the work was done.
