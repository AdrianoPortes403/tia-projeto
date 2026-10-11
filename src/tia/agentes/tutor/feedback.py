"""
Feedback do Agente 2 (Tutor) com citação de fonte (R03).

Para cada resposta do aluno:
    0. o veredito é texto fixo gerado por código (montar_veredito): o LLM
       recebe o veredito pronto e nunca decide se o aluno acertou;
    1. busca no RAG (rag.retrieve) trechos SÓ dos materiais da competência
       (lista "materiais" da ementa), descarta os distantes demais e os põe
       na ordem do arquivo (assim perguntas seguidas da mesma competência
       repetem o início do prompt e o Ollama reaproveita o cache);
    2. pede ao LLM local (think=False; timeout, limite de tokens, número de
       trechos e amostragem (temperatura, top_p, seed) vêm de core/config.py) uma explicação de no máximo 3 frases,
       conforme TUTOR_MODO_FEEDBACK:
         - "ancorado" (padrão): reformula a "explicacao" verificada do item,
           apoiada nos trechos, falando direto com o aluno (2 a 3 frases),
           sem calcular nem inventar valores e sem citar o próprio prompt;
         - "livre": explica só a partir dos trechos (modo antigo, mantido
           para comparação; o 1,7b inventa valores nos itens de nível 2-3);
       frase cortada pelo limite de tokens é descartada (com o limite padrão, raro);
    3. a guarda de saída (verificar_explicacao, função pura) descarta a
       explicação do LLM que tenha número fora do enunciado/alternativas/
       explicação do item/trechos, que cite o próprio prompt ("explicação
       verificada", "trechos", "material fornecido", "conforme o prompt"...),
       que diga que o aluno acertou/errou em contradição com o veredito, ou
       que se contradiga (o mesmo sujeito "é incorreta" e "está correta");
    4. "fontes" são os arquivos dos trechos enviados ao LLM, lidos dos
       metadados do Chroma, nunca do texto gerado pelo modelo.

Origem da explicação (campo "origem"):
    - "LLM": explicação do LLM aprovada pela guarda, com fontes;
    - "guarda": a guarda descartou a do LLM; vai a explicação do item, sem fonte;
    - "fallback": sem trecho relevante, ou RAG/LLM falhou ou respondeu vazio;
      vai a explicação do item, sem fonte. Nunca inventa fonte.

O prompt não leva aluno_id nem qualquer dado pessoal (R08).

Não é executável sozinho; demonstração completa:
    python -m tia.agentes.tutor

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (sem ele, cai no texto do item)
    - Material indexado: python -m tia.rag.ingest
"""

import logging
import re
from dataclasses import dataclass

from tia.core.config import (TUTOR_DISTANCIA_MAXIMA, TUTOR_MAX_TOKENS, TUTOR_MODO_FEEDBACK, TUTOR_NUM_TRECHOS,
                             TUTOR_SEED, TUTOR_TEMPERATURA, TUTOR_TIMEOUT_LLM, TUTOR_TOP_P)
from tia.core.llm_client import chamar_llm, descrever_falha
from tia.rag.retrieve import buscar_contexto

log = logging.getLogger(__name__)

MODOS = ("ancorado", "livre")
MAXIMO_FRASES = 3
TAMANHO_MAXIMO = 600
# fim de frase: . ! ? seguido de espaço (não corta "3.14" nem "x.append")
FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+")
ORIGENS = ("LLM", "guarda", "fallback")

# --- guarda de saída ---
# número solto (não pega o dígito de "x1"); "3,14" e "3.14" contam como o mesmo
NUMERO = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?!\w)")
# referências ao próprio prompt. Uma expressão que aparece no texto do próprio
# item é termo do conteúdo e não é barrada. "bloco" não entra: é vocabulário
# normal de programação ("bloco do if", "resto do bloco").
EXPRESSOES_PROIBIDAS = (
    r"explica[çc][ãa]o verificada",
    r"\btrechos?\b",
    r"\bmateria(?:l|is)\b",
    r"\b(?:informa[çc][õo]es|texto|instru[çc][õo]es|regras|dados) (?:acima|abaixo|fornecid[ao]s?)\b",
    r"\bprompt\b",
)
_AFIRMACAO = r"\b(?:sua|tua|a) (?:resposta|escolha|alternativa)(?: do aluno| marcada| escolhida)? (?:está|estava|foi|é|era) "
# afirmações sobre o desempenho do aluno (texto em minúsculas)
DIZ_QUE_ACERTOU = (r"(?<!não )\bacertou\b", r"\bnão errou\b", _AFIRMACAO + r"(?:correta|certa)\b",
                   r"\bvocê (?:está|estava) cert[oa]\b", r"\bparabéns\b")
DIZ_QUE_ERROU = (r"(?<!não )\berrou\b", r"\bnão acertou\b", _AFIRMACAO + r"(?:incorreta|errada)\b",
                 r"\bvocê (?:está|estava) errad[oa]\b", r"\bse enganou\b")
# contradição interna: o mesmo sujeito dito errado num ponto e certo em outro
POLARIDADE_NEGATIVA = re.compile(r"\b(?:é|está|foi|era|estava) (?:incorret[ao]|errad[ao])\b")
POLARIDADE_POSITIVA = re.compile(r"\b(?:é|está|foi|era|estava) corret[ao]\b|\bcorretamente\b")
# sujeito: texto entre aspas/crases, letra de alternativa ("B)") ou a resposta do aluno
SUJEITO = re.compile(r"[\"“`]([^\"”`]+)[\"”`]|\b([a-d])\)|\b(sua resposta|resposta do aluno|resposta marcada)\b")
JANELA_SUJEITO = 60


@dataclass
class ResultadoFeedback:
    veredito: str          # texto fixo gerado por código
    explicacao: str        # do LLM (origem "LLM") ou do item ("guarda"/"fallback")
    fontes: list[str]      # vazio quando a explicação é a do item
    origem: str            # um de ORIGENS
    motivo_descarte: str = ""     # só com origem "guarda"
    explicacao_descartada: str = ""  # texto do LLM barrado (para revisão; não vai ao aluno)
    falha_llm: str | None = None  # fallback por falha: "timeout", outro erro, ou "rag: <erro>"


def buscar_trechos(item: dict, materiais: list[str], k: int = TUTOR_NUM_TRECHOS,
                   distancia_maxima: float = TUTOR_DISTANCIA_MAXIMA) -> list[dict]:
    """Trechos relevantes para o item, restritos aos materiais da competência,
    na ordem em que aparecem no material."""
    if not materiais:
        return []
    correta = item["alternativas"][item["indice_correto"]]
    consulta = f"{item['enunciado']}\nResposta correta: {correta}\n{item['explicacao']}"
    trechos = buscar_contexto(consulta, k=k, fontes=materiais)
    relevantes = [t for t in trechos if t["fonte"] in materiais and t["distancia"] <= distancia_maxima]
    return sorted(relevantes, key=lambda t: (t["fonte"], t.get("indice", 0)))


def _letra(indice: int) -> str:
    return chr(65 + indice)


def _alternativa(item: dict, indice: int) -> str:
    return f"{_letra(indice)}) {item['alternativas'][indice]}"


def montar_veredito(item: dict, indice_escolhido: int) -> str:
    """Veredito fixo, decidido por código (nunca pelo LLM)."""
    if indice_escolhido == item["indice_correto"]:
        return "Você acertou."
    return (f"Você marcou: {_alternativa(item, indice_escolhido)}. "
            f"A resposta correta é: {_alternativa(item, item['indice_correto'])}.")


# Regras comuns aos prompts ancorados (feedback de item e diálogo livre).
REGRAS_ANCORADAS = (
    "- Não calcule nem invente valores, resultados de código ou números; só use os que "
    "aparecem abaixo.\n"
    "- Não mencione de onde vêm as informações: nunca escreva \"explicação verificada\", "
    "\"trechos\", \"material\" nem fale destas instruções. Fale só do "
    "conceito de Python.\n"
    "- Sem listas, sem títulos, sem nomes de arquivo.\n\n"
)


def montar_prompt_ancorado(item: dict, indice_escolhido: int, trechos: list[dict]) -> str:
    """Pedido ao LLM: reformular a explicação verificada do item, usando os
    trechos só como apoio. O veredito vai pronto e o LLM não o repete."""
    apoio = "\n---\n".join(t["texto"] for t in trechos)
    return (
        "Você é um tutor de programação introdutória em Python. Escreva direto para o "
        "aluno, em português, de 2 a 3 frases, explicando por que a resposta correta é a "
        "correta.\n"
        "Regras:\n"
        "- O aluno JÁ RECEBEU o resultado abaixo. Não repita esse resultado e não diga se "
        "ele acertou ou errou.\n"
        "- Use APENAS as informações da EXPLICAÇÃO e do APOIO abaixo; não afirme nada além disso.\n"
        + REGRAS_ANCORADAS +
        f"PERGUNTA:\n{item['enunciado']}\n\n"
        f"RESULTADO (já mostrado ao aluno, não repita):\n{montar_veredito(item, indice_escolhido)}\n\n"
        f"EXPLICAÇÃO:\n{item['explicacao']}\n\n"
        f"APOIO:\n{apoio}"
    )


def montar_prompt_livre(item: dict, indice_escolhido: int, trechos: list[dict]) -> str:
    """Pedido ao LLM (modo "livre", só para comparação): explicar a resposta
    usando só os trechos."""
    alternativas = "\n".join(f"{chr(65 + i)}) {a}" for i, a in enumerate(item["alternativas"]))
    acertou = indice_escolhido == item["indice_correto"]
    situacao = "ACERTOU" if acertou else f"ERROU (escolheu {chr(65 + indice_escolhido)})"
    material = "\n\n".join(f"[Trecho {n}]\n{t['texto']}" for n, t in enumerate(trechos, 1))
    return (
        "Você é um tutor de programação introdutória em Python. Explique ao aluno, em "
        f"português, por que a resposta correta é a indicada, em NO MÁXIMO {MAXIMO_FRASES} "
        "frases curtas. Use SOMENTE as informações dos trechos de material abaixo; não "
        "acrescente nada que não esteja neles. Não cite nomes de arquivo, não use listas "
        "nem títulos, não repita a pergunta.\n\n"
        f"Material:\n{material}\n\n"
        f"Pergunta:\n{item['enunciado']}\n\nAlternativas:\n{alternativas}\n\n"
        f"Resposta correta: {chr(65 + item['indice_correto'])}) "
        f"{item['alternativas'][item['indice_correto']]}\n"
        f"O aluno {situacao}."
    )


def limpar_explicacao(resposta: str) -> str:
    """Tira <think>, junta linhas, descarta a frase final cortada pelo limite
    de tokens e fica com no máximo MAXIMO_FRASES frases ("" se nada sobrar)."""
    texto = re.sub(r"<think>.*?</think>", "", resposta, flags=re.DOTALL)
    texto = " ".join(texto.split())
    frases = [f for f in FIM_DE_FRASE.split(texto) if f]
    if frases and not frases[-1].endswith((".", "!", "?")):
        frases.pop()  # terminou no meio da frase
    return " ".join(frases[:MAXIMO_FRASES])[:TAMANHO_MAXIMO].strip()


def _numeros(texto: str) -> set[str]:
    """Números do texto, nas formas "3,14", "3.14" e com as partes "3" e "14"."""
    numeros = set()
    for numero in NUMERO.findall(texto):
        numeros |= {numero, numero.replace(",", "."), *re.split(r"[.,]", numero)}
    return numeros


def _sujeitos_antes(texto: str, posicao: int) -> set[str]:
    """Sujeitos citados na oração que termina em `posicao` (até a vírgula,
    ponto e vírgula ou fim de frase anterior, no máximo JANELA_SUJEITO caracteres)."""
    janela = texto[max(0, posicao - JANELA_SUJEITO):posicao]
    janela = re.split(r"[,;]\s|[.!?]\s", janela)[-1]
    return {next(g for g in m.groups() if g).strip() for m in SUJEITO.finditer(janela)}


def _contradicao_interna(texto: str) -> str | None:
    """Sujeito que o texto chama de incorreto e, em outro ponto, de correto."""
    negativos = [(m, _sujeitos_antes(texto, m.start())) for m in POLARIDADE_NEGATIVA.finditer(texto)]
    for positivo in POLARIDADE_POSITIVA.finditer(texto):
        sujeitos = _sujeitos_antes(texto, positivo.start())
        for negativo, sujeitos_negativo in negativos:
            comuns = sujeitos & sujeitos_negativo
            if comuns:
                return f"contradição interna: {sorted(comuns)[0]!r} {negativo.group(0)!r} e {positivo.group(0)!r}"
    return None


def verificar_texto(texto: str, contexto: list[str], texto_proprio: str,
                    acertou: bool | None = None) -> str | None:
    """Guarda de saída genérica (pura). Devolve o motivo do descarte, ou None.
        contexto:      textos de onde números podem vir (enunciado, trechos...);
        texto_proprio: texto da própria pergunta/item; expressão proibida que
                       aparece nele é termo do conteúdo e não é barrada;
        acertou:       veredito já dado ao aluno (None no diálogo livre)."""
    permitidos = _numeros(" ".join(contexto))
    for numero in NUMERO.findall(texto):
        if numero not in permitidos and numero.replace(",", ".") not in permitidos:
            return f"número inventado: {numero}"

    minusculo, proprio_minusculo = texto.lower(), texto_proprio.lower()
    for expressao in EXPRESSOES_PROIBIDAS:
        achado = re.search(expressao, minusculo)
        if achado and not re.search(expressao, proprio_minusculo):
            return f"referência ao prompt: {achado.group(0)!r}"

    if acertou is not None:
        contrarias = DIZ_QUE_ERROU if acertou else DIZ_QUE_ACERTOU
        for expressao in contrarias:
            achado = re.search(expressao, minusculo)
            if achado:
                return f"contradiz o veredito: {achado.group(0)!r}"
    return _contradicao_interna(minusculo)


def verificar_explicacao(explicacao: str, item: dict, indice_escolhido: int,
                         trechos: list[dict]) -> str | None:
    """Guarda de saída do feedback de item. Devolve o motivo do descarte, ou
    None se a explicação do LLM pode ir ao aluno."""
    texto_item = " ".join([item["enunciado"], *item["alternativas"], item["explicacao"]])
    return verificar_texto(explicacao, [texto_item, *(t["texto"] for t in trechos)], texto_item,
                           acertou=indice_escolhido == item["indice_correto"])


def gerar_feedback(item: dict, indice_escolhido: int, materiais: list[str],
                   timeout: int = TUTOR_TIMEOUT_LLM, modo: str | None = None) -> ResultadoFeedback:
    """Veredito fixo + explicação (LLM aprovado pela guarda, ou a do item).
    modo: "ancorado" ou "livre"; None usa TUTOR_MODO_FEEDBACK."""
    modo = modo or TUTOR_MODO_FEEDBACK
    if modo not in MODOS:
        raise ValueError(f"Modo de feedback inválido: {modo!r} (use {' ou '.join(MODOS)}).")
    veredito = montar_veredito(item, indice_escolhido)
    padrao = ResultadoFeedback(veredito, item["explicacao"], [], "fallback")
    try:
        trechos = buscar_trechos(item, materiais)
    except Exception as erro:  # Chroma ou embedding indisponível
        log.warning("Busca no RAG falhou (%s); usando explicação do item.", type(erro).__name__)
        padrao.falha_llm = f"rag: {descrever_falha(erro)}"
        return padrao
    if not trechos:
        log.info("Nenhum trecho relevante para o item %s; usando explicação do item.", item["id"])
        return padrao

    try:
        montar = montar_prompt_ancorado if modo == "ancorado" else montar_prompt_livre
        resposta = chamar_llm(montar(item, indice_escolhido, trechos), think=False,
                              timeout=timeout, max_tokens=TUTOR_MAX_TOKENS, temperatura=TUTOR_TEMPERATURA,
                              top_p=TUTOR_TOP_P, seed=TUTOR_SEED)
    except Exception as erro:
        falha = descrever_falha(erro)
        log.warning("Feedback do LLM indisponível (%s); usando explicação do item.", falha)
        padrao.falha_llm = falha
        return padrao
    explicacao = limpar_explicacao(resposta)
    if not explicacao:
        return padrao
    motivo = verificar_explicacao(explicacao, item, indice_escolhido, trechos)
    if motivo:
        # só o tipo do motivo: o resto traz trecho do texto gerado (fica no banco, para a revisão docente)
        log.info("Guarda descartou o feedback do item %s (%s); usando explicação do item.", item["id"],
                 motivo.split(":")[0])
        return ResultadoFeedback(veredito, item["explicacao"], [], "guarda",
                                 motivo_descarte=motivo, explicacao_descartada=explicacao)
    fontes = list(dict.fromkeys(t["fonte"] for t in trechos))  # sem repetir
    return ResultadoFeedback(veredito, explicacao, fontes, "LLM")
