"""
Modelos Pydantic das rotas de leitura do painel do docente (EAP 1.4.5).

Os números agregados seguem a mesma regra do Agente 3: contagem de alunos
abaixo de RELATORIO_MIN_GRUPO sai como Contagem(valor=None, texto="menos de N")
e grupo abaixo do mínimo sai suprimido (R08). Só as rotas de alertas de
risco, da lista de alunos e de revisão mostram códigos de aluno (nunca nomes),
e cada consulta delas é registrada na auditoria. A contagem da revisão
(ContagemRevisao) é só um número: não mostra código e não é auditada.

Não é executável: importar com "from tia.painel.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Literal

from pydantic import BaseModel

from tia.agentes.relatorio.modelos import Contagem, Direcao

TipoRisco = Literal["inatividade", "desempenho_em_queda", "desempenho_baixo", "conclusao_sem_dominio"]
SituacaoRevisao = Literal["a_revisar", "aprovadas", "vetadas", "todas"]
# situação de um aluno na lista da visão geral (uma só, pela ordem de prioridade
# em consultas.situacao_do_aluno)
SituacaoAluno = Literal["no_ritmo", "desempenho_em_queda", "desempenho_baixo", "conclusao_sem_dominio",
                        "inatividade", "trilha_concluida", "sem_trilha"]


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
    criterios: dict[str, int | float]  # limiares usados (em core/config.py)
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


# --- lista de alunos da visão geral (com código; auditada) ---

class AlunoTurma(BaseModel):
    """Só o necessário para a tabela da visão geral (minimização, R08): nunca
    nome, objetivo do cadastro nem texto do diálogo."""
    aluno_id: str  # código, nunca nome
    perfil_id: str | None
    competencia_atual: str | None  # tópico da EAP; None: trilha concluída ou sem trilha
    taxa_acerto: float | None
    situacao: SituacaoAluno


class ListaAlunos(BaseModel):
    gerado_em: str
    perfil_id: str | None
    alunos: list[AlunoTurma]
    auditoria_id: int  # registro desta consulta na auditoria (R11)


# --- revisão docente (R12) ---

TipoRevisao = Literal["dialogo", "feedback"]


class ItemRevisao(BaseModel):
    """Texto gerado pelo Tutor como o docente vê: o ORIGINAL (o que o aluno viu
    antes de um veto) e, se vetado, a correção. tipo "dialogo": resposta a uma
    pergunta livre (id = dialogo_id); tipo "feedback": explicação de uma questão
    respondida (id = resposta_id; pergunta = enunciado do item)."""
    tipo: TipoRevisao
    id: int
    ts: str
    aluno_id: str
    competencia_id: str | None
    pergunta: str
    item_id: str | None = None
    nivel: int | None = None
    acertou: bool | None = None
    veredito: str | None = None
    resposta: str | None  # texto original do Tutor (resposta do diálogo ou explicação do feedback)
    origem: str
    fontes: list[str] = []
    falha_llm: str | None = None
    # só feedback com origem "guarda": o texto do LLM barrado (o aluno não viu) e o motivo
    explicacao_descartada: str | None = None
    motivo_descarte: str | None = None
    vetada: bool
    correcao_docente: str | None = None
    situacao: Literal["a_revisar", "aprovada", "vetada"]


class ResumoRevisao(BaseModel):
    """Contagens de um tipo (sem filtro): taxa_veto = vetados / total."""
    total: int
    vetados: int
    aprovados: int
    a_revisar: int
    taxa_veto: float | None


class ListaRevisao(BaseModel):
    tipo: TipoRevisao | None
    situacao: SituacaoRevisao
    origem: str | None
    competencia_id: str | None
    total: int  # itens com o filtro, antes da paginação
    pagina: int
    por_pagina: int
    itens: list[ItemRevisao]
    dialogo: ResumoRevisao
    feedback: ResumoRevisao
    feedbacks_sem_texto: int  # respostas anteriores à gravação do texto (não revisáveis)
    feedbacks_por_origem: dict[str, int]  # todas as respostas de questões, pela auditoria
    auditoria_id: int


class ContagemRevisao(BaseModel):
    """Só o número de textos a revisar (contador do menu): sem códigos, não auditada."""
    a_revisar: int


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
    usuario_id: str | None = None   # quem agiu (1.4.6)
    usuario_papel: str | None = None


class PaginaAuditoria(BaseModel):
    total: int
    pagina: int
    por_pagina: int
    registros: list[RegistroPainel]
