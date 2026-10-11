"""
Regras da Orquestração: TODAS aqui, como funções puras. Limiares em
core/config.py. Decisões e quem as tomou em docs/arquitetura/arquitetura.md,
seção "Decisões de orquestração". As marcadas PROVISÓRIO dependem de validação
pedagógica da Pessoa 4.

Detecção (reaproveita o Agente 3, sem duplicar cálculo):
    R1 conclusão (PROVISÓRIO): a sessão do Tutor na competência foi concluída e a
        conclusão ainda não foi tratada -> "avancar": replaneja só o que falta
        (Planejador incremental) e avisa o aluno;
    R2 queda (PROVISÓRIO): a tendência do Relatório está "caindo"
        (RELATORIO_TENDENCIA_*), a sessão não é de reforço, ainda não causou
        reforço e houve ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS respostas desde o
        último -> "reforcar": pausa a sessão e abre reforço do pré-requisito
        DIRETO, no nível 1; sem pré-requisito, não reforça;
    fim do reforço: a sessão de reforço foi concluída -> "retomar_original": a
        sessão pausada volta no nível em que parou;
    R3 inatividade (PROVISÓRIO): avaliada pela verificação agendada.
        A partir de INATIVIDADE_DIAS -> "incentivar" (só incentivo, sem refazer a
        trilha), uma vez por período sem atividade; a partir de
        ORQ_INATIVIDADE_REFAZER_DIAS -> "refazer_trilha" (replaneja o que falta a
        partir de hoje), também uma vez por período.

Próxima ação (proxima_acao): reforço em curso > concluído > continuar sessão
aberta > iniciar sessão na competência atual.

Não é executável sozinho; demonstração:
    python -m tia.orquestrador --demo

Pré-requisitos:
    - nenhum (funções puras)
"""

from dataclasses import dataclass

from tia.agentes.relatorio.modelos import Engajamento, Tendencia
from tia.core.config import (INATIVIDADE_DIAS, ORQ_INATIVIDADE_REFAZER_DIAS, ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS,
                             RELATORIO_TENDENCIA_LIMIAR)
from tia.orquestrador.modelos import EstadoAluno, ProximaAcao

# PROVISÓRIO: textos dos avisos ao aluno, até a revisão pedagógica (Pessoa 4).
AVISO_CONCLUSAO = "Parabéns! Você concluiu \"{concluida}\". {seguinte}"
AVISO_SEGUINTE = "Próxima etapa: \"{proxima}\"."
AVISO_FIM_DA_TRILHA = "Você concluiu todas as etapas da sua trilha."
AVISO_REFORCO = ("Vamos revisar \"{reforco}\" antes de continuar \"{original}\". A sessão de \"{original}\" "
                 "fica guardada e volta de onde parou.")
AVISO_RETOMADA = "Revisão de \"{reforco}\" concluída! Voltando a \"{original}\" no nível {nivel}, de onde você parou."


@dataclass
class Avaliacao:
    """Resultado de uma regra: se dispara, a ação e o motivo (vai para a auditoria)."""
    regra: str
    dispara: bool
    acao: str           # ação se disparar; "nenhuma" se não
    competencia_id: str | None
    motivo: str
    sessao_id: str | None = None           # sessão do Tutor que levou à decisão
    competencia_reforco: str | None = None  # R2: pré-requisito direto a reforçar


def prerequisito_direto(competencia_id: str, ementa: list[dict]) -> str | None:
    """Primeiro pré-requisito direto da competência na ementa (None se não há)."""
    competencia = next((c for c in ementa if c["id"] == competencia_id), None)
    prerequisitos = competencia.get("prerequisitos", []) if competencia else []
    return prerequisitos[0] if prerequisitos else None


def regra_conclusao(competencia_id: str, concluidas: set[str], ja_avancou: bool) -> Avaliacao:
    """R1. ja_avancou: já houve replanejamento por conclusão desta competência."""
    if competencia_id not in concluidas:
        return Avaliacao("conclusao", False, "nenhuma", competencia_id,
                         f"Competência '{competencia_id}' ainda não tem sessão concluída no Tutor.")
    if ja_avancou:
        return Avaliacao("conclusao", False, "nenhuma", competencia_id,
                         f"Conclusão de '{competencia_id}' já foi tratada; nada a replanejar.")
    return Avaliacao("conclusao", True, "avancar", competencia_id,
                     f"Competência '{competencia_id}' concluída no Tutor: avançar e replanejar só o que falta.")


def regra_queda(tendencia: Tendencia, competencia_id: str | None, respostas_desde_ultimo_reforco: int | None,
                sessao_id: str | None = None, sessao_ja_reforcada: bool = False, em_reforco: bool = False,
                prerequisito: str | None = None,
                minimo_entre: int = ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS) -> Avaliacao:
    """R2. respostas_desde_ultimo_reforco: None se nunca houve reforço.
    sessao_ja_reforcada: esta sessão já provocou um reforço. em_reforco: a
    sessão É um reforço (não se encadeia reforço de reforço)."""
    def nao(motivo: str) -> Avaliacao:
        return Avaliacao("queda", False, "nenhuma", competencia_id, motivo, sessao_id)

    if tendencia.direcao != "caindo":
        return nao(f"Tendência '{tendencia.direcao}': sem queda.")
    if em_reforco:
        return nao("Queda dentro de uma sessão de reforço: não se reforça o reforço.")
    if sessao_ja_reforcada:
        return nao("A queda desta sessão já foi tratada.")
    if respostas_desde_ultimo_reforco is not None and respostas_desde_ultimo_reforco < minimo_entre:
        return nao(f"Queda já tratada há {respostas_desde_ultimo_reforco} respostas "
                   f"(mínimo {minimo_entre} entre reforços).")
    base = "na última sessão" if tendencia.base == "sessao" else "nas últimas respostas"
    queda = (f"acerto {round((tendencia.recentes.taxa or 0) * 100)}% {base} contra "
             f"{round((tendencia.anteriores.taxa or 0) * 100)}% antes (limiar {round(RELATORIO_TENDENCIA_LIMIAR * 100)} "
             f"pontos)")
    if prerequisito is None:
        return nao(f"Desempenho em queda ({queda}), mas '{competencia_id}' não tem pré-requisito direto para reforçar.")
    return Avaliacao("queda", True, "reforcar", competencia_id,
                     f"Desempenho em queda ({queda}): pausar '{competencia_id}' e reforçar o pré-requisito direto "
                     f"'{prerequisito}' a partir do nível 1.", sessao_id, prerequisito)


def _tratada(ultima_acao_ts: str | None, ultima_interacao: str | None) -> bool:
    """A ação já foi tomada depois da última atividade do aluno?"""
    return ultima_acao_ts is not None and (ultima_interacao is None or ultima_acao_ts >= ultima_interacao)


def regra_inatividade(engajamento: Engajamento, ultimo_incentivo_ts: str | None, ultimo_refazer_ts: str | None,
                      refazer_dias: int = ORQ_INATIVIDADE_REFAZER_DIAS) -> Avaliacao:
    """R3. Os ts são os das últimas decisões "incentivar" e "refazer_trilha"."""
    dias = engajamento.dias_inativo
    if not engajamento.inativo:
        return Avaliacao("inatividade", False, "nenhuma", None,
                         f"Ativo: {dias} dias desde a última atividade (limite {INATIVIDADE_DIAS}).")
    texto_dias = "sem atividade registrada" if dias is None else f"{dias} dias sem atividade"
    if (dias is None or dias >= refazer_dias) and not _tratada(ultimo_refazer_ts, engajamento.ultima_interacao):
        return Avaliacao("inatividade", True, "refazer_trilha", None,
                         f"Inatividade longa ({texto_dias}; limite {refazer_dias}): refazer a trilha a partir de hoje.")
    if _tratada(ultimo_incentivo_ts, engajamento.ultima_interacao) or \
            _tratada(ultimo_refazer_ts, engajamento.ultima_interacao):
        return Avaliacao("inatividade", False, "nenhuma", None,
                         f"Inatividade ({texto_dias}) já tratada; aguardando o aluno voltar.")
    return Avaliacao("inatividade", True, "incentivar", None,
                     f"Inatividade ({texto_dias}; limite {INATIVIDADE_DIAS}): enviar incentivo, sem refazer a trilha "
                     f"(a trilha só é refeita a partir de {refazer_dias} dias).")


def aviso_conclusao(concluida: str, proxima: str | None) -> str:
    seguinte = AVISO_SEGUINTE.format(proxima=proxima) if proxima else AVISO_FIM_DA_TRILHA
    return AVISO_CONCLUSAO.format(concluida=concluida, seguinte=seguinte)


def proxima_acao(estado: EstadoAluno) -> ProximaAcao:
    """O que o aluno deve fazer agora (no fluxo gerenciado)."""
    reforco = estado.reforco
    if reforco is not None:
        motivo = (f"Reforço de '{reforco.competencia_reforco}' antes de voltar a '{reforco.competencia_original}' "
                  f"(sessão pausada).")
        if reforco.estado == "em_andamento":
            return ProximaAcao(acao="continuar_sessao", competencia_id=reforco.competencia_reforco,
                               sessao_id=reforco.sessao_reforco_id, reforco=True, motivo=motivo)
        return ProximaAcao(acao="iniciar_sessao", competencia_id=reforco.competencia_reforco, reforco=True,
                           motivo=motivo + " Abra com POST /aluno/{id}/sessao.")
    if estado.concluido:
        return ProximaAcao(acao="concluido",
                           motivo="Todas as etapas da trilha concluídas; o relatório está em /relatorio/aluno.")
    if estado.sessao_aberta_id:
        return ProximaAcao(acao="continuar_sessao", competencia_id=estado.competencia_atual,
                           sessao_id=estado.sessao_aberta_id,
                           motivo=f"Há sessão em andamento em '{estado.competencia_atual}'.")
    return ProximaAcao(acao="iniciar_sessao", competencia_id=estado.competencia_atual,
                       motivo=f"Próxima etapa da trilha: '{estado.competencia_atual}'. Abra com POST /aluno/{{id}}/sessao.")
