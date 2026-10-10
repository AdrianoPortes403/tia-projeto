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


# Colunas acrescentadas ao historico_respostas pelo Agente 2 (Tutor), também só por ADD COLUMN.
COLUNAS_NOVAS_HISTORICO = {
    "nivel": "INTEGER",
    "fontes": "TEXT",  # lista de nomes de arquivo, em JSON
    "tempo_ms": "INTEGER",
    # item e sessão de cada resposta (usados pelo Agente 3: pontos fracos por
    # item e tendência por sessão); respostas anteriores a esta coluna ficam NULL
    "item_id": "TEXT",
    "sessao_id": "TEXT",
}


def _acrescentar_colunas(cursor: sqlite3.Cursor, tabela: str, colunas: dict[str, str]):
    """Acrescenta à tabela as colunas que ainda não existem."""
    existentes = {linha[1] for linha in cursor.execute(f"PRAGMA table_info({tabela})")}
    for nome, tipo in colunas.items():
        if nome not in existentes:
            cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


def _migrar_trilha_estudo(cursor: sqlite3.Cursor):
    """Acrescenta à trilha_estudo as colunas que ainda não existem."""
    _acrescentar_colunas(cursor, "trilha_estudo", COLUNAS_NOVAS_TRILHA)


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

    _acrescentar_colunas(cursor, "historico_respostas", COLUNAS_NOVAS_HISTORICO)

    # Estado das sessões do questionário adaptativo (Agente 2). Fica no
    # banco, e não em memória, para sobreviver a reinícios da API.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutor_sessoes (
            id TEXT PRIMARY KEY,
            aluno_id TEXT,
            competencia_id TEXT,
            nivel INTEGER,
            item_atual_id TEXT,
            itens_usados TEXT,
            acertos_seguidos_nivel_max INTEGER,
            concluida BOOLEAN,
            criado_em DATETIME,
            atualizado_em DATETIME,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    # Diálogo livre com o Tutor (parte 2b). A pergunta do aluno é texto livre:
    # fica só aqui no banco, nunca em log (R08). vetada/correcao_docente: veto
    # docente (R12); a resposta original é preservada.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutor_dialogo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id TEXT,
            ts DATETIME,
            competencia_id TEXT,
            pergunta TEXT,
            resposta TEXT,
            fontes TEXT,
            origem TEXT,
            tempo_ms INTEGER,
            vetada INTEGER NOT NULL DEFAULT 0,
            correcao_docente TEXT,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    # Auditoria (R11): uma linha por interação do Tutor (resposta de item,
    # diálogo, incentivo). Sem texto livre: só o tipo, a referência à linha
    # da tabela de origem, a origem da resposta e as fontes citadas.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME,
            aluno_id TEXT,
            tipo TEXT,
            referencia_id TEXT,
            origem TEXT,
            fontes TEXT,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auditoria_aluno ON auditoria (aluno_id, ts)")

    conexao.commit()
    conexao.close()
    print(f"Tabelas criadas/confirmadas em: {DB_PATH}")


if __name__ == "__main__":
    criar_tabelas()
