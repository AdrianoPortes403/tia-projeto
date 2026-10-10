"""
Trilha de auditoria das interações do Tutor (requisito R11).

Cada interação (resposta de item, pergunta do diálogo, incentivo) e cada
relatório gerado (Agente 3) grava uma linha na tabela auditoria: quando,
qual aluno (código, nunca nome; R08; vazio no relatório da turma),
tipo, referência à linha da tabela de origem, origem da resposta (LLM,
guarda, fallback, template) e fontes citadas. Não guarda texto livre do
aluno: ele fica só na tabela de origem (ex.: tutor_dialogo).

registrar() recebe a conexão aberta, para gravar na MESMA transação da
interação: ou grava as duas linhas, ou nenhuma.

Não é executável sozinho; consulta pela API:
    GET /auditoria/{aluno_id}

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
import sqlite3
from datetime import datetime

from tia.core.database import obter_conexao

# tipos de interação registrados
TIPOS = ("resposta_item", "dialogo", "incentivo", "relatorio_aluno", "relatorio_turma")


def registrar(conexao: sqlite3.Connection, aluno_id: str | None, tipo: str, referencia_id: str | int | None,
              origem: str, fontes: list[str], ts: str | None = None):
    """Grava uma linha de auditoria (dentro da transação de quem chama)."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de auditoria inválido: {tipo!r}.")
    conexao.execute(
        """INSERT INTO auditoria (ts, aluno_id, tipo, referencia_id, origem, fontes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ts or datetime.now().isoformat(timespec="seconds"), aluno_id, tipo,
         None if referencia_id is None else str(referencia_id), origem,
         json.dumps(fontes, ensure_ascii=False)),
    )


def listar(aluno_id: str) -> list[dict]:
    """Interações do aluno, da mais antiga para a mais recente."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT * FROM auditoria WHERE aluno_id = ? ORDER BY ts, id", (aluno_id,),
        ).fetchall()
    finally:
        conexao.close()
    return [{"id": linha["id"], "ts": linha["ts"], "tipo": linha["tipo"],
             "referencia_id": linha["referencia_id"], "origem": linha["origem"],
             "fontes": json.loads(linha["fontes"] or "[]")} for linha in linhas]
