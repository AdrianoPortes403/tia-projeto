"""
Justificativas da trilha do Agente 1 (Planejador), escritas pelo LLM local.

Faz UM único pedido ao llm_client para a trilha toda (uma frase curta por
etapa), com timeout curto. Se o LLM falhar, demorar ou responder fora do
formato, cada etapa sem frase válida fica com o texto padrão gerado por
planejar.py: a trilha nunca é bloqueada por falha do LLM.

O prompt não leva aluno_id nem qualquer dado pessoal (R08), só nomes de
competências e notas.

Como rodar (demonstração completa):
    python -m tia.agentes.planejador

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (sem ele, cai no texto padrão)
"""

import logging
import re

from tia.agentes.planejador.modelos import Trilha
from tia.core.config import PLANEJADOR_TIMEOUT_LLM
from tia.core.llm_client import chamar_llm, descrever_falha

log = logging.getLogger(__name__)

# "1. frase", "1) frase" ou "1 - frase", uma por linha
PADRAO_LINHA = re.compile(r"^\s*(\d+)\s*[.)\-:]\s*(.+?)\s*$")
TAMANHO_MAXIMO_FRASE = 240


def _pendentes(trilha: Trilha) -> list:
    """Etapas que o LLM justifica: as não concluídas, na ordem da trilha."""
    return [e for e in trilha.etapas if not e.concluida]


def montar_prompt(trilha: Trilha, diagnostico: dict[str, float]) -> str:
    """Monta o pedido único ao LLM, com uma linha numerada por etapa que falta
    (as concluídas ficam de fora)."""
    linhas = []
    for numero, etapa in enumerate(_pendentes(trilha), 1):
        if etapa.competencia_id in diagnostico:
            detalhe = f"nota no diagnóstico: {diagnostico[etapa.competencia_id]:.2f}; "
        else:
            detalhe = "sem diagnóstico; "
        linhas.append(f"{numero}. {etapa.nome} ({detalhe}{etapa.horas} h)")
    return (
        "Você é o planejador de estudos de alunos de Engenharia da Computação.\n"
        "Abaixo está a trilha de um aluno, já em ordem. Para CADA etapa, escreva UMA frase "
        "curta (no máximo 20 palavras), em português, dizendo ao aluno por que estudar aquilo "
        "naquele momento.\n"
        "Responda SOMENTE com a lista numerada, no formato '1. frase', uma linha por etapa, "
        "sem introdução nem conclusão.\n\n"
        + "\n".join(linhas)
    )


def extrair_frases(resposta: str, quantidade: int) -> dict[int, str]:
    """Lê a resposta do LLM e devolve {ordem: frase} só para linhas válidas."""
    resposta = re.sub(r"<think>.*?</think>", "", resposta, flags=re.DOTALL)
    frases = {}
    for linha in resposta.splitlines():
        achado = PADRAO_LINHA.match(linha)
        if not achado:
            continue
        ordem, frase = int(achado.group(1)), achado.group(2).strip(" *\"'")
        if 1 <= ordem <= quantidade and frase and ordem not in frases:
            frases[ordem] = frase[:TAMANHO_MAXIMO_FRASE]
    return frases


def _sem_prefixo_do_nome(frase: str, nome: str) -> str:
    """Remove o "Nome da etapa:" que o modelo às vezes repete no início."""
    if frase.lower().startswith(nome.lower()):
        resto = frase[len(nome):].lstrip(" :—-")
        if resto:
            return resto[0].upper() + resto[1:]
    return frase


def justificar_trilha(trilha: Trilha, diagnostico: dict[str, float],
                      timeout: int = PLANEJADOR_TIMEOUT_LLM) -> Trilha:
    """Devolve uma cópia da trilha com as justificativas do LLM onde houver;
    nas demais etapas mantém o texto padrão. Marca a origem de cada etapa e,
    se alguma caiu no texto padrão, o motivo em trilha.falha_llm."""
    pendentes = _pendentes(trilha)
    if not pendentes:  # nada a justificar (trilha vazia ou toda concluída)
        return trilha
    numero = {e.ordem: n for n, e in enumerate(pendentes, 1)}  # ordem na trilha -> número no prompt

    def com_origem(etapa, frases: dict[int, str] | None):
        if etapa.concluida:
            return etapa  # texto fixo "já concluída", sem origem
        n = numero[etapa.ordem]
        if frases and n in frases:
            return etapa.model_copy(update={"justificativa": _sem_prefixo_do_nome(frases[n], etapa.nome),
                                            "origem_justificativa": "LLM"})
        return etapa.model_copy(update={"origem_justificativa": "fallback"})

    try:
        resposta = chamar_llm(montar_prompt(trilha, diagnostico), think=False, timeout=timeout)
        frases = extrair_frases(resposta, len(pendentes))
    except Exception as erro:  # qualquer falha do LLM: segue com o texto padrão
        falha = descrever_falha(erro)
        log.warning("Justificativas do LLM indisponíveis (%s); usando texto padrão.", falha)
        return trilha.model_copy(update={"etapas": [com_origem(e, None) for e in trilha.etapas], "falha_llm": falha})

    if len(frases) < len(pendentes):
        log.info("LLM justificou %d de %d etapas; restante com texto padrão.", len(frases), len(pendentes))
    falha = None if len(frases) == len(pendentes) else "formato"
    return trilha.model_copy(update={"etapas": [com_origem(e, frases) for e in trilha.etapas], "falha_llm": falha})
