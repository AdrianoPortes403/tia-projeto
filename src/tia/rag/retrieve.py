"""
Módulo de busca do pipeline de RAG (pacote 1.4.2).

Dada uma pergunta do aluno, retorna os pedaços de material do curso
mais relevantes para embasar a resposta do Agente 2 (Tutor) — inclusive
para cumprir o requisito R03 (feedback com citação de fontes institucionais).

Como testar sozinho:
    python -m tia.rag.retrieve

Pré-requisitos:
    - Ollama rodando, com EMBED_MODEL baixado
    - Material indexado: python -m tia.rag.ingest
"""

import chromadb

from tia.core.llm_client import gerar_embedding
from tia.core.config import CHROMA_DIR, COLLECTION_NAME


def buscar_contexto(pergunta: str, k: int = 3, fontes: list[str] | None = None) -> list[dict]:
    """Busca os k pedaços de material mais relevantes para a pergunta.

    Se "fontes" for informado (lista de nomes de arquivo), a busca fica
    restrita a esses arquivos; lista vazia não encontra nada.

    Retorna uma lista de dicionários, cada um com o texto do trecho,
    a fonte (arquivo de origem), o índice do pedaço dentro do arquivo e a
    distância (quanto menor, mais parecido).
    """
    if fontes is not None and not fontes:
        return []
    cliente = chromadb.PersistentClient(path=CHROMA_DIR)
    colecao = cliente.get_or_create_collection(COLLECTION_NAME)

    embedding_pergunta = gerar_embedding(pergunta)
    filtro = {"fonte": {"$in": fontes}} if fontes else None
    resultado = colecao.query(query_embeddings=[embedding_pergunta], n_results=k, where=filtro)

    trechos = []
    documentos = resultado.get("documents", [[]])[0]
    metadados = resultado.get("metadatas", [[]])[0]
    distancias = resultado.get("distances", [[]])[0]

    for texto, meta, distancia in zip(documentos, metadados, distancias):
        trechos.append({
            "texto": texto,
            "fonte": meta.get("fonte", "desconhecida"),
            "indice": meta.get("indice", 0),
            "distancia": distancia,
        })
    return trechos


if __name__ == "__main__":
    pergunta_teste = "O que é recursão?"
    resultados = buscar_contexto(pergunta_teste)
    print(f"Pergunta: {pergunta_teste}\n")
    if not resultados:
        print("Nenhum resultado — rode 'python -m tia.rag.ingest' primeiro.")
    for r in resultados:
        print(f"[fonte: {r['fonte']} | distância: {r['distancia']:.4f}]")
        print(r["texto"][:200], "...\n")
