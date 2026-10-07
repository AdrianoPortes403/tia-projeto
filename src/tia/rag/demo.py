"""
Demonstração ponta a ponta do RAG: busca o contexto relevante no material
indexado e usa o Qwen (via Ollama) para gerar uma resposta citando a fonte.
É o mesmo padrão que o Agente 2 (Tutor) vai usar internamente.

Como rodar:
    python -m tia.rag.demo "sua pergunta aqui"

Pré-requisitos:
    - Ollama rodando, com CHAT_MODEL e EMBED_MODEL baixados
    - Material indexado: python -m tia.rag.ingest

O /nothink é acrescentado automaticamente pelo llm_client (think=False).
"""

import sys

from tia.core.llm_client import chamar_llm
from tia.rag.retrieve import buscar_contexto


def responder_com_fontes(pergunta: str) -> str:
    trechos = buscar_contexto(pergunta, k=3)

    if not trechos:
        contexto_formatado = "(nenhum material indexado ainda)"
    else:
        partes = [f"Fonte: {t['fonte']}\nTrecho: {t['texto']}" for t in trechos]
        contexto_formatado = "\n\n".join(partes)

    prompt = f"""Você é um tutor educacional. Responda à pergunta do aluno
usando APENAS as informações do material abaixo. Ao final da resposta,
cite explicitamente de qual arquivo-fonte veio a informação usada.

Material disponível:
{contexto_formatado}

Pergunta do aluno: {pergunta}

Responda de forma clara e didática."""

    return chamar_llm(prompt)


if __name__ == "__main__":
    pergunta = sys.argv[1] if len(sys.argv) > 1 else "O que é recursão?"
    print(responder_com_fontes(pergunta))
