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
    "origem_justificativa": "TEXT",  # "LLM" ou "fallback"; NULL nas trilhas antigas
    "concluida": "INTEGER",  # etapa já concluída no replanejamento incremental; NULL = não
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


# Colunas acrescentadas à auditoria: o motivo de cada decisão (orquestração) e
# quem agiu (1.4.6): id e papel do usuário logado; "sistema" fora de uma requisição
# (comandos, agendador) e "sem_login" no modo de desenvolvimento (TIA_AUTH=desligada).
COLUNAS_NOVAS_AUDITORIA = {
    "motivo": "TEXT",
    "usuario_id": "TEXT",
    "usuario_papel": "TEXT",
}

# Segurança, etapa 2 (1.4.6): senha temporária (troca obrigatória no primeiro
# acesso) e último uso da sessão (expiração por inatividade)
COLUNAS_NOVAS_USUARIOS = {"trocar_senha": "INTEGER NOT NULL DEFAULT 0"}
COLUNAS_NOVAS_SESSOES = {"ultimo_uso": "DATETIME"}


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
    # pausada: sessão suspensa pelo orquestrador durante um reforço (R2); guarda
    # nível e itens e é retomada de onde parou. NULL/0 = não pausada.
    _acrescentar_colunas(cursor, "tutor_sessoes", {"pausada": "INTEGER"})

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

    # Feedback de cada resposta do questionário (R12): o texto que o aluno viu,
    # para o docente revisar e vetar como no diálogo. Uma linha por resposta
    # (resposta_id = historico_respostas.id); respostas anteriores a esta tabela
    # não têm linha. É texto gerado pelo sistema, mas fica SÓ aqui (como o
    # diálogo): o Agente 3 lê apenas "vetada", nunca o texto (R08).
    # explicacao_descartada/motivo_descarte: texto do LLM barrado pela guarda
    # (origem "guarda"), que o aluno não viu; só para a revisão docente.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutor_feedbacks (
            resposta_id INTEGER PRIMARY KEY,
            aluno_id TEXT,
            sessao_id TEXT,
            item_id TEXT,
            competencia_id TEXT,
            ts DATETIME,
            veredito TEXT,
            explicacao TEXT,
            origem TEXT,
            falha_llm TEXT,
            fontes TEXT,
            explicacao_descartada TEXT,
            motivo_descarte TEXT,
            vetada INTEGER NOT NULL DEFAULT 0,
            correcao_docente TEXT,
            FOREIGN KEY (resposta_id) REFERENCES historico_respostas(id),
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedbacks_aluno ON tutor_feedbacks (aluno_id, ts)")

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
    _acrescentar_colunas(cursor, "auditoria", COLUNAS_NOVAS_AUDITORIA)

    # Orquestração (EAP 1.3.5). Matrícula no fluxo: guarda o que o Planejador
    # precisa para REPLANEJAR (perfil, horas e diagnóstico, que o Planejador não
    # grava). O diagnóstico é atualizado a cada replanejamento.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orquestrador_matriculas (
            aluno_id TEXT PRIMARY KEY,
            perfil_id TEXT,
            horas_semanais REAL,
            diagnostico TEXT,
            criado_em DATETIME,
            atualizado_em DATETIME,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)
    # Eventos recebidos (idempotência): o mesmo evento_id devolve o resultado
    # gravado, sem processar de novo.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orquestrador_eventos (
            evento_id TEXT PRIMARY KEY,
            aluno_id TEXT,
            tipo TEXT,
            recebido_em DATETIME,
            resultado TEXT,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)
    # Decisões do orquestrador (planejar, replanejar ou nada), com regra e motivo;
    # cada uma também vai para a auditoria.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orquestrador_decisoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id TEXT,
            ts DATETIME,
            regra TEXT,
            acao TEXT,
            competencia_id TEXT,
            motivo TEXT,
            replanejou INTEGER,
            evento_id TEXT,
            sessao_id TEXT,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)
    _acrescentar_colunas(cursor, "orquestrador_decisoes", {
        "sessao_id": "TEXT",
        # quando o Planejador foi acionado: origem das justificativas ("LLM",
        # "parcial" ou "fallback"), motivo da falha ("timeout"...) e tempo gasto
        "origem_justificativas": "TEXT",
        "falha_llm": "TEXT",
        "tempo_planejador_ms": "INTEGER",
        "aviso": "TEXT",  # mensagem ao aluno (conclusão, reforço, retomada, incentivo)
    })
    # Reforço por queda (R2): a sessão original fica pausada enquanto o aluno faz
    # uma sessão do pré-requisito direto; ao concluí-la, a original é retomada.
    # estado: pendente (sessão de reforço ainda não aberta), em_andamento, concluido.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orquestrador_reforcos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id TEXT,
            competencia_original TEXT,
            sessao_original_id TEXT,
            competencia_reforco TEXT,
            sessao_reforco_id TEXT,
            estado TEXT,
            decisao_id INTEGER,
            criado_em DATETIME,
            concluido_em DATETIME,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    # Segurança (EAP 1.4.6). Usuários: id é um código de login (nunca nome, R08);
    # aluno_id liga o papel "aluno" aos dados dele. A senha fica só como hash
    # scrypt com sal (seguranca.senhas), nunca em texto.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            papel TEXT NOT NULL,
            aluno_id TEXT,
            senha_hash TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em DATETIME,
            atualizado_em DATETIME
        )
    """)
    _acrescentar_colunas(cursor, "usuarios", COLUNAS_NOVAS_USUARIOS)
    # Sessões no servidor: o cookie leva um token aleatório; aqui fica só o
    # SHA-256 dele, com o token anti-CSRF, a expiração absoluta e o último uso.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessoes (
            token_hash TEXT PRIMARY KEY,
            usuario_id TEXT NOT NULL,
            csrf TEXT NOT NULL,
            criada_em DATETIME,
            expira_em DATETIME,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    """)
    _acrescentar_colunas(cursor, "auth_sessoes", COLUNAS_NOVAS_SESSOES)
    # Tentativas de login (limite por usuário e por IP). Sem senha.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_tentativas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME,
            login TEXT,
            ip TEXT,
            sucesso INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tentativas ON auth_tentativas (ts)")
    # Pedidos sem login (401) e logins bloqueados, contados por origem (IP),
    # janela de tempo e tipo: só o primeiro de cada janela vai para a auditoria
    # (seguranca.anonimos). O IP fica só aqui, apagado após AUTH_RETENCAO_IP_DIAS.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_anonimos (
            ip TEXT NOT NULL,
            janela DATETIME NOT NULL,
            tipo TEXT NOT NULL,
            pedidos INTEGER NOT NULL,
            registrado INTEGER NOT NULL DEFAULT 0,
            resumido INTEGER NOT NULL DEFAULT 0,
            primeiro_ts DATETIME,
            ultimo_ts DATETIME,
            PRIMARY KEY (ip, janela, tipo)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_anonimos_janela ON auth_anonimos (janela, tipo)")

    conexao.commit()
    conexao.close()
    print(f"Tabelas criadas/confirmadas em: {DB_PATH}")


if __name__ == "__main__":
    criar_tabelas()
