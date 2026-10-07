"""
Configuração central do Sistema TIA.

Toda configuração do projeto vem daqui, lida de variáveis de ambiente
(arquivo .env na raiz, carregado com python-dotenv) com valor padrão.
Os demais módulos importam as constantes deste arquivo; nenhum outro
lugar deve chamar os.getenv.

Como conferir os valores em uso:
    python -m tia.core.config

Pré-requisitos:
    - .env na raiz (copiar de .env.example); sem ele, valem os padrões abaixo.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- LLM local (Ollama) — requisito R07: nunca API externa ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen3:1.7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# --- Banco de dados (SQLite) ---
DB_PATH = os.getenv("DB_PATH", "data/tia.db")

# --- RAG ---
# Pasta com os arquivos .txt do material do curso
MATERIAIS_DIR = os.getenv("MATERIAIS_DIR", "conteudo/materiais")
# Pasta onde o Chroma guarda o índice vetorial (persistente entre execuções)
CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma_db")
# Nome da "coleção" dentro do Chroma (como uma tabela, dentro do banco vetorial)
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "material_curso")
# Tamanho de cada pedaço (chunk) de texto indexado, em caracteres
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
# Sobreposição entre pedaços consecutivos, para não cortar uma ideia ao meio
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# --- Agente 1 (Planejador) ---
# Arquivos de conteúdo pedagógico (PROVISÓRIOS até a entrega da Pessoa 4)
EMENTA_PATH = os.getenv("EMENTA_PATH", "conteudo/ementa/ementa.json")
PERFIS_PATH = os.getenv("PERFIS_PATH", "conteudo/perfis/perfis.json")
# Tempo máximo (s) para o LLM escrever as justificativas; abaixo do limite de 15 s do R09
PLANEJADOR_TIMEOUT_LLM = int(os.getenv("PLANEJADOR_TIMEOUT_LLM", "12"))


if __name__ == "__main__":
    for nome in ("OLLAMA_URL", "CHAT_MODEL", "EMBED_MODEL", "DB_PATH",
                 "MATERIAIS_DIR", "CHROMA_DIR", "COLLECTION_NAME",
                 "CHUNK_SIZE", "CHUNK_OVERLAP", "EMENTA_PATH", "PERFIS_PATH",
                 "PLANEJADOR_TIMEOUT_LLM"):
        print(f"{nome} = {globals()[nome]}")
