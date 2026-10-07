"""
Rotas da API do Agente 1 (Planejador).

    POST /planejador/trilha        gera a trilha do aluno, salva e devolve
    GET  /alunos/{aluno_id}/trilha lê a última trilha salva (404 se não houver)

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, justificativas padrão)
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from tia.agentes.planejador import planejar_e_salvar
from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO, EntradaPlanejador, Trilha
from tia.agentes.planejador.planejar import CicloPrerequisitos, ErroPlanejador
from tia.agentes.planejador.repositorio import ler_trilha

router = APIRouter(tags=["planejador"])


@router.post("/planejador/trilha", response_model=Trilha)
def criar_trilha(entrada: EntradaPlanejador) -> Trilha:
    """Gera a trilha a partir do diagnóstico e salva (substitui a anterior)."""
    try:
        return planejar_e_salvar(entrada)
    except CicloPrerequisitos as erro:
        # defeito no conteúdo da ementa, não no pedido
        raise HTTPException(status_code=500, detail=str(erro))
    except ErroPlanejador as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router.get("/alunos/{aluno_id}/trilha", response_model=Trilha)
def obter_trilha(aluno_id: Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]) -> Trilha:
    """Devolve a trilha salva do aluno."""
    trilha = ler_trilha(aluno_id)
    if trilha is None:
        raise HTTPException(status_code=404, detail="Nenhuma trilha encontrada para este aluno.")
    return trilha
