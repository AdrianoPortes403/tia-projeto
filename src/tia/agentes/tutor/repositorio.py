"""
Persistência do Agente 2 (Tutor): leitura do banco de itens e da ementa,
estado das sessões (tabela tutor_sessoes), histórico de respostas
(tabela historico_respostas) e diálogo livre (tabela tutor_dialogo).
Toda interação grava também a auditoria (R11), na mesma transação.

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
from tia.core import auditoria
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


def palavras_chave(competencia_id: str | None) -> list[list[str]]:
    """Grupos de sinônimos (campo opcional "palavras_chave" da ementa,
    PROVISÓRIO) da competência; com None, os de todas as competências."""
    grupos = []
    for competencia in carregar_ementa():
        if competencia_id is None or competencia["id"] == competencia_id:
            grupos += competencia.get("palavras_chave", [])
    return grupos


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
                       acertou: bool, fontes: list[str], tempo_ms: int, origem: str) -> bool:
    """Atualiza a sessão, grava a resposta no histórico e a auditoria (R11),
    numa transação. Devolve False (sem gravar nada) se a sessão já saiu deste item."""
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
            cursor = conexao.execute(
                """INSERT INTO historico_respostas
                   (aluno_id, topico, dificuldade, acertou, timestamp, nivel, fontes, tempo_ms, item_id, sessao_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, item_respondido["competencia_id"], DIFICULDADE_POR_NIVEL.get(nivel), acertou,
                 agora, nivel, json.dumps(fontes, ensure_ascii=False), tempo_ms,
                 item_respondido["id"], sessao_id),
            )
            auditoria.registrar(conexao, aluno_id, "resposta_item", cursor.lastrowid, origem, fontes, ts=agora)
    finally:
        conexao.close()
    return True


def registrar_dialogo(aluno_id: str, competencia_id: str | None, pergunta: str, resposta: str,
                      fontes: list[str], origem: str, tempo_ms: int) -> int:
    """Grava uma pergunta livre, a resposta do Tutor e a auditoria (R11),
    numa transação; devolve o id do diálogo."""
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("INSERT OR IGNORE INTO alunos (id) VALUES (?)", (aluno_id,))
            cursor = conexao.execute(
                """INSERT INTO tutor_dialogo
                   (aluno_id, ts, competencia_id, pergunta, resposta, fontes, origem, tempo_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, agora, competencia_id, pergunta, resposta,
                 json.dumps(fontes, ensure_ascii=False), origem, tempo_ms),
            )
            dialogo_id = cursor.lastrowid
            auditoria.registrar(conexao, aluno_id, "dialogo", dialogo_id, origem, fontes, ts=agora)
    finally:
        conexao.close()
    return dialogo_id


def vetar_dialogo(dialogo_id: int, vetada: bool, correcao_docente: str | None) -> bool:
    """Marca ou desmarca o veto docente (R12). A resposta original nunca é
    apagada; ao desmarcar, a correção fica guardada. False se o id não existe."""
    conexao = obter_conexao()
    try:
        with conexao:
            if vetada:
                cursor = conexao.execute(
                    "UPDATE tutor_dialogo SET vetada = 1, correcao_docente = ? WHERE id = ?",
                    (correcao_docente, dialogo_id))
            else:
                cursor = conexao.execute("UPDATE tutor_dialogo SET vetada = 0 WHERE id = ?", (dialogo_id,))
    finally:
        conexao.close()
    return cursor.rowcount == 1


def _dialogo_visivel(linha) -> dict:
    """Linha de tutor_dialogo como o aluno vê: se vetada, a correção do
    docente no lugar da resposta, sem fontes, origem "docente"."""
    vetada = bool(linha["vetada"])
    return {
        "dialogo_id": linha["id"], "ts": linha["ts"], "competencia_id": linha["competencia_id"],
        "pergunta": linha["pergunta"],
        "resposta": linha["correcao_docente"] if vetada else linha["resposta"],
        "fontes": [] if vetada else json.loads(linha["fontes"] or "[]"),
        "origem": "docente" if vetada else linha["origem"],
        "vetada": vetada,
    }


def listar_dialogo(aluno_id: str) -> list[dict]:
    """Histórico do diálogo do aluno, mais antigo primeiro (ver _dialogo_visivel)."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT * FROM tutor_dialogo WHERE aluno_id = ? ORDER BY ts, id", (aluno_id,),
        ).fetchall()
    finally:
        conexao.close()
    return [_dialogo_visivel(linha) for linha in linhas]


def ler_dialogo(dialogo_id: int) -> dict | None:
    """Um diálogo como o aluno vê; None se não existir."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT * FROM tutor_dialogo WHERE id = ?", (dialogo_id,)).fetchone()
    finally:
        conexao.close()
    return None if linha is None else _dialogo_visivel(linha)


def ultima_interacao(aluno_id: str) -> datetime | None:
    """Data da última ação do aluno no Tutor: sessão aberta ou respondida,
    resposta de item ou pergunta no diálogo. Não usa a auditoria, que também
    registra o incentivo (consultá-lo não conta como atividade)."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            """SELECT MAX(ts) AS ultima FROM (
                   SELECT timestamp AS ts FROM historico_respostas WHERE aluno_id = ?
                   UNION ALL SELECT atualizado_em FROM tutor_sessoes WHERE aluno_id = ?
                   UNION ALL SELECT ts FROM tutor_dialogo WHERE aluno_id = ?
               )""",
            (aluno_id, aluno_id, aluno_id),
        ).fetchone()
    finally:
        conexao.close()
    return datetime.fromisoformat(linha["ultima"]) if linha["ultima"] else None


def competencias_concluidas(aluno_id: str) -> set[str]:
    """Competências em que o aluno concluiu ao menos uma sessão do questionário."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT DISTINCT competencia_id FROM tutor_sessoes WHERE aluno_id = ? AND concluida",
            (aluno_id,),
        ).fetchall()
    finally:
        conexao.close()
    return {linha["competencia_id"] for linha in linhas}


def registrar_incentivo(aluno_id: str, competencia_id: str | None):
    """Auditoria (R11) do incentivo mostrado; referência = competência citada."""
    conexao = obter_conexao()
    try:
        with conexao:
            auditoria.registrar(conexao, aluno_id, "incentivo", competencia_id, "template", [], ts=_agora())
    finally:
        conexao.close()


def criacao_da_trilha(aluno_id: str) -> datetime | None:
    """Quando a trilha atual do aluno foi gerada pelo Planejador."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            "SELECT MAX(criado_em) AS criado FROM trilha_estudo WHERE aluno_id = ? AND competencia_id IS NOT NULL",
            (aluno_id,),
        ).fetchone()
    finally:
        conexao.close()
    return datetime.fromisoformat(linha["criado"]) if linha["criado"] else None


def sessao_aberta(aluno_id: str, competencia_id: str) -> str | None:
    """Id da sessão não concluída mais recente do aluno na competência (usado
    pela orquestração para "continuar sessão"); None se não houver."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            """SELECT id FROM tutor_sessoes WHERE aluno_id = ? AND competencia_id = ? AND NOT concluida
               ORDER BY atualizado_em DESC, criado_em DESC LIMIT 1""",
            (aluno_id, competencia_id),
        ).fetchone()
    finally:
        conexao.close()
    return linha["id"] if linha else None
