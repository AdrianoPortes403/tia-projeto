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
    GET /painel/auditoria?agente=&aluno_id=&desde=&ate=&pagina=  (painel do docente, 1.4.5)

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

import json
import sqlite3
from contextvars import ContextVar
from datetime import datetime

from tia.core.database import obter_conexao

# tipos de interação registrados. veto_docente: veto ou retirada do veto (R12);
# consulta_painel: consulta do docente que mostra códigos de aluno (painel 1.4.5);
# segurança (1.4.6): login, login_falha, login_bloqueado, logout, acesso_negado
# (401/403) e gestao_usuario (criar, desativar, redefinir senha; nunca a senha)
TIPOS = ("resposta_item", "dialogo", "incentivo", "relatorio_aluno", "relatorio_turma", "decisao_orquestrador",
         "veto_docente", "consulta_painel", "login", "login_falha", "login_bloqueado", "logout", "acesso_negado",
         "gestao_usuario")

# Quem está agindo (1.4.6): (usuario_id, papel), definido por requisição pela
# segurança (seguranca.acesso). Sem valor (comandos, agendador, testes de
# repositório): ninguém logado, papel "sistema".
USUARIO_ATUAL: ContextVar[tuple[str | None, str] | None] = ContextVar("usuario_atual", default=None)


def definir_usuario(usuario_id: str | None, papel: str):
    """Usuário da requisição atual, gravado em toda linha de auditoria dela."""
    USUARIO_ATUAL.set((usuario_id, papel))


def registrar(conexao: sqlite3.Connection, aluno_id: str | None, tipo: str, referencia_id: str | int | None,
              origem: str, fontes: list[str], ts: str | None = None, motivo: str | None = None) -> int:
    """Grava uma linha de auditoria (dentro da transação de quem chama) e
    devolve o id. motivo: por que a decisão foi tomada (decisões do orquestrador).
    O usuário (id e papel) vem de USUARIO_ATUAL."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de auditoria inválido: {tipo!r}.")
    usuario_id, papel = USUARIO_ATUAL.get() or (None, "sistema")
    cursor = conexao.execute(
        """INSERT INTO auditoria (ts, aluno_id, tipo, referencia_id, origem, fontes, motivo, usuario_id, usuario_papel)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ts or datetime.now().isoformat(timespec="seconds"), aluno_id, tipo,
         None if referencia_id is None else str(referencia_id), origem,
         json.dumps(fontes, ensure_ascii=False), motivo, usuario_id, papel),
    )
    return cursor.lastrowid


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
             "fontes": json.loads(linha["fontes"] or "[]"), "motivo": linha["motivo"],
             "usuario_id": linha["usuario_id"], "usuario_papel": linha["usuario_papel"]} for linha in linhas]


# agente responsável por cada tipo; as decisões do orquestrador que acionaram
# o Planejador (replanejou) contam também como "planejador"
AGENTE_POR_TIPO = {
    "resposta_item": "tutor", "dialogo": "tutor", "incentivo": "tutor", "veto_docente": "tutor",
    "relatorio_aluno": "relatorio", "relatorio_turma": "relatorio",
    "decisao_orquestrador": "orquestrador", "consulta_painel": "painel",
    "login": "seguranca", "login_falha": "seguranca", "login_bloqueado": "seguranca", "logout": "seguranca",
    "acesso_negado": "seguranca", "gestao_usuario": "seguranca",
}
AGENTES = ("orquestrador", "planejador", "tutor", "relatorio", "painel", "seguranca")


def consultar(agente: str | None = None, aluno_id: str | None = None, desde: str | None = None,
              ate: str | None = None, pagina: int = 1, por_pagina: int = 50) -> tuple[int, list[dict]]:
    """Registros filtrados, do mais recente para o mais antigo, paginados.
    desde/ate: datas "AAAA-MM-DD" (inclusivas). Devolve (total, página)."""
    condicoes, parametros = [], []
    if agente == "planejador":
        condicoes.append("a.tipo = 'decisao_orquestrador' AND d.replanejou")
    elif agente is not None:
        tipos = [t for t, a in AGENTE_POR_TIPO.items() if a == agente]
        condicoes.append(f"a.tipo IN ({', '.join('?' * len(tipos))})")
        parametros += tipos
    if aluno_id is not None:
        condicoes.append("a.aluno_id = ?")
        parametros.append(aluno_id)
    if desde is not None:
        condicoes.append("a.ts >= ?")
        parametros.append(desde)
    if ate is not None:
        condicoes.append("a.ts < ?")
        parametros.append(ate + "T99")  # o dia inteiro: "AAAA-MM-DDT..." < "AAAA-MM-DDT99"
    onde = (" WHERE " + " AND ".join(condicoes)) if condicoes else ""
    juncao = """FROM auditoria a LEFT JOIN orquestrador_decisoes d
                ON a.tipo = 'decisao_orquestrador' AND a.referencia_id = CAST(d.id AS TEXT)"""
    conexao = obter_conexao()
    try:
        total = conexao.execute(f"SELECT COUNT(*) {juncao}{onde}", parametros).fetchone()[0]
        linhas = conexao.execute(
            f"""SELECT a.*, d.replanejou, d.regra, d.origem_justificativas {juncao}{onde}
                ORDER BY a.ts DESC, a.id DESC LIMIT ? OFFSET ?""",
            parametros + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    finally:
        conexao.close()
    registros = []
    for linha in linhas:
        agentes = [AGENTE_POR_TIPO.get(linha["tipo"], "outro")]
        if linha["replanejou"]:
            agentes.append("planejador")
        registros.append({"id": linha["id"], "ts": linha["ts"], "aluno_id": linha["aluno_id"], "agentes": agentes,
                          "tipo": linha["tipo"], "referencia_id": linha["referencia_id"], "origem": linha["origem"],
                          "fontes": json.loads(linha["fontes"] or "[]"), "motivo": linha["motivo"],
                          "origem_justificativas": linha["origem_justificativas"],
                          "usuario_id": linha["usuario_id"], "usuario_papel": linha["usuario_papel"]})
    return total, registros
