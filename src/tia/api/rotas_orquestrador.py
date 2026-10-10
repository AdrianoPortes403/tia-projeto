"""
Rotas da Orquestração (EAP 1.3.5): fluxo ponta a ponta do aluno.

    POST /aluno/{aluno_id}/iniciar  matrícula: o Planejador gera a trilha inicial
    GET  /aluno/{aluno_id}/proximo  próxima ação: iniciar_sessao, continuar_sessao,
                                    replanejar ou concluido
    POST /aluno/{aluno_id}/evento   evento do Tutor (resposta, conclusao, inatividade);
                                    idempotente por evento_id
    GET  /aluno/{aluno_id}/estado   estado do aluno nos três agentes

A sessão do Tutor é aberta por POST /tutor/sessao (o "proximo" diz a
competência), e as respostas vão por evento "resposta", para o orquestrador
avaliar as regras de replanejamento. O veto docente (R12), o histórico do
diálogo e os relatórios continuam nas rotas de cada agente, listadas em
EstadoAluno.rotas.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, textos fixos)
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.planejador.planejar import CicloPrerequisitos, ErroPlanejador
from tia.agentes.tutor import RespostaForaDeOrdem, SessaoInexistente
from tia import orquestrador
from tia.orquestrador.modelos import EstadoAluno, EventoTutor, Matricula, ProximaAcao, ResultadoEvento, ResultadoMatricula

router = APIRouter(prefix="/aluno", tags=["orquestracao"])
CodigoNaRota = Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]


# TODO 1.4.6: exigir autenticação (o próprio aluno ou um docente)
@router.post("/{aluno_id}/iniciar", response_model=ResultadoMatricula)
def iniciar(aluno_id: CodigoNaRota, matricula: Matricula) -> ResultadoMatricula:
    """Matricula o aluno no fluxo e gera a trilha inicial."""
    try:
        return orquestrador.iniciar(aluno_id, matricula)
    except orquestrador.JaMatriculado as erro:
        raise HTTPException(status_code=409, detail=str(erro))
    except CicloPrerequisitos as erro:
        raise HTTPException(status_code=500, detail=str(erro))  # defeito da ementa, não do pedido
    except ErroPlanejador as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router.get("/{aluno_id}/proximo", response_model=ProximaAcao)
def proximo(aluno_id: CodigoNaRota) -> ProximaAcao:
    """O que o aluno deve fazer agora."""
    try:
        return orquestrador.proxima(aluno_id)
    except orquestrador.AlunoNaoMatriculado as erro:
        raise HTTPException(status_code=404, detail=str(erro))


@router.post("/{aluno_id}/evento", response_model=ResultadoEvento)
def evento(aluno_id: CodigoNaRota, evento_tutor: EventoTutor) -> ResultadoEvento:
    """Processa um evento do Tutor e as regras de replanejamento (uma vez por evento_id)."""
    try:
        return orquestrador.processar_evento(aluno_id, evento_tutor)
    except (orquestrador.AlunoNaoMatriculado, SessaoInexistente) as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except (orquestrador.EventoConflitante, RespostaForaDeOrdem) as erro:
        raise HTTPException(status_code=409, detail=str(erro))


@router.get("/{aluno_id}/estado", response_model=EstadoAluno)
def estado(aluno_id: CodigoNaRota) -> EstadoAluno:
    """Estado do aluno: trilha, competência atual, tendência, inatividade, decisões e vetos."""
    try:
        return orquestrador.estado(aluno_id)
    except orquestrador.AlunoNaoMatriculado as erro:
        raise HTTPException(status_code=404, detail=str(erro))
