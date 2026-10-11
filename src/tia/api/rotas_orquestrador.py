"""
Rotas da Orquestração (EAP 1.3.5): fluxo ponta a ponta do aluno.

    POST /aluno/{aluno_id}/iniciar  matrícula: o Planejador gera a trilha inicial
    GET  /aluno/{aluno_id}/proximo  próxima ação: iniciar_sessao, continuar_sessao ou concluido
    POST /aluno/{aluno_id}/sessao   abre sessão do Tutor SÓ para a competência atual ou o
                                    reforço decidido; qualquer outra é recusada (409, auditada)
    POST /aluno/{aluno_id}/evento   evento do Tutor (resposta, conclusao, inatividade);
                                    idempotente por evento_id
    GET  /aluno/{aluno_id}/estado   estado do aluno nos três agentes
    POST /orquestrador/verificar-inatividade
                                    R3 em todos os alunos; para o agendador externo (cron/timer
                                    na VM), que não faz parte deste pacote

No fluxo gerenciado, a sessão é aberta por POST /aluno/{id}/sessao e as
respostas vão por evento "resposta", para o orquestrador avaliar as regras.
POST /tutor/sessao continua para uso standalone e NÃO passa pelo orquestrador.
O veto docente (R12), o histórico do diálogo e os relatórios continuam nas
rotas de cada agente, listadas em EstadoAluno.rotas.

Autenticação (1.4.6): escrita só pelo próprio aluno; leitura (proximo, estado)
pelo próprio aluno ou por um docente; verificar-inatividade por docente ou admin.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, textos fixos)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.planejador.planejar import CicloPrerequisitos, ErroPlanejador
from tia.agentes.tutor import RespostaForaDeOrdem, SessaoInexistente
from tia.seguranca.acesso import acesso_ao_aluno, exigir_papel
from tia import orquestrador
from tia.orquestrador.modelos import (EstadoAluno, EventoTutor, Matricula, PedidoSessao, ProximaAcao, ResultadoEvento,
                                      ResultadoMatricula, ResultadoVerificacao, SessaoOrquestrada)

router = APIRouter(prefix="/aluno", tags=["orquestracao"])
router_sistema = APIRouter(prefix="/orquestrador", tags=["orquestracao"])
SoOAluno = [Depends(acesso_ao_aluno())]                 # escrita: só o próprio aluno
AlunoOuDocente = [Depends(acesso_ao_aluno("docente"))]  # leitura: o próprio aluno ou um docente
CodigoNaRota = Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]


@router.post("/{aluno_id}/iniciar", response_model=ResultadoMatricula, dependencies=SoOAluno)
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


@router.get("/{aluno_id}/proximo", response_model=ProximaAcao, dependencies=AlunoOuDocente)
def proximo(aluno_id: CodigoNaRota) -> ProximaAcao:
    """O que o aluno deve fazer agora."""
    try:
        return orquestrador.proxima(aluno_id)
    except orquestrador.AlunoNaoMatriculado as erro:
        raise HTTPException(status_code=404, detail=str(erro))


@router.post("/{aluno_id}/sessao", response_model=SessaoOrquestrada, dependencies=SoOAluno)
def sessao(aluno_id: CodigoNaRota, pedido: PedidoSessao) -> SessaoOrquestrada:
    """Abre a sessão da competência atual ou do reforço; recusa qualquer outra."""
    try:
        return orquestrador.abrir_sessao(aluno_id, pedido.competencia_id)
    except orquestrador.AlunoNaoMatriculado as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except orquestrador.SessaoRecusada as erro:
        raise HTTPException(status_code=409, detail=str(erro))


@router.post("/{aluno_id}/evento", response_model=ResultadoEvento, dependencies=SoOAluno)
def evento(aluno_id: CodigoNaRota, evento_tutor: EventoTutor) -> ResultadoEvento:
    """Processa um evento do Tutor e as regras de replanejamento (uma vez por evento_id)."""
    try:
        return orquestrador.processar_evento(aluno_id, evento_tutor)
    except (orquestrador.AlunoNaoMatriculado, SessaoInexistente) as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except (orquestrador.EventoConflitante, RespostaForaDeOrdem) as erro:
        raise HTTPException(status_code=409, detail=str(erro))


@router.get("/{aluno_id}/estado", response_model=EstadoAluno, dependencies=AlunoOuDocente)
def estado(aluno_id: CodigoNaRota) -> EstadoAluno:
    """Estado do aluno: trilha, competência atual, tendência, inatividade, decisões e vetos."""
    try:
        return orquestrador.estado(aluno_id)
    except orquestrador.AlunoNaoMatriculado as erro:
        raise HTTPException(status_code=404, detail=str(erro))


# o agendador na VM usa o comando (python -m tia.orquestrador --verificar-inatividade), sem HTTP
@router_sistema.post("/verificar-inatividade", response_model=ResultadoVerificacao,
                     dependencies=[Depends(exigir_papel("docente", "admin"))])
def verificar_inatividade() -> ResultadoVerificacao:
    """Avalia a inatividade (R3) de todos os alunos e registra cada decisão na auditoria."""
    return orquestrador.verificar_inatividade()
