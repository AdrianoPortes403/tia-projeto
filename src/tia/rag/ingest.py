"""
Script de ingestão do pipeline de RAG (pacote 1.4.2).

O que faz:
1. Lê todos os arquivos .txt da pasta de materiais do curso.
2. Quebra cada arquivo em pedaços menores (chunks).
3. Gera um "embedding" (representação numérica) de cada pedaço, usando
   o modelo de embedding local via Ollama.
4. Guarda tudo no Chroma (banco de dados vetorial), para consulta rápida depois.

Como rodar:
    python -m tia.rag.ingest

Pré-requisitos:
    - Ollama rodando localmente (já roda sozinho como serviço, no Linux e no Windows)
    - Modelo de embedding baixado: ollama pull nomic-embed-text
    - Arquivos .txt do material do curso dentro de conteudo/materiais/ (ou MATERIAIS_DIR no .env)
"""

import os
import glob
import chromadb

from tia.core.llm_client import gerar_embedding
from tia.core.config import (
    MATERIAIS_DIR, CHROMA_DIR, COLLECTION_NAME, CHUNK_SIZE, CHUNK_OVERLAP,
)


def dividir_em_chunks(texto: str, tamanho: int = CHUNK_SIZE, sobreposicao: int = CHUNK_OVERLAP) -> list[str]:
    """Quebra um texto longo em pedaços menores, com uma pequena sobreposição
    entre eles para não cortar uma explicação no meio de uma frase."""
    chunks = []
    inicio = 0
    while inicio < len(texto):
        fim = inicio + tamanho
        chunks.append(texto[inicio:fim])
        inicio += tamanho - sobreposicao
    return [c.strip() for c in chunks if c.strip()]


def carregar_arquivos_texto(pasta: str) -> list[dict]:
    """Lê todos os arquivos .txt de uma pasta (e subpastas) e retorna uma
    lista com o nome do arquivo e o conteúdo de cada um."""
    documentos = []
    caminhos = glob.glob(os.path.join(pasta, "**", "*.txt"), recursive=True)
    for caminho in caminhos:
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
        documentos.append({"fonte": os.path.basename(caminho), "conteudo": conteudo})
    return documentos


def indexar_materiais():
    documentos = carregar_arquivos_texto(MATERIAIS_DIR)
    if not documentos:
        print(f"Nenhum arquivo .txt encontrado em '{MATERIAIS_DIR}'. "
              f"Coloque o material do curso lá antes de rodar de novo.")
        return

    cliente = chromadb.PersistentClient(path=CHROMA_DIR)
    colecao = cliente.get_or_create_collection(COLLECTION_NAME)

    total_chunks = 0
    for doc in documentos:
        chunks = dividir_em_chunks(doc["conteudo"])
        for i, chunk in enumerate(chunks):
            embedding = gerar_embedding(chunk)
            id_chunk = f"{doc['fonte']}_{i}"
            colecao.upsert(
                ids=[id_chunk],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"fonte": doc["fonte"], "indice": i}],
            )
            total_chunks += 1
        print(f"Indexado: {doc['fonte']} ({len(chunks)} pedaço(s))")

    print(f"\nConcluído. {total_chunks} pedaço(s) de texto indexado(s), "
          f"a partir de {len(documentos)} arquivo(s).")


if __name__ == "__main__":
    indexar_materiais()
