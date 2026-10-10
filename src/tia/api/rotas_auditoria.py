"""
Rotas da auditoria das interações do Tutor (requisito R11).

    GET /auditoria/{aluno_id}  lista as interações do aluno (resposta de item,
                               diálogo, incentivo), da mais antiga para a mais
                               recente, sem texto livre

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - tabelas criadas/migradas (a API faz isso ao subir)
"""

from typing import Annotated

from fastapi import APIRouter, Path

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.tutor.modelos import RegistroAuditoria
from tia.core import auditoria

router = APIRouter(tags=["auditoria"])


# TODO 1.4.6: exigir autenticação de docente
@router.get("/auditoria/{aluno_id}", response_model=list[RegistroAuditoria])
def listar_auditoria(aluno_id: Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)]) -> list[dict]:
    """Interações do Tutor com o aluno (lista vazia se não houver)."""
    return auditoria.listar(aluno_id)
