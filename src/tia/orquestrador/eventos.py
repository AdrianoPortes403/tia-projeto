"""
Processamento dos eventos do Tutor pela Orquestração (POST /aluno/{id}/evento).

Idempotência: o evento_id é reservado antes de processar. Repetir o mesmo
id devolve o resultado gravado (repetido=True), sem chamar o Tutor nem o
Planejador de novo; se o docente vetou o feedback nesse meio-tempo, o
reenvio traz a correção do docente, nunca o texto vetado (R12). Se o
processamento falha, a reserva é desfeita e o evento pode ser reenviado.

    resposta:    repassa a resposta ao Tutor (tutor.responder; sessão pausada é
                 recusada). Se a sessão concluiu: sendo de reforço, retoma a
                 sessão original (sem zerar); senão, avalia R1 (conclusão). Se
                 não concluiu, avalia R2 (queda). Só grava decisão quando algo
                 acontece (não registra "nenhuma" a cada resposta);
    conclusao:   confere no banco e avalia R1; grava a decisão, mesmo "nenhuma";
    inatividade: avalia R3 só para este aluno (o mesmo que a verificação
                 agendada faz para todos); grava a decisão, mesmo "nenhuma".

Não é executável sozinho; demonstração:
    python -m tia.orquestrador --demo

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

from datetime import datetime

from tia.agentes import tutor
from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.relatorio import indicadores
from tia.agentes.relatorio.repositorio import ler_dados_aluno
from tia.agentes.tutor.modelos import RespostaAluno
from tia.orquestrador import fluxo, regras, repositorio
from tia.orquestrador.modelos import DecisaoReplanejamento, EventoTutor, ResultadoEvento


class EventoConflitante(fluxo.ErroOrquestracao):
    """evento_id já usado por outro aluno/tipo, ou ainda em processamento."""


def _ja_avancou(aluno_id: str, competencia_id: str) -> bool:
    return any(d["competencia_id"] == competencia_id for d in repositorio.listar_decisoes(aluno_id, "avancar"))


def _avaliar_queda(aluno_id: str, competencia_id: str | None, sessao_id: str) -> regras.Avaliacao:
    dados = ler_dados_aluno(aluno_id)
    reforcos = repositorio.listar_decisoes(aluno_id, "reforcar")
    desde = sum(r["ts"] > reforcos[-1]["ts"] for r in dados.respostas) if reforcos else None
    ativo = repositorio.reforco_ativo(aluno_id)
    return regras.regra_queda(
        indicadores.tendencia(dados.respostas), competencia_id, desde, sessao_id,
        sessao_ja_reforcada=any(r["sessao_id"] == sessao_id for r in reforcos),
        em_reforco=ativo is not None and ativo["sessao_reforco_id"] == sessao_id,
        prerequisito=regras.prerequisito_direto(competencia_id, carregar_ementa()) if competencia_id else None)


def _avaliar_lacuna(aluno_id: str, competencia_id: str | None, sessao_id: str) -> regras.Avaliacao:
    reforcos = repositorio.listar_decisoes(aluno_id, "reforcar")
    ativo = repositorio.reforco_ativo(aluno_id)
    return regras.regra_lacuna(
        competencia_id, sessao_id,
        regras.prerequisito_direto(competencia_id, carregar_ementa()) if competencia_id else None,
        em_reforco=ativo is not None and ativo["sessao_reforco_id"] == sessao_id,
        sessao_ja_reforcada=any(r["sessao_id"] == sessao_id for r in reforcos))


def _competencia_da_sessao(aluno_id: str, sessao_id: str) -> str | None:
    sessao = tutor.repositorio.ler_sessao(sessao_id, aluno_id)
    return sessao.competencia_id if sessao else None


def _despachar(aluno_id: str, evento: EventoTutor, agora: datetime) -> ResultadoEvento:
    decisoes: list[DecisaoReplanejamento] = []
    feedback = None
    if evento.tipo == "resposta":
        competencia = _competencia_da_sessao(aluno_id, evento.sessao_id)
        feedback = tutor.responder(RespostaAluno(sessao_id=evento.sessao_id, aluno_id=aluno_id,
                                                 item_id=evento.item_id, indice_escolhido=evento.indice_escolhido))
        if feedback.concluida:
            retomada = fluxo.concluir_reforco(aluno_id, evento.sessao_id, evento.evento_id, agora)
            if retomada is not None:
                decisoes.append(retomada)
            else:
                avaliacao = regras.regra_conclusao(competencia, tutor.repositorio.competencias_concluidas(aluno_id),
                                                   _ja_avancou(aluno_id, competencia))
                if avaliacao.dispara:
                    decisoes.append(fluxo.aplicar(aluno_id, avaliacao, evento.evento_id, agora))
        else:
            # lacuna (1.2.5) tem prioridade; se ela não agiu, avalia a queda (R2)
            avaliacao = _avaliar_lacuna(aluno_id, competencia, evento.sessao_id) if feedback.lacuna else None
            if avaliacao is None or not avaliacao.dispara:
                avaliacao = _avaliar_queda(aluno_id, competencia, evento.sessao_id)
            if avaliacao.dispara:
                decisoes.append(fluxo.aplicar(aluno_id, avaliacao, evento.evento_id, agora))
    elif evento.tipo == "conclusao":
        competencia = evento.competencia_id or _competencia_da_sessao(aluno_id, evento.sessao_id)
        if competencia is None:
            raise tutor.SessaoInexistente("Sessão não encontrada para este aluno.")
        avaliacao = regras.regra_conclusao(competencia, tutor.repositorio.competencias_concluidas(aluno_id),
                                           _ja_avancou(aluno_id, competencia))
        decisoes.append(fluxo.aplicar(aluno_id, avaliacao, evento.evento_id, agora))
    else:  # inatividade
        avaliacao = fluxo.avaliar_inatividade(aluno_id, ler_dados_aluno(aluno_id), agora)
        decisoes.append(fluxo.aplicar(aluno_id, avaliacao, evento.evento_id, agora))
    return ResultadoEvento(evento_id=evento.evento_id, tipo=evento.tipo, feedback=feedback, decisoes=decisoes,
                           avisos=[d.aviso for d in decisoes if d.aviso], proxima=fluxo.proxima(aluno_id, agora))


def _aplicar_veto(resultado: ResultadoEvento) -> ResultadoEvento:
    """No resultado gravado, troca a explicação vetada pela correção do docente."""
    feedback = resultado.feedback
    if feedback is None or feedback.resposta_id is None:
        return resultado
    atual = tutor.repositorio.ler_feedback(feedback.resposta_id)
    if atual is not None and atual["vetada"]:
        resultado.feedback = feedback.model_copy(update={
            "explicacao": atual["explicacao"], "fontes": [], "origem": "docente", "falha_llm": None})
    return resultado


def processar_evento(aluno_id: str, evento: EventoTutor, agora: datetime | None = None) -> ResultadoEvento:
    """Processa o evento uma única vez por evento_id. Levanta AlunoNaoMatriculado,
    EventoConflitante e os erros do Tutor (SessaoInexistente, RespostaForaDeOrdem)."""
    agora = fluxo.instante(agora)
    fluxo.exigir_matricula(aluno_id)  # AlunoNaoMatriculado antes de reservar o evento
    existente = repositorio.reservar_evento(evento.evento_id, aluno_id, evento.tipo, agora)
    if existente is not None:
        if (existente["aluno_id"], existente["tipo"]) != (aluno_id, evento.tipo):
            raise EventoConflitante(f"evento_id '{evento.evento_id}' já foi usado em outro evento.")
        if existente["resultado"] is None:
            raise EventoConflitante(f"Evento '{evento.evento_id}' ainda em processamento.")
        return _aplicar_veto(ResultadoEvento(**{**existente["resultado"], "repetido": True}))
    try:
        resultado = _despachar(aluno_id, evento, agora)
    except Exception:
        repositorio.cancelar_evento(evento.evento_id)
        raise
    repositorio.concluir_evento(evento.evento_id, resultado.model_dump())
    return resultado
