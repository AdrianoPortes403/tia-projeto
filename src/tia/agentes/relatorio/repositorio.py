"""
Leitura dos dados para o Agente 3 (Relatório) e auditoria dos relatórios.

Só lê o que os Agentes 1 e 2 já gravam: trilha_estudo (Planejador),
tutor_sessoes, historico_respostas, tutor_dialogo e auditoria (Tutor). Não
lê o texto livre do diálogo (pergunta/resposta): o relatório não precisa
dele (minimização, R08).

A origem (LLM/guarda/fallback) de cada resposta de item vem da auditoria
(tipo "resposta_item", referencia_id = id em historico_respostas);
respostas gravadas antes da auditoria ficam sem origem.

Não é executável sozinho; usado pelo agente, pela API e pela demonstração:
    python -m tia.agentes.relatorio --demo

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

from dataclasses import dataclass, field
from datetime import datetime

from tia.agentes.planejador.modelos import Trilha
from tia.agentes.planejador.repositorio import ler_trilha
from tia.core import auditoria
from tia.core.database import obter_conexao


@dataclass
class DadosAluno:
    aluno_id: str
    perfil_id: str | None
    trilha: Trilha | None
    trilha_criada_em: str | None
    # cada resposta: competencia_id, nivel, acertou, ts, origem (None sem auditoria),
    # item_id e sessao_id (None nas respostas gravadas antes dessas colunas) e
    # feedback_vetado (None sem texto gravado em tutor_feedbacks; o texto NÃO é lido)
    respostas: list[dict] = field(default_factory=list)
    # cada sessão: competencia_id, nivel, concluida, criado_em, atualizado_em
    sessoes: list[dict] = field(default_factory=list)
    # cada diálogo: competencia_id, origem, vetada, ts (sem texto)
    dialogos: list[dict] = field(default_factory=list)


def listar_alunos(perfil_id: str | None = None) -> list[str]:
    """Códigos dos alunos cadastrados; com perfil_id, só os com trilha desse perfil."""
    conexao = obter_conexao()
    try:
        if perfil_id is None:
            linhas = conexao.execute("SELECT id FROM alunos ORDER BY id").fetchall()
        else:
            linhas = conexao.execute(
                """SELECT DISTINCT aluno_id AS id FROM trilha_estudo
                   WHERE perfil_id = ? AND competencia_id IS NOT NULL ORDER BY aluno_id""",
                (perfil_id,),
            ).fetchall()
    finally:
        conexao.close()
    return [linha["id"] for linha in linhas]


def ler_dados_aluno(aluno_id: str) -> DadosAluno | None:
    """Tudo o que o relatório usa sobre o aluno; None se o código não existe."""
    conexao = obter_conexao()
    try:
        if conexao.execute("SELECT 1 FROM alunos WHERE id = ?", (aluno_id,)).fetchone() is None:
            return None
        trilha_info = conexao.execute(
            """SELECT MAX(criado_em) AS criado, MAX(perfil_id) AS perfil FROM trilha_estudo
               WHERE aluno_id = ? AND competencia_id IS NOT NULL""", (aluno_id,),
        ).fetchone()
        respostas = conexao.execute(
            """SELECT h.id, h.topico AS competencia_id, h.nivel, h.acertou, h.timestamp AS ts, a.origem,
                      h.item_id, h.sessao_id, f.vetada AS feedback_vetado
               FROM historico_respostas h
               LEFT JOIN auditoria a ON a.tipo = 'resposta_item' AND a.referencia_id = CAST(h.id AS TEXT)
               LEFT JOIN tutor_feedbacks f ON f.resposta_id = h.id
               WHERE h.aluno_id = ? AND h.nivel IS NOT NULL
               ORDER BY h.timestamp, h.id""", (aluno_id,),
        ).fetchall()
        sessoes = conexao.execute(
            """SELECT competencia_id, nivel, concluida, criado_em, atualizado_em FROM tutor_sessoes
               WHERE aluno_id = ? ORDER BY atualizado_em, criado_em""", (aluno_id,),
        ).fetchall()
        dialogos = conexao.execute(
            """SELECT competencia_id, origem, vetada, ts FROM tutor_dialogo
               WHERE aluno_id = ? ORDER BY ts, id""", (aluno_id,),
        ).fetchall()
    finally:
        conexao.close()
    return DadosAluno(
        aluno_id=aluno_id,
        perfil_id=trilha_info["perfil"],
        trilha=ler_trilha(aluno_id),
        trilha_criada_em=trilha_info["criado"],
        respostas=[{"competencia_id": r["competencia_id"], "nivel": r["nivel"], "acertou": bool(r["acertou"]),
                    "ts": r["ts"], "origem": r["origem"], "item_id": r["item_id"],
                    "sessao_id": r["sessao_id"],
                    "feedback_vetado": None if r["feedback_vetado"] is None else bool(r["feedback_vetado"])}
                   for r in respostas],
        sessoes=[{"competencia_id": s["competencia_id"], "nivel": s["nivel"], "concluida": bool(s["concluida"]),
                  "criado_em": s["criado_em"], "atualizado_em": s["atualizado_em"]} for s in sessoes],
        dialogos=[{"competencia_id": d["competencia_id"], "origem": d["origem"], "vetada": bool(d["vetada"]),
                   "ts": d["ts"]} for d in dialogos],
    )


def registrar_relatorio(tipo: str, aluno_id: str | None, referencia: str | None, origem: str):
    """Auditoria (R11) da geração de um relatório. No da turma, aluno_id é
    None e a referência é o perfil filtrado (ou None, instituição inteira)."""
    conexao = obter_conexao()
    try:
        with conexao:
            auditoria.registrar(conexao, aluno_id, tipo, referencia, origem, [],
                                ts=datetime.now().isoformat(timespec="seconds"))
    finally:
        conexao.close()
