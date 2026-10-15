"""
Persistência da Orquestração: matrícula no fluxo (orquestrador_matriculas),
eventos recebidos para idempotência (orquestrador_eventos), decisões
(orquestrador_decisoes) e reforços por queda (orquestrador_reforcos). Cada decisão grava, na MESMA transação, uma linha
de auditoria (tipo "decisao_orquestrador", com o motivo; R11).

Os dados dos agentes (trilha, sessões, respostas) não são lidos aqui: o
fluxo usa os repositórios e as interfaces públicas de cada agente.

Não é executável sozinho; usado pelo fluxo e pela API.

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
from datetime import datetime

from tia.core import auditoria
from tia.core.database import obter_conexao


def _texto(agora: datetime) -> str:
    return agora.isoformat(timespec="seconds")


# --- matrícula ---

def salvar_matricula(aluno_id: str, perfil_id: str, horas_semanais: float, diagnostico: dict[str, float],
                     agora: datetime, trilha: str | None = None, prazo_dias: int | None = None,
                     escopo: str = "completa") -> bool:
    """Grava a matrícula; False se o aluno já está matriculado (nada muda).
    perfil_id é o perfil em uso (o enquadrado pelo Planejador, se não informado)."""
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """INSERT OR IGNORE INTO orquestrador_matriculas
                   (aluno_id, perfil_id, horas_semanais, diagnostico, criado_em, atualizado_em,
                    trilha, prazo_dias, escopo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, perfil_id, horas_semanais, json.dumps(diagnostico), _texto(agora), _texto(agora),
                 trilha, prazo_dias, escopo))
    finally:
        conexao.close()
    return cursor.rowcount == 1


def ler_matricula(aluno_id: str) -> dict | None:
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT * FROM orquestrador_matriculas WHERE aluno_id = ?", (aluno_id,)).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return None
    return {"aluno_id": aluno_id, "perfil_id": linha["perfil_id"], "horas_semanais": linha["horas_semanais"],
            "diagnostico": json.loads(linha["diagnostico"] or "{}"), "trilha": linha["trilha"],
            "prazo_dias": linha["prazo_dias"], "escopo": linha["escopo"] or "completa",
            "criado_em": linha["criado_em"]}


def listar_matriculas() -> list[str]:
    """Códigos dos alunos matriculados no fluxo (para a verificação de inatividade)."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute("SELECT aluno_id FROM orquestrador_matriculas ORDER BY aluno_id").fetchall()
    finally:
        conexao.close()
    return [linha["aluno_id"] for linha in linhas]


# --- eventos (idempotência) ---

def reservar_evento(evento_id: str, aluno_id: str, tipo: str, agora: datetime) -> dict | None:
    """Reserva o evento_id. None: evento novo (processar). Senão, o registro
    existente: aluno_id, tipo e resultado (None enquanto em processamento)."""
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """INSERT OR IGNORE INTO orquestrador_eventos (evento_id, aluno_id, tipo, recebido_em)
                   VALUES (?, ?, ?, ?)""", (evento_id, aluno_id, tipo, _texto(agora)))
            if cursor.rowcount == 1:
                return None
            linha = conexao.execute("SELECT * FROM orquestrador_eventos WHERE evento_id = ?", (evento_id,)).fetchone()
    finally:
        conexao.close()
    return {"aluno_id": linha["aluno_id"], "tipo": linha["tipo"],
            "resultado": json.loads(linha["resultado"]) if linha["resultado"] else None}


def concluir_evento(evento_id: str, resultado: dict):
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("UPDATE orquestrador_eventos SET resultado = ? WHERE evento_id = ?",
                            (json.dumps(resultado, ensure_ascii=False), evento_id))
    finally:
        conexao.close()


def cancelar_evento(evento_id: str):
    """Libera a reserva de um evento que falhou (pode ser reenviado)."""
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("DELETE FROM orquestrador_eventos WHERE evento_id = ? AND resultado IS NULL", (evento_id,))
    finally:
        conexao.close()


# --- decisões ---

def _decisao(linha) -> dict:
    return {"decisao_id": linha["id"], "ts": linha["ts"], "regra": linha["regra"], "acao": linha["acao"],
            "competencia_id": linha["competencia_id"], "motivo": linha["motivo"],
            "replanejou": bool(linha["replanejou"]), "sessao_id": linha["sessao_id"],
            "origem_justificativas": linha["origem_justificativas"], "falha_llm": linha["falha_llm"],
            "tempo_planejador_ms": linha["tempo_planejador_ms"], "aviso": linha["aviso"]}


def registrar_decisao(aluno_id: str, regra: str, acao: str, competencia_id: str | None, motivo: str,
                      replanejou: bool, evento_id: str | None, agora: datetime, sessao_id: str | None = None,
                      planejador: dict | None = None, aviso: str | None = None) -> dict:
    """Grava a decisão e a auditoria (R11, com o motivo) numa transação.
    planejador: origem_justificativas, falha_llm e tempo_planejador_ms, se acionado.
    aviso: mensagem mostrada ao aluno."""
    planejador = planejador or {}
    ts = _texto(agora)
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """INSERT INTO orquestrador_decisoes
                   (aluno_id, ts, regra, acao, competencia_id, motivo, replanejou, evento_id, sessao_id,
                    origem_justificativas, falha_llm, tempo_planejador_ms, aviso)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, ts, regra, acao, competencia_id, motivo, replanejou, evento_id, sessao_id,
                 planejador.get("origem_justificativas"), planejador.get("falha_llm"),
                 planejador.get("tempo_planejador_ms"), aviso))
            auditoria.registrar(conexao, aluno_id, "decisao_orquestrador", cursor.lastrowid, acao, [], ts=ts,
                                motivo=f"[{regra}] {motivo}")
            linha = conexao.execute("SELECT * FROM orquestrador_decisoes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    finally:
        conexao.close()
    return _decisao(linha)


def listar_decisoes(aluno_id: str, acao: str | None = None) -> list[dict]:
    """Decisões do aluno, da mais antiga para a mais recente (só de uma ação, se informada)."""
    sql = "SELECT * FROM orquestrador_decisoes WHERE aluno_id = ?"
    parametros: tuple = (aluno_id,)
    if acao is not None:
        sql += " AND acao = ?"
        parametros += (acao,)
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(sql + " ORDER BY ts, id", parametros).fetchall()
    finally:
        conexao.close()
    return [_decisao(linha) for linha in linhas]


# --- reforços por queda (R2) ---

def _reforco(linha) -> dict:
    return {campo: linha[campo] for campo in ("id", "aluno_id", "competencia_original", "sessao_original_id",
                                              "competencia_reforco", "sessao_reforco_id", "estado", "decisao_id")}


def criar_reforco(aluno_id: str, competencia_original: str, sessao_original_id: str, competencia_reforco: str,
                  decisao_id: int, agora: datetime) -> int:
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """INSERT INTO orquestrador_reforcos (aluno_id, competencia_original, sessao_original_id,
                       competencia_reforco, estado, decisao_id, criado_em)
                   VALUES (?, ?, ?, ?, 'pendente', ?, ?)""",
                (aluno_id, competencia_original, sessao_original_id, competencia_reforco, decisao_id, _texto(agora)))
    finally:
        conexao.close()
    return cursor.lastrowid


def reforco_ativo(aluno_id: str) -> dict | None:
    """Reforço pendente ou em andamento do aluno (no máximo um)."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            """SELECT * FROM orquestrador_reforcos WHERE aluno_id = ? AND estado != 'concluido'
               ORDER BY id DESC LIMIT 1""", (aluno_id,)).fetchone()
    finally:
        conexao.close()
    return _reforco(linha) if linha else None


def vincular_sessao_reforco(reforco_id: int, sessao_id: str):
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("""UPDATE orquestrador_reforcos SET sessao_reforco_id = ?, estado = 'em_andamento'
                               WHERE id = ? AND estado = 'pendente'""", (sessao_id, reforco_id))
    finally:
        conexao.close()


def concluir_reforco(reforco_id: int, agora: datetime):
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("""UPDATE orquestrador_reforcos SET estado = 'concluido', concluido_em = ?
                               WHERE id = ?""", (_texto(agora), reforco_id))
    finally:
        conexao.close()
