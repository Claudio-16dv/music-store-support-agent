# Pedido atrasado lgpd

> Status de pedido: primeiro com contato errado (LGPD), depois correto; pedido atrasado vira chamado.
>
> Gerado automaticamente por `scripts/gerar_exemplos.py` em 02/11/2026 09:00 (horário de Campo Grande) com o modelo `gpt-4.1-mini` (OpenAI).

**Cliente:** Boa tarde, cadê meu pedido 8? Meu email é ana@gmail.com

<details><summary>🔧 Ferramentas consultadas</summary>

- `consultar_pedido({"numero_pedido": 8, "email_ou_telefone": "ana@gmail.com"})`

  ```json
  {"verificado": false, "mensagem": "Não foi possível confirmar o pedido com os dados informados. Peça ao cliente para conferir o número do pedido e o e-mail/telefone usados na compra. Não revele se o pedido existe nem dados de terceiros."}
  ```

</details>

**Lia:** Oi! Não consegui localizar o pedido com o número 8 e o e-mail ana@gmail.com. Pode conferir se os dados estão certinhos? Se quiser, pode passar o telefone usado na compra também.

---

**Cliente:** Ah desculpa, é o telefone (67) 99654-7821

<details><summary>🔧 Ferramentas consultadas</summary>

- `consultar_pedido({"numero_pedido": 8, "email_ou_telefone": "67996547821"})`

  ```json
  {"verificado": true, "cliente_primeiro_nome": "Ana", "pedido": 8, "data_pedido": "2026-02-15", "status": "enviado", "itens": [{"produto": "Kala KA-C Concert Mogno", "quantidade": 1}], "total_pago": "R$ 349,90", "forma_pagamento": "cartão de débito", "data_hoje": "2026-11-02", "codigo_rastreio": "BRJL5544332BR", "previsao_entrega": "2026-02-28", "alertas": ["Previsão de entrega vencida há 247 dias. Peça desculpas, passe o rastreio e ofereça registrar um chamado de atraso para a equipe."]}
  ```

</details>

**Lia:** Oi Ana! Seu pedido 8, do ukulele Kala KA-C Concert Mogno, foi enviado, mas a previsão de entrega já venceu faz tempo (28/02/2026). O código de rastreio é BRJL5544332BR. Desculpa pelo atraso! Quer que eu registre um chamado para a equipe verificar isso pra você?

---

**Cliente:** Já faz muito tempo! Quero registrar uma reclamação, pode me ligar nesse mesmo número.

<details><summary>🔧 Ferramentas consultadas</summary>

- `registrar_chamado({"tipo": "reclamacao", "resumo": "Cliente Ana reclama de atraso na entrega do pedido 8, com previsão vencida desde 28/02/2026. Solicita contato por telefone (67) 99654-7821.", "nome_cliente": "Ana", "contato": "67996547821", "numero_pedido": 8})`

  ```json
  {"protocolo": "EM-20261102-A958A4", "prazo_retorno": "até 24 horas úteis", "mensagem": "Chamado registrado e encaminhado para a equipe responsável."}
  ```

</details>

**Lia:** Ana, registrei sua reclamação sobre o atraso do pedido 8 com o protocolo EM-20261102-A958A4. A equipe vai te ligar no número (67) 99654-7821 e responder em até 24 horas úteis. Se precisar de mais alguma coisa, só avisar!

---
