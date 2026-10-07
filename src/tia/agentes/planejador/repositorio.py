"""
Persistência da trilha do Agente 1 (Planejador) na tabela trilha_estudo.

Cada etapa vira uma linha. Gerar uma nova trilha para o mesmo aluno
substitui a anterior (numa única transação). A tabela só guarda aluno_id
(código), nunca dado pessoal (R08).

Não é executável sozinho; usado pela API e pela demonstração:
    python -m tia.agentes.planejador

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
from datetime import datetime

from tia.agentes.planejador.modelos import EtapaTrilha, Trilha
from tia.core.database import obter_conexao


def salvar_trilha(trilha: Trilha, horas_semanais: float):
    """Grava a trilha (substituindo a anterior do aluno) e registra o aluno
    na tabela alunos, se ainda não existir."""
    agora = datetime.now().isoformat(timespec="seconds")
    conexao = obter_conexao()
    try:
        with conexao:  # commit no fim, rollback se der erro
            conexao.execute(
                """INSERT INTO alunos (id, conhecimento_previo, horas_semana_disponiveis)
                   VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       conhecimento_previo = excluded.conhecimento_previo,
                       horas_semana_disponiveis = excluded.horas_semana_disponiveis""",
                (trilha.aluno_id, trilha.perfil_id, horas_semanais),
            )
            conexao.execute("DELETE FROM trilha_estudo WHERE aluno_id = ?", (trilha.aluno_id,))
            conexao.executemany(
                """INSERT INTO trilha_estudo
                   (aluno_id, semana, topico, horas_previstas, ordem, competencia_id,
                    perfil_id, materiais, justificativa, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (trilha.aluno_id, e.semana_inicio, e.nome, e.horas, e.ordem, e.competencia_id,
                     trilha.perfil_id, json.dumps(e.materiais, ensure_ascii=False), e.justificativa, agora)
                    for e in trilha.etapas
                ],
            )
    finally:
        conexao.close()


def ler_trilha(aluno_id: str) -> Trilha | None:
    """Lê a trilha gerada pelo Planejador para o aluno; None se não houver.
    Linhas antigas (sem competencia_id, de antes desta versão) são ignoradas."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            """SELECT * FROM trilha_estudo
               WHERE aluno_id = ? AND competencia_id IS NOT NULL
               ORDER BY ordem""",
            (aluno_id,),
        ).fetchall()
    finally:
        conexao.close()
    if not linhas:
        return None
    etapas = [
        EtapaTrilha(
            ordem=linha["ordem"],
            competencia_id=linha["competencia_id"],
            nome=linha["topico"],
            materiais=json.loads(linha["materiais"] or "[]"),
            horas=linha["horas_previstas"],
            semana_inicio=linha["semana"],
            justificativa=linha["justificativa"] or "",
        )
        for linha in linhas
    ]
    return Trilha(aluno_id=aluno_id, perfil_id=linhas[0]["perfil_id"], etapas=etapas)
