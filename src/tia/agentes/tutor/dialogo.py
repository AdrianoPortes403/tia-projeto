"""
Diálogo livre do Agente 2 (Tutor), parte 2b: o aluno pergunta, o Tutor
responde ancorado SOMENTE no material do curso (RAG), citando a fonte (R03).

Para cada pergunta:
    1. busca no RAG (só no material da competência, se informada) e descarta
       os trechos distantes demais (TUTOR_DISTANCIA_MAXIMA);
    2. portão de cobertura lexical (avaliar_cobertura, função pura): a
       distância sozinha não separa pergunta coberta de pergunta fora do
       material (medido em 10/10). A pergunta é normalizada (minúsculas, sem
       acento nem pontuação, plural simples), perde stopwords e termos
       genéricos do índice (presentes em mais de metade dos trechos), e pelo
       menos TUTOR_COBERTURA_MIN dos termos restantes (ou um sinônimo do campo
       "palavras_chave" da ementa) precisa aparecer nos trechos recuperados.
       Com TUTOR_EXIGE_TERMO_RARO, também o termo de conteúdo mais raro do
       índice (maior IDF, contando os sinônimos) precisa estar coberto: uma
       pergunta como "list comprehension" empatava em 0,50 com uma coberta;
    3. sem trecho relevante ou sem passar no portão: resposta FIXA gerada por
       código (MENSAGEM_SEM_MATERIAL), sem chamar o LLM;
    4. com trechos: prompt ancorado (mesmas regras do feedback de item,
       feedback.REGRAS_ANCORADAS) e mesma amostragem da config. Se os trechos
       não respondem à pergunta, o LLM devolve SINAL_SEM_RESPOSTA e o código
       troca pela mensagem fixa;
    5. guardas de saída: a do feedback (feedback.verificar_texto: número que
       não está na pergunta nem nos trechos, referência ao prompt, contradição
       interna) e a de identificadores (identificador_inventado: nome de
       código, biblioteca ou função que não está na pergunta nem nos trechos).
       Se uma barrar, vai o trecho mais relevante TRANSCRITO, com a fonte
       ("Do material: ..."), sem passar pelo LLM;
    6. "fontes" vêm dos metadados do RAG, nunca do texto do LLM; resposta
       fixa não tem fonte.

O texto livre do aluno vai só para o banco (tabela tutor_dialogo), nunca
para log (R08); o prompt não leva aluno_id.

Não é executável sozinho; demonstração:
    python -m tia.agentes.tutor --dialogo

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (sem ele, resposta fixa)
    - Material indexado: python -m tia.rag.ingest
"""

import keyword
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from tia.agentes.tutor import CompetenciaInexistente, repositorio
from tia.agentes.tutor.feedback import REGRAS_ANCORADAS, limpar_explicacao, verificar_texto
from tia.agentes.tutor.modelos import PerguntaAluno, RespostaDialogo
from tia.core.config import (TUTOR_COBERTURA_MIN, TUTOR_DISTANCIA_MAXIMA, TUTOR_EXIGE_TERMO_RARO, TUTOR_MAX_TOKENS,
                             TUTOR_NUM_TRECHOS, TUTOR_SEED, TUTOR_TEMPERATURA, TUTOR_TIMEOUT_LLM, TUTOR_TOP_P)
from tia.core.llm_client import chamar_llm
from tia.rag.retrieve import buscar_contexto, listar_trechos

log = logging.getLogger(__name__)

MENSAGEM_SEM_MATERIAL = "Não encontrei isso no material disponível; vale perguntar ao professor."
MENSAGEM_SEM_RESPOSTA = ("Não consegui montar uma resposta confiável com o material disponível; "
                         "vale perguntar ao professor.")
# o LLM escreve isto quando os trechos não respondem à pergunta
SINAL_SEM_RESPOSTA = "SEM_RESPOSTA"
PREFIXO_DO_MATERIAL = "Do material: "

# --- portão de cobertura lexical ---
# palavra presente em mais desta fração dos trechos do índice é genérica
FRACAO_GENERICA = 0.5
# stopwords do português, já normalizadas (sem acento, singular), mais as
# palavras de formato de pergunta ("serve", "diferenca", "crio"...) e "python",
# que aparece em qualquer pergunta e nada diz sobre o assunto
STOPWORDS = frozenset("""
a o as os um uma uns umas de do da dos das em no na nos nas num numa para pra por pelo pela
pelos pelas com sem sob sobre entre ate apos ao aos que qual quais quando quanto quantos
quantas como onde porque porque quem cujo cuja e ou mas se nao sim ja tambem mais menos muito
muita pouco pouca ser sao foi era sera esta estao estar estou ter tem tinha ha havia eu voce
voces ele ela eles elas me mim meu minha meus minhas seu sua seus suas nosso nossa isso isto
esse essa esses essas este estes aquilo aquele aquela la aqui ali algum alguma alguns todo toda
todos cada outro outra mesmo mesma so dentro fora antes depois entao assim
serve servem funciona funcionam acontece significa quer dizer diferenca exemplo explica explicar
quero saber preciso ajuda duvida pode podem posso poder devo deve consigo
criar crio cria fazer faco faz fazem usar uso usa utilizar definir defino escrever escrevo
python
""".split())
_TOKEN = re.compile(r"[a-z0-9_]+")


def _singular(palavra: str) -> str:
    """Plural simples do português (o mesmo vale para pergunta e trechos)."""
    if len(palavra) <= 3:
        return palavra
    if palavra.endswith(("oes", "aes")):
        return palavra[:-3] + "ao"
    if palavra.endswith(("ais", "eis")) and len(palavra) > 4:
        return palavra[:-2] + "l"
    if palavra.endswith(("res", "zes")):
        return palavra[:-2]
    if palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


def normalizar(texto: str) -> list[str]:
    """Minúsculas, sem acento nem pontuação, plural simples."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    return [_singular(t) for t in _TOKEN.findall(sem_acento)]


STOPWORDS_NORMALIZADAS = frozenset(_singular(p) for p in STOPWORDS) | STOPWORDS


def calcular_termos_genericos(textos: list[str], fracao: float = FRACAO_GENERICA) -> set[str]:
    """Termos (normalizados) presentes em mais de `fracao` dos textos (IDF baixo)."""
    if not textos:
        return set()
    contagem: dict[str, int] = {}
    for texto in textos:
        for termo in set(normalizar(texto)):
            contagem[termo] = contagem.get(termo, 0) + 1
    return {termo for termo, n in contagem.items() if n > fracao * len(textos)}


@lru_cache(maxsize=1)
def textos_do_indice() -> tuple[str, ...]:
    """Textos de todos os trechos do índice (lidos uma vez por processo)."""
    return tuple(t["texto"] for t in listar_trechos())


@lru_cache(maxsize=1)
def termos_genericos() -> frozenset[str]:
    """Termos genéricos do índice inteiro (calculado uma vez por processo)."""
    return frozenset(calcular_termos_genericos(list(textos_do_indice())))


@dataclass
class Cobertura:
    passou: bool
    fracao: float
    termos: list[str]       # termos de conteúdo da pergunta
    cobertos: list[str]     # os que aparecem (ou um sinônimo) nos trechos
    raros: list[str] | None = None  # termos mais raros no índice (só com a regra do termo raro)


def _presente(termo: str, tokens: set[str] | frozenset[str], grupos: list[list[list[str]]]) -> bool:
    """O termo, ou um sinônimo do seu grupo, está entre os tokens? (membro de
    várias palavras: todas elas presentes)"""
    if termo in tokens:
        return True
    return any([termo] in grupo and any(m and set(m) <= tokens for m in grupo) for grupo in grupos)


def avaliar_cobertura(pergunta: str, textos_trechos: list[str], genericos: set[str] | frozenset[str],
                      sinonimos: list[list[str]], minimo: float = TUTOR_COBERTURA_MIN,
                      textos_indice: list[str] | tuple[str, ...] | None = None) -> Cobertura:
    """Portão de cobertura (puro): fração dos termos de conteúdo da pergunta
    presentes nos trechos. Sem termo de conteúdo, não passa.
    sinonimos: grupos do campo "palavras_chave" da ementa; um termo que é
    membro de um grupo conta como presente se qualquer membro estiver nos
    trechos (membro de várias palavras: todas elas presentes).
    textos_indice: com ele, aplica a regra do termo mais raro: o(s) termo(s)
    de conteúdo presentes no menor número de trechos do índice (maior IDF,
    contando os sinônimos) precisam estar todos cobertos. Vazio ou None: sem a regra."""
    termos = list(dict.fromkeys(t for t in normalizar(pergunta)
                                if len(t) > 1 and not t.isdigit()
                                and t not in STOPWORDS_NORMALIZADAS and t not in genericos))
    presentes = {t for texto in textos_trechos for t in normalizar(texto)}
    grupos = [[normalizar(membro) for membro in grupo] for grupo in sinonimos]

    cobertos = [t for t in termos if _presente(t, presentes, grupos)]
    fracao = len(cobertos) / len(termos) if termos else 0.0
    passou = bool(termos) and fracao >= minimo
    raros = None
    if textos_indice and termos:
        indice = [set(normalizar(texto)) for texto in textos_indice]
        frequencia = {t: sum(_presente(t, tokens, grupos) for tokens in indice) for t in termos}
        menor = min(frequencia.values())
        raros = [t for t in termos if frequencia[t] == menor]
        passou = passou and all(t in cobertos for t in raros)
    return Cobertura(passou=passou, fracao=fracao, termos=termos, cobertos=cobertos, raros=raros)


# --- guarda de identificadores ---
_CRASES = re.compile(r"`([^`]+)`")
_LITERAL = re.compile(r"(['\"]).*?\1")
_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# fora das crases: nome pontuado (requests.get), chamada (connect(), nome com
# dígito ou "_" (psycopg2, fetch_all)
_CODIGO_SOLTO = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|\b[A-Za-z_]\w*(?=\()"
                           r"|\b(?=[A-Za-z_]*[_\d])(?=\w*[A-Za-z])[A-Za-z_]\w*\b")


def identificador_inventado(resposta: str, contexto: list[str]) -> str | None:
    """Guarda (pura): nome de código, biblioteca ou função citado na resposta
    (entre crases, pontuado, chamado com "(" ou com dígito/"_") que não
    aparece na pergunta nem nos trechos. Palavras reservadas do Python e
    nomes de uma letra não contam. Devolve o motivo, ou None."""
    conhecidos = {i.lower() for texto in contexto for i in _IDENTIFICADOR.findall(texto)}
    trechos_de_codigo = [_LITERAL.sub(" ", c) for c in _CRASES.findall(resposta)]
    trechos_de_codigo += _CODIGO_SOLTO.findall(_CRASES.sub(" ", resposta))
    for codigo in trechos_de_codigo:
        for nome in _IDENTIFICADOR.findall(codigo):
            if len(nome) > 1 and not keyword.iskeyword(nome) and nome.lower() not in conhecidos:
                return f"identificador fora do material: {nome}"
    return None


@dataclass
class ResultadoDialogo:
    resposta: str
    fontes: list[str]
    origem: str            # "LLM", "guarda" ou "fallback"
    motivo_descarte: str = ""
    cobertura: float | None = None  # fração do portão (None se nem chegou a ele)


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


def frases_inteiras(texto: str) -> str:
    """Tira as pontas cortadas no meio pela divisão do material em trechos
    (por número de caracteres): o começo, se não inicia frase, até o primeiro
    fim de frase; o final, depois do último fim de frase. Sem frase inteira,
    devolve o texto todo."""
    texto = " ".join(texto.split())
    inicio = 0
    if texto and texto[0].islower():
        fim_primeira = re.search(r"[.!?:]\s+", texto)
        inicio = fim_primeira.end() if fim_primeira else 0
    ultimo_fim = max(texto.rfind(". "), texto.rfind("! "), texto.rfind("? "))
    final = len(texto) if texto.endswith((".", "!", "?")) else (ultimo_fim + 1 if ultimo_fim >= inicio else len(texto))
    return texto[inicio:final].strip() or texto


def trecho_transcrito(trechos: list[dict]) -> ResultadoDialogo:
    """Trecho mais relevante (menor distância), transcrito em frases inteiras, com a fonte."""
    melhor = min(trechos, key=lambda t: t["distancia"])
    return ResultadoDialogo(PREFIXO_DO_MATERIAL + frases_inteiras(melhor["texto"]), [melhor["fonte"]], "guarda")


def gerar_resposta(pergunta: str, materiais: list[str] | None, sinonimos: list[list[str]] | None = None,
                   timeout: int = TUTOR_TIMEOUT_LLM) -> ResultadoDialogo:
    """Resposta ancorada nos trechos, aprovada pelas guardas; trecho transcrito
    se uma guarda barrar; ou texto fixo. sinonimos: None = os de todas as
    competências da ementa."""
    sem_material = ResultadoDialogo(MENSAGEM_SEM_MATERIAL, [], "fallback")
    try:
        trechos = buscar_trechos_dialogo(pergunta, materiais)
        genericos = termos_genericos() if trechos else frozenset()
    except Exception as erro:  # Chroma ou embedding indisponível
        log.warning("Busca no RAG falhou no diálogo (%s); resposta fixa.", type(erro).__name__)
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback")
    if not trechos:
        log.info("Diálogo sem trecho relevante; resposta fixa sem chamar o LLM.")
        return sem_material

    sinonimos = repositorio.palavras_chave(None) if sinonimos is None else sinonimos
    cobertura = avaliar_cobertura(pergunta, [t["texto"] for t in trechos], genericos, sinonimos,
                                  textos_indice=textos_do_indice() if TUTOR_EXIGE_TERMO_RARO else None)
    if not cobertura.passou:
        # só a fração: os termos são texto livre do aluno (R08)
        log.info("Portão de cobertura barrou a pergunta (%.2f); resposta fixa sem chamar o LLM.", cobertura.fracao)
        return ResultadoDialogo(MENSAGEM_SEM_MATERIAL, [], "fallback", cobertura=cobertura.fracao)

    try:
        bruta = chamar_llm(montar_prompt_dialogo(pergunta, trechos), think=False, timeout=timeout,
                           max_tokens=TUTOR_MAX_TOKENS, temperatura=TUTOR_TEMPERATURA,
                           top_p=TUTOR_TOP_P, seed=TUTOR_SEED)
    except Exception as erro:
        log.warning("LLM indisponível no diálogo (%s); resposta fixa.", type(erro).__name__)
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback", cobertura=cobertura.fracao)
    if SINAL_SEM_RESPOSTA in bruta:
        log.info("O LLM indicou que os trechos não respondem à pergunta; resposta fixa.")
        return ResultadoDialogo(MENSAGEM_SEM_MATERIAL, [], "fallback", cobertura=cobertura.fracao)
    resposta = limpar_explicacao(bruta)
    if not resposta:
        return ResultadoDialogo(MENSAGEM_SEM_RESPOSTA, [], "fallback", cobertura=cobertura.fracao)

    contexto = [pergunta, *(t["texto"] for t in trechos)]
    motivo = verificar_texto(resposta, contexto, pergunta) or identificador_inventado(resposta, contexto)
    if motivo:
        # só a categoria do motivo: o detalhe pode ecoar texto da pergunta (R08)
        log.info("Guarda descartou a resposta do diálogo (%s); vai o trecho do material.", motivo.split(":")[0])
        transcrito = trecho_transcrito(trechos)
        transcrito.motivo_descarte, transcrito.cobertura = motivo, cobertura.fracao
        return transcrito
    fontes = list(dict.fromkeys(t["fonte"] for t in trechos))  # sem repetir
    return ResultadoDialogo(resposta, fontes, "LLM", cobertura=cobertura.fracao)


def perguntar(entrada: PerguntaAluno) -> RespostaDialogo:
    """Responde à pergunta livre do aluno e grava em tutor_dialogo."""
    inicio = time.perf_counter()
    materiais = None
    if entrada.competencia_id is not None:
        materiais = repositorio.materiais_da_competencia(entrada.competencia_id)
        if materiais is None:
            raise CompetenciaInexistente(f"Competência '{entrada.competencia_id}' não existe na ementa.")
    resultado = gerar_resposta(entrada.pergunta, materiais, repositorio.palavras_chave(entrada.competencia_id))
    tempo_ms = round((time.perf_counter() - inicio) * 1000)
    dialogo_id = repositorio.registrar_dialogo(entrada.aluno_id, entrada.competencia_id, entrada.pergunta,
                                               resultado.resposta, resultado.fontes, resultado.origem, tempo_ms)
    return RespostaDialogo(dialogo_id=dialogo_id, resposta=resultado.resposta, fontes=resultado.fontes,
                           origem=resultado.origem, tempo_ms=tempo_ms)
