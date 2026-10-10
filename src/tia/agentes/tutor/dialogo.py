"""
Diálogo livre do Agente 2 (Tutor), parte 2b: o aluno pergunta, o Tutor
responde ancorado SOMENTE no material do curso (RAG), citando a fonte (R03).

Para cada pergunta:
    1. busca no RAG (só no material da competência, se informada) e descarta
       os trechos distantes demais (TUTOR_DISTANCIA_MAXIMA);
    2. sem trecho relevante: resposta FIXA gerada por código
       (MENSAGEM_SEM_MATERIAL), sem chamar o LLM;
    3. com trechos: prompt ancorado (mesmas regras do feedback de item,
       feedback.REGRAS_ANCORADAS) e mesma amostragem da config. Se os trechos
       não respondem à pergunta, o LLM devolve SINAL_SEM_RESPOSTA e o código
       troca pela mensagem fixa;
    4. a guarda de saída do feedback (feedback.verificar_texto) barra número
       que não está na pergunta nem nos trechos, referência ao prompt e
       contradição interna; se barrar, vai MENSAGEM_SEM_RESPOSTA;
    5. "fontes" vêm dos metadados do RAG, nunca do texto do LLM; resposta
       fixa não tem fonte.

O texto livre do aluno vai só para o banco (tabela tutor_dialogo), nunca
para log (R08); o prompt não leva aluno_id.

Não é executável sozinho; demonstração:
    python -m tia.agentes.tutor --dialogo

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (sem ele, resposta fixa)
    - Material indexado: python -m tia.rag.ingest
"""

import logging
import time
from dataclasses import dataclass

from tia.agentes.tutor import CompetenciaInexistente, repositorio
from tia.agentes.tutor.feedback import REGRAS_ANCORADAS, limpar_explicacao, verificar_texto
from tia.agentes.tutor.modelos import PerguntaAluno, RespostaDialogo
from tia.core.config import (TUTOR_DISTANCIA_MAXIMA, TUTOR_MAX_TOKENS, TUTOR_NUM_TRECHOS, TUTOR_SEED,
                             TUTOR_TEMPERATURA, TUTOR_TIMEOUT_LLM, TUTOR_TOP_P)
from tia.core.llm_client import chamar_llm
from tia.rag.retrieve import buscar_contexto

log = logging.getLogger(__name__)

MENSAGEM_SEM_MATERIAL = "Não encontrei isso no material disponível; vale perguntar ao professor."
MENSAGEM_SEM_RESPOSTA = ("Não consegui montar uma resposta confiável com o material disponível; "
                         "vale perguntar ao professor.")
# o LLM escreve isto quando os trechos não respondem à pergunta
SINAL_SEM_RESPOSTA = "SEM_RESPOSTA"


@dataclass
class ResultadoDialogo:
    resposta: str
    fontes: list[str]
    origem: str            # "LLM", "guarda" ou "fallback"
    motivo_descarte: str = ""


def buscar_trechos_dialogo(pergunta: str, materiais: list[str] | None) -> list[dict]:
    """Trechos relevantes para a pergunta (só dos materiais, se informados),
    na ordem em que aparecem no material."""
    trechos = buscar_contexto(pergunta, k=TUTOR_NUM_TRECHOS, fontes=materiais)
    relevantes = [t for t in trechos if t["distancia"] <= TUTOR_DISTANCIA_MAXIMA
                  and (materiais is None or t["fonte"] in materiais)]
    return sorted(relevantes, key=lambda t: (t["fonte"], t.get("indice", 0)))


def montar_prompt_dialogo(pergunta: str, trechos: list[dict]) -> str:
    """Pedido ao LLM: responder só com base nos trechos (mesmas regras do
    prompt ancorado do feedback)."""
    apoio = "\n---\n".join(t["texto"] for t in trechos)
    return (
        "Você é um tutor de programação introdutória em Python. Responda direto para o "
        "aluno, em português, de 2 a 3 frases, à pergunta abaixo.\n"
        "Regras:\n"
        "- Use APENAS as informações do APOIO abaixo; não afirme nada além disso.\n"
        f"- Se o APOIO não responde à pergunta, escreva só: {SINAL_SEM_RESPOSTA}\n"
        + REGRAS_ANCORADAS +
        f"PERGUNTA DO ALUNO:\n{pergunta}\n\n"
        f"APOIO:\n{apoio}"
    )


def gerar_resposta(pergunta: str, materiais: list[str] | None,
                   timeout: int = TUTOR_TIMEOUT_LLM) -> ResultadoDialogo:
    """Resposta ancorada nos trechos, aprovada pela guarda; ou texto fixo."""
    sem_material = ResultadoDialogo(MENSAGEM_SEM_MATERIAL, [], "fallback")
    try:
        trechos = buscar_trechos_dialogo(pergunta, materiais)
    except Exception as erro:  # Chroma ou embedding indisponível
        log.warning("Busca no RAG falhou no diálogo (%s); resposta fixa.", type(erro).__name__)
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback")
    if not trechos:
        log.info("Diálogo sem trecho relevante; resposta fixa sem chamar o LLM.")
        return sem_material

    try:
        bruta = chamar_llm(montar_prompt_dialogo(pergunta, trechos), think=False, timeout=timeout,
                           max_tokens=TUTOR_MAX_TOKENS, temperatura=TUTOR_TEMPERATURA,
                           top_p=TUTOR_TOP_P, seed=TUTOR_SEED)
    except Exception as erro:
        log.warning("LLM indisponível no diálogo (%s); resposta fixa.", type(erro).__name__)
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback")
    if SINAL_SEM_RESPOSTA in bruta:
        log.info("O LLM indicou que os trechos não respondem à pergunta; resposta fixa.")
        return sem_material
    resposta = limpar_explicacao(bruta)
    if not resposta:
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback")

    motivo = verificar_texto(resposta, [pergunta, *(t["texto"] for t in trechos)], pergunta)
    if motivo:
        # só a categoria do motivo: o detalhe pode ecoar texto da pergunta (R08)
        log.info("Guarda descartou a resposta do diálogo (%s).", motivo.split(":")[0])
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "guarda", motivo_descarte=motivo)
    fontes = list(dict.fromkeys(t["fonte"] for t in trechos))  # sem repetir
    return ResultadoDialogo(resposta, fontes, "LLM")


def perguntar(entrada: PerguntaAluno) -> RespostaDialogo:
    """Responde à pergunta livre do aluno e grava em tutor_dialogo."""
    inicio = time.perf_counter()
    materiais = None
    if entrada.competencia_id is not None:
        materiais = repositorio.materiais_da_competencia(entrada.competencia_id)
        if materiais is None:
            raise CompetenciaInexistente(f"Competência '{entrada.competencia_id}' não existe na ementa.")
    resultado = gerar_resposta(entrada.pergunta, materiais)
    tempo_ms = round((time.perf_counter() - inicio) * 1000)
    dialogo_id = repositorio.registrar_dialogo(entrada.aluno_id, entrada.competencia_id, entrada.pergunta,
                                               resultado.resposta, resultado.fontes, resultado.origem, tempo_ms)
    return RespostaDialogo(dialogo_id=dialogo_id, resposta=resultado.resposta, fontes=resultado.fontes,
                           origem=resultado.origem, tempo_ms=tempo_ms)
