"""
Modelos Pydantic — definem o formato (schema) dos dados que entram e saem
da API. O FastAPI usa isso para validar requisições automaticamente e
gerar a documentação em /docs.

Não é executável: importar com "from tia.core.schemas import ...".

Pré-requisitos:
    - pydantic 2
"""

from pydantic import BaseModel


class PerfilAluno(BaseModel):
    id: str
    conhecimento_previo: str  # "baixo" | "medio" | "alto"
    horas_semana_disponiveis: int


class TopicoEmenta(BaseModel):
    topico: str
    pre_requisitos: list[str] = []
    carga_horaria: int
    dificuldade_base: str  # "facil" | "medio" | "dificil"
    palavras_chave: list[str] = []


class ItemTrilha(BaseModel):
    semana: int
    topico: str
    horas_previstas: int
    recomendacao: str | None = None


class RespostaAluno(BaseModel):
    aluno_id: str
    topico: str
    dificuldade: str
    acertou: bool
