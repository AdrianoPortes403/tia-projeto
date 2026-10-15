"""
Modelos Pydantic do Agente 1 (Planejador): o que entra (diagnóstico do
aluno) e o que sai (trilha de estudo em etapas).

Usados tanto pela lógica do agente quanto pela API (validação e /docs).

Não é executável: importar com "from tia.agentes.planejador.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# R08 (LGPD): aluno_id é um código (letras sem acento, números, "_" e "-"),
# nunca o nome do aluno. Espaços e acentos são recusados de propósito.
PADRAO_CODIGO_ALUNO = r"^[A-Za-z0-9_-]{1,32}$"
CodigoAluno = Annotated[str, Field(pattern=PADRAO_CODIGO_ALUNO, examples=["A2026-001"])]
Nota = Annotated[float, Field(ge=0.0, le=1.0)]


# Trilhas da base pedagógica (1.2.4). A base comum (etapa 0, Python) entra nas duas.
TrilhaId = Literal["dev", "defesa_cibernetica"]


class EntradaPlanejador(BaseModel):
    aluno_id: CodigoAluno
    # Perfil base (1.2.3). None: o Planejador calcula pelo diagnóstico (regras de
    # enquadramento de conteudo/perfis/perfis.json). Informado: usado como está
    # (compatibilidade com chamadas antigas e com o docente que queira fixar o perfil).
    perfil_id: str | None = None
    # Trilha escolhida pelo aluno no onboarding. None: só a base comum (compatibilidade).
    trilha: TrilhaId | None = None
    # nota do diagnóstico (0..1) por id de competência (tópico); ausente = não diagnosticada.
    # Convenção do diagnóstico (1.2.5): 1 = dominado; 2/3 = começa no nível 3;
    # 1/3 = começa no nível 2; 0 = começa no nível 1.
    diagnostico: dict[str, Nota] = {}
    horas_semanais: float = Field(gt=0, le=60)
    # replanejamento incremental: competências já concluídas entram na trilha
    # marcadas como concluídas e não são planejadas de novo; só as que faltam
    # são agendadas (a partir da semana 1)
    concluidas: list[str] = []
    # prazo total em dias a partir de hoje (no piloto: 8); None = sem prazo
    prazo_dias: int | None = Field(default=None, gt=0, le=730)
    # "piloto": só os tópicos marcados no_piloto na ementa (trilha proposta do 1.5.1)
    escopo: Literal["completa", "piloto"] = "completa"


class EtapaTrilha(BaseModel):
    ordem: int
    competencia_id: str
    nome: str
    materiais: list[str] = []
    horas: float
    semana_inicio: int
    justificativa: str
    # "LLM": frase do LLM; "fallback": texto padrão (LLM falhou ou não deu frase
    # válida para a etapa); None: trilha lida do banco (origem não é gravada)
    origem_justificativa: Literal["LLM", "fallback"] | None = None
    # já concluída (replanejamento incremental): fica na trilha para o histórico e
    # o progresso, sem horas nem semana (0) e sem justificativa do LLM
    concluida: bool = False
    # perfil iniciante: pré-requisitos a revisar antes de um tópico médio ou difícil
    # (informativo para o aluno e o Tutor; não vira etapa)
    revisar_antes: list[str] = []
    # nível inicial dos itens no Tutor, vindo do diagnóstico (padrão do perfil se não diagnosticado)
    nivel_inicial: int | None = None
    # perfil intermediário: desafio prático opcional no fim da etapa (não conta horas)
    desafio_pratico: str | None = None


class OpcoesPrazo(BaseModel):
    """Quando a trilha não cabe no prazo: mais horas por semana ou um recorte."""
    horas_semanais_necessarias: float
    recorte_que_cabe: list[str]


class Trilha(BaseModel):
    aluno_id: str
    perfil_id: str
    etapas: list[EtapaTrilha]
    trilha: str | None = None
    # P do enquadramento (0 a 3); None se o perfil foi informado ou se a trilha foi lida do banco antigo
    pontuacao_enquadramento: float | None = None
    perfil_automatico: bool = False
    prazo_dias: int | None = None
    cabe_no_prazo: bool | None = None
    opcoes_prazo: OpcoesPrazo | None = None
    avisos: list[str] = []
    # por que as justificativas caíram no texto padrão: "timeout", outro erro
    # (ex.: "ConnectionError") ou "formato" (resposta sem frase válida); None se não caíram
    falha_llm: str | None = None
