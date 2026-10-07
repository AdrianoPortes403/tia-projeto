"""
Camada de banco de dados do Sistema TIA (pacote 1.4.1 / infraestrutura).

Usa SQLite puro (módulo sqlite3 nativo do Python), sem ORM — decisão
consciente para manter simplicidade, já que o time é iniciante e o
volume de dados do piloto é pequeno (30 alunos).

Como rodar (cria/confirma as tabelas):
    python -m tia.core.database

Pré-requisitos:
    - nenhum além do Python; o caminho do arquivo vem de DB_PATH (tia.core.config).
"""

import os
import sqlite3

from tia.core.config import DB_PATH


def obter_conexao() -> sqlite3.Connection:
    """Abre (ou cria, se não existir) o arquivo do banco de dados."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conexao = sqlite3.connect(DB_PATH)
    conexao.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
    return conexao


# Colunas acrescentadas à trilha_estudo pelo Agente 1 (Planejador).
# Migração só por ADD COLUMN: linhas antigas são preservadas (ficam com NULL).
COLUNAS_NOVAS_TRILHA = {
    "ordem": "INTEGER",
    "competencia_id": "TEXT",
    "perfil_id": "TEXT",
    "materiais": "TEXT",  # lista de nomes de arquivo, em JSON
    "justificativa": "TEXT",
    "criado_em": "DATETIME",
}


def _migrar_trilha_estudo(cursor: sqlite3.Cursor):
    """Acrescenta à trilha_estudo as colunas que ainda não existem."""
    existentes = {linha[1] for linha in cursor.execute("PRAGMA table_info(trilha_estudo)")}
    for nome, tipo in COLUNAS_NOVAS_TRILHA.items():
        if nome not in existentes:
            cursor.execute(f"ALTER TABLE trilha_estudo ADD COLUMN {nome} {tipo}")


def criar_tabelas():
    """Cria as tabelas do projeto, caso ainda não existam.
    Seguro rodar múltiplas vezes (usa IF NOT EXISTS)."""
    conexao = obter_conexao()
    cursor = conexao.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos (
            id TEXT PRIMARY KEY,
            conhecimento_previo TEXT,
            horas_semana_disponiveis INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trilha_estudo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id TEXT,
            semana INTEGER,
            topico TEXT,
            horas_previstas INTEGER,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    _migrar_trilha_estudo(cursor)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id TEXT,
            topico TEXT,
            dificuldade TEXT,
            acertou BOOLEAN,
            timestamp DATETIME,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    conexao.commit()
    conexao.close()
    print(f"Tabelas criadas/confirmadas em: {DB_PATH}")


if __name__ == "__main__":
    criar_tabelas()
