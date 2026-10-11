"""
Modelos Pydantic do Agente 3 (Relatório): os 5 indicadores e os dois
relatórios (por aluno e por turma/instituição), em JSON estruturado para o
dashboard (pacote 1.4.5) consumir.

Os 5 indicadores são PROVISÓRIOS: critérios finais a validar com a Pessoa 4
(ver docs/arquitetura/relatorio_indicadores.md).

Taxas são frações de 0 a 1 (None quando não há dado). No relatório da
turma, toda contagem de alunos abaixo de RELATORIO_MIN_GRUPO sai como
Contagem(valor=None, texto="menos de N") (R08).

Não é executável: importar com "from tia.agentes.relatorio.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Literal

from pydantic import BaseModel

Direcao = Literal["subindo", "caindo", "estavel", "insuficiente"]
OrigemNarrativa = Literal["LLM", "guarda", "fallback"]


class Taxa(BaseModel):
    """Acertos sobre respostas de um grupo (competência, nível, janela...)."""
    chave: str
    respostas: int
    acertos: int
    taxa: float | None  # None sem respostas


# --- 1. progresso na trilha ---

class ProgressoCompetencia(BaseModel):
    competencia_id: str
    nome: str
    concluida: bool
    nivel_atual: int | None  # nível da sessão mais recente; None se nunca praticou


class Progresso(BaseModel):
    tem_trilha: bool
    etapas: int
    concluidas: int
    percentual: float | None  # concluidas / etapas; None sem trilha
    por_competencia: list[ProgressoCompetencia] = []


# --- 2. desempenho ---

class Tendencia(BaseModel):
    """Acerto recente x anterior (PROVISÓRIO). base "sessao": última sessão x
    sessões anteriores (respostas com sessao_id); base "janela": últimas
    respostas x anteriores, para respostas antigas, sem sessao_id."""
    base: Literal["sessao", "janela"]
    recentes: Taxa
    anteriores: Taxa
    variacao: float | None  # recentes.taxa - anteriores.taxa
    direcao: Direcao


class Desempenho(BaseModel):
    geral: Taxa
    por_competencia: list[Taxa] = []
    por_nivel: list[Taxa] = []
    tendencia: Tendencia


# --- 3. engajamento ---

class Engajamento(BaseModel):
    sessoes: int
    sessoes_concluidas: int
    respostas: int
    perguntas_dialogo: int
    dias_ativos: int
    ultima_interacao: str | None
    dias_inativo: int | None  # None se nunca interagiu e não tem trilha
    # dias_inativo >= INATIVIDADE_DIAS e a trilha NÃO concluída: quem concluiu não
    # é inativo (mesmo critério do orquestrador, R3, e do painel)
    inativo: bool
    trilha_concluida: bool = False


# --- 4. pontos fracos ---

class PontoFraco(BaseModel):
    competencia_id: str
    nome: str
    respostas: int
    erros: int
    taxa_erro: float
    maior_sequencia_erros: int
    # proxy de "uso de explicação": não existe recurso de dica nem registro de
    # leitura da explicação; conta as perguntas do diálogo na competência
    perguntas_dialogo: int


# --- 5. qualidade do feedback ---

class ItemFraco(BaseModel):
    """Item do banco com erro repetido (só respostas com item_id)."""
    item_id: str
    competencia_id: str
    respostas: int
    erros: int
    taxa_erro: float
    maior_sequencia_erros: int


class QualidadeFeedback(BaseModel):
    respostas_com_origem: int
    respostas_sem_registro: int  # anteriores à auditoria (sem origem gravada)
    por_origem: dict[str, int]   # LLM, guarda, fallback (respostas de item + diálogo)
    taxa_por_origem: dict[str, float | None]
    dialogos: int
    vetados: int
    taxa_veto: float | None
    # feedback das questões (R12): só as respostas com texto gravado (tutor_feedbacks)
    feedbacks_com_texto: int = 0
    feedbacks_vetados: int = 0
    taxa_veto_feedback: float | None = None


class Narrativa(BaseModel):
    """Parágrafo de interpretação. Só o LLM redige; os números vêm dos
    indicadores e a guarda descarta texto com número que não está neles."""
    texto: str
    origem: OrigemNarrativa
    motivo_descarte: str = ""
    falha_llm: str | None = None  # fallback por falha do LLM: "timeout" ou outro erro


class RelatorioAluno(BaseModel):
    """Visão do próprio aluno (identificado só pelo código, R08)."""
    aluno_id: str
    gerado_em: str
    provisorio: bool = True
    progresso: Progresso
    desempenho: Desempenho
    engajamento: Engajamento
    pontos_fracos: list[PontoFraco] = []
    itens_fracos: list[ItemFraco] = []
    qualidade_feedback: QualidadeFeedback
    narrativa: Narrativa


# --- turma / instituição (só agregados) ---

class Contagem(BaseModel):
    """Contagem de alunos; abaixo do grupo mínimo, valor=None e texto "menos de N"."""
    valor: int | None
    texto: str


class GrupoTaxa(BaseModel):
    """Taxa agregada de um grupo; suprimida se o grupo tem menos de N alunos."""
    chave: str
    alunos: Contagem
    suprimido: bool
    respostas: int | None = None
    taxa: float | None = None


class EngajamentoTurma(BaseModel):
    media_sessoes: float
    media_dias_ativos: float
    media_perguntas_dialogo: float
    inativos: Contagem


class AlertaTurma(BaseModel):
    tipo: Literal["inatividade", "desempenho_em_queda", "competencia_com_erro_alto"]
    descricao: str
    alunos: Contagem
    competencia_id: str | None = None


class RelatorioTurma(BaseModel):
    """Visão agregada da turma/instituição: sem aluno_id nem grupo com menos
    de min_grupo alunos (R08). PROVISÓRIO: não existe turma no banco; o grupo
    é a instituição inteira ou um perfil (perfil_id da trilha)."""
    gerado_em: str
    perfil_id: str | None
    min_grupo: int
    provisorio: bool = True
    alunos: Contagem
    suprimido: bool  # grupo inteiro abaixo do mínimo: nenhum indicador exibido
    progresso_medio: float | None = None
    alunos_com_trilha: Contagem | None = None
    desempenho_por_competencia: list[GrupoTaxa] = []
    desempenho_por_nivel: list[GrupoTaxa] = []
    engajamento: EngajamentoTurma | None = None
    pontos_fracos: list[GrupoTaxa] = []  # alunos com a competência como ponto fraco
    itens_fracos: list[GrupoTaxa] = []   # alunos que erraram o item; taxa = erro agregado
    qualidade_feedback: QualidadeFeedback | None = None
    alertas: list[AlertaTurma] = []
    narrativa: Narrativa
