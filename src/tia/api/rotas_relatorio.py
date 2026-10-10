"""
Rotas da API do Agente 3 (Relatório), em JSON estruturado para o dashboard (1.4.5).

    GET /relatorio/aluno/{aluno_id}  relatório do aluno (visão do próprio aluno)
    GET /relatorio/turma             relatório agregado da instituição; ?perfil_id=
                                     restringe a um perfil (não existe turma no banco)

?narrativa=false pula o LLM (o parágrafo de interpretação vira o texto
fixo); os indicadores são os mesmos. Toda geração entra na auditoria (R11).

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, texto fixo)
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.agentes.relatorio import gerar_relatorio_aluno, gerar_relatorio_turma
from tia.agentes.relatorio.modelos import RelatorioAluno, RelatorioTurma

router = APIRouter(prefix="/relatorio", tags=["relatorio"])


# TODO 1.4.6: exigir autenticação (o próprio aluno ou um docente)
@router.get("/aluno/{aluno_id}", response_model=RelatorioAluno)
def relatorio_aluno(aluno_id: Annotated[str, Path(pattern=PADRAO_CODIGO_ALUNO)],
                    narrativa: bool = True) -> RelatorioAluno:
    """Indicadores do aluno e um parágrafo de interpretação."""
    relatorio = gerar_relatorio_aluno(aluno_id, com_narrativa=narrativa)
    if relatorio is None:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")
    return relatorio


# TODO 1.4.6: exigir autenticação de docente
@router.get("/turma", response_model=RelatorioTurma)
def relatorio_turma(perfil_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
                    narrativa: bool = True) -> RelatorioTurma:
    """Indicadores agregados (sem grupos com menos de RELATORIO_MIN_GRUPO alunos)."""
    return gerar_relatorio_turma(perfil_id, com_narrativa=narrativa)
