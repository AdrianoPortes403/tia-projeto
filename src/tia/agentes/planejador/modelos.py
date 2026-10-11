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


class EntradaPlanejador(BaseModel):
    aluno_id: CodigoAluno
    perfil_id: str
    # nota do diagnóstico (0..1) por id de competência; competência ausente conta como 0
    diagnostico: dict[str, Nota] = {}
    horas_semanais: float = Field(gt=0, le=60)
    # replanejamento incremental: competências já concluídas entram na trilha
    # marcadas como concluídas e não são planejadas de novo; só as que faltam
    # são agendadas (a partir da semana 1)
    concluidas: list[str] = []


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


class Trilha(BaseModel):
    aluno_id: str
    perfil_id: str
    etapas: list[EtapaTrilha]
    # por que as justificativas caíram no texto padrão: "timeout", outro erro
    # (ex.: "ConnectionError") ou "formato" (resposta sem frase válida); None se não caíram
    falha_llm: str | None = None
