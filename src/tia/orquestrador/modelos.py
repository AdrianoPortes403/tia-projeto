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
from tia.agentes.tutor.modelos import Feedback

TipoEvento = Literal["resposta", "conclusao", "inatividade"]
# "matricula" planeja a trilha inicial; as outras três são as regras de replanejamento
Regra = Literal["matricula", "conclusao", "queda", "inatividade"]
# planejar: trilha inicial; avancar: competência concluída; reforcar: desempenho
# em queda; retomar: inatividade; nenhuma: a regra avaliou e não replanejou
Acao = Literal["planejar", "avancar", "reforcar", "retomar", "nenhuma"]
AcaoProxima = Literal["iniciar_sessao", "continuar_sessao", "replanejar", "concluido"]
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


class EtapaEstado(BaseModel):
    ordem: int
    competencia_id: str
    nome: str
    concluida: bool


class EstadoAluno(BaseModel):
    """Situação do aluno no fluxo, montada a partir dos Agentes 1, 2 e 3."""
    aluno_id: str
    perfil_id: str
    horas_semanais: float
    diagnostico: dict[str, float]  # diagnóstico em uso (atualizado a cada replanejamento)
    etapas: list[EtapaEstado]
    competencia_atual: str | None   # primeira etapa não concluída
    sessao_aberta_id: str | None    # sessão não concluída na competência atual
    concluido: bool
    tendencia: str                  # direção do Relatório: subindo, caindo, estavel, insuficiente
    inativo: bool
    dias_inativo: int | None
    replanejamento_pendente: str | None  # motivo, se uma regra pede replanejar agora
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
    motivo: str


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
    proxima: ProximaAcao
