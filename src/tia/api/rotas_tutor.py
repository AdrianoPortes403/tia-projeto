"""
Rotas da API do Agente 2 (Tutor), parte 2a: questionário adaptativo.

    POST /tutor/sessao    inicia (aluno_id, competencia_id) e devolve a primeira pergunta.
                          Uso STANDALONE: não passa pelo orquestrador (não confere a
                          competência atual nem as regras). No fluxo gerenciado, use
                          POST /aluno/{id}/sessao
    POST /tutor/resposta  corrige, devolve o Feedback e a próxima pergunta (ou o fim)
    POST /tutor/perguntar diálogo livre: resposta ancorada no material, com fonte (R03)
    GET  /alunos/{aluno_id}/dialogo   histórico do diálogo (resposta vetada sai trocada
                                      pela correção do docente)
    PATCH /tutor/dialogo/{id}/veto    veto docente (R12): vetada + correcao_docente
    GET  /tutor/incentivo/{aluno_id}  inatividade e mensagem de incentivo (template, sem LLM)

aluno_id é validado como código (mesmo padrão do Planejador, R08). Os logs
do agente não registram aluno_id nem respostas.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, feedback com o texto do item)
    - Material indexado: python -m tia.rag.ingest
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.tutor import (
    CompetenciaInexistente, RespostaForaDeOrdem, SessaoInexistente, iniciar_sessao, repositorio, responder,
)
from tia.agentes.tutor.dialogo import perguntar
from tia.agentes.tutor.incentivo import montar_incentivo
from tia.agentes.tutor.modelos import (
    Feedback, Incentivo, IniciarSessao, ItemDialogo, PerguntaAluno, RespostaAluno, RespostaDialogo,
    SessaoIniciada, Veto,
)

router = APIRouter(tags=["tutor"])


@router.post("/tutor/sessao", response_model=SessaoIniciada)
def criar_sessao(entrada: IniciarSessao) -> SessaoIniciada:
    """Abre uma sessão de questionário na competência (começa no nível 1)."""
    try:
        return iniciar_sessao(entrada)
    except CompetenciaInexistente as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router.post("/tutor/resposta", response_model=Feedback)
def enviar_resposta(resposta: RespostaAluno) -> Feedback:
    """Corrige a resposta ao item atual e devolve o feedback com as fontes."""
    try:
        return responder(resposta)
    except SessaoInexistente as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except RespostaForaDeOrdem as erro:
        raise HTTPException(status_code=409, detail=str(erro))


@router.post("/tutor/perguntar", response_model=RespostaDialogo)
def enviar_pergunta(entrada: PerguntaAluno) -> RespostaDialogo:
    """Responde à pergunta livre do aluno só com o material do curso (até 500 caracteres)."""
    try:
        return perguntar(entrada)
    except CompetenciaInexistente as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router.get("/alunos/{aluno_id}/dialogo", response_model=list[ItemDialogo])
def obter_dialogo(aluno_id: Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]) -> list[dict]:
    """Histórico do diálogo do aluno; resposta vetada vem com a correção do docente."""
    return repositorio.listar_dialogo(aluno_id)


# TODO 1.4.6: exigir autenticação de docente
@router.patch("/tutor/dialogo/{dialogo_id}/veto", response_model=ItemDialogo)
def vetar(dialogo_id: int, veto: Veto) -> dict:
    """Veta (ou retira o veto de) uma resposta do diálogo (R12)."""
    if not repositorio.vetar_dialogo(dialogo_id, veto.vetada, veto.correcao_docente):
        raise HTTPException(status_code=404, detail="Diálogo não encontrado.")
    return repositorio.ler_dialogo(dialogo_id)


@router.get("/tutor/incentivo/{aluno_id}", response_model=Incentivo)
def obter_incentivo(aluno_id: Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]) -> Incentivo:
    """Diz se o aluno está inativo e devolve a mensagem de incentivo (registrada na auditoria)."""
    incentivo = montar_incentivo(aluno_id)
    repositorio.registrar_incentivo(aluno_id, incentivo.proxima_etapa)
    return incentivo
