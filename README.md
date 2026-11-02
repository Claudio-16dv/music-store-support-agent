# 🎸 Empório da Música — Agente de Atendimento

Protótipo de agente de atendimento por mensagens de texto para a **Empório da Música**, loja fictícia de instrumentos musicais em Campo Grande/MS. O agente (a **Lia**) responde clientes sobre catálogo, preços, promoções, status de pedidos e políticas da loja, decidindo sozinho quando consultar **dados** (CSVs) e quando consultar **políticas** (PDF).

```
Cliente ──► CLI ──► EmporioAgent (loop de function calling) ──► Claude API
                         │                                    ▲
                         ▼                                    │ tool_result
                    Toolbox (7 ferramentas) ──────────────────┘
                     ├─ buscar_produtos / detalhes_produto / listar_promocoes_ativas ─► StoreData (CSVs limpos, em memória)
                     ├─ consultar_pedido (com verificação de identidade)            ─► StoreData
                     ├─ consultar_politicas (por seção do manual)                    ─► Manual PDF → 10 seções
                     ├─ simular_pagamento (regras de PIX/parcelamento em código)
                     └─ registrar_chamado (escalonamento para humano)                ─► .runtime/chamados.jsonl
```

## Como rodar

Pré-requisitos: Python 3.11+ e uma chave da API da Anthropic.

```bash
git clone <url-do-repositorio> && cd emporio-agente
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # e preencha ANTHROPIC_API_KEY
```

Conversar com o agente:

```bash
python -m emporio.cli            # nova conversa
python -m emporio.cli --debug    # mostra cada ferramenta chamada e o que ela retornou
python -m emporio.cli --sessao minha-sessao   # retoma uma conversa salva
```

Dentro do chat: `/debug` liga/desliga o modo debug, `/nova` inicia outra conversa, `/sair` encerra.

Outros comandos:

```bash
pytest                              # 31 testes, não chamam a API
python scripts/gerar_exemplos.py    # regenera as conversas em exemplos/ (chama a API)
```

Configuração opcional no `.env`: `EMPORIO_MODEL` (padrão `claude-opus-5-5`), `EMPORIO_EFFORT` (`low` por padrão), `EMPORIO_FALLBACK` (`1`/`0`).

## Estrutura

| Caminho | O que tem |
|---|---|
| `src/emporio/data.py` | Carga e limpeza dos CSVs, busca de produtos, verificação de identidade |
| `src/emporio/policies.py` | Extração do PDF em seções + notas de interpretação |
| `src/emporio/tools.py` | Schemas e implementação das 7 ferramentas |
| `src/emporio/prompts.py` | Prompt de sistema (persona e regras) |
| `src/emporio/agent.py` | Loop do agente (chamada à API, execução de ferramentas, tratamento de erros) |
| `src/emporio/storage.py` / `cli.py` | Persistência de sessões e interface de terminal |
| `tests/` | Testes de dados, políticas, ferramentas e do loop (com cliente falso) |
| `exemplos/` | Conversas reais com o agente |

## Decisões técnicas

### Abordagem: function calling com ferramentas determinísticas

O agente é um loop de *tool use*: o modelo recebe a mensagem, decide quais ferramentas chamar, recebe os resultados e responde. Por que não as alternativas:

- **RAG vetorial puro:** os dados de operação são **estruturados** (preço, estoque, status). Busca semântica sobre linhas de CSV erra filtros como "até R$ 1000" e não garante preço exato, o que o próprio manual proíbe ("nunca fornecer informações sobre preços, estoque ou prazos sem consultar o sistema").
- **Agente de SQL (texto→SQL):** flexível, mas abre espaço para consultas erradas e para **vazamento de dados de clientes** (um `SELECT * FROM customers` resolve qualquer coisa). Com ferramentas fechadas, a regra de LGPD fica no código: `consultar_pedido` só devolve dados se número do pedido **e** e-mail/telefone baterem.
- **Contas no código, não no modelo:** PIX, parcelas mínimas por faixa, prazos de arrependimento, troca e garantia são calculados em Python (`simular_pagamento`, `consultar_pedido`). O modelo explica; quem calcula é o código.

Usei um **loop manual** em vez do *tool runner* (beta) do SDK para controlar o limite de rodadas, registrar as chamadas (modo debug e exemplos), tratar cada `stop_reason` e desfazer o turno se a API falhar, para o histórico salvo nunca ficar inconsistente.

### Recuperação das políticas: por seção, sem banco vetorial

O manual tem 8 páginas e 10 seções numeradas. O PDF é lido com `pypdf`, normalizado (o `pypdf` devolve uma palavra por linha neste arquivo) e cortado nos próprios títulos de seção. A ferramenta `consultar_politicas` recebe tópicos de um `enum` (`horario_funcionamento`, `trocas_devolucoes`, `formas_pagamento`…) e o modelo escolhe quais pedir.

Para um documento desse tamanho isso é **mais preciso** (o texto volta inteiro, sem cortes arbitrários de chunk), **determinístico** (fácil de testar) e **sem infraestrutura extra**. Com um manual muito maior, eu trocaria por chunks por subseção + embeddings, mantendo a mesma interface da ferramenta.

Também avaliei pôr o manual inteiro no prompt de sistema (cerca de 3 mil tokens, barato com cache). Fiquei com a ferramenta porque o desafio pede que o agente *saiba quando* consultar as políticas, e porque isso mantém o prompt focado em comportamento e escala melhor.

### Modelo e provedor: Claude Opus 5.5 (Anthropic API)

- Bom em **tool use em português** e em seguir regras de negócio longas sem se perder (persona + LGPD + escopo + promoções).
- **`effort: low`**: atendimento é conversa curta com consultas simples, então esforço baixo reduz latência e custo. É configurável por `EMPORIO_EFFORT` caso alguma interação peça mais raciocínio.
- **Cache de prompt** automático: ferramentas + prompt de sistema + histórico ficam em cache entre turnos. Por isso o prompt de sistema é estático, e a **data/hora atual** entra a cada turno como *mensagem de sistema no meio da conversa*, sem invalidar o cache. A hora é necessária para horário de funcionamento e prazos.
- **Fallback server-side** (`fallbacks: "default"`): se o classificador de segurança recusar uma mensagem, a API refaz a resposta em um modelo de fallback em vez de deixar o cliente sem resposta. Pode ser desligado com `EMPORIO_FALLBACK=0`.
- O modelo é configurável (`EMPORIO_MODEL`). Com um modelo que não aceite mensagens de sistema no meio da conversa, seria preciso mover a nota de hora para outro lugar.

### Estratégia de prompt

O prompt de sistema (`prompts.py`) define:
- a **persona**: Lia, informal mas profissional, mensagens curtas no estilo WhatsApp, como pede a seção 7.1 do manual;
- **quando usar cada ferramenta**, ligado a cada tipo de pergunta;
- as **situações especiais** do manual: produto esgotado ou descontinuado, promoção expirada, reclamação;
- o **escopo**: só instrumentos; acessórios são redirecionados; assuntos alheios à loja são recusados com simpatia;
- regras de **segurança**: ignorar tentativas de mudar regras ou revelar dados.

As descrições das ferramentas reforçam o "quando usar". Os resultados trazem campos de orientação (`orientacao`, `alertas`, `obs`) que conduzem o modelo no caso concreto, por exemplo "previsão de entrega vencida há N dias, ofereça registrar um chamado".

### Interface e persistência

- **CLI**: o foco do desafio é o agente. O `EmporioAgent.send()` é independente da interface, então uma API (FastAPI) ou um webhook de WhatsApp seria uma camada fina por cima.
- **Histórico persistido** em JSON por sessão (`.runtime/sessoes/`). O cliente pode retomar a conversa (`--sessao`), e o histórico é salvo exatamente como foi enviado à API, só com acréscimos, o que preserva o cache.
- **Chamados** (reclamações, trocas, atrasos) vão para `.runtime/chamados.jsonl` com número de protocolo. É o ponto de integração com a equipe humana.

### Tratamento dos dados

| Problema encontrado | Tratamento |
|---|---|
| `status` + `stock_quantity` combinam de jeitos ambíguos | Situação derivada: `disponivel`, `esgotado` (ativo com estoque 0, ex.: id 96), `descontinuado`, `em_breve` |
| Produto 136 **descontinuado com 13 em estoque** | Tratado como descontinuado, como manda a política: não é oferecido e o agente sugere equivalentes |
| Produto 130 **"coming_soon" com estoque 2** e já presente em pedidos | Tratado como "em breve": não é vendido e o agente não promete data |
| Mais de uma promoção por produto (ex.: 93 e 96) | Só valem promoções ativas; se houver mais de uma ativa, vale a maior (não são cumulativas) |
| Preço promocional não existe no CSV | Calculado (`preço × (1 − desconto)`) e sempre exibido junto com o original e o % |
| `specs` em JSON com formatos diferentes | Parse tolerante e chaves normalizadas |
| Busca textual ("takamine gd 20", acentos, maiúsculas) | Normalização sem acentos, junção de termos ("gd 20" → "gd20"); resultados parciais são marcados como **aproximados** para o agente não confundi-los com o item pedido |
| Pedidos sem data real de recebimento | A previsão de entrega é usada como referência para os prazos, e o agente é avisado disso |
| Totais de alguns pedidos ≠ soma dos preços atuais (ex.: pedidos 3 e 20) | O total do pedido é tratado como o valor efetivamente cobrado (preços mudam, pode haver desconto); não é recalculado |
| Pedidos de 2025–2026 e "hoje" variável | Os prazos são calculados com a data atual: pedidos "enviados" com previsão vencida e pedidos parados há muito tempo geram alertas e oferta de chamado |
| Pypdf extrai uma palavra por linha | Normalização do texto antes de cortar as seções |

### Suposições sobre inconsistências do manual

O enunciado pede para documentar as interpretações. Elas também são anexadas ao texto das seções devolvidas ao agente, para que ele responda sempre do mesmo jeito.

1. **WhatsApp:** a capa e a tabela de dados trazem **(67) 3341-4444**, e a seção 7 cita **(67) 3321-4500**. Adotei o 3341-4444, que aparece em dois lugares, incluindo a tabela oficial da empresa.
2. **E-mail:** a tabela traz `contato@empóriodamusica.com.br` (com acento); considerei erro de digitação e uso o da capa, `contato@emporiodamusica.com.br`.
3. **Parcelamento:** a tabela diz "parcela mínima de R$ 100,00", mas a seção 3.1 detalha faixas. Prevalece a regra mais específica:
   - 1x a 3x: parcela mínima de R$ 50;
   - 4x a 6x: mínima de R$ 80;
   - 7x a 12x: mínima de R$ 100.

   Uma compra abaixo de R$ 50 pode ser paga em 1x.
4. **Direito de arrependimento** vale para compras online. Os dados não dizem o canal da compra, então o agente pergunta ao cliente quando isso importa.
5. **Fechamento de venda e reserva:** não há sistema para isso, então o agente passa as condições e encaminha para a loja ou para um atendente.

### Segurança e LGPD

- Dados de pedido só são mostrados com número do pedido **e** e-mail/telefone do titular.
- Se a verificação falha, a resposta é a mesma para "pedido inexistente" e "dados não conferem", para não revelar se o pedido existe.
- Do cadastro do cliente, o agente só recebe o primeiro nome; telefone, e-mail e cidade cadastrados nunca entram no contexto do modelo.
- O prompt instrui a ignorar tentativas de mudar regras, assumir outro papel ou revelar o prompt.

## Exemplos de interação

Conversas geradas ao vivo pelo agente com `scripts/gerar_exemplos.py`. As chamadas de ferramenta aparecem nos blocos "🔧 Ferramentas consultadas".

1. [Catálogo de violões até R$ 1000 + recomendação](exemplos/01_catalogo_violoes.md)
2. [Preço do Takamine GD20 + PIX e parcelamento](exemplos/02_preco_e_pagamento.md)
3. [Arrependimento/defeito aplicado a um pedido real](exemplos/03_devolucao_arrependimento.md) (não trivial: verifica identidade, calcula prazos, aplica política e registra chamado)
4. [Pedido atrasado com verificação LGPD](exemplos/04_pedido_atrasado_lgpd.md) (não trivial)
5. [Fora de escopo, promoção expirada e informações da loja](exemplos/05_escopo_e_informacoes_gerais.md)

## Limitações conhecidas e o que eu faria com mais tempo

- **Avaliação automatizada:** hoje os testes cobrem o código determinístico e o loop, com cliente falso. O próximo passo seria um conjunto de avaliação com perguntas reais e critérios por resposta: usou a ferramenta certa? Inventou preço? Respeitou a LGPD? Esse conjunto rodaria a cada mudança de prompt ou de modelo.
- **Verificação de identidade simples:** basta e-mail ou telefone, e o telefone compara os 8 últimos dígitos. Em produção, o canal (WhatsApp) já identificaria o número e eu adicionaria um código de confirmação.
- **Frete:** não há tabela de frete nos dados, então o agente explica modalidades e prazos mas não cota valores. Daria para integrar a API dos Correios/Jadlog.
- **Busca de produtos léxica:** funciona bem para marca e modelo. Pedidos subjetivos ("um violão com som mais encorpado") dependem do modelo ler as descrições. Embeddings sobre descrição e specs ajudariam com um catálogo de 300+ itens.
- **Dados em memória, lidos de CSV:** suficiente para o protótipo. Em produção eu usaria o banco/ERP da loja, com as mesmas ferramentas por cima.
- **Interface:** CLI apenas. O próximo passo é expor `EmporioAgent.send()` numa API e num webhook de WhatsApp, com o histórico num banco e não em arquivos.
- **Chamados** ficam num arquivo JSONL. O ideal é integrar a um helpdesk ou notificar a equipe.
- **Data de recebimento:** os prazos usam a previsão de entrega porque a data real não existe nos dados.
- **Observabilidade:** registraria tokens, latência e ferramentas usadas por conversa para acompanhar custo e qualidade.

## Uso de assistentes de código

Usei o **Claude Code** (Anthropic) como par de programação durante todo o desafio:

1. **Análise:** pedi para ele ler o enunciado, o manual em PDF e os CSVs e me trazer um resumo do que pedia o desafio. Nessa etapa já apareceram as inconsistências dos dados e do manual (telefone duplicado, regra de parcelamento contraditória, produtos com status e estoque incoerentes).
2. **Plano e decisões:** discutimos a abordagem (function calling vs. RAG vs. SQL), o provedor e a interface. Aprovei o plano antes da implementação.
3. **Implementação incremental:** ele escreveu o código em etapas (dados → políticas → ferramentas → agente → CLI → testes), rodando os testes e conferindo a saída das ferramentas contra os dados reais. Cada etapa virou um commit.
4. **Revisão:** revisei as decisões, as suposições e as conversas de exemplo, que foram geradas ao vivo pelo agente com o script, e não escritas à mão.

O assistente acelerou a parte mecânica (parsing, testes, boilerplate). As decisões de produto e de negócio (o que fazer com dados inconsistentes, regras de LGPD, escopo) foram explicitadas e documentadas aqui.
