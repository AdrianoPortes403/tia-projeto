"""
Máquina de estados do questionário adaptativo do Agente 2 (Tutor).

Regras (PURAS e determinísticas: sem I/O, sem LLM, sem aleatoriedade):
    - o nível vai de 1 a 3 e começa em 1;
    - acerto sobe um nível, erro desce um (sem passar dos limites);
    - um item nunca é repetido na mesma sessão;
    - o próximo item é o primeiro não usado do nível atual, na ordem do
      banco; se o nível atual não tiver mais itens, usa o nível mais
      próximo que ainda tiver (empate: o mais fácil), e o nível passa a
      ser o desse item;
    - a competência termina quando o aluno acerta 2 itens seguidos no
      nível 3, ou quando os itens dela acabam.

Os itens são dicionários no formato de conteudo/banco_itens/itens.json.
Quem lê o banco e grava o estado é repositorio.py.

Não é executável sozinho; demonstração completa:
    python -m tia.agentes.tutor

Pré-requisitos:
    - nenhum (só a biblioteca padrão)
"""

from dataclasses import dataclass, replace

NIVEL_MINIMO = 1
NIVEL_MAXIMO = 3
ACERTOS_PARA_CONCLUIR = 2  # seguidos, no nível máximo


@dataclass(frozen=True)
class EstadoSessao:
    competencia_id: str
    nivel: int = NIVEL_MINIMO
    item_atual_id: str | None = None  # None quando concluída
    itens_usados: tuple[str, ...] = ()
    acertos_seguidos_nivel_max: int = 0
    concluida: bool = False


class SemItens(ValueError):
    """A competência não tem nenhum item no banco."""


def corrigir(item: dict, indice_escolhido: int) -> bool:
    """True se a alternativa escolhida é a correta."""
    return indice_escolhido == item["indice_correto"]


def escolher_item(itens: list[dict], competencia_id: str, nivel: int,
                  usados: tuple[str, ...]) -> dict | None:
    """Primeiro item não usado da competência no nível pedido; se não houver,
    no nível mais próximo (empate: o mais fácil). None se acabaram."""
    disponiveis = [i for i in itens if i["competencia_id"] == competencia_id and i["id"] not in usados]
    if not disponiveis:
        return None
    # min é estável: entre itens equivalentes, fica o primeiro do banco
    return min(disponiveis, key=lambda i: (abs(i["nivel"] - nivel), i["nivel"]))


def iniciar(itens: list[dict], competencia_id: str) -> EstadoSessao:
    """Estado inicial: nível 1, com o primeiro item já escolhido."""
    item = escolher_item(itens, competencia_id, NIVEL_MINIMO, ())
    if item is None:
        raise SemItens(f"Não há itens no banco para a competência '{competencia_id}'.")
    return EstadoSessao(competencia_id=competencia_id, nivel=item["nivel"], item_atual_id=item["id"])


def avancar(estado: EstadoSessao, itens: list[dict], acertou: bool) -> EstadoSessao:
    """Registra a resposta ao item atual e devolve o novo estado (com o
    próximo item, ou concluído). Não altera o estado recebido."""
    if estado.concluida or estado.item_atual_id is None:
        raise ValueError("Sessão já concluída: não há item para responder.")

    usados = estado.itens_usados + (estado.item_atual_id,)
    if acertou and estado.nivel == NIVEL_MAXIMO:
        seguidos = estado.acertos_seguidos_nivel_max + 1
    else:
        seguidos = 0
    if acertou:
        nivel = min(estado.nivel + 1, NIVEL_MAXIMO)
    else:
        nivel = max(estado.nivel - 1, NIVEL_MINIMO)

    proximo = None
    if seguidos < ACERTOS_PARA_CONCLUIR:
        proximo = escolher_item(itens, estado.competencia_id, nivel, usados)
    if proximo is None:
        return replace(estado, nivel=nivel, item_atual_id=None, itens_usados=usados,
                       acertos_seguidos_nivel_max=seguidos, concluida=True)
    if proximo["nivel"] != NIVEL_MAXIMO:
        seguidos = 0  # sequência no nível máximo interrompida por falta de itens
    return replace(estado, nivel=proximo["nivel"], item_atual_id=proximo["id"], itens_usados=usados,
                   acertos_seguidos_nivel_max=seguidos)
