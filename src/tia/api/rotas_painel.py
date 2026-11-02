"""
Rotas SOMENTE DE LEITURA do painel do docente/instituição (EAP 1.4.5).

    GET /conteudo/ementa                competências (id, nome, pré-requisitos)
    GET /conteudo/perfis                perfis (id, nome)
    GET /painel/alunos-em-risco         alunos com inatividade, queda ou desempenho baixo,
                                        COM código (nunca nome); cada consulta vai para a
                                        auditoria (R11). ?perfil_id=
    GET /painel/alunos                  todos os alunos: código, perfil, competência atual,
                                        acerto e situação (nada além); auditada. ?perfil_id=
    GET /painel/competencias            acerto e tendência por competência e itens com erro
                                        repetido; só agregados (grupo mínimo, R08). ?perfil_id=
    GET /painel/revisao                 respostas do diálogo e feedbacks das questões para o
                                        veto docente (R12); auditada. ?tipo=dialogo|feedback
                                        &situacao=a_revisar|aprovadas|vetadas|todas&origem=
                                        &competencia_id=&pagina=
    GET /painel/revisao/contagem        só o número de textos a revisar (contador do menu);
                                        sem códigos, NÃO auditada. ?origem=
    GET /painel/auditoria               trilha de auditoria filtrável e paginada
                                        ?agente=&aluno_id=&desde=&ate=&pagina=&por_pagina=
    GET /painel/exportar/indicadores.csv  indicadores agregados do Agente 3 em CSV. ?perfil_id=

A escrita do painel (aprovar e vetar) usa as rotas do Tutor (tia.api.rotas_tutor):
PATCH /tutor/dialogo/{id}/veto e PATCH /tutor/feedback/{resposta_id}/veto.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - tabelas criadas/migradas (a API faz isso ao subir)
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from tia.agentes.planejador.modelos import PADRAO_CODIGO_ALUNO
from tia.core import auditoria
from tia.painel import consultas
from tia.seguranca.acesso import exigir_papel, usuario_atual
from tia.painel.modelos import (CompetenciaEmenta, ConsultaRisco, ContagemRevisao, DesempenhoCompetencias,
                                ListaAlunos, ListaRevisao, PaginaAuditoria, PerfilResumo, SituacaoRevisao,
                                TipoRevisao)

# Autenticação (1.4.6): /painel/* só docente (a auditoria grava quem consultou);
# /conteudo/* qualquer usuário logado (ementa e perfis não têm dado pessoal)
router = APIRouter(prefix="/painel", tags=["painel"], dependencies=[Depends(exigir_papel("docente"))])
router_conteudo = APIRouter(prefix="/conteudo", tags=["painel"], dependencies=[Depends(usuario_atual)])

Perfil = Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")]  # vai para o nome do arquivo CSV
Origem = Literal["LLM", "guarda", "fallback"]
Data = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2026-10-11"])]


@router_conteudo.get("/ementa", response_model=list[CompetenciaEmenta])
def listar_ementa() -> list[CompetenciaEmenta]:
    """Competências da ementa (validada pela Pessoa 4)."""
    return consultas.ementa()


@router_conteudo.get("/perfis", response_model=list[PerfilResumo])
def listar_perfis() -> list[PerfilResumo]:
    """Perfis de aluno (validados pela Pessoa 4)."""
    return consultas.perfis()


@router.get("/alunos-em-risco", response_model=ConsultaRisco)
def alunos_em_risco(perfil_id: Perfil = None) -> ConsultaRisco:
    """Alunos em risco, com código; a consulta é registrada na auditoria."""
    return consultas.alunos_em_risco(perfil_id)


@router.get("/alunos", response_model=ListaAlunos)
def alunos(perfil_id: Perfil = None) -> ListaAlunos:
    """Alunos com código, perfil, competência atual, acerto e situação; a consulta é auditada."""
    return consultas.listar_alunos_turma(perfil_id)


@router.get("/competencias", response_model=DesempenhoCompetencias)
def competencias(perfil_id: Perfil = None) -> DesempenhoCompetencias:
    """Acerto agregado e tendência por competência; itens com erro repetido."""
    return consultas.desempenho_competencias(perfil_id)


@router.get("/revisao", response_model=ListaRevisao)
def revisao(situacao: SituacaoRevisao = "a_revisar",
            origem: Origem | None = None,
            tipo: TipoRevisao | None = None,
            competencia_id: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = None,
            pagina: Annotated[int, Query(ge=1)] = 1,
            por_pagina: Annotated[int, Query(ge=1, le=100)] = 20) -> ListaRevisao:
    """Respostas do diálogo e feedbacks das questões para revisão (original + correção)."""
    return consultas.listar_revisao(situacao, origem, pagina, por_pagina, tipo, competencia_id)


@router.get("/revisao/contagem", response_model=ContagemRevisao)
def revisao_contagem(origem: Origem | None = None) -> ContagemRevisao:
    """Só o número de textos a revisar (sem códigos; não auditada)."""
    return consultas.contar_a_revisar(origem)


@router.get("/auditoria", response_model=PaginaAuditoria)
def consultar_auditoria(agente: Literal[auditoria.AGENTES] | None = None,
                        aluno_id: Annotated[str | None, Query(pattern=PADRAO_CODIGO_ALUNO)] = None,
                        desde: Data = None, ate: Data = None,
                        pagina: Annotated[int, Query(ge=1)] = 1,
                        por_pagina: Annotated[int, Query(ge=1, le=100)] = 25) -> PaginaAuditoria:
    """Registros de auditoria (mais recentes primeiro), com o agente responsável."""
    total, registros = auditoria.consultar(agente, aluno_id, desde, ate, pagina, por_pagina)
    return PaginaAuditoria(total=total, pagina=pagina, por_pagina=por_pagina, registros=registros)


@router.get("/exportar/indicadores.csv", response_class=Response)
def exportar_indicadores(perfil_id: Perfil = None) -> Response:
    """Indicadores agregados (sem códigos de aluno) em CSV para planilha."""
    nome = "indicadores_tia" + (f"_{perfil_id}" if perfil_id else "") + ".csv"
    return Response(content=consultas.exportar_indicadores_csv(perfil_id), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})
