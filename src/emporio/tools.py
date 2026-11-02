"""Ferramentas (function calling) expostas ao modelo.

Cada ferramenta tem um schema JSON (enviado à API) e uma implementação Python
que devolve uma string JSON. Erros de entrada viram ToolError, que o loop do
agente devolve ao modelo como tool_result com is_error=True.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime
from typing import Any, Callable

from . import config
from .data import (
    DISPONIVEL,
    ESGOTADO,
    ORDER_STATUS_PT,
    Product,
    StoreData,
    payment_method_pt,
)
from .policies import SECTION_KEYS, get_sections

ARREPENDIMENTO_DIAS = 7
TROCA_DEFEITO_DIAS = 30
GARANTIA_LEGAL_DIAS = 90
PIX_DESCONTO = 0.05
# (parcelas até, parcela mínima) — seção 3.1 do manual.
FAIXAS_PARCELAMENTO = [(3, 50.0), (6, 80.0), (12, 100.0)]
COMBINACAO_MINIMA = 2000.0


class ToolError(Exception):
    """Entrada inválida ou consulta impossível; a mensagem vai para o modelo."""


def brl(value: float) -> str:
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


def _product_summary(p: Product) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": p.id,
        "nome": p.name,
        "categoria": p.category.name,
        "situacao": p.situacao,
        "preco": brl(p.price),
    }
    if p.active_promotion:
        item["promocao"] = {
            "campanha": p.active_promotion.description,
            "desconto": f"{p.active_promotion.discount_percent:g}%",
            "preco_promocional": brl(p.promo_price),
        }
    if p.situacao == DISPONIVEL:
        item["estoque"] = p.stock
    return item


class Toolbox:
    def __init__(self, store: StoreData, clock: Callable[[], date] = today):
        self.store = store
        self.clock = clock
        self._handlers: dict[str, Callable[..., Any]] = {
            "buscar_produtos": self.buscar_produtos,
            "detalhes_produto": self.detalhes_produto,
            "listar_promocoes_ativas": self.listar_promocoes_ativas,
            "consultar_pedido": self.consultar_pedido,
            "consultar_politicas": self.consultar_politicas,
            "simular_pagamento": self.simular_pagamento,
            "registrar_chamado": self.registrar_chamado,
        }

    # ----------------------------------------------------------------- schemas

    @property
    def schemas(self) -> list[dict]:
        categorias = [c.name for c in self.store.categories.values()]
        return [
            {
                "name": "buscar_produtos",
                "description": (
                    "Busca instrumentos no catálogo da loja com preço, promoção ativa e situação de "
                    "estoque atuais. Use para qualquer pergunta sobre produtos, preços, modelos, "
                    "marcas ou disponibilidade — nunca informe preço ou estoque sem consultar. "
                    "Por padrão retorna só itens disponíveis para compra; para checar um modelo "
                    "específico que pode estar esgotado/descontinuado, use incluir_indisponiveis=true. "
                    "Filtros de preço consideram o preço final (já com promoção, sem desconto PIX)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "termo": {
                            "type": "string",
                            "description": "Palavras-chave: marca, modelo, tipo (ex.: 'Takamine GD20', 'nylon', 'elétrico', 'tenor'). Vazio para listar a categoria.",
                        },
                        "categoria": {"type": "string", "enum": categorias},
                        "preco_min": {"type": "number", "description": "Preço mínimo em reais."},
                        "preco_max": {"type": "number", "description": "Preço máximo em reais."},
                        "incluir_indisponiveis": {"type": "boolean"},
                        "limite": {"type": "integer", "description": "Máximo de itens (padrão 8)."},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "detalhes_produto",
                "description": (
                    "Ficha completa de um produto pelo id (descrição, especificações técnicas, preço, "
                    "promoção, estoque) e, se não estiver disponível, alternativas parecidas em estoque."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"produto_id": {"type": "integer"}},
                    "required": ["produto_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "listar_promocoes_ativas",
                "description": (
                    "Lista as promoções vigentes agora, com preço original, desconto e preço promocional. "
                    "Use também para checar se uma promoção que o cliente citou ainda vale."
                ),
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "consultar_pedido",
                "description": (
                    "Consulta status, itens, rastreio, previsão de entrega e prazos de troca/devolução "
                    "de um pedido. Exige o número do pedido E o e-mail ou telefone cadastrado do "
                    "cliente (verificação de identidade — LGPD). Peça os dois ao cliente antes de chamar."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "numero_pedido": {"type": "integer"},
                        "email_ou_telefone": {
                            "type": "string",
                            "description": "E-mail ou telefone informado pelo cliente para confirmar a titularidade.",
                        },
                    },
                    "required": ["numero_pedido", "email_ou_telefone"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "consultar_politicas",
                "description": (
                    "Retorna o texto oficial do manual de políticas da loja para os tópicos pedidos. "
                    "Consulte antes de responder sobre endereço/contato, horários, pagamento e "
                    "parcelamento, trocas e devoluções, frete e prazos, regras de promoção, garantia "
                    "ou privacidade de dados. Pode pedir vários tópicos de uma vez."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topicos": {
                            "type": "array",
                            "items": {"type": "string", "enum": [*SECTION_KEYS.values(), "todas"]},
                            "minItems": 1,
                        }
                    },
                    "required": ["topicos"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "simular_pagamento",
                "description": (
                    "Calcula as condições de pagamento para um valor de compra seguindo as regras da loja: "
                    "preço no PIX (5% de desconto, que não se aplica a preço promocional), opções de "
                    "parcelamento sem juros respeitando as parcelas mínimas e se é possível combinar "
                    "formas de pagamento. Use em vez de fazer as contas de cabeça."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "valor": {"type": "number", "description": "Valor total da compra em reais."},
                        "valor_ja_promocional": {
                            "type": "boolean",
                            "description": "true se o valor já é um preço promocional (então não há desconto PIX).",
                        },
                    },
                    "required": ["valor", "valor_ja_promocional"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "registrar_chamado",
                "description": (
                    "Registra um chamado para a equipe humana: reclamação, problema com pedido (atraso, "
                    "avaria, troca/devolução a efetivar), pedido de exclusão de dados ou quando o cliente "
                    "pede para falar com um atendente. Confirme o resumo e um contato com o cliente "
                    "antes de registrar. Retorna o número de protocolo."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": ["reclamacao", "troca_devolucao", "atraso_entrega", "privacidade", "falar_com_atendente", "outro"],
                        },
                        "resumo": {"type": "string"},
                        "nome_cliente": {"type": "string"},
                        "contato": {"type": "string", "description": "Telefone ou e-mail para retorno."},
                        "numero_pedido": {"type": "integer"},
                    },
                    "required": ["tipo", "resumo", "contato"],
                    "additionalProperties": False,
                },
            },
        ]

    # --------------------------------------------------------------- execução

    def run(self, name: str, args: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolError(f"Ferramenta desconhecida: {name}")
        try:
            result = handler(**args)
        except TypeError as e:  # argumento faltando/sobrando
            raise ToolError(f"Argumentos inválidos para {name}: {e}") from e
        return json.dumps(result, ensure_ascii=False)

    # ------------------------------------------------------------- ferramentas

    def buscar_produtos(
        self,
        termo: str = "",
        categoria: str | None = None,
        preco_min: float | None = None,
        preco_max: float | None = None,
        incluir_indisponiveis: bool = False,
        limite: int = 8,
    ) -> dict:
        if categoria and not self.store.category_by_name(categoria):
            raise ToolError(f"Categoria inexistente: {categoria}")
        found, aproximado = self.store.search_products(
            termo, categoria, preco_min, preco_max, incluir_indisponiveis
        )
        limite = max(1, min(int(limite or 8), 20))
        result: dict[str, Any] = {
            "total_encontrado": len(found),
            "produtos": [_product_summary(p) for p in found[:limite]],
        }
        if aproximado:
            result["obs"] = (
                "Nenhum produto contém todos os termos; estes são resultados APROXIMADOS (casam só "
                "parte dos termos). Não os apresente como o item pedido. Lembre que a loja não vende acessórios."
            )
        elif len(found) > limite:
            result["obs"] = f"Mostrando os {limite} mais baratos; refine a busca para ver outros."
        if not found:
            result["obs"] = (
                "Nenhum produto encontrado com esses critérios. A loja vende apenas instrumentos "
                "musicais (sem acessórios). Tente outros termos, outra categoria ou incluir_indisponiveis=true."
            )
        return result

    def detalhes_produto(self, produto_id: int) -> dict:
        p = self.store.products.get(int(produto_id))
        if p is None:
            raise ToolError(f"Produto {produto_id} não existe no catálogo.")
        result = _product_summary(p)
        result["descricao"] = p.description
        result["especificacoes"] = p.specs
        orientacao = {
            ESGOTADO: "Temporariamente sem estoque: informe e sugira as alternativas.",
            "descontinuado": "Não faz mais parte do catálogo: ofereça modelos equivalentes.",
            "em_breve": "Lançamento ainda não disponível para venda: não confirme compra ou prazo.",
        }.get(p.situacao)
        if orientacao:
            result["orientacao"] = orientacao
            result["alternativas_disponiveis"] = [_product_summary(a) for a in self.store.similar_available(p)]
        expiradas = self.store.inactive_promotions_for(p.id)
        if expiradas and not p.active_promotion:
            result["promocoes_encerradas"] = sorted({pr.description for pr in expiradas})
        return result

    def listar_promocoes_ativas(self) -> dict:
        return {
            "promocoes_ativas": [_product_summary(p) for p in self.store.active_promotions()],
            "regras": "Promoções não são cumulativas e o desconto PIX não se aplica sobre preço promocional.",
        }

    def consultar_pedido(self, numero_pedido: int, email_ou_telefone: str) -> dict:
        order = self.store.get_order(int(numero_pedido))
        negado = {
            "verificado": False,
            "mensagem": (
                "Não foi possível confirmar o pedido com os dados informados. Peça ao cliente para "
                "conferir o número do pedido e o e-mail/telefone usados na compra. Não revele se o "
                "pedido existe nem dados de terceiros."
            ),
        }
        if order is None or order.customer is None:
            return negado
        if not self.store.identity_matches(order.customer, email_or_phone=email_ou_telefone):
            return negado

        hoje = self.clock()
        dias_desde_compra = (hoje - order.order_date).days
        result: dict[str, Any] = {
            "verificado": True,
            "cliente_primeiro_nome": order.customer.first_name,
            "pedido": order.id,
            "data_pedido": order.order_date.isoformat(),
            "status": ORDER_STATUS_PT.get(order.status, order.status),
            "itens": [
                {
                    "produto": i.product.name if i.product else f"produto #{i.product_id}",
                    "quantidade": i.quantity,
                }
                for i in order.items
            ],
            "total_pago": brl(order.total),
            "forma_pagamento": payment_method_pt(order.payment_method),
            "data_hoje": hoje.isoformat(),
        }
        if order.tracking_code:
            result["codigo_rastreio"] = order.tracking_code
        if order.estimated_delivery:
            result["previsao_entrega"] = order.estimated_delivery.isoformat()
        if order.notes:
            result["observacao"] = order.notes

        alertas = []
        if order.status == "shipped" and order.estimated_delivery and order.estimated_delivery < hoje:
            atraso = (hoje - order.estimated_delivery).days
            alertas.append(
                f"Previsão de entrega vencida há {atraso} dias. Peça desculpas, passe o rastreio e "
                "ofereça registrar um chamado de atraso para a equipe."
            )
        if order.status in ("pending", "confirmed") and dias_desde_compra > 15:
            alertas.append(
                f"Pedido sem avanço há {dias_desde_compra} dias (fora do normal). Não invente motivo: "
                "ofereça registrar um chamado para a equipe verificar."
            )
        if order.status == "delivered":
            # Não temos a data real de recebimento; usamos a previsão de entrega como referência.
            recebido = order.estimated_delivery or order.order_date
            dias_recebido = (hoje - recebido).days
            result["prazos"] = {
                "referencia_recebimento": f"{recebido.isoformat()} (previsão de entrega; data real de recebimento não consta no sistema)",
                "arrependimento_7_dias_apos_recebimento": "dentro do prazo" if dias_recebido <= ARREPENDIMENTO_DIAS else f"expirado ({dias_recebido} dias desde o recebimento)",
                "troca_por_defeito_30_dias_apos_compra": "dentro do prazo" if dias_desde_compra <= TROCA_DEFEITO_DIAS else f"expirado ({dias_desde_compra} dias desde a compra) — defeito vai para garantia do fabricante, loja pode intermediar",
                "garantia_legal_90_dias_apos_recebimento": "vigente" if dias_recebido <= GARANTIA_LEGAL_DIAS else "encerrada (verificar garantia do fabricante: 6 meses a 2 anos)",
            }
        if alertas:
            result["alertas"] = alertas
        return result

    def consultar_politicas(self, topicos: list[str]) -> dict:
        if not topicos:
            raise ToolError("Informe ao menos um tópico.")
        return {"politicas": get_sections(topicos)}

    def simular_pagamento(self, valor: float, valor_ja_promocional: bool) -> dict:
        valor = float(valor)
        if valor <= 0:
            raise ToolError("O valor deve ser positivo.")
        opcoes = []
        for n in range(1, 13):
            minimo = next(m for limite, m in FAIXAS_PARCELAMENTO if n <= limite)
            parcela = valor / n
            # Uma compra abaixo de R$ 50 ainda pode ser paga em 1x.
            if n == 1 or parcela >= minimo:
                opcoes.append(n)
        max_parcelas = max(opcoes)
        result: dict[str, Any] = {
            "valor": brl(valor),
            "pix": (
                brl(valor) + " (sem desconto adicional: valor já é promocional)"
                if valor_ja_promocional
                else f"{brl(valor * (1 - PIX_DESCONTO))} (5% de desconto)"
            ),
            "debito_ou_boleto": f"{brl(valor)} à vista (boleto compensa em até 3 dias úteis)",
            "credito_sem_juros": f"até {max_parcelas}x de {brl(math.floor(valor / max_parcelas * 100) / 100)}",
            "parcelas_possiveis": opcoes,
            "combinar_formas_pagamento": valor > COMBINACAO_MINIMA,
        }
        return result

    def registrar_chamado(
        self,
        tipo: str,
        resumo: str,
        contato: str,
        nome_cliente: str = "",
        numero_pedido: int | None = None,
    ) -> dict:
        protocolo = f"EM-{datetime.now(config.TIMEZONE):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        registro = {
            "protocolo": protocolo,
            "criado_em": datetime.now(config.TIMEZONE).isoformat(timespec="seconds"),
            "tipo": tipo,
            "resumo": resumo,
            "nome_cliente": nome_cliente,
            "contato": contato,
            "numero_pedido": numero_pedido,
        }
        config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with config.TICKETS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return {
            "protocolo": protocolo,
            "prazo_retorno": "até 24 horas úteis",
            "mensagem": "Chamado registrado e encaminhado para a equipe responsável.",
        }
