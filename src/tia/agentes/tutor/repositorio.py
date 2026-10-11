"""
Persistência do Agente 2 (Tutor): leitura do banco de itens e da ementa,
estado das sessões (tabela tutor_sessoes), histórico de respostas
(tabela historico_respostas), texto do feedback de cada resposta (tabela
tutor_feedbacks) e diálogo livre (tabela tutor_dialogo). O veto docente
(R12) vale para o diálogo e para o feedback das questões.
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
                       acertou: bool, fontes: list[str], tempo_ms: int, origem: str,
                       feedback: dict | None = None) -> int | None:
    """Atualiza a sessão, grava a resposta no histórico, o texto do feedback
    (tutor_feedbacks) e a auditoria (R11), numa transação. feedback: veredito,
    explicacao, falha_llm, explicacao_descartada, motivo_descarte. Devolve o id
    da resposta, ou None (sem gravar nada) se a sessão já saiu deste item."""
    agora = _agora()
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """UPDATE tutor_sessoes
                   SET nivel = ?, item_atual_id = ?, itens_usados = ?,
                       acertos_seguidos_nivel_max = ?, concluida = ?, atualizado_em = ?
                   WHERE id = ? AND aluno_id = ? AND item_atual_id = ? AND NOT concluida
                     AND NOT COALESCE(pausada, 0)""",
                (novo_estado.nivel, novo_estado.item_atual_id, json.dumps(list(novo_estado.itens_usados)),
                 novo_estado.acertos_seguidos_nivel_max, novo_estado.concluida, agora,
                 sessao_id, aluno_id, item_respondido["id"]),
            )
            if cursor.rowcount != 1:
                return None
            nivel = item_respondido["nivel"]
            cursor = conexao.execute(
                """INSERT INTO historico_respostas
                   (aluno_id, topico, dificuldade, acertou, timestamp, nivel, fontes, tempo_ms, item_id, sessao_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aluno_id, item_respondido["competencia_id"], DIFICULDADE_POR_NIVEL.get(nivel), acertou,
                 agora, nivel, json.dumps(fontes, ensure_ascii=False), tempo_ms,
                 item_respondido["id"], sessao_id),
            )
            resposta_id = cursor.lastrowid
            if feedback is not None:
                conexao.execute(
                    """INSERT INTO tutor_feedbacks
                       (resposta_id, aluno_id, sessao_id, item_id, competencia_id, ts, veredito, explicacao, origem,
                        falha_llm, fontes, explicacao_descartada, motivo_descarte)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (resposta_id, aluno_id, sessao_id, item_respondido["id"], item_respondido["competencia_id"], agora,
                     feedback.get("veredito"), feedback.get("explicacao"), origem, feedback.get("falha_llm"),
                     json.dumps(fontes, ensure_ascii=False), feedback.get("explicacao_descartada") or None,
                     feedback.get("motivo_descarte") or None))
            auditoria.registrar(conexao, aluno_id, "resposta_item", resposta_id, origem, fontes, ts=agora)
    finally:
        conexao.close()
    return resposta_id


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


def _vetar(tabela: str, chave: str, registro_id: int, referencia: str, vetada: bool,
           correcao_docente: str | None) -> bool:
    """Veto docente (R12) numa linha de tutor_dialogo ou tutor_feedbacks e a
    auditoria (R11), na mesma transação. A resposta original nunca é apagada;
    ao desmarcar, a correção fica guardada. False se o id não existe."""
    conexao = obter_conexao()
    try:
        with conexao:
            linha = conexao.execute(f"SELECT aluno_id, vetada FROM {tabela} WHERE {chave} = ?",
                                    (registro_id,)).fetchone()
            if linha is None:
                return False
            if vetada:
                conexao.execute(f"UPDATE {tabela} SET vetada = 1, correcao_docente = ? WHERE {chave} = ?",
                                (correcao_docente, registro_id))
            else:
                conexao.execute(f"UPDATE {tabela} SET vetada = 0 WHERE {chave} = ?", (registro_id,))
            # sem o texto da correção (fica só na tabela de origem); quem vetou vem da sessão (auditoria.USUARIO_ATUAL).
            # vetada=False numa resposta sem veto é a APROVAÇÃO do docente: fica só aqui, na auditoria
            motivo = ("resposta vetada e corrigida" if vetada else
                      "veto retirado" if linha["vetada"] else "resposta aprovada")
            auditoria.registrar(conexao, linha["aluno_id"], "veto_docente", referencia,
                                "vetada" if vetada else "aprovada", [], ts=_agora(), motivo=motivo)
    finally:
        conexao.close()
    return True


def vetar_dialogo(dialogo_id: int, vetada: bool, correcao_docente: str | None) -> bool:
    """Veto docente (R12) de uma resposta do diálogo (auditoria: referência = id do diálogo)."""
    return _vetar("tutor_dialogo", "id", dialogo_id, str(dialogo_id), vetada, correcao_docente)


# referência do veto de feedback na auditoria: "feedback:<id da resposta>" (o do diálogo é só o id)
PREFIXO_VETO_FEEDBACK = "feedback:"


def vetar_feedback(resposta_id: int, vetada: bool, correcao_docente: str | None) -> bool:
    """Veto docente (R12) do feedback de uma questão. False se a resposta não
    tem feedback gravado (inexistente ou anterior à tabela tutor_feedbacks)."""
    return _vetar("tutor_feedbacks", "resposta_id", resposta_id, PREFIXO_VETO_FEEDBACK + str(resposta_id),
                  vetada, correcao_docente)


def _feedback_visivel(linha, enunciados: dict[str, str]) -> dict:
    """Feedback como o aluno vê: se vetado, a correção do docente no lugar da
    explicação, sem fontes, origem "docente". Nunca o texto descartado pela guarda."""
    vetada = bool(linha["vetada"])
    return {
        "resposta_id": linha["resposta_id"], "ts": linha["ts"], "sessao_id": linha["sessao_id"],
        "item_id": linha["item_id"], "enunciado": enunciados.get(linha["item_id"]),
        "competencia_id": linha["competencia_id"], "veredito": linha["veredito"],
        "explicacao": linha["correcao_docente"] if vetada else linha["explicacao"],
        "fontes": [] if vetada else json.loads(linha["fontes"] or "[]"),
        "origem": "docente" if vetada else linha["origem"],
        "vetada": vetada,
    }


def listar_feedbacks(aluno_id: str) -> list[dict]:
    """Feedbacks gravados do aluno, mais antigo primeiro (ver _feedback_visivel)."""
    conexao = obter_conexao()
    try:
        linhas = conexao.execute("SELECT * FROM tutor_feedbacks WHERE aluno_id = ? ORDER BY ts, resposta_id",
                                 (aluno_id,)).fetchall()
    finally:
        conexao.close()
    return [_feedback_visivel(linha, _enunciados()) for linha in linhas]


def _enunciados() -> dict[str, str]:
    return {item["id"]: item["enunciado"] for item in carregar_itens()}


def ler_feedback(resposta_id: int) -> dict | None:
    """Um feedback como o aluno vê; None se não houver."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT * FROM tutor_feedbacks WHERE resposta_id = ?", (resposta_id,)).fetchone()
    finally:
        conexao.close()
    return None if linha is None else _feedback_visivel(linha, _enunciados())


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
    """Id da sessão não concluída nem pausada mais recente do aluno na
    competência (usado pela orquestração para "continuar sessão"); None se não houver."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            """SELECT id FROM tutor_sessoes WHERE aluno_id = ? AND competencia_id = ? AND NOT concluida
                 AND NOT COALESCE(pausada, 0)
               ORDER BY atualizado_em DESC, criado_em DESC LIMIT 1""",
            (aluno_id, competencia_id),
        ).fetchone()
    finally:
        conexao.close()
    return linha["id"] if linha else None


def _marcar_pausa(sessao_id: str, aluno_id: str, pausada: bool) -> bool:
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """UPDATE tutor_sessoes SET pausada = ?, atualizado_em = ?
                   WHERE id = ? AND aluno_id = ? AND NOT concluida AND COALESCE(pausada, 0) = ?""",
                (int(pausada), _agora(), sessao_id, aluno_id, int(not pausada)))
    finally:
        conexao.close()
    return cursor.rowcount == 1


def pausar_sessao(sessao_id: str, aluno_id: str) -> bool:
    """Suspende a sessão (reforço por queda, na orquestração), guardando nível e
    itens. False se não existe, é de outro aluno, já terminou ou já está pausada."""
    return _marcar_pausa(sessao_id, aluno_id, True)


def retomar_sessao(sessao_id: str, aluno_id: str) -> bool:
    """Volta a sessão pausada ao ponto em que parou (mesmo nível e item)."""
    return _marcar_pausa(sessao_id, aluno_id, False)


def sessao_pausada(sessao_id: str, aluno_id: str) -> bool:
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT pausada FROM tutor_sessoes WHERE id = ? AND aluno_id = ?",
                                (sessao_id, aluno_id)).fetchone()
    finally:
        conexao.close()
    return bool(linha and linha["pausada"])
