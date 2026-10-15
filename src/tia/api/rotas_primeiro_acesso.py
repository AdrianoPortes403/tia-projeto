"""
Rotas do primeiro acesso do aluno (Agente 1, contrato 1.3.2): onboarding
conversacional -> diagnóstico inicial -> matrícula no fluxo (trilha gerada
pelo Planejador com o perfil enquadrado pelo diagnóstico).

    GET  /aluno/{id}/primeiro-acesso                  em que passo o aluno está
    POST /aluno/{id}/onboarding/iniciar               primeira mensagem do tutor (recomeça se já havia)
    POST /aluno/{id}/onboarding/mensagem              resposta do aluno -> próxima pergunta
    POST /aluno/{id}/diagnostico/iniciar              primeira questão do diagnóstico (trilha do onboarding)
    POST /aluno/{id}/diagnostico/responder            resposta -> próxima questão ou fim
    POST /aluno/{id}/primeiro-acesso/concluir         matricula com onboarding + diagnóstico + piloto

Autenticação (1.4.6): só o próprio aluno (leitura do passo: também docente, mas
sem o objetivo, que é texto livre do aluno; R08).
Nada disso é permitido depois da matrícula (409): o replanejamento é das regras.
A conversa aceita até ONBOARDING_MAX_MENSAGENS mensagens (depois, 409: recomeçar).

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, o onboarding usa regras)
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from tia import orquestrador
from tia.agentes.planejador import diagnostico, onboarding
from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.planejador.planejar import CicloPrerequisitos, ErroPlanejador
from tia.agentes.tutor.modelos import Pergunta
from tia.core.config import PILOTO_ESCOPO, PILOTO_PRAZO_DIAS
from tia.orquestrador import repositorio as repositorio_orquestrador
from tia.orquestrador.modelos import Matricula, ResultadoMatricula
from tia.seguranca.acesso import SEM_LOGIN, UsuarioSessao, acesso_ao_aluno

router = APIRouter(prefix="/aluno", tags=["primeiro acesso"])
SoOAluno = [Depends(acesso_ao_aluno())]
CodigoNaRota = Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]


class MensagemOnboarding(BaseModel):
    texto: str = Field(min_length=1, max_length=500)


class InicioOnboarding(BaseModel):
    resposta: str
    proxima_pergunta: str


class RespostaDiagnostico(BaseModel):
    item_id: str = Field(min_length=1, max_length=64)
    indice_escolhido: int = Field(ge=0, le=3)


class SituacaoDiagnostico(BaseModel):
    pergunta: Pergunta | None = None      # questão atual (sem gabarito); None se concluído
    acertou: bool | None = None           # resultado da resposta anterior (None ao iniciar)
    concluido: bool
    topico_atual: int                     # 1..total (posição do tópico em avaliação)
    total_topicos: int
    notas: dict[str, float] | None = None  # só depois de concluído


class PassoPrimeiroAcesso(BaseModel):
    passo: Literal["onboarding", "diagnostico", "concluir", "matriculado"]
    onboarding: dict | None = None        # dados já coletados (sem o texto da conversa)
    diagnostico_concluido: bool = False
    prazo_dias: int | None = None
    escopo: str


def _prazo() -> int | None:
    return PILOTO_PRAZO_DIAS or None


def _exigir_nao_matriculado(aluno_id: str):
    if repositorio_orquestrador.ler_matricula(aluno_id) is not None:
        raise HTTPException(status_code=409, detail="O aluno já está matriculado; o primeiro acesso já foi feito.")


def _pergunta(item_id: str | None) -> Pergunta | None:
    if item_id is None:
        return None
    item = next(i for i in diagnostico.carregar_itens() if i["id"] == item_id)
    return Pergunta(item_id=item["id"], competencia_id=item["competencia_id"], nivel=item["nivel"],
                    enunciado=item["enunciado"], alternativas=item["alternativas"])


def _situacao(estado: diagnostico.EstadoDiagnostico, acertou: bool | None = None) -> SituacaoDiagnostico:
    total = len(estado.topicos)
    return SituacaoDiagnostico(pergunta=_pergunta(estado.item_atual_id), acertou=acertou, concluido=estado.concluido,
                               topico_atual=min(estado.indice + 1, total), total_topicos=total,
                               notas=dict(estado.notas) if estado.concluido else None)


# campos do cadastro que só o próprio aluno recebe (texto livre; R08)
SO_DO_ALUNO = ("objetivo",)


@router.get("/{aluno_id}/primeiro-acesso", response_model=PassoPrimeiroAcesso)
def passo(aluno_id: CodigoNaRota,
          usuario: UsuarioSessao = Depends(acesso_ao_aluno("docente"))) -> PassoPrimeiroAcesso:
    """Em que passo do primeiro acesso o aluno está. O docente não recebe o objetivo."""
    comum = {"prazo_dias": _prazo(), "escopo": PILOTO_ESCOPO}
    if repositorio_orquestrador.ler_matricula(aluno_id) is not None:
        return PassoPrimeiroAcesso(passo="matriculado", **comum)
    sessao = onboarding.ler(aluno_id)
    dados = None
    if sessao is not None:
        do_aluno = usuario.papel in ("aluno", SEM_LOGIN)  # SEM_LOGIN: só no modo de desenvolvimento
        dados = {k: v for k, v in sessao.dados.items() if do_aluno or k not in SO_DO_ALUNO}
    if sessao is None or not sessao.concluido:
        return PassoPrimeiroAcesso(passo="onboarding", onboarding=dados, **comum)
    estado = diagnostico.ler(aluno_id)
    feito = estado is not None and estado.concluido and estado.trilha == sessao.dados.get("trilha")
    return PassoPrimeiroAcesso(passo="concluir" if feito else "diagnostico", onboarding=dados,
                               diagnostico_concluido=feito, **comum)


@router.post("/{aluno_id}/onboarding/iniciar", response_model=InicioOnboarding, dependencies=SoOAluno)
def iniciar_onboarding(aluno_id: CodigoNaRota) -> InicioOnboarding:
    """Começa (ou recomeça) a conversa de cadastro."""
    _exigir_nao_matriculado(aluno_id)
    sessao, mensagem = onboarding.nova_sessao(aluno_id, onboarding.ler(aluno_id))
    onboarding.salvar(sessao, auditar="inicio")
    return InicioOnboarding(resposta=mensagem, proxima_pergunta=sessao.ultima_pergunta)


@router.post("/{aluno_id}/onboarding/mensagem", response_model=onboarding.RespostaOnboarding, dependencies=SoOAluno)
def mensagem_onboarding(aluno_id: CodigoNaRota, mensagem: MensagemOnboarding) -> onboarding.RespostaOnboarding:
    """Resposta do aluno na conversa de cadastro -> próxima pergunta."""
    _exigir_nao_matriculado(aluno_id)
    sessao = onboarding.ler(aluno_id)
    if sessao is None:
        raise HTTPException(status_code=404, detail="Cadastro não iniciado; use POST /aluno/{id}/onboarding/iniciar.")
    try:
        resposta = onboarding.processar(sessao, mensagem.texto, _prazo())
    except onboarding.ErroOnboarding as erro:
        raise HTTPException(status_code=409, detail=str(erro))
    onboarding.salvar(sessao, auditar=resposta.origem)
    return resposta


@router.post("/{aluno_id}/diagnostico/iniciar", response_model=SituacaoDiagnostico, dependencies=SoOAluno)
def iniciar_diagnostico(aluno_id: CodigoNaRota) -> SituacaoDiagnostico:
    """Começa (ou recomeça) o diagnóstico na trilha escolhida no cadastro."""
    _exigir_nao_matriculado(aluno_id)
    sessao = onboarding.ler(aluno_id)
    if sessao is None or not sessao.concluido:
        raise HTTPException(status_code=409, detail="Conclua o cadastro (onboarding) antes do diagnóstico.")
    return _situacao(diagnostico.comecar(aluno_id, sessao.dados["trilha"]))


@router.post("/{aluno_id}/diagnostico/responder", response_model=SituacaoDiagnostico, dependencies=SoOAluno)
def responder_diagnostico(aluno_id: CodigoNaRota, resposta: RespostaDiagnostico) -> SituacaoDiagnostico:
    """Resposta à questão atual do diagnóstico -> próxima questão ou fim."""
    _exigir_nao_matriculado(aluno_id)
    try:
        acertou, estado = diagnostico.responder(aluno_id, resposta.item_id, resposta.indice_escolhido)
    except diagnostico.DiagnosticoInexistente as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except diagnostico.RespostaForaDeOrdem as erro:
        raise HTTPException(status_code=409, detail=str(erro))
    return _situacao(estado, acertou)


@router.post("/{aluno_id}/primeiro-acesso/concluir", response_model=ResultadoMatricula, dependencies=SoOAluno)
def concluir(aluno_id: CodigoNaRota) -> ResultadoMatricula:
    """Matricula o aluno: trilha e horas do cadastro, notas do diagnóstico e,
    no piloto, prazo e escopo da configuração (PILOTO_PRAZO_DIAS, PILOTO_ESCOPO)."""
    _exigir_nao_matriculado(aluno_id)
    sessao = onboarding.ler(aluno_id)
    estado = diagnostico.ler(aluno_id)
    if sessao is None or not sessao.concluido:
        raise HTTPException(status_code=409, detail="Conclua o cadastro (onboarding) antes de montar a trilha.")
    if estado is None or not estado.concluido or estado.trilha != sessao.dados["trilha"]:
        raise HTTPException(status_code=409, detail="Conclua o diagnóstico antes de montar a trilha.")
    matricula = Matricula(trilha=sessao.dados["trilha"], horas_semanais=sessao.dados["horas_semana"],
                          diagnostico=dict(estado.notas), prazo_dias=_prazo(),
                          escopo="piloto" if PILOTO_ESCOPO == "piloto" else "completa")
    try:
        return orquestrador.iniciar(aluno_id, matricula)
    except orquestrador.JaMatriculado as erro:
        raise HTTPException(status_code=409, detail=str(erro))
    except CicloPrerequisitos as erro:
        raise HTTPException(status_code=500, detail=str(erro))
    except ErroPlanejador as erro:
        raise HTTPException(status_code=422, detail=str(erro))

