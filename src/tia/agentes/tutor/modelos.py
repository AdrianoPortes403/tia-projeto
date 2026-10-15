"""
Modelos Pydantic do Agente 2 (Tutor): questionário adaptativo (parte 2a)
e diálogo livre (parte 2b).

O que entra (início de sessão, resposta do aluno, pergunta livre) e o que
sai (pergunta do questionário, feedback, resposta do diálogo). A Pergunta nunca leva o gabarito nem a explicação: só depois da
resposta o Feedback revela o índice correto.

Usados tanto pela lógica do agente quanto pela API (validação e /docs).

Não é executável: importar com "from tia.agentes.tutor.modelos import ...".

Pré-requisitos:
    - pydantic 2
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Mesmo padrão do Planejador (R08): aluno_id é código, nunca nome.
from tia.agentes.planejador.modelos import CodigoAluno


class IniciarSessao(BaseModel):
    aluno_id: CodigoAluno
    competencia_id: str = Field(min_length=1, max_length=64, examples=["repeticao"])
    # nível inicial vindo do diagnóstico (EtapaTrilha.nivel_inicial); None = nível 1
    nivel_inicial: int | None = Field(default=None, ge=1, le=3)


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
    # do LLM; "fallback": sem trecho ou LLM falhou (nos dois, texto do item);
    # "docente": só no reenvio de um evento cujo feedback o docente já vetou
    # (a explicação é a correção do docente)
    origem: Literal["LLM", "guarda", "fallback", "docente"]
    # com origem "fallback" por falha: "timeout", outro erro, ou "rag: <erro>"
    falha_llm: str | None = None
    # arquivos do material usados na explicação (R03); vazio quando a
    # explicação é o texto fixo do item
    fontes: list[str] = []
    nivel_atual: int
    concluida: bool
    # a resposta fechou uma sequência de erros no nível 1 (1.2.5): o orquestrador decide o reforço
    lacuna: bool = False
    # concluída porque os itens acabaram, sem domínio (TUTOR_ACERTOS_CONCLUIR acertos
    # seguidos no nível 3): o orquestrador decide se avança (ORQ_ACERTO_MIN_AVANCO)
    com_ressalvas: bool = False
    # None quando a competência foi concluída
    proxima_pergunta: Pergunta | None = None
    tempo_ms: int
    # id da resposta (historico_respostas); o feedback fica gravado para a revisão
    # docente (R12) e o veto usa este id: PATCH /tutor/feedback/{resposta_id}/veto
    resposta_id: int | None = None


# --- parte 2b: diálogo livre ---

Origem = Literal["LLM", "guarda", "fallback"]
LIMITE_PERGUNTA = 500
TextoPergunta = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_PERGUNTA)]


class PerguntaAluno(BaseModel):
    aluno_id: CodigoAluno
    # texto livre: vai só para o banco (tutor_dialogo), nunca para log (R08)
    pergunta: TextoPergunta
    # restringe a busca ao material da competência; None = todo o material
    competencia_id: str | None = Field(default=None, min_length=1, max_length=64, examples=["repeticao"])


class RespostaDialogo(BaseModel):
    dialogo_id: int
    resposta: str
    # arquivos do material usados (R03), dos metadados do RAG; vazio na resposta fixa
    fontes: list[str] = []
    # "LLM": ancorada nos trechos e aprovada pela guarda; "guarda": a guarda barrou
    # a do LLM; "fallback": sem trecho relevante, LLM falhou ou o material não cobre
    origem: Origem
    falha_llm: str | None = None  # "timeout", outro erro, ou "rag: <erro>"
    tempo_ms: int


class RegistroAuditoria(BaseModel):
    """Uma interação do Tutor (R11). Sem texto livre do aluno."""
    id: int
    ts: str
    tipo: Literal["resposta_item", "dialogo", "incentivo", "relatorio_aluno", "relatorio_turma",
                  "decisao_orquestrador", "veto_docente", "consulta_painel", "login", "login_falha",
                  "login_bloqueado", "logout", "acesso_negado", "gestao_usuario"]
    # id da linha na tabela de origem (historico_respostas, tutor_dialogo) ou,
    # no incentivo, a competência da próxima etapa citada
    referencia_id: str | None
    origem: str
    fontes: list[str] = []
    motivo: str | None = None  # decisões do orquestrador
    usuario_id: str | None = None   # quem agiu (1.4.6); None: sistema ou modo sem login
    usuario_papel: str | None = None  # aluno, docente, admin, sistema ou sem_login


class Veto(BaseModel):
    """Veto docente (R12) a uma resposta do diálogo ou ao feedback de uma
    questão. Vetar exige a correção;
    retirar o veto (vetada=False) volta a mostrar a resposta original."""
    vetada: bool
    correcao_docente: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                       max_length=2000)] | None = None

    @model_validator(mode="after")
    def correcao_obrigatoria_ao_vetar(self):
        if self.vetada and not self.correcao_docente:
            raise ValueError("Ao vetar, informe a correcao_docente que o aluno vai ver.")
        return self


class ItemDialogo(BaseModel):
    """Uma pergunta do histórico do aluno. Se vetada, "resposta" é a correção
    do docente, sem fontes, e "origem" é "docente"."""
    dialogo_id: int
    ts: str
    competencia_id: str | None
    pergunta: str
    resposta: str
    fontes: list[str] = []
    origem: str
    vetada: bool


class ItemFeedback(BaseModel):
    """Feedback de uma questão já respondida, como o aluno vê. Se vetado,
    "explicacao" é a correção do docente, sem fontes, e "origem" é "docente"."""
    resposta_id: int
    ts: str
    sessao_id: str | None
    item_id: str | None
    enunciado: str | None = None  # do banco de itens atual
    competencia_id: str | None
    veredito: str | None
    explicacao: str | None
    fontes: list[str] = []
    origem: str
    vetada: bool


class Incentivo(BaseModel):
    """Incentivo por inatividade, montado por template (sem LLM)."""
    inativo: bool
    # dias desde a última interação; None se o aluno nunca interagiu
    dias: int | None
    mensagem: str
    # próxima etapa pendente da trilha do Planejador; None sem trilha ou com ela concluída
    proxima_etapa: str | None = None
    etapas_restantes: int | None = None
