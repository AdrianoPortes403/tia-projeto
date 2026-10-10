"""
Regras de replanejamento da Orquestração: TODAS aqui, como funções puras.
Limiares em core/config.py. PROVISÓRIO: critérios a validar com a Pessoa 2
(agentes) e a Pessoa 4 (pedagogia); lista em docs/arquitetura/arquitetura.md.

Detecção (reaproveita o Agente 3, sem duplicar cálculo):
    R1 conclusão:   a sessão do Tutor na competência foi concluída e ainda não
                    houve replanejamento por conclusão dessa competência
                    -> ação "avancar";
    R2 queda:       a tendência do Relatório (indicadores.tendencia) está
                    "caindo" (limiar RELATORIO_TENDENCIA_LIMIAR), a sessão atual
                    ainda não provocou replanejamento por queda e houve pelo
                    menos ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS respostas desde o
                    último replanejamento por queda -> ação "reforcar";
    R3 inatividade: o engajamento do Relatório marca o aluno como inativo
                    (INATIVIDADE_DIAS) e ainda não houve replanejamento por
                    inatividade depois da última atividade -> ação "retomar".

Efeito no diagnóstico enviado ao Planejador (novo_diagnostico):
    avancar:  sem mudança (o Planejador não conhece etapas concluídas; a
              conclusão fica nas sessões do Tutor; ver perguntas no docs);
    reforcar: nota da competência = taxa de acerto observada nela; pré-requisitos
              diretos NÃO concluídos recebem ORQ_NOTA_PREREQ_REFORCO, e os que
              o perfil tinha dispensado voltam à trilha;
    retomar:  sem mudança (a trilha é refeita a partir de hoje).

Próxima ação (proxima_acao): replanejar (regra pendente) > concluído >
continuar sessão aberta > iniciar sessão na competência atual.

Não é executável sozinho; demonstração:
    python -m tia.orquestrador --demo

Pré-requisitos:
    - nenhum (funções puras)
"""

from dataclasses import dataclass

from tia.agentes.relatorio.modelos import Engajamento, Tendencia
from tia.core.config import (INATIVIDADE_DIAS, ORQ_NOTA_PREREQ_REFORCO, ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS,
                             RELATORIO_TENDENCIA_LIMIAR)
from tia.orquestrador.modelos import EstadoAluno, ProximaAcao


@dataclass
class Avaliacao:
    """Resultado de uma regra: se dispara, a ação e o motivo (vai para a auditoria)."""
    regra: str
    dispara: bool
    acao: str           # ação se disparar; "nenhuma" se não
    competencia_id: str | None
    motivo: str
    sessao_id: str | None = None  # sessão do Tutor que levou à decisão (R2: uma vez por sessão)


def regra_conclusao(competencia_id: str, concluidas: set[str], ja_avancou: bool) -> Avaliacao:
    """R1. ja_avancou: já houve replanejamento por conclusão desta competência."""
    if competencia_id not in concluidas:
        return Avaliacao("conclusao", False, "nenhuma", competencia_id,
                         f"Competência '{competencia_id}' ainda não tem sessão concluída no Tutor.")
    if ja_avancou:
        return Avaliacao("conclusao", False, "nenhuma", competencia_id,
                         f"Conclusão de '{competencia_id}' já foi tratada; nada a replanejar.")
    return Avaliacao("conclusao", True, "avancar", competencia_id,
                     f"Competência '{competencia_id}' concluída no Tutor: replanejar o restante da trilha.")


def regra_queda(tendencia: Tendencia, competencia_id: str | None, respostas_desde_ultimo_reforco: int | None,
                sessao_id: str | None = None, sessao_ja_reforcada: bool = False,
                minimo_entre: int = ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS) -> Avaliacao:
    """R2. respostas_desde_ultimo_reforco: None se nunca houve replanejamento por
    queda. sessao_ja_reforcada: esta sessão do Tutor já provocou um (a queda
    dela já foi tratada; retomar a mesma sessão não replaneja de novo)."""
    if tendencia.direcao != "caindo":
        return Avaliacao("queda", False, "nenhuma", competencia_id, f"Tendência '{tendencia.direcao}': sem queda.",
                         sessao_id)
    if sessao_ja_reforcada:
        return Avaliacao("queda", False, "nenhuma", competencia_id,
                         "A queda desta sessão já foi tratada.", sessao_id)
    if respostas_desde_ultimo_reforco is not None and respostas_desde_ultimo_reforco < minimo_entre:
        return Avaliacao("queda", False, "nenhuma", competencia_id,
                         f"Queda já tratada há {respostas_desde_ultimo_reforco} respostas "
                         f"(mínimo {minimo_entre} entre replanejamentos).", sessao_id)
    base = "na última sessão" if tendencia.base == "sessao" else "nas últimas respostas"
    return Avaliacao("queda", True, "reforcar", competencia_id,
                     f"Desempenho em queda: acerto {round((tendencia.recentes.taxa or 0) * 100)}% {base} contra "
                     f"{round((tendencia.anteriores.taxa or 0) * 100)}% antes (limiar "
                     f"{round(RELATORIO_TENDENCIA_LIMIAR * 100)} pontos): reforçar '{competencia_id}' e "
                     f"pré-requisitos.", sessao_id)


def regra_inatividade(engajamento: Engajamento, ultimo_retomar_ts: str | None) -> Avaliacao:
    """R3. ultimo_retomar_ts: momento do último replanejamento por inatividade."""
    if not engajamento.inativo:
        return Avaliacao("inatividade", False, "nenhuma", None,
                         f"Ativo: {engajamento.dias_inativo} dias desde a última atividade "
                         f"(limite {INATIVIDADE_DIAS}).")
    ja_tratada = ultimo_retomar_ts is not None and (
        engajamento.ultima_interacao is None or ultimo_retomar_ts >= engajamento.ultima_interacao)
    if ja_tratada:
        return Avaliacao("inatividade", False, "nenhuma", None,
                         "Inatividade já tratada depois da última atividade; aguardando o aluno voltar.")
    dias = "nunca usou o Tutor" if engajamento.dias_inativo is None else \
        f"{engajamento.dias_inativo} dias sem atividade"
    return Avaliacao("inatividade", True, "retomar", None,
                     f"Inatividade ({dias}; limite {INATIVIDADE_DIAS}): refazer a trilha a partir de hoje.")


def novo_diagnostico(acao: str, diagnostico: dict[str, float], competencia_id: str | None,
                     taxa_competencia: float | None, prerequisitos: list[str],
                     concluidas: set[str]) -> dict[str, float]:
    """Diagnóstico a enviar ao Planejador para a ação (ver docstring do módulo)."""
    novo = dict(diagnostico)
    if acao == "reforcar" and competencia_id:
        if taxa_competencia is not None:
            novo[competencia_id] = round(taxa_competencia, 3)
        for pre in prerequisitos:
            if pre not in concluidas:
                novo[pre] = ORQ_NOTA_PREREQ_REFORCO
    return novo


def proxima_acao(estado: EstadoAluno) -> ProximaAcao:
    """O que o aluno (ou o cliente) deve fazer agora."""
    if estado.replanejamento_pendente:
        return ProximaAcao(acao="replanejar", motivo=estado.replanejamento_pendente)
    if estado.concluido:
        return ProximaAcao(acao="concluido",
                           motivo="Todas as etapas da trilha concluídas; o relatório está em /relatorio/aluno.")
    if estado.sessao_aberta_id:
        return ProximaAcao(acao="continuar_sessao", competencia_id=estado.competencia_atual,
                           sessao_id=estado.sessao_aberta_id,
                           motivo=f"Há sessão em andamento em '{estado.competencia_atual}'.")
    return ProximaAcao(acao="iniciar_sessao", competencia_id=estado.competencia_atual,
                       motivo=f"Próxima etapa da trilha: '{estado.competencia_atual}' (POST /tutor/sessao).")
