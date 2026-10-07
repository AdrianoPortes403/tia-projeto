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

Quando think=False (padrão), o sufixo /nothink é acrescentado
automaticamente à última mensagem do usuário (requisito R09 — resposta em
até 15 segundos). Quem chama não precisa escrevê-lo no prompt.

Como rodar (teste rápido de conexão):
    python -m tia.core.llm_client

Pré-requisitos:
    - Ollama rodando localmente
    - Modelos baixados: ollama pull qwen3:1.7b && ollama pull nomic-embed-text
"""

import requests

from tia.core.config import CHAT_MODEL, EMBED_MODEL, OLLAMA_URL

SUFIXO_NOTHINK = "/nothink"


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


def chamar_llm(prompt: str, model: str = None, think: bool = False, timeout: int = 120) -> str:
    """Envia um prompt ao modelo local e retorna a resposta em texto.

    Parâmetros:
        prompt: o texto da pergunta/instrução.
        model: nome do modelo Ollama a usar (ex: "qwen3:1.7b"). Se não for
               informado, usa o padrão definido em CHAT_MODEL.
        think: se True, permite que o modelo "raciocine" antes de
               responder (mais lento, mas pode melhorar respostas
               complexas). Padrão é False, para priorizar velocidade
               (requisito R09 — resposta em até 15 segundos).
        timeout: tempo máximo de espera pela resposta, em segundos.
    """
    return chamar_llm_com_historico(
        [{"role": "user", "content": prompt}], model=model, think=think, timeout=timeout,
    )


def chamar_llm_com_historico(mensagens: list[dict], model: str = None, think: bool = False, timeout: int = 120) -> str:
    """Igual a chamar_llm, mas aceita um histórico de conversa (multi-turno),
    no formato [{"role": "user"/"assistant", "content": "..."}].
    Necessário para o Agente 2 (Tutor), que mantém contexto entre perguntas.
    """
    modelo_usado = model or CHAT_MODEL
    if not think:
        mensagens = _aplicar_nothink(mensagens)
    resposta = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": modelo_usado,
            "messages": mensagens,
            "think": think,
            "stream": False,
        },
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()["message"]["content"]


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
        json={"model": modelo_usado, "prompt": texto},
        timeout=timeout,
    )
    resposta.raise_for_status()
    return resposta.json()["embedding"]


if __name__ == "__main__":
    print(chamar_llm("Diga oi em uma frase curta"))
