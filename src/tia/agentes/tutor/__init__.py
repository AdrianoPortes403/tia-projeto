"""
Agente 2 (Tutor), parte 2a: questionário adaptativo com feedback e fonte citada.

Pontos de entrada (usados pela API e pela demonstração):
    iniciar_sessao(IniciarSessao) -> SessaoIniciada
    responder(RespostaAluno)      -> Feedback

Módulos:
    adaptativo.py  máquina de estados pura (nível, item, fim da competência)
    feedback.py    veredito fixo + explicação com RAG + LLM local, citando a fonte (R03),
                   com guarda de saída
    repositorio.py banco de itens, ementa e estado/histórico no SQLite

Como rodar a demonstração:
    python -m tia.agentes.tutor

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (sem ele, o feedback usa o texto do item)
    - Material indexado: python -m tia.rag.ingest
"""

import time

from tia.agentes.tutor import adaptativo, repositorio
from tia.agentes.tutor.feedback import gerar_feedback
from tia.agentes.tutor.modelos import Feedback, IniciarSessao, Pergunta, RespostaAluno, SessaoIniciada


class ErroTutor(ValueError):
    """Erro de dados no questionário (mensagem pensada para o usuário)."""


class CompetenciaInexistente(ErroTutor):
    pass


class SessaoInexistente(ErroTutor):
    pass


class RespostaForaDeOrdem(ErroTutor):
    """Sessão concluída, ou a resposta não é do item atual (ex.: envio duplicado)."""


def _pergunta(item: dict) -> Pergunta:
    """Item como o aluno vê: sem gabarito nem explicação."""
    return Pergunta(item_id=item["id"], competencia_id=item["competencia_id"], nivel=item["nivel"],
                    enunciado=item["enunciado"], alternativas=item["alternativas"])


def _item_por_id(itens: list[dict], item_id: str) -> dict:
    for item in itens:
        if item["id"] == item_id:
            return item
    # o banco mudou durante a sessão: defeito de conteúdo, não do pedido
    raise RuntimeError(f"Item '{item_id}' não existe mais no banco de itens.")


def iniciar_sessao(entrada: IniciarSessao) -> SessaoIniciada:
    """Abre uma sessão na competência e devolve a primeira pergunta (nível 1)."""
    if repositorio.materiais_da_competencia(entrada.competencia_id) is None:
        raise CompetenciaInexistente(f"Competência '{entrada.competencia_id}' não existe na ementa.")
    itens = repositorio.carregar_itens()
    try:
        estado = adaptativo.iniciar(itens, entrada.competencia_id)
    except adaptativo.SemItens as erro:
        raise CompetenciaInexistente(str(erro))
    sessao_id = repositorio.criar_sessao(entrada.aluno_id, estado)
    return SessaoIniciada(sessao_id=sessao_id, nivel_atual=estado.nivel,
                          pergunta=_pergunta(_item_por_id(itens, estado.item_atual_id)))


def responder(resposta: RespostaAluno, modo: str | None = None) -> Feedback:
    """Corrige a resposta, gera o feedback, avança o estado e grava tudo.
    modo: "ancorado" ou "livre"; None usa TUTOR_MODO_FEEDBACK."""
    inicio = time.perf_counter()
    estado = repositorio.ler_sessao(resposta.sessao_id, resposta.aluno_id)
    if estado is None:
        raise SessaoInexistente("Sessão não encontrada para este aluno.")
    if estado.concluida:
        raise RespostaForaDeOrdem("Esta sessão já foi concluída.")
    if resposta.item_id != estado.item_atual_id:
        raise RespostaForaDeOrdem("A resposta não corresponde à pergunta atual da sessão.")

    itens = repositorio.carregar_itens()
    item = _item_por_id(itens, estado.item_atual_id)
    acertou = adaptativo.corrigir(item, resposta.indice_escolhido)
    materiais = repositorio.materiais_da_competencia(estado.competencia_id) or []
    resultado = gerar_feedback(item, resposta.indice_escolhido, materiais, modo=modo)
    novo = adaptativo.avancar(estado, itens, acertou)
    tempo_ms = round((time.perf_counter() - inicio) * 1000)

    if not repositorio.registrar_resposta(resposta.sessao_id, resposta.aluno_id, item, novo,
                                          acertou, resultado.fontes, tempo_ms):
        raise RespostaForaDeOrdem("A resposta não corresponde à pergunta atual da sessão.")

    proxima = None if novo.concluida else _pergunta(_item_por_id(itens, novo.item_atual_id))
    return Feedback(acertou=acertou, indice_correto=item["indice_correto"], veredito=resultado.veredito,
                    explicacao=resultado.explicacao, origem=resultado.origem,
                    fontes=resultado.fontes, nivel_atual=novo.nivel, concluida=novo.concluida,
                    proxima_pergunta=proxima, tempo_ms=tempo_ms)
