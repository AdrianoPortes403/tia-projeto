"""
Contratos Pydantic da Orquestração (EAP 1.3.5): o que entra (matrícula,
eventos do Tutor) e o que sai (estado do aluno, próxima ação, decisões de
replanejamento, resultado de um evento).

Usados pelo fluxo, pela API (validação e /docs) e pela demonstração.

Não é executável: importar com "from tia.orquestrador.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from tia.agentes.planejador.modelos import Nota, Trilha
from tia.agentes.tutor.modelos import Feedback, Pergunta, SessaoIniciada

TipoEvento = Literal["resposta", "conclusao", "inatividade"]
# matricula: trilha inicial; conclusao (R1), queda (R2), inatividade (R3): regras;
# reforco: fim de um reforço; sessao: pedido de abertura de sessão
Regra = Literal["matricula", "conclusao", "queda", "reforco", "inatividade", "sessao"]
# planejar: trilha inicial; avancar: competência concluída, replaneja o que falta;
# reforcar: pausa a sessão e abre reforço do pré-requisito direto; retomar_original:
# reforço concluído, volta à sessão pausada; incentivar: inatividade, só incentivo;
# refazer_trilha: inatividade longa, replaneja a partir de hoje; abrir_sessao /
# recusar_sessao: pedido de sessão; nenhuma: a regra avaliou e não fez nada
Acao = Literal["planejar", "avancar", "reforcar", "retomar_original", "incentivar", "refazer_trilha",
               "abrir_sessao", "recusar_sessao", "nenhuma"]
AcaoProxima = Literal["iniciar_sessao", "continuar_sessao", "concluido"]
IdEvento = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$", examples=["evt-0001"])]


class Matricula(BaseModel):
    """Entrada de POST /aluno/{id}/iniciar (o mesmo que o Planejador pede)."""
    perfil_id: str = Field(min_length=1, max_length=64, examples=["intermediario"])
    # nota do diagnóstico (0..1) por competência; ausente conta como 0
    diagnostico: dict[str, Nota] = {}
    horas_semanais: float = Field(gt=0, le=60)


class EventoTutor(BaseModel):
    """Evento enviado ao orquestrador. evento_id torna o envio idempotente:
    repetir o mesmo id devolve o resultado gravado, sem processar de novo.
        resposta:    resposta do aluno a um item (o orquestrador a repassa ao Tutor);
        conclusao:   aviso de competência concluída (o orquestrador confere no banco);
        inatividade: pedido de verificação de inatividade (o orquestrador confere)."""
    evento_id: IdEvento
    tipo: TipoEvento
    sessao_id: str | None = Field(default=None, min_length=1, max_length=64)
    item_id: str | None = Field(default=None, min_length=1, max_length=64)
    indice_escolhido: int | None = Field(default=None, ge=0, le=3)
    competencia_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def campos_do_tipo(self):
        if self.tipo == "resposta" and None in (self.sessao_id, self.item_id, self.indice_escolhido):
            raise ValueError("Evento 'resposta' exige sessao_id, item_id e indice_escolhido.")
        if self.tipo == "conclusao" and self.competencia_id is None and self.sessao_id is None:
            raise ValueError("Evento 'conclusao' exige competencia_id ou sessao_id.")
        return self


class DecisaoReplanejamento(BaseModel):
    """Uma decisão do orquestrador (também gravada na auditoria, com o motivo)."""
    decisao_id: int
    ts: str
    regra: Regra
    acao: Acao
    competencia_id: str | None = None
    motivo: str
    replanejou: bool  # o Planejador foi acionado
    sessao_id: str | None = None  # sessão do Tutor que levou à decisão, se houver
    # quando replanejou: origem das justificativas do Planejador ("LLM", "parcial"
    # ou "fallback"), motivo do texto padrão ("timeout", "formato"...) e tempo
    origem_justificativas: Literal["LLM", "parcial", "fallback"] | None = None
    falha_llm: str | None = None
    tempo_planejador_ms: int | None = None
    aviso: str | None = None  # mensagem ao aluno (conclusão, reforço, retomada, incentivo); template


class EtapaEstado(BaseModel):
    ordem: int
    competencia_id: str
    nome: str
    concluida: bool


class Reforco(BaseModel):
    """Reforço por queda (R2) em curso: a sessão original fica pausada."""
    competencia_original: str
    sessao_original_id: str
    competencia_reforco: str            # pré-requisito direto
    sessao_reforco_id: str | None       # None até a sessão de reforço ser aberta
    estado: Literal["pendente", "em_andamento"]


class EstadoAluno(BaseModel):
    """Situação do aluno no fluxo, montada a partir dos Agentes 1, 2 e 3."""
    aluno_id: str
    perfil_id: str
    horas_semanais: float
    diagnostico: dict[str, float]  # diagnóstico em uso (atualizado a cada replanejamento)
    etapas: list[EtapaEstado]
    competencia_atual: str | None   # primeira etapa não concluída
    sessao_aberta_id: str | None    # sessão não concluída nem pausada na competência atual
    reforco: Reforco | None = None  # reforço em curso (tem prioridade sobre a competência atual)
    concluido: bool
    tendencia: str                  # direção do Relatório: subindo, caindo, estavel, insuficiente
    inativo: bool
    dias_inativo: int | None
    # motivo, se a regra de inatividade (R3) pede ação; quem age é a verificação
    # agendada (POST /orquestrador/verificar-inatividade), não o aluno
    replanejamento_pendente: str | None
    replanejamentos: int
    ultima_decisao: DecisaoReplanejamento | None = None
    dialogos: int
    dialogos_vetados: int           # veto docente (R12)
    # onde o fluxo continua: histórico do diálogo (com vetos aplicados), veto
    # docente e relatório, pelas rotas que já existem
    rotas: dict[str, str] = {}


class ProximaAcao(BaseModel):
    acao: AcaoProxima
    competencia_id: str | None = None
    sessao_id: str | None = None
    reforco: bool = False  # a sessão é de reforço de pré-requisito (R2)
    motivo: str
    # só em "continuar_sessao": a pergunta em aberto da sessão (sem gabarito), para o
    # cliente (web standalone) retomar a sessão depois de recarregar ou de um reforço
    pergunta: Pergunta | None = None


class PedidoSessao(BaseModel):
    """Entrada de POST /aluno/{id}/sessao: só é aceita a competência atual ou o reforço."""
    competencia_id: str = Field(min_length=1, max_length=64, examples=["funcoes"])


class SessaoOrquestrada(BaseModel):
    sessao: SessaoIniciada
    reforco: bool
    decisao: DecisaoReplanejamento


class DecisaoDeAluno(BaseModel):
    aluno_id: str
    decisao: DecisaoReplanejamento


class ResultadoVerificacao(BaseModel):
    """Resultado de uma rodada da verificação de inatividade (R3) em todos os alunos."""
    verificados: int
    decisoes: list[DecisaoDeAluno]


class ResultadoMatricula(BaseModel):
    trilha: Trilha
    decisao: DecisaoReplanejamento
    proxima: ProximaAcao


class ResultadoEvento(BaseModel):
    evento_id: str
    tipo: TipoEvento
    repetido: bool = False      # True: evento já processado; resultado gravado
    feedback: Feedback | None = None  # só no evento "resposta"
    decisoes: list[DecisaoReplanejamento] = []
    avisos: list[str] = []      # mensagens ao aluno das decisões (ex.: "Você concluiu...")
    proxima: ProximaAcao
