"""
Consultas SOMENTE DE LEITURA do painel do docente (EAP 1.4.5).

    ementa(), perfis()                    conteúdo pedagógico (PROVISÓRIO, Pessoa 4)
    alunos_em_risco(perfil_id)            alunos com inatividade, queda ou desempenho baixo,
                                          COM código; a consulta é auditada (R11)
    desempenho_competencias(perfil_id)    acerto e tendência por competência e itens com
                                          erro repetido; só agregados (grupo mínimo, R08)
    listar_revisao(situacao, origem, ...) respostas do diálogo para o veto docente (R12) e
                                          origem dos feedbacks; a consulta é auditada
    exportar_indicadores_csv(perfil_id)   os indicadores agregados do Agente 3 em CSV

Os números vêm das funções do Agente 3 (tia.agentes.relatorio.indicadores):
nada é recalculado aqui de outro jeito. A única escrita é a linha de
auditoria das consultas que mostram códigos de aluno.

Não é executável sozinho; usado pelas rotas /painel (tia.api.rotas_painel).
Dados de demonstração: python -m tia.web.dados_painel

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

import csv
import io
import json
from datetime import datetime
from typing import get_args

from tia.agentes.planejador.planejar import carregar_ementa, carregar_perfis
from tia.agentes.relatorio import gerar_relatorio_turma, indicadores
from tia.agentes.relatorio.modelos import Direcao, GrupoTaxa
from tia.agentes.relatorio.repositorio import ler_dados_aluno, listar_alunos
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core import auditoria
from tia.core.config import INATIVIDADE_DIAS, PAINEL_DESEMPENHO_BAIXO, PAINEL_MIN_RESPOSTAS, RELATORIO_MIN_GRUPO, \
    RELATORIO_TENDENCIA_LIMIAR
from tia.core.database import obter_conexao
from tia.painel.modelos import (AlunoEmRisco, CompetenciaEmenta, CompetenciaTurma, ConsultaRisco,
                                DesempenhoCompetencias, FeedbackRegistro, ItemRevisao, ItemTurma, ListaRevisao,
                                MotivoRisco, PerfilResumo)

ORIGENS = ("LLM", "guarda", "fallback")
FEEDBACKS_RECENTES = 20


def _texto(agora: datetime) -> str:
    return agora.isoformat(timespec="seconds")


def _porcento(fracao: float | None) -> str:
    return "sem dados" if fracao is None else f"{round(fracao * 100)}%"


def _auditar_consulta(referencia: str, motivo: str) -> int:
    """Uma linha de auditoria por consulta que mostra códigos de aluno. Quem
    consultou só será conhecido com o login (TODO 1.4.6)."""
    conexao = obter_conexao()
    try:
        with conexao:
            return auditoria.registrar(conexao, None, "consulta_painel", referencia, "painel", [],
                                       ts=_texto(datetime.now()), motivo=motivo)
    finally:
        conexao.close()


# --- conteúdo ---

def ementa() -> list[CompetenciaEmenta]:
    return [CompetenciaEmenta(id=c["id"], nome=c["nome"], prerequisitos=c.get("prerequisitos", []))
            for c in carregar_ementa()]


def perfis() -> list[PerfilResumo]:
    return [PerfilResumo(id=p["id"], nome=p.get("nome", p["id"])) for p in carregar_perfis()]


def _nomes() -> dict[str, str]:
    return {c["id"]: c["nome"] for c in carregar_ementa()}


# --- alertas de risco ---

def avaliar_risco(dados, agora: datetime, nomes: dict[str, str]) -> AlunoEmRisco | None:
    """Motivos de risco de um aluno (None se não há nenhum). PROVISÓRIO:
    inatividade e queda usam as mesmas regras do Agente 3 e do orquestrador;
    quem concluiu a trilha não entra por inatividade."""
    progresso = indicadores.progresso(dados, nomes)
    engajamento = indicadores.engajamento(dados, agora)
    desempenho = indicadores.desempenho(dados.respostas)
    tendencia = desempenho.tendencia
    concluiu = progresso.tem_trilha and progresso.etapas > 0 and progresso.concluidas == progresso.etapas
    motivos = []
    if engajamento.inativo and engajamento.dias_inativo is not None and not concluiu:
        motivos.append(MotivoRisco(tipo="inatividade", descricao=(
            f"Sem atividade há {engajamento.dias_inativo} dia(s) (alerta a partir de {INATIVIDADE_DIAS}).")))
    if tendencia.direcao == "caindo":
        base = "na última sessão" if tendencia.base == "sessao" else "nas respostas mais recentes"
        motivos.append(MotivoRisco(tipo="desempenho_em_queda", descricao=(
            f"Acerto {base}: {_porcento(tendencia.recentes.taxa)}, contra {_porcento(tendencia.anteriores.taxa)} "
            f"antes (queda de {round(RELATORIO_TENDENCIA_LIMIAR * 100)} pontos ou mais).")))
    geral = desempenho.geral
    if geral.respostas >= PAINEL_MIN_RESPOSTAS and geral.taxa is not None and geral.taxa < PAINEL_DESEMPENHO_BAIXO:
        motivos.append(MotivoRisco(tipo="desempenho_baixo", descricao=(
            f"Acertou {geral.acertos} de {geral.respostas} ({_porcento(geral.taxa)}; "
            f"alerta abaixo de {_porcento(PAINEL_DESEMPENHO_BAIXO)}).")))
    if not motivos:
        return None
    return AlunoEmRisco(aluno_id=dados.aluno_id, perfil_id=dados.perfil_id, motivos=motivos,
                        dias_inativo=engajamento.dias_inativo, respostas=geral.respostas, taxa_acerto=geral.taxa,
                        tendencia=tendencia.direcao, progresso=progresso.percentual)


def alunos_em_risco(perfil_id: str | None = None, agora: datetime | None = None) -> ConsultaRisco:
    """Alunos com pelo menos um motivo de risco, os com mais motivos primeiro.
    Mostra códigos: a consulta é registrada na auditoria, com os códigos exibidos."""
    agora = agora or datetime.now()
    nomes = _nomes()
    todos = [d for d in (ler_dados_aluno(a) for a in listar_alunos(perfil_id)) if d]
    em_risco = [r for r in (avaliar_risco(d, agora, nomes) for d in todos) if r]
    em_risco.sort(key=lambda r: (-len(r.motivos), -(r.dias_inativo or 0), r.aluno_id))
    codigos = ", ".join(r.aluno_id for r in em_risco) or "nenhum"
    auditoria_id = _auditar_consulta(
        "alunos_em_risco", f"perfil={perfil_id or 'todos'}; {len(em_risco)} aluno(s) exibido(s): {codigos}")
    return ConsultaRisco(
        gerado_em=_texto(agora), perfil_id=perfil_id, alunos_avaliados=len(todos), alunos=em_risco,
        auditoria_id=auditoria_id,
        criterios={"inatividade_dias": INATIVIDADE_DIAS, "queda_pontos": RELATORIO_TENDENCIA_LIMIAR,
                   "desempenho_baixo": PAINEL_DESEMPENHO_BAIXO, "min_respostas": PAINEL_MIN_RESPOSTAS})


# --- desempenho por competência (só agregados) ---

def desempenho_competencias(perfil_id: str | None = None, agora: datetime | None = None,
                            min_grupo: int = RELATORIO_MIN_GRUPO) -> DesempenhoCompetencias:
    """Acerto agregado e tendência por competência (na ordem da ementa) e itens
    com erro repetido. Usa indicadores.agregar_turma: competência com menos de
    min_grupo alunos sai suprimida e só entram itens respondidos por pelo
    menos min_grupo alunos (R08). Não mostra códigos: não é auditada."""
    agora = agora or datetime.now()
    nomes = _nomes()
    dados = [d for d in (ler_dados_aluno(a) for a in listar_alunos(perfil_id)) if d]
    campos = indicadores.agregar_turma(dados, agora, min_grupo, nomes)
    cabecalho = {"gerado_em": _texto(agora), "perfil_id": perfil_id, "min_grupo": min_grupo,
                 "alunos": campos["alunos"], "suprimido": campos["suprimido"]}
    if campos["suprimido"]:
        return DesempenhoCompetencias(**cabecalho)

    ordem = {c: i for i, c in enumerate(nomes)}
    competencias = []
    for grupo in sorted(campos["desempenho_por_competencia"], key=lambda g: ordem.get(g.chave, len(ordem))):
        tendencia = None
        if not grupo.suprimido:
            direcoes = [indicadores.tendencia(respostas).direcao for respostas in
                        ([r for r in d.respostas if r["competencia_id"] == grupo.chave] for d in dados) if respostas]
            tendencia = {direcao: indicadores.contagem(direcoes.count(direcao), min_grupo)
                         for direcao in get_args(Direcao)}
        competencias.append(CompetenciaTurma(competencia_id=grupo.chave, nome=nomes.get(grupo.chave, grupo.chave),
                                             alunos=grupo.alunos, suprimido=grupo.suprimido,
                                             respostas=grupo.respostas, taxa=grupo.taxa, tendencia=tendencia))

    banco = {i["id"]: i for i in carregar_itens()}
    itens = []
    for grupo in campos["itens_fracos"]:
        item = banco.get(grupo.chave, {})
        competencia = item.get("competencia_id", "")
        itens.append(ItemTurma(item_id=grupo.chave, competencia_id=competencia,
                               nome_competencia=nomes.get(competencia, competencia), nivel=item.get("nivel"),
                               enunciado=item.get("enunciado", "(item fora do banco atual)"),
                               alunos_com_erro=grupo.alunos, respostas=grupo.respostas, taxa_erro=grupo.taxa))
    return DesempenhoCompetencias(**cabecalho, competencias=competencias, itens_fracos=itens)


# --- revisão docente (R12) ---

# revisada = existe veto_docente na auditoria (veto, retirada ou aprovação pela rota do veto)
_REVISADA = """EXISTS (SELECT 1 FROM auditoria a WHERE a.tipo = 'veto_docente'
                         AND a.referencia_id = CAST(t.id AS TEXT))"""
_FILTRO_SITUACAO = {
    "a_revisar": f"NOT t.vetada AND NOT {_REVISADA}",
    "aprovadas": f"NOT t.vetada AND {_REVISADA}",
    "vetadas": "t.vetada",
    "todas": "1",
}


def listar_revisao(situacao: str = "a_revisar", origem: str | None = None, pagina: int = 1,
                   por_pagina: int = 20) -> ListaRevisao:
    """Respostas do diálogo (mais recentes primeiro) com a resposta ORIGINAL do
    Tutor, a correção do docente e a situação; mais a origem dos feedbacks de
    item, cujo texto não é gravado. Mostra códigos e textos: auditada."""
    condicao, parametros = _FILTRO_SITUACAO[situacao], []
    if origem is not None:
        condicao += " AND t.origem = ?"
        parametros.append(origem)
    conexao = obter_conexao()
    try:
        total = conexao.execute(f"SELECT COUNT(*) FROM tutor_dialogo t WHERE {condicao}", parametros).fetchone()[0]
        linhas = conexao.execute(
            f"""SELECT t.*, {_REVISADA} AS revisada FROM tutor_dialogo t WHERE {condicao}
                ORDER BY t.ts DESC, t.id DESC LIMIT ? OFFSET ?""",
            parametros + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
        contagens = conexao.execute(
            f"""SELECT COUNT(*) AS dialogos, COALESCE(SUM(t.vetada), 0) AS vetados,
                       COALESCE(SUM(NOT t.vetada AND {_REVISADA}), 0) AS aprovados
                FROM tutor_dialogo t""").fetchone()
        por_origem = dict(conexao.execute(
            """SELECT a.origem, COUNT(*) FROM auditoria a WHERE a.tipo = 'resposta_item'
               GROUP BY a.origem""").fetchall())
        feedbacks = conexao.execute(
            f"""SELECT h.id, h.timestamp AS ts, h.aluno_id, h.item_id, h.topico AS competencia_id, h.nivel,
                       h.acertou, a.origem, COALESCE(a.fontes, h.fontes) AS fontes
                FROM historico_respostas h
                LEFT JOIN auditoria a ON a.tipo = 'resposta_item' AND a.referencia_id = CAST(h.id AS TEXT)
                WHERE h.nivel IS NOT NULL {'AND a.origem = ?' if origem else ''}
                ORDER BY h.timestamp DESC, h.id DESC LIMIT ?""",
            ([origem] if origem else []) + [FEEDBACKS_RECENTES]).fetchall()
    finally:
        conexao.close()
    itens = [ItemRevisao(
        dialogo_id=t["id"], ts=t["ts"], aluno_id=t["aluno_id"], competencia_id=t["competencia_id"],
        pergunta=t["pergunta"], resposta=t["resposta"], origem=t["origem"], fontes=json.loads(t["fontes"] or "[]"),
        vetada=bool(t["vetada"]), correcao_docente=t["correcao_docente"],
        situacao="vetada" if t["vetada"] else "aprovada" if t["revisada"] else "a_revisar") for t in linhas]
    dialogos, vetados, aprovados = contagens["dialogos"], contagens["vetados"], contagens["aprovados"]
    codigos = ", ".join(dict.fromkeys(i.aluno_id for i in itens)) or "nenhum"
    auditoria_id = _auditar_consulta(
        "revisao", f"situacao={situacao}; origem={origem or 'todas'}; pagina={pagina}; "
                   f"{len(itens)} resposta(s) exibida(s) de: {codigos}")
    return ListaRevisao(
        situacao=situacao, origem=origem, total=total, pagina=pagina, por_pagina=por_pagina, itens=itens,
        dialogos=dialogos, vetados=vetados, aprovados=aprovados, a_revisar=dialogos - vetados - aprovados,
        taxa_veto=round(vetados / dialogos, 3) if dialogos else None,
        feedbacks_por_origem={o: por_origem.get(o, 0) for o in ORIGENS},
        feedbacks=[FeedbackRegistro(resposta_id=f["id"], ts=f["ts"], aluno_id=f["aluno_id"], item_id=f["item_id"],
                                    competencia_id=f["competencia_id"], nivel=f["nivel"], acertou=bool(f["acertou"]),
                                    origem=f["origem"], fontes=json.loads(f["fontes"] or "[]")) for f in feedbacks],
        auditoria_id=auditoria_id)


# --- exportação ---

def _celula(valor) -> str:
    """Texto seguro para planilha: sem fórmula (=, +, -, @ no início) e com
    vírgula decimal (Excel/LibreOffice em pt-BR)."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        return f"{valor:.3f}".replace(".", ",")
    texto = str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def _linhas_grupo(indicador: str, grupos: list[GrupoTaxa], nomes: dict[str, str], valor: str) -> list[list]:
    return [[indicador, nomes.get(g.chave, g.chave), g.alunos.texto, g.respostas, valor,
             None if g.suprimido else g.taxa, "suprimido (grupo mínimo)" if g.suprimido else ""] for g in grupos]


def exportar_indicadores_csv(perfil_id: str | None = None, agora: datetime | None = None) -> str:
    """Os indicadores agregados do relatório da turma (sem narrativa do LLM e
    sem códigos de aluno), em CSV separado por ";" com BOM (abre direto no
    Excel em pt-BR). PROVISÓRIO: formato a confirmar com a Pessoa 4."""
    relatorio = gerar_relatorio_turma(perfil_id, agora=agora, com_narrativa=False)
    nomes = _nomes()
    linhas = [["indicador", "grupo", "alunos", "respostas", "medida", "valor", "observacao"],
              ["cabecalho", "perfil: " + (perfil_id or "todos"), relatorio.alunos.texto, None,
               "grupo mínimo", relatorio.min_grupo, "gerado em " + relatorio.gerado_em]]
    if relatorio.suprimido:
        linhas.append(["todos", "", relatorio.alunos.texto, None, "", None,
                       f"suprimido: menos de {relatorio.min_grupo} alunos"])
    else:
        linhas.append(["1. progresso", "trilha", relatorio.alunos_com_trilha.texto, None,
                       "progresso médio (fração)", relatorio.progresso_medio, ""])
        linhas += _linhas_grupo("2. desempenho por competência", relatorio.desempenho_por_competencia, nomes,
                                "taxa de acerto")
        linhas += _linhas_grupo("2. desempenho por nível", relatorio.desempenho_por_nivel,
                                {g.chave: "nível " + g.chave for g in relatorio.desempenho_por_nivel},
                                "taxa de acerto")
        e = relatorio.engajamento
        linhas += [["3. engajamento", "turma", relatorio.alunos.texto, None, medida, valor, ""]
                   for medida, valor in (("média de sessões", e.media_sessoes),
                                         ("média de dias ativos", e.media_dias_ativos),
                                         ("média de perguntas ao tutor", e.media_perguntas_dialogo))]
        linhas.append(["3. engajamento", "inativos", e.inativos.texto, None, "alunos inativos", None, ""])
        linhas += _linhas_grupo("4. pontos fracos", relatorio.pontos_fracos, nomes, "taxa de erro")
        linhas += _linhas_grupo("4. itens com erro repetido", relatorio.itens_fracos, {}, "taxa de erro")
        q = relatorio.qualidade_feedback
        linhas += [["5. qualidade do feedback", "origem " + o, None, q.por_origem.get(o), "fração das respostas",
                    q.taxa_por_origem.get(o), ""] for o in ORIGENS]
        linhas.append(["5. qualidade do feedback", "veto docente", None, q.dialogos, "taxa de veto", q.taxa_veto,
                       f"{q.vetados} vetada(s)"])
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    for linha in linhas:
        escritor.writerow([_celula(v) for v in linha])
    return "﻿" + saida.getvalue()
