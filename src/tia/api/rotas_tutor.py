"""
Rotas da API do Agente 2 (Tutor), parte 2a: questionário adaptativo.

    POST /tutor/sessao    inicia (aluno_id, competencia_id) e devolve a primeira pergunta
    POST /tutor/resposta  corrige, devolve o Feedback e a próxima pergunta (ou o fim)

aluno_id é validado como código (mesmo padrão do Planejador, R08). Os logs
do agente não registram aluno_id nem respostas.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, feedback com o texto do item)
    - Material indexado: python -m tia.rag.ingest
"""

from fastapi import APIRouter, HTTPException

from tia.agentes.tutor import (
    CompetenciaInexistente, RespostaForaDeOrdem, SessaoInexistente, iniciar_sessao, responder,
)
from tia.agentes.tutor.modelos import Feedback, IniciarSessao, RespostaAluno, SessaoIniciada

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post("/sessao", response_model=SessaoIniciada)
def criar_sessao(entrada: IniciarSessao) -> SessaoIniciada:
    """Abre uma sessão de questionário na competência (começa no nível 1)."""
    try:
        return iniciar_sessao(entrada)
    except CompetenciaInexistente as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router.post("/resposta", response_model=Feedback)
def enviar_resposta(resposta: RespostaAluno) -> Feedback:
    """Corrige a resposta ao item atual e devolve o feedback com as fontes."""
    try:
        return responder(resposta)
    except SessaoInexistente as erro:
        raise HTTPException(status_code=404, detail=str(erro))
    except RespostaForaDeOrdem as erro:
        raise HTTPException(status_code=409, detail=str(erro))
