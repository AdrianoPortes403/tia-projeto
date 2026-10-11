"""
Modelos Pydantic das rotas de leitura do painel do docente (EAP 1.4.5).

Os números agregados seguem a mesma regra do Agente 3: contagem de alunos
abaixo de RELATORIO_MIN_GRUPO sai como Contagem(valor=None, texto="menos de N")
e grupo abaixo do mínimo sai suprimido (R08). Só as rotas de alertas de
risco e de revisão mostram códigos de aluno (nunca nomes), e cada consulta
delas é registrada na auditoria.

Não é executável: importar com "from tia.painel.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Literal

from pydantic import BaseModel

from tia.agentes.relatorio.modelos import Contagem, Direcao

TipoRisco = Literal["inatividade", "desempenho_em_queda", "desempenho_baixo"]
SituacaoRevisao = Literal["a_revisar", "aprovadas", "vetadas", "todas"]


# --- conteúdo (ementa e perfis) ---

class CompetenciaEmenta(BaseModel):
    id: str
    nome: str
    prerequisitos: list[str] = []


class PerfilResumo(BaseModel):
    id: str
    nome: str


# --- alertas de risco (com códigos de aluno) ---

class MotivoRisco(BaseModel):
    tipo: TipoRisco
    descricao: str


class AlunoEmRisco(BaseModel):
    aluno_id: str  # código, nunca nome (R08)
    perfil_id: str | None
    motivos: list[MotivoRisco]
    dias_inativo: int | None
    respostas: int
    taxa_acerto: float | None
    tendencia: Direcao
    progresso: float | None  # fração das etapas da trilha concluídas


class ConsultaRisco(BaseModel):
    gerado_em: str
    perfil_id: str | None
    criterios: dict[str, int | float]  # limiares usados (todos PROVISÓRIOS, em core/config.py)
    alunos_avaliados: int
    alunos: list[AlunoEmRisco]
    auditoria_id: int  # registro desta consulta na auditoria (R11)


# --- desempenho por competência (só agregados) ---

class CompetenciaTurma(BaseModel):
    competencia_id: str
    nome: str
    alunos: Contagem
    suprimido: bool
    respostas: int | None = None
    taxa: float | None = None
    # quantos alunos com a tendência subindo/caindo/estavel/insuficiente na competência;
    # None quando a competência está suprimida
    tendencia: dict[str, Contagem] | None = None


class ItemTurma(BaseModel):
    """Item com erro repetido, respondido por pelo menos min_grupo alunos."""
    item_id: str
    competencia_id: str
    nome_competencia: str
    nivel: int | None
    enunciado: str
    alunos_com_erro: Contagem
    respostas: int
    taxa_erro: float


class DesempenhoCompetencias(BaseModel):
    gerado_em: str
    perfil_id: str | None
    min_grupo: int
    alunos: Contagem
    suprimido: bool
    competencias: list[CompetenciaTurma] = []
    itens_fracos: list[ItemTurma] = []


# --- revisão docente (R12) ---

class ItemRevisao(BaseModel):
    """Resposta do diálogo como o docente vê: a original e, se vetada, a correção."""
    dialogo_id: int
    ts: str
    aluno_id: str
    competencia_id: str | None
    pergunta: str
    resposta: str  # sempre a resposta original do Tutor
    origem: str
    fontes: list[str] = []
    vetada: bool
    correcao_docente: str | None = None
    situacao: Literal["a_revisar", "aprovada", "vetada"]


class FeedbackRegistro(BaseModel):
    """Feedback de item: o texto da explicação NÃO é gravado, só a origem e as fontes."""
    resposta_id: int
    ts: str
    aluno_id: str
    item_id: str | None
    competencia_id: str
    nivel: int | None
    acertou: bool
    origem: str | None
    fontes: list[str] = []


class ListaRevisao(BaseModel):
    situacao: SituacaoRevisao
    origem: str | None
    total: int  # itens do diálogo com o filtro, antes da paginação
    pagina: int
    por_pagina: int
    itens: list[ItemRevisao]
    dialogos: int
    vetados: int
    aprovados: int
    a_revisar: int
    taxa_veto: float | None  # vetados / respostas do diálogo (mesma do Agente 3)
    feedbacks_por_origem: dict[str, int]
    feedbacks: list[FeedbackRegistro]  # os mais recentes
    auditoria_id: int


# --- auditoria (R11) ---

class RegistroPainel(BaseModel):
    id: int
    ts: str
    aluno_id: str | None
    agentes: list[str]
    tipo: str
    referencia_id: str | None
    origem: str | None
    fontes: list[str] = []
    motivo: str | None = None
    origem_justificativas: str | None = None  # quando o Planejador foi acionado


class PaginaAuditoria(BaseModel):
    total: int
    pagina: int
    por_pagina: int
    registros: list[RegistroPainel]
