"""
Máquina de estados do questionário adaptativo do Agente 2 (Tutor).

Regras (base pedagógica 1.2.5, seção 3; PURAS e determinísticas: sem I/O,
sem LLM, sem aleatoriedade). Os limiares vêm de core/config.py:
    - o nível vai de 1 a 3 e começa em 1, ou no nível inicial vindo do
      diagnóstico (Planejador);
    - TUTOR_ACERTOS_SUBIR acertos seguidos sobem um nível; TUTOR_ERROS_DESCER
      erros seguidos descem um (as sequências zeram ao mudar de nível);
    - TUTOR_ERROS_DESCER erros seguidos já no nível 1 sinalizam LACUNA de
      aprendizagem (o orquestrador decide o reforço) e zeram a sequência;
    - um item nunca é repetido na mesma sessão; itens já vistos no diagnóstico
      inicial ficam de fora enquanto houver outros;
    - o próximo item é o primeiro não usado do nível atual, na ordem do
      banco; se o nível atual não tiver mais itens, usa o nível mais
      próximo que ainda tiver (empate: na direção da resposta, ou seja, o
      mais difícil depois de um acerto e o mais fácil depois de um erro ou
      no início), e o nível passa a ser o desse item (as sequências zeram);
    - a competência termina quando o aluno acerta TUTOR_ACERTOS_CONCLUIR itens
      seguidos no nível 3 (domínio), ou quando os itens dela acabam. No
      segundo caso a sessão termina "concluída com ressalvas" (com_ressalvas):
      não é conclusão plena, e quem decide se o aluno avança é o orquestrador
      (R1, pela taxa de acerto da sessão; ORQ_ACERTO_MIN_AVANCO).

Os itens são dicionários no formato de conteudo/banco_itens/itens.json.
Quem lê o banco e grava o estado é repositorio.py.

Não é executável sozinho; demonstração completa:
    python -m tia.agentes.tutor

Pré-requisitos:
    - nenhum (só a biblioteca padrão)
"""

from dataclasses import dataclass, replace

from tia.core import config

NIVEL_MINIMO = 1
NIVEL_MAXIMO = 3


def acertos_para_subir() -> int:
    return config.TUTOR_ACERTOS_SUBIR


def erros_para_descer() -> int:
    return config.TUTOR_ERROS_DESCER


def acertos_para_concluir() -> int:
    return config.TUTOR_ACERTOS_CONCLUIR


@dataclass(frozen=True)
class EstadoSessao:
    competencia_id: str
    nivel: int = NIVEL_MINIMO
    item_atual_id: str | None = None  # None quando concluída
    itens_usados: tuple[str, ...] = ()
    acertos_seguidos_nivel_max: int = 0
    concluida: bool = False
    acertos_seguidos: int = 0  # no nível atual
    erros_seguidos: int = 0    # no nível atual
    lacuna: bool = False       # a ÚLTIMA resposta fechou uma sequência de erros no nível 1 (não é gravado)
    com_ressalvas: bool = False  # concluída porque os itens acabaram, sem domínio


class SemItens(ValueError):
    """A competência não tem nenhum item no banco."""


def corrigir(item: dict, indice_escolhido: int) -> bool:
    """True se a alternativa escolhida é a correta."""
    return indice_escolhido == item["indice_correto"]


def escolher_item(itens: list[dict], competencia_id: str, nivel: int,
                  usados: tuple[str, ...], evitar: frozenset[str] | set[str] = frozenset(),
                  preferir_acima: bool = False) -> dict | None:
    """Primeiro item não usado da competência no nível pedido; se não houver,
    no nível mais próximo (empate: o mais fácil, ou o mais difícil com
    preferir_acima, depois de um acerto). Itens em 'evitar' (vistos no
    diagnóstico) só entram se não sobrar outro. None se acabaram."""
    disponiveis = [i for i in itens if i["competencia_id"] == competencia_id and i["id"] not in usados]
    if not disponiveis:
        return None
    novos = [i for i in disponiveis if i["id"] not in evitar]
    candidatos = novos or disponiveis
    # min é estável: entre itens equivalentes, fica o primeiro do banco
    return min(candidatos, key=lambda i: (abs(i["nivel"] - nivel), -i["nivel"] if preferir_acima else i["nivel"]))


def iniciar(itens: list[dict], competencia_id: str, nivel: int = NIVEL_MINIMO,
            evitar: frozenset[str] | set[str] = frozenset()) -> EstadoSessao:
    """Estado inicial no nível pedido (1 por padrão), com o primeiro item já escolhido."""
    nivel = min(max(nivel, NIVEL_MINIMO), NIVEL_MAXIMO)
    item = escolher_item(itens, competencia_id, nivel, (), evitar)
    if item is None:
        raise SemItens(f"Não há itens no banco para a competência '{competencia_id}'.")
    return EstadoSessao(competencia_id=competencia_id, nivel=item["nivel"], item_atual_id=item["id"])


def avancar(estado: EstadoSessao, itens: list[dict], acertou: bool,
            evitar: frozenset[str] | set[str] = frozenset()) -> EstadoSessao:
    """Registra a resposta ao item atual e devolve o novo estado (com o
    próximo item, ou concluído). Não altera o estado recebido."""
    if estado.concluida or estado.item_atual_id is None:
        raise ValueError("Sessão já concluída: não há item para responder.")

    usados = estado.itens_usados + (estado.item_atual_id,)
    nivel, lacuna = estado.nivel, False
    if acertou:
        acertos, erros = estado.acertos_seguidos + 1, 0
        seguidos_max = estado.acertos_seguidos_nivel_max + 1 if nivel == NIVEL_MAXIMO else 0
        if nivel < NIVEL_MAXIMO and acertos >= acertos_para_subir():
            nivel, acertos = nivel + 1, 0
    else:
        acertos, erros, seguidos_max = 0, estado.erros_seguidos + 1, 0
        if erros >= erros_para_descer():
            if nivel > NIVEL_MINIMO:
                nivel = nivel - 1
            else:
                lacuna = True  # errou de novo no nível mais fácil: lacuna de aprendizagem
            erros = 0

    proximo = None
    if seguidos_max < acertos_para_concluir():
        proximo = escolher_item(itens, estado.competencia_id, nivel, usados, evitar, preferir_acima=acertou)
    if proximo is None:
        return replace(estado, nivel=nivel, item_atual_id=None, itens_usados=usados,
                       acertos_seguidos_nivel_max=seguidos_max, concluida=True,
                       acertos_seguidos=acertos, erros_seguidos=erros, lacuna=lacuna,
                       com_ressalvas=seguidos_max < acertos_para_concluir())
    if proximo["nivel"] != nivel:
        # nível sem itens: seguiu para o mais próximo; as sequências recomeçam
        acertos, erros = 0, 0
    if proximo["nivel"] != NIVEL_MAXIMO:
        seguidos_max = 0  # sequência no nível máximo interrompida por falta de itens
    return replace(estado, nivel=proximo["nivel"], item_atual_id=proximo["id"], itens_usados=usados,
                   acertos_seguidos_nivel_max=seguidos_max, acertos_seguidos=acertos, erros_seguidos=erros,
                   lacuna=lacuna)
