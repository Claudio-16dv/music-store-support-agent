# Preco e pagamento

> Consulta de preço de um modelo específico e simulação de PIX/parcelamento pelas regras da loja.
>
> Gerado automaticamente por `scripts/gerar_exemplos.py` em 02/11/2026 09:00 (horário de Campo Grande) com o modelo `gpt-4.1-mini` (OpenAI).

**Cliente:** Quanto custa o Takamine GD20?

<details><summary>🔧 Ferramentas consultadas</summary>

- `buscar_produtos({"termo": "Takamine GD20"})`

  ```json
  {"total_encontrado": 1, "produtos": [{"id": 95, "nome": "Takamine GD20 Dreadnought Natural", "categoria": "Violões", "situacao": "disponivel", "preco": "R$ 2.199,00", "estoque": 5}]}
  ```

</details>

**Lia:** Oi! Aqui é a Lia, da Empório da Música 🎸 O Takamine GD20 Dreadnought Natural está disponível por R$ 2.199,00. Quer saber algo mais sobre ele ou sobre outros violões?

---

**Cliente:** Se eu pagar no PIX fica quanto? E dá pra parcelar em quantas vezes?

<details><summary>🔧 Ferramentas consultadas</summary>

- `simular_pagamento({"valor": 2199, "valor_ja_promocional": false})`

  ```json
  {"valor": "R$ 2.199,00", "pix": "R$ 2.089,05 (5% de desconto)", "debito_ou_boleto": "R$ 2.199,00 à vista (boleto compensa em até 3 dias úteis)", "credito_sem_juros": "até 12x de R$ 183,25", "parcelas_possiveis": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], "combinar_formas_pagamento": true}
  ```

</details>

**Lia:** No PIX, o Takamine GD20 sai por R$ 2.089,05 com 5% de desconto. Dá pra parcelar em até 12x de R$ 183,25 sem juros no cartão. Quer ajuda com mais alguma coisa?

---
