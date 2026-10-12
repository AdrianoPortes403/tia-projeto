"""
Camada de abstração da chamada ao LLM (pacote 1.4.1 / usado por todos os agentes).

Todo código do projeto que precisa "perguntar algo à IA" (chat ou
embedding) deve passar por aqui, em vez de chamar o Ollama diretamente.
Endereço e modelos vêm de tia.core.config — se algo mudar (ex: trocar de
modelo, migrar para a VM oficial), ajusta-se no .env, sem tocar no código
dos agentes.

Importante: por decisão do TAP (requisito R07), este projeto usa
exclusivamente um LLM local (Qwen, via Ollama) — nunca uma API externa,
nem mesmo em ambiente de desenvolvimento.

Raciocínio ("thinking"): quando think=False (padrão; R09), o raciocínio é
desligado conforme o modelo (RACIOCINIO_POR_MODELO em core/config.py): sufixo
/nothink na última mensagem do usuário, opção "think": false do Ollama, os
dois, ou nada. Quem chama não escreve /nothink no prompt. Em qualquer caso,
blocos de raciocínio que vierem no texto (<think>...</think> e afins,
RACIOCINIO_TAGS) são REMOVIDOS aqui, antes das guardas e dos limites de
tamanho dos agentes, inclusive bloco aberto e não fechado (resposta cortada
no meio do raciocínio: sobra texto vazio).

Medição (deploy/verificar.sh --medir-r09): usar_modelo(nome) troca o modelo
padrão dentro de um bloco "with", e coletar_chamadas() devolve, para cada
chamada, uma RespostaLLM (tempo, se veio raciocínio, se foi cortada pelo
limite de tokens, se ficou vazia, falha).

Amostragem (temperatura, top_p, seed) pode ser passada por chamada; quem
não passa fica com o padrão do Ollama (ex.: justificativa do Planejador).

Toda chamada envia "keep_alive" (OLLAMA_KEEP_ALIVE, padrão "30m"), para o
modelo continuar carregado na memória entre interações.

Como rodar (teste rápido de conexão):
    python -m tia.core.llm_client

Pré-requisitos:
    - Ollama rodando localmente
    - Modelos baixados: deploy/modelos.sh (ou ollama pull qwen3:1.7b && ollama pull nomic-embed-text)
"""

import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from fnmatch import fnmatchcase

import requests

import tia.core.config as config
from tia.core.config import EMBED_MODEL, OLLAMA_KEEP_ALIVE, OLLAMA_URL

SUFIXO_NOTHINK = "/nothink"
MODOS_RACIOCINIO = ("prompt", "api", "prompt+api", "nada")


@dataclass
class RespostaLLM:
    """O que aconteceu numa chamada de chat (para medir o R09 por modelo)."""
    modelo: str
    modo_raciocinio: str
    tempo_ms: int
    texto: str = ""                  # já sem raciocínio
    raciocinio_no_texto: bool = False  # veio raciocínio (não vazio) no texto e foi removido
    raciocinio_aberto: bool = False    # bloco aberto sem fechar: cortado no meio do raciocínio
    raciocinio_api: bool = False       # o Ollama devolveu "thinking" separado (pensou mesmo desligado)
    cortada: bool = False              # parou pelo limite de tokens (done_reason "length")
    tokens: int | None = None          # eval_count
    falha: str | None = None           # timeout, ConnectionError... (a chamada levantou o erro)

    @property
    def vazia(self) -> bool:
        return self.falha is None and not self.texto.strip()


_MODELO: ContextVar[str | None] = ContextVar("modelo_llm", default=None)
_COLETOR: ContextVar[list | None] = ContextVar("coletor_llm", default=None)


@contextmanager
def usar_modelo(nome: str):
    """Dentro do bloco, chamadas sem model= usam este modelo (em vez de MODELO_PADRAO)."""
    marca = _MODELO.set(nome)
    try:
        yield
    finally:
        _MODELO.reset(marca)


@contextmanager
def coletar_chamadas():
    """Dentro do bloco, cada chamada de chat acrescenta uma RespostaLLM à lista devolvida."""
    chamadas: list[RespostaLLM] = []
    marca = _COLETOR.set(chamadas)
    try:
        yield chamadas
    finally:
        _COLETOR.reset(marca)


def modelo_atual() -> str:
    return _MODELO.get() or config.MODELO_PADRAO


def modo_raciocinio(modelo: str) -> str:
    """Modo de desligar o raciocínio do modelo, pelo mapa RACIOCINIO_POR_MODELO."""
    for regra in config.RACIOCINIO_POR_MODELO.split(";"):
        if not regra.strip():
            continue
        padrao, separador, modo = regra.partition("=")
        modo = modo.strip()
        if not separador or modo not in MODOS_RACIOCINIO:
            raise ValueError(f"RACIOCINIO_POR_MODELO: regra inválida {regra.strip()!r} "
                             f"(use padrão=modo, com modo em {', '.join(MODOS_RACIOCINIO)}).")
        if fnmatchcase(modelo, padrao.strip()):
            return modo
    return "nada"


def remover_raciocinio(texto: str, tags: list[str] | None = None) -> tuple[str, bool, bool]:
    """Tira os blocos de raciocínio do texto. Devolve (texto limpo, se havia
    raciocínio não vazio, se ficou um bloco aberto sem fechar). Casos:
    <think>...</think> completo; só o fechamento (a abertura veio no modelo de
    prompt: some tudo até ele); só a abertura (cortado no meio: some até o fim)."""
    nomes = "|".join(re.escape(t) for t in (tags or config.RACIOCINIO_TAGS))
    if not nomes:
        return texto.strip(), False, False
    havia = False

    def completo(achado: re.Match) -> str:
        nonlocal havia
        havia = havia or bool(achado.group(2).strip())
        return " "

    limpo = re.sub(rf"<({nomes})\b[^>]*>(.*?)</\1\s*>", completo, texto, flags=re.S | re.I)
    fechamentos = list(re.finditer(rf"</(?:{nomes})\s*>", limpo, flags=re.I))
    if fechamentos:
        havia = havia or bool(limpo[:fechamentos[-1].start()].strip())
        limpo = limpo[fechamentos[-1].end():]
    abertura = re.search(rf"<(?:{nomes})\b[^>]*>", limpo, flags=re.I)
    aberto = abertura is not None
    if aberto:
        havia = havia or bool(limpo[abertura.end():].strip())
        limpo = limpo[:abertura.start()]
    return limpo.strip(), havia, aberto


def _aplicar_nothink(mensagens: list[dict]) -> list[dict]:
    """Retorna uma cópia das mensagens com /nothink no fim da última
    mensagem do usuário (se ainda não estiver lá)."""
    copia = [dict(m) for m in mensagens]
    for mensagem in reversed(copia):
        if mensagem.get("role") == "user":
            conteudo = mensagem.get("content", "").rstrip()
            if not conteudo.endswith(SUFIXO_NOTHINK):
                mensagem["content"] = f"{conteudo} {SUFIXO_NOTHINK}"
            break
    return copia


def chamar_llm(prompt: str, model: str = None, think: bool = False, timeout: int = 120,
               max_tokens: int | None = None, temperatura: float | None = None,
               top_p: float | None = None, seed: int | None = None) -> str:
    """Envia um prompt ao modelo local e retorna a resposta em texto.

    Parâmetros:
        prompt: o texto da pergunta/instrução.
        model: nome do modelo Ollama a usar (ex: "qwen3:1.7b"). Se não for
               informado, usa o de usar_modelo() ou MODELO_PADRAO.
        think: se True, permite que o modelo "raciocine" antes de
               responder (mais lento, mas pode melhorar respostas
               complexas). Padrão é False, para priorizar velocidade
               (requisito R09 — resposta em até 15 segundos).
        timeout: tempo máximo de espera pela resposta, em segundos.
        max_tokens: limite de tokens gerados (opção num_predict do Ollama).
               Em CPU, a geração é o que mais pesa no tempo; limitar evita
               estourar o R09. None = sem limite. O texto pode vir cortado.
        temperatura, top_p, seed: opções de amostragem do Ollama
               (options.temperature, options.top_p, options.seed). None =
               não envia e o Ollama usa o padrão dele. Temperatura baixa e
               seed fixa deixam a resposta mais estável entre execuções.
    """
    return chamar_llm_com_historico(
        [{"role": "user", "content": prompt}], model=model, think=think, timeout=timeout,
        max_tokens=max_tokens, temperatura=temperatura, top_p=top_p, seed=seed,
    )


def chamar_llm_com_historico(mensagens: list[dict], model: str = None, think: bool = False, timeout: int = 120,
                             max_tokens: int | None = None, temperatura: float | None = None,
                             top_p: float | None = None, seed: int | None = None) -> str:
    """Igual a chamar_llm, mas aceita um histórico de conversa (multi-turno),
    no formato [{"role": "user"/"assistant", "content": "..."}].
    Necessário para o Agente 2 (Tutor), que mantém contexto entre perguntas.
    Devolve o texto SEM blocos de raciocínio (remover_raciocinio).
    """
    modelo_usado = model or modelo_atual()
    modo = modo_raciocinio(modelo_usado)
    if not think and modo in ("prompt", "prompt+api"):
        mensagens = _aplicar_nothink(mensagens)
    corpo = {
        "model": modelo_usado,
        "messages": mensagens,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
    }
    if think and modo != "nada":
        corpo["think"] = True
    elif not think and modo in ("api", "prompt+api"):
        corpo["think"] = False
    opcoes = {"num_predict": max_tokens, "temperature": temperatura, "top_p": top_p, "seed": seed}
    opcoes = {nome: valor for nome, valor in opcoes.items() if valor is not None}
    if opcoes:
        corpo["options"] = opcoes
    coletor = _COLETOR.get()
    inicio = time.perf_counter()
    try:
        resposta = requests.post(f"{OLLAMA_URL}/api/chat", json=corpo, timeout=timeout)
        resposta.raise_for_status()
        dados = resposta.json()
    except Exception as erro:
        if coletor is not None:
            coletor.append(RespostaLLM(modelo_usado, modo, round((time.perf_counter() - inicio) * 1000),
                                       falha=descrever_falha(erro)))
        raise
    mensagem = dados["message"]
    texto, havia, aberto = remover_raciocinio(mensagem.get("content") or "")
    if coletor is not None:
        coletor.append(RespostaLLM(modelo_usado, modo, round((time.perf_counter() - inicio) * 1000), texto,
                                   raciocinio_no_texto=havia, raciocinio_aberto=aberto,
                                   raciocinio_api=bool((mensagem.get("thinking") or "").strip()),
                                   cortada=dados.get("done_reason") == "length", tokens=dados.get("eval_count")))
    return texto


def listar_modelos_instalados(timeout: int = 10) -> list[str]:
    """Nomes dos modelos que o Ollama tem (GET /api/tags), para a verificação da VM."""
    resposta = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
    resposta.raise_for_status()
    return [m["name"] for m in resposta.json().get("models", [])]


def descrever_falha(erro: Exception) -> str:
    """Rótulo curto da falha de uma chamada ao Ollama, para mostrar ao usuário
    e nas respostas da API: "timeout" quando estourou o tempo; senão, o nome do
    tipo do erro (ex.: "ConnectionError")."""
    if isinstance(erro, (requests.Timeout, TimeoutError)):
        return "timeout"
    return type(erro).__name__


def gerar_embedding(texto: str, model: str = None, timeout: int = 60) -> list[float]:
    """Transforma um texto em um vetor numérico (embedding), usado pelo RAG
    para medir o quão parecidos dois textos são.

    Parâmetros:
        texto: o texto a ser convertido.
        model: nome do modelo de embedding no Ollama. Se não for
               informado, usa o padrão definido em EMBED_MODEL
               (precisa ser baixado antes: ollama pull nomic-embed-text).
        timeout: tempo máximo de espera pela resposta, em segundos.
    """
    modelo_usado = model or EMBED_MODEL
    resposta = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": modelo_usado, "prompt": texto, "keep_alive": OLLAMA_KEEP_ALIVE},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()["embedding"]


if __name__ == "__main__":
    print(chamar_llm("Diga oi em uma frase curta"))
