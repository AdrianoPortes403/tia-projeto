"""
Os 5 indicadores do Agente 3 (Relatório), calculados por CÓDIGO, de forma
determinística (mesmos dados e mesmo "agora", mesmo resultado). O LLM não
calcula nada: só redige a interpretação dos números (narrativa.py).

PROVISÓRIO: definições, limiares e janelas abaixo são da frente A3, até a
validação dos critérios com a Pessoa 4 (docs/arquitetura/relatorio_indicadores.md).

    1. progresso:          % de etapas da trilha concluídas e nível atual por competência
    2. desempenho:         taxa de acerto por competência e por nível, com tendência
                           (última sessão x anteriores; sem sessao_id, janela de respostas)
    3. engajamento:        sessões, dias ativos e dias de inatividade (INATIVIDADE_DIAS)
    4. pontos fracos:      competências e itens (com item_id) com erro repetido
                           (+ perguntas no diálogo)
    5. qualidade feedback: taxa de origem LLM/guarda/fallback e taxa de veto docente

Turma/instituição (agregar_turma): só agregados; grupo com menos de
min_grupo alunos é suprimido e contagens abaixo disso viram "menos de N" (R08).

Não é executável sozinho; demonstração:
    python -m tia.agentes.relatorio --demo

Pré-requisitos:
    - nenhum (funções puras sobre repositorio.DadosAluno)
"""

from datetime import datetime

from tia.agentes.relatorio.modelos import (AlertaTurma, Contagem, Desempenho, Engajamento, EngajamentoTurma,
                                           GrupoTaxa, ItemFraco, Progresso, ProgressoCompetencia, PontoFraco,
                                           QualidadeFeedback, Taxa, Tendencia)
from tia.agentes.relatorio.repositorio import DadosAluno
from tia.core.config import (INATIVIDADE_DIAS, RELATORIO_TENDENCIA_JANELA, RELATORIO_TENDENCIA_LIMIAR,
                             RELATORIO_TENDENCIA_MIN_RESPOSTAS)

# PROVISÓRIO: critérios a validar com a Pessoa 4.
# tendência: limiares em core/config.py (também usados pela regra de queda do orquestrador)
JANELA_TENDENCIA = RELATORIO_TENDENCIA_JANELA
MIN_RESPOSTAS_TENDENCIA = RELATORIO_TENDENCIA_MIN_RESPOSTAS
LIMIAR_TENDENCIA = RELATORIO_TENDENCIA_LIMIAR
PONTO_FRACO_MIN_ERROS = 2       # erros na competência para contar como recorrente...
PONTO_FRACO_TAXA_ERRO = 0.5     # ...com taxa de erro de pelo menos isto
TURMA_TAXA_ERRO_ALTO = 0.5      # alerta: acerto agregado da competência abaixo de 1 - isto
ORIGENS = ("LLM", "guarda", "fallback")


def _taxa(chave: str, respostas: list[dict]) -> Taxa:
    acertos = sum(r["acertou"] for r in respostas)
    return Taxa(chave=chave, respostas=len(respostas), acertos=acertos,
                taxa=round(acertos / len(respostas), 3) if respostas else None)


def _data(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


# --- 1. progresso na trilha ---

def progresso(dados: DadosAluno, nomes: dict[str, str]) -> Progresso:
    """Etapa concluída = sessão do questionário concluída na competência (mesmo
    critério do incentivo). Nível atual = nível da sessão mais recente."""
    concluidas = {s["competencia_id"] for s in dados.sessoes if s["concluida"]}
    nivel_atual = {}
    for sessao in dados.sessoes:  # em ordem de atualização: a última vence
        nivel_atual[sessao["competencia_id"]] = sessao["nivel"]
    if dados.trilha is not None:
        competencias = [e.competencia_id for e in sorted(dados.trilha.etapas, key=lambda e: e.ordem)]
    else:
        competencias = list(dict.fromkeys(s["competencia_id"] for s in dados.sessoes))
    # etapa marcada como concluída pelo Planejador (replanejamento incremental) também conta
    if dados.trilha is not None:
        concluidas |= {e.competencia_id for e in dados.trilha.etapas if e.concluida}
    por_competencia = [ProgressoCompetencia(competencia_id=c, nome=nomes.get(c, c), concluida=c in concluidas,
                                            nivel_atual=nivel_atual.get(c)) for c in competencias]
    if dados.trilha is None:
        return Progresso(tem_trilha=False, etapas=0, concluidas=0, percentual=None, por_competencia=por_competencia)
    feitas = sum(p.concluida for p in por_competencia)
    etapas = len(por_competencia)
    return Progresso(tem_trilha=True, etapas=etapas, concluidas=feitas,
                     percentual=round(feitas / etapas, 3) if etapas else None, por_competencia=por_competencia)


# --- 2. desempenho ---

def _comparar(base: str, recentes: list[dict], anteriores: list[dict]) -> Tendencia:
    t_recentes, t_anteriores = _taxa("recentes", recentes), _taxa("anteriores", anteriores)
    if len(recentes) < MIN_RESPOSTAS_TENDENCIA or len(anteriores) < MIN_RESPOSTAS_TENDENCIA:
        return Tendencia(base=base, recentes=t_recentes, anteriores=t_anteriores, variacao=None,
                         direcao="insuficiente")
    variacao = round(t_recentes.taxa - t_anteriores.taxa, 3)
    direcao = ("subindo" if variacao >= LIMIAR_TENDENCIA else
               "caindo" if variacao <= -LIMIAR_TENDENCIA else "estavel")
    return Tendencia(base=base, recentes=t_recentes, anteriores=t_anteriores, variacao=variacao, direcao=direcao)


def tendencia(respostas: list[dict]) -> Tendencia:
    """Com sessao_id: respostas da última sessão (a da resposta mais recente)
    x respostas das outras sessões. Usada se houver 2 sessões ou mais e
    MIN_RESPOSTAS_TENDENCIA respostas de cada lado; senão (respostas antigas,
    sem sessao_id, ou sessão recém-aberta), últimas JANELA_TENDENCIA respostas
    x todas as anteriores. Respostas em ordem de tempo."""
    com_sessao = [r for r in respostas if r.get("sessao_id")]
    if com_sessao:
        ultima = com_sessao[-1]["sessao_id"]
        recentes = [r for r in com_sessao if r["sessao_id"] == ultima]
        anteriores = [r for r in com_sessao if r["sessao_id"] != ultima]
        if len(recentes) >= MIN_RESPOSTAS_TENDENCIA and len(anteriores) >= MIN_RESPOSTAS_TENDENCIA:
            return _comparar("sessao", recentes, anteriores)
    return _comparar("janela", respostas[-JANELA_TENDENCIA:], respostas[:-JANELA_TENDENCIA])


def desempenho(respostas: list[dict]) -> Desempenho:
    competencias = list(dict.fromkeys(r["competencia_id"] for r in respostas))
    niveis = sorted({r["nivel"] for r in respostas})
    return Desempenho(
        geral=_taxa("geral", respostas),
        por_competencia=[_taxa(c, [r for r in respostas if r["competencia_id"] == c]) for c in competencias],
        por_nivel=[_taxa(str(n), [r for r in respostas if r["nivel"] == n]) for n in niveis],
        tendencia=tendencia(respostas),
    )


# --- 3. engajamento ---

def engajamento(dados: DadosAluno, agora: datetime) -> Engajamento:
    """Mesma regra de inatividade do incentivo (tutor/incentivo.py): conta da
    última ação do aluno no Tutor; sem nenhuma, da criação da trilha."""
    momentos = ([r["ts"] for r in dados.respostas] + [d["ts"] for d in dados.dialogos]
                + [s["atualizado_em"] for s in dados.sessoes] + [s["criado_em"] for s in dados.sessoes])
    momentos = [m for m in momentos if m]
    ultima = max(momentos) if momentos else None
    referencia = _data(ultima) or _data(dados.trilha_criada_em)
    dias_inativo = max(0, (agora - referencia).days) if referencia else None
    return Engajamento(
        sessoes=len(dados.sessoes),
        sessoes_concluidas=sum(s["concluida"] for s in dados.sessoes),
        respostas=len(dados.respostas),
        perguntas_dialogo=len(dados.dialogos),
        dias_ativos=len({m[:10] for m in momentos}),
        ultima_interacao=ultima,
        dias_inativo=dias_inativo,
        inativo=dias_inativo is None or dias_inativo >= INATIVIDADE_DIAS,
    )


# --- 4. pontos fracos recorrentes ---

def _maior_sequencia_erros(respostas: list[dict]) -> int:
    maior = atual = 0
    for r in respostas:
        atual = 0 if r["acertou"] else atual + 1
        maior = max(maior, atual)
    return maior


def _erro_repetido(erros: int, respostas: int) -> bool:
    return erros >= PONTO_FRACO_MIN_ERROS and erros / respostas >= PONTO_FRACO_TAXA_ERRO


def pontos_fracos(respostas: list[dict], dialogos: list[dict], nomes: dict[str, str]) -> list[PontoFraco]:
    """Competências com pelo menos PONTO_FRACO_MIN_ERROS erros e taxa de erro
    >= PONTO_FRACO_TAXA_ERRO, da mais errada para a menos. Usa todas as
    respostas, com ou sem item_id (o detalhe por item está em itens_fracos)."""
    fracos = []
    for c in dict.fromkeys(r["competencia_id"] for r in respostas):
        da_competencia = [r for r in respostas if r["competencia_id"] == c]
        erros = sum(not r["acertou"] for r in da_competencia)
        taxa_erro = erros / len(da_competencia)
        if _erro_repetido(erros, len(da_competencia)):
            fracos.append(PontoFraco(
                competencia_id=c, nome=nomes.get(c, c), respostas=len(da_competencia), erros=erros,
                taxa_erro=round(taxa_erro, 3), maior_sequencia_erros=_maior_sequencia_erros(da_competencia),
                perguntas_dialogo=sum(d["competencia_id"] == c for d in dialogos)))
    return sorted(fracos, key=lambda p: (-p.taxa_erro, -p.erros, p.competencia_id))


def itens_fracos(respostas: list[dict]) -> list[ItemFraco]:
    """Itens com erro repetido (mesmos limiares da competência), só entre as
    respostas com item_id; as antigas, sem item_id, ficam só no agrupamento
    por competência."""
    fracos = []
    for item_id in dict.fromkeys(r["item_id"] for r in respostas if r.get("item_id")):
        do_item = [r for r in respostas if r.get("item_id") == item_id]
        erros = sum(not r["acertou"] for r in do_item)
        if _erro_repetido(erros, len(do_item)):
            fracos.append(ItemFraco(item_id=item_id, competencia_id=do_item[0]["competencia_id"],
                                    respostas=len(do_item), erros=erros, taxa_erro=round(erros / len(do_item), 3),
                                    maior_sequencia_erros=_maior_sequencia_erros(do_item)))
    return sorted(fracos, key=lambda f: (-f.taxa_erro, -f.erros, f.item_id))


# --- 5. qualidade do feedback ---

def qualidade_feedback(respostas: list[dict], dialogos: list[dict]) -> QualidadeFeedback:
    """Origens das respostas de item (pela auditoria) e do diálogo; veto docente
    só existe no diálogo."""
    origens = [r["origem"] for r in respostas if r["origem"]] + [d["origem"] for d in dialogos if d["origem"]]
    por_origem = {o: origens.count(o) for o in ORIGENS}
    total = sum(por_origem.values())
    vetados = sum(d["vetada"] for d in dialogos)
    return QualidadeFeedback(
        respostas_com_origem=sum(bool(r["origem"]) for r in respostas),
        respostas_sem_registro=sum(not r["origem"] for r in respostas),
        por_origem=por_origem,
        taxa_por_origem={o: round(n / total, 3) if total else None for o, n in por_origem.items()},
        dialogos=len(dialogos),
        vetados=vetados,
        taxa_veto=round(vetados / len(dialogos), 3) if dialogos else None,
    )


# --- turma / instituição: só agregados ---

def contagem(valor: int, min_grupo: int) -> Contagem:
    """Contagem de alunos; abaixo do mínimo (e acima de zero) não sai o número (R08)."""
    if 0 < valor < min_grupo:
        return Contagem(valor=None, texto=f"menos de {min_grupo}")
    return Contagem(valor=valor, texto=str(valor))


def _grupo(chave: str, respostas_por_aluno: list[list[dict]], min_grupo: int) -> GrupoTaxa:
    """Taxa agregada das respostas de quem respondeu; suprimida abaixo do mínimo."""
    com_respostas = [r for r in respostas_por_aluno if r]
    alunos = contagem(len(com_respostas), min_grupo)
    if len(com_respostas) < min_grupo:
        return GrupoTaxa(chave=chave, alunos=alunos, suprimido=True)
    todas = [r for respostas in com_respostas for r in respostas]
    taxa = _taxa(chave, todas)
    return GrupoTaxa(chave=chave, alunos=alunos, suprimido=False, respostas=taxa.respostas, taxa=taxa.taxa)


def agregar_turma(dados: list[DadosAluno], agora: datetime, min_grupo: int, nomes: dict[str, str]) -> dict:
    """Campos do RelatorioTurma (menos narrativa e cabeçalho). Grupo inteiro
    abaixo do mínimo: só a contagem e suprimido=True."""
    n = len(dados)
    if n < min_grupo:
        return {"alunos": contagem(n, min_grupo), "suprimido": True}

    progressos = [progresso(d, nomes) for d in dados]
    com_trilha = [p.percentual for p in progressos if p.tem_trilha and p.percentual is not None]
    engajamentos = [engajamento(d, agora) for d in dados]
    tendencias = [tendencia(d.respostas) for d in dados]
    competencias = list(dict.fromkeys(r["competencia_id"] for d in dados for r in d.respostas))
    niveis = sorted({r["nivel"] for d in dados for r in d.respostas})

    por_competencia = [_grupo(c, [[r for r in d.respostas if r["competencia_id"] == c] for d in dados], min_grupo)
                       for c in competencias]
    por_nivel = [_grupo(str(nv), [[r for r in d.respostas if r["nivel"] == nv] for d in dados], min_grupo)
                 for nv in niveis]

    fracos = []
    for c in competencias:
        com_ponto_fraco = sum(any(p.competencia_id == c for p in pontos_fracos(d.respostas, d.dialogos, nomes))
                              for d in dados)
        if com_ponto_fraco:
            grupo = _grupo(c, [[r for r in d.respostas if r["competencia_id"] == c] for d in dados], min_grupo)
            # alunos = quantos têm a competência como ponto fraco; taxa = ERRO agregado
            fracos.append(GrupoTaxa(chave=c, alunos=contagem(com_ponto_fraco, min_grupo), suprimido=grupo.suprimido,
                                    respostas=grupo.respostas,
                                    taxa=None if grupo.taxa is None else round(1 - grupo.taxa, 3)))

    # itens: só os respondidos por pelo menos min_grupo alunos são avaliados (R08)
    itens = []
    for item_id in dict.fromkeys(r["item_id"] for d in dados for r in d.respostas if r.get("item_id")):
        por_aluno = [[r for r in d.respostas if r.get("item_id") == item_id] for d in dados]
        grupo = _grupo(item_id, por_aluno, min_grupo)
        erros = sum(not r["acertou"] for respostas in por_aluno for r in respostas)
        if not grupo.suprimido and _erro_repetido(erros, grupo.respostas):
            erraram = sum(any(not r["acertou"] for r in respostas) for respostas in por_aluno)
            itens.append(GrupoTaxa(chave=item_id, alunos=contagem(erraram, min_grupo), suprimido=False,
                                   respostas=grupo.respostas, taxa=round(1 - grupo.taxa, 3)))
    itens.sort(key=lambda g: (-g.taxa, g.chave))

    inativos = sum(e.inativo for e in engajamentos)
    em_queda = sum(t.direcao == "caindo" for t in tendencias)
    alertas = []
    if inativos:
        alertas.append(AlertaTurma(tipo="inatividade", alunos=contagem(inativos, min_grupo),
                                   descricao=f"Alunos sem atividade há {INATIVIDADE_DIAS} dias ou mais."))
    if em_queda:
        alertas.append(AlertaTurma(tipo="desempenho_em_queda", alunos=contagem(em_queda, min_grupo),
                                   descricao=(f"Alunos com acerto na última sessão (ou, sem sessão registrada, nas "
                                              f"últimas {JANELA_TENDENCIA} respostas) {round(LIMIAR_TENDENCIA * 100)} "
                                              f"pontos ou mais abaixo do anterior.")))
    for grupo in por_competencia:
        if not grupo.suprimido and grupo.taxa is not None and grupo.taxa < 1 - TURMA_TAXA_ERRO_ALTO:
            alertas.append(AlertaTurma(tipo="competencia_com_erro_alto", alunos=grupo.alunos,
                                       competencia_id=grupo.chave,
                                       descricao=f"Acerto agregado abaixo de {round((1 - TURMA_TAXA_ERRO_ALTO) * 100)}% "
                                                 f"em {nomes.get(grupo.chave, grupo.chave)}."))

    todas_respostas = [r for d in dados for r in d.respostas]
    todos_dialogos = [x for d in dados for x in d.dialogos]
    return {
        "alunos": contagem(n, min_grupo),
        "suprimido": False,
        "progresso_medio": round(sum(com_trilha) / len(com_trilha), 3) if len(com_trilha) >= min_grupo else None,
        "alunos_com_trilha": contagem(len(com_trilha), min_grupo),
        "desempenho_por_competencia": por_competencia,
        "desempenho_por_nivel": por_nivel,
        "engajamento": EngajamentoTurma(
            media_sessoes=round(sum(e.sessoes for e in engajamentos) / n, 1),
            media_dias_ativos=round(sum(e.dias_ativos for e in engajamentos) / n, 1),
            media_perguntas_dialogo=round(sum(e.perguntas_dialogo for e in engajamentos) / n, 1),
            inativos=contagem(inativos, min_grupo)),
        "pontos_fracos": fracos,
        "itens_fracos": itens,
        "qualidade_feedback": qualidade_feedback(todas_respostas, todos_dialogos),
        "alertas": alertas,
    }
