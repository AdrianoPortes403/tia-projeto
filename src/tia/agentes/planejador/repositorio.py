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

from tia.agentes.planejador.modelos import EtapaTrilha, OpcoesPrazo, Trilha
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
            opcoes = trilha.opcoes_prazo.model_dump_json() if trilha.opcoes_prazo else None
            avisos = json.dumps(trilha.avisos, ensure_ascii=False)
            conexao.executemany(
                """INSERT INTO trilha_estudo
                   (aluno_id, semana, topico, horas_previstas, ordem, competencia_id,
                    perfil_id, materiais, justificativa, criado_em, origem_justificativa, concluida,
                    revisar_antes, nivel_inicial, desafio_pratico, trilha, pontuacao_enquadramento,
                    perfil_automatico, prazo_dias, cabe_no_prazo, opcoes_prazo, avisos)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (trilha.aluno_id, e.semana_inicio, e.nome, e.horas, e.ordem, e.competencia_id,
                     trilha.perfil_id, json.dumps(e.materiais, ensure_ascii=False), e.justificativa, agora,
                     e.origem_justificativa, e.concluida,
                     json.dumps(e.revisar_antes), e.nivel_inicial, e.desafio_pratico, trilha.trilha,
                     trilha.pontuacao_enquadramento, trilha.perfil_automatico, trilha.prazo_dias,
                     trilha.cabe_no_prazo, opcoes, avisos)
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
            origem_justificativa=linha["origem_justificativa"],
            concluida=bool(linha["concluida"]),
            revisar_antes=json.loads(linha["revisar_antes"] or "[]"),
            nivel_inicial=linha["nivel_inicial"],
            desafio_pratico=linha["desafio_pratico"],
        )
        for linha in linhas
    ]
    primeira = linhas[0]
    cabe = primeira["cabe_no_prazo"]
    return Trilha(aluno_id=aluno_id, perfil_id=primeira["perfil_id"], etapas=etapas, trilha=primeira["trilha"],
                  pontuacao_enquadramento=primeira["pontuacao_enquadramento"],
                  perfil_automatico=bool(primeira["perfil_automatico"]), prazo_dias=primeira["prazo_dias"],
                  cabe_no_prazo=None if cabe is None else bool(cabe),
                  opcoes_prazo=OpcoesPrazo.model_validate_json(primeira["opcoes_prazo"])
                  if primeira["opcoes_prazo"] else None,
                  avisos=json.loads(primeira["avisos"] or "[]"))
