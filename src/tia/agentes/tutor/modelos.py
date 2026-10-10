"""
Modelos Pydantic do Agente 2 (Tutor), parte 2a: questionário adaptativo.

O que entra (início de sessão e resposta do aluno) e o que sai (pergunta e
feedback). A Pergunta nunca leva o gabarito nem a explicação: só depois da
resposta o Feedback revela o índice correto.

Usados tanto pela lógica do agente quanto pela API (validação e /docs).

Não é executável: importar com "from tia.agentes.tutor.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Literal

from pydantic import BaseModel, Field

# Mesmo padrão do Planejador (R08): aluno_id é código, nunca nome.
from tia.agentes.planejador.modelos import CodigoAluno


class IniciarSessao(BaseModel):
    aluno_id: CodigoAluno
    competencia_id: str = Field(min_length=1, max_length=64, examples=["repeticao"])


class Pergunta(BaseModel):
    """Item do banco como o aluno vê: sem indice_correto nem explicacao."""
    item_id: str
    competencia_id: str
    nivel: int
    enunciado: str
    alternativas: list[str]


class SessaoIniciada(BaseModel):
    sessao_id: str
    nivel_atual: int
    pergunta: Pergunta


class RespostaAluno(BaseModel):
    sessao_id: str = Field(min_length=1, max_length=64)
    aluno_id: CodigoAluno
    # item que o aluno está respondendo; evita corrigir a pergunta errada
    # se a mesma resposta for enviada duas vezes
    item_id: str = Field(min_length=1, max_length=64)
    indice_escolhido: int = Field(ge=0, le=3)


class Feedback(BaseModel):
    acertou: bool
    indice_correto: int
    # texto fixo gerado por código ("Você acertou." / "Você marcou: ... A resposta
    # correta é: ..."); o aluno lê o veredito e depois a explicação
    veredito: str
    explicacao: str
    # "LLM": explicação do LLM aprovada pela guarda; "guarda": a guarda barrou a
    # do LLM; "fallback": sem trecho ou LLM falhou (nos dois, texto do item)
    origem: Literal["LLM", "guarda", "fallback"]
    # arquivos do material usados na explicação (R03); vazio quando a
    # explicação é o texto fixo do item
    fontes: list[str] = []
    nivel_atual: int
    concluida: bool
    # None quando a competência foi concluída
    proxima_pergunta: Pergunta | None = None
    tempo_ms: int
