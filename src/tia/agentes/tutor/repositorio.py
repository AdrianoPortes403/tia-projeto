"""
Persistência do Agente 2 (Tutor): leitura do banco de itens e da ementa,
estado das sessões (tabela tutor_sessoes) e histórico de respostas
(tabela historico_respostas).

Nada fica em memória entre requisições: cada pedido lê o estado do SQLite
e grava o novo. A gravação da resposta é atômica e só acontece se a sessão
ainda estiver no mesmo item, para que a mesma resposta enviada duas vezes
não seja corrigida contra a pergunta seguinte. As tabelas guardam só
aluno_id (código), nunca dado pessoal (R08).

Não é executável sozinho; usado pela API e pela demonstração:
    python -m tia.agentes.tutor

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - conteudo/banco_itens/itens.json (BANCO_ITENS_PATH; PROVISÓRIO até a entrega da Pessoa 4)
"""

import json
import uuid
from datetime import datetime

from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.tutor.adaptativo import EstadoSessao
from tia.core.config import BANCO_ITENS_PATH
from tia.core.database import obter_conexao

# rótulo gravado na coluna antiga "dificuldade", ao lado do novo "nivel"
DIFICULDADE_POR_NIVEL = {1: "facil", 2: "medio", 3: "dificil"}


def carregar_itens(caminho: str = BANCO_ITENS_PATH) -> list[dict]:
    """Lê todos os itens do banco de questões."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["itens"]


def materiais_da_competencia(competencia_id: str) -> list[str] | None:
    """Arquivos de material da competência na ementa; None se ela não existe."""
    for competencia in carregar_ementa():
        if competencia["id"] == competencia_id:
            return competencia.get("materiais", [])
    return None


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def criar_sessao(aluno_id: str, estado: EstadoSessao) -> str:
    """Grava uma sessão nova e devolve o seu id."""
    sessao_id = uuid.uuid4().hex
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("INSERT OR IGNORE INTO alunos (id) VALUES (?)", (aluno_id,))
            conexao.execute(
                """INSERT INTO tutor_sessoes
                   (id, aluno_id, competencia_id, nivel, item_atual_id, itens_usados,
                    acertos_seguidos_nivel_max, concluida, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sessao_id, aluno_id, estado.competencia_id, estado.nivel, estado.item_atual_id,
                 json.dumps(list(estado.itens_usados)), estado.acertos_seguidos_nivel_max,
                 estado.concluida, agora, agora),
            )
    finally:
        conexao.close()
    return sessao_id


def ler_sessao(sessao_id: str, aluno_id: str) -> EstadoSessao | None:
    """Estado da sessão; None se não existir ou for de outro aluno."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            "SELECT * FROM tutor_sessoes WHERE id = ? AND aluno_id = ?", (sessao_id, aluno_id),
        ).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return None
    return EstadoSessao(
        competencia_id=linha["competencia_id"],
        nivel=linha["nivel"],
        item_atual_id=linha["item_atual_id"],
        itens_usados=tuple(json.loads(linha["itens_usados"] or "[]")),
        acertos_seguidos_nivel_max=linha["acertos_seguidos_nivel_max"],
        concluida=bool(linha["concluida"]),
    )


def registrar_resposta(sessao_id: str, aluno_id: str, item_respondido: dict, novo_estado: EstadoSessao,
                       acertou: bool, fontes: list[str], tempo_ms: int) -> bool:
    """Atualiza a sessão e grava a resposta no histórico, numa transação.
    Devolve False (sem gravar nada) se a sessão já saiu deste item."""
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """UPDATE tutor_sessoes
                   SET nivel = ?, item_atual_id = ?, itens_usados = ?,
                       acertos_seguidos_nivel_max = ?, concluida = ?, atualizado_em = ?
                   WHERE id = ? AND aluno_id = ? AND item_atual_id = ? AND NOT concluida""",
                (novo_estado.nivel, novo_estado.item_atual_id, json.dumps(list(novo_estado.itens_usados)),
                 novo_estado.acertos_seguidos_nivel_max, novo_estado.concluida, agora,
                 sessao_id, aluno_id, item_respondido["id"]),
            )
            if cursor.rowcount != 1:
                return False
            nivel = item_respondido["nivel"]
            conexao.execute(
                """INSERT INTO historico_respostas
                   (aluno_id, topico, dificuldade, acertou, timestamp, nivel, fontes, tempo_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, item_respondido["competencia_id"], DIFICULDADE_POR_NIVEL.get(nivel), acertou,
                 agora, nivel, json.dumps(fontes, ensure_ascii=False), tempo_ms),
            )
    finally:
        conexao.close()
    return True
