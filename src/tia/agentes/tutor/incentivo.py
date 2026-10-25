"""
Incentivo por inatividade do Agente 2 (Tutor), parte 2b.

verificar_inatividade(aluno_id, agora=None): dias desde a última ação do
aluno no Tutor (repositorio.ultima_interacao); inativo a partir de
INATIVIDADE_DIAS (core/config.py). Se o aluno nunca usou o Tutor, conta a
partir da criação da trilha; sem trilha nem interação, inativo e dias None.
O relógio ("agora") é injetável para teste.

montar_incentivo(aluno_id, agora=None): mensagem por TEMPLATE (sem LLM),
citando a próxima etapa pendente da trilha do Planejador e quantas faltam.
Aluno sem trilha recebe a sugestão de gerá-la.

Não é executável sozinho; usado pela API:
    GET /tutor/incentivo/{aluno_id}

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""

from dataclasses import dataclass
from datetime import datetime

from tia.agentes.planejador.modelos import Trilha
from tia.agentes.planejador.repositorio import ler_trilha
from tia.agentes.tutor import repositorio
from tia.agentes.tutor.modelos import Incentivo
from tia.core.config import INATIVIDADE_DIAS

# Textos dos templates (validados pela Pessoa 4).
MENSAGEM_SEM_TRILHA = ("Você ainda não tem uma trilha de estudo. Que tal gerar a sua agora? "
                       "Ela mostra por onde começar.")
MENSAGEM_TRILHA_CONCLUIDA = ("Você concluiu todas as etapas da sua trilha. Que tal revisar algum "
                             "tema conversando com o Tutor?")
MENSAGEM_INATIVO = ("Faz {dias} dias que você não estuda por aqui. Que tal retomar pela etapa "
                    "\"{etapa}\"? {faltam} para concluir a sua trilha.")
MENSAGEM_ATIVO = "Bom ritmo! Sua próxima etapa é \"{etapa}\". {faltam} para concluir a sua trilha."


@dataclass
class Inatividade:
    inativo: bool
    dias: int | None


def verificar_inatividade(aluno_id: str, agora: datetime | None = None,
                          trilha: Trilha | None = None) -> Inatividade:
    """Inativo se passaram INATIVIDADE_DIAS dias ou mais desde a última
    interação (dias inteiros). trilha: a já lida, para não ler de novo."""
    agora = agora or datetime.now()
    referencia = repositorio.ultima_interacao(aluno_id)
    if referencia is None:
        trilha = trilha or ler_trilha(aluno_id)
        criada = repositorio.criacao_da_trilha(aluno_id) if trilha else None
        if criada is None:
            return Inatividade(inativo=True, dias=None)
        referencia = criada
    dias = max(0, (agora - referencia).days)
    return Inatividade(inativo=dias >= INATIVIDADE_DIAS, dias=dias)


def _faltam(n: int) -> str:
    return "Falta 1 etapa" if n == 1 else f"Faltam {n} etapas"


def etapas_pendentes(aluno_id: str, trilha: Trilha) -> list:
    """Etapas da trilha, na ordem, cuja competência ainda não foi concluída.
    PROVISÓRIO: etapa concluída = sessão do questionário concluída na
    competência, até o critério oficial do Agente 2 (Pessoa 2)."""
    concluidas = repositorio.competencias_concluidas(aluno_id)
    return [e for e in sorted(trilha.etapas, key=lambda e: e.ordem)
            if e.competencia_id not in concluidas and not e.concluida]


def montar_incentivo(aluno_id: str, agora: datetime | None = None) -> Incentivo:
    """Situação do aluno e mensagem de incentivo por template."""
    trilha = ler_trilha(aluno_id)
    situacao = verificar_inatividade(aluno_id, agora, trilha)
    if trilha is None:
        return Incentivo(inativo=situacao.inativo, dias=situacao.dias, mensagem=MENSAGEM_SEM_TRILHA)
    pendentes = etapas_pendentes(aluno_id, trilha)
    if not pendentes:
        # trilha concluída: não é inatividade (mesmo critério do orquestrador e do Relatório)
        return Incentivo(inativo=False, dias=situacao.dias, mensagem=MENSAGEM_TRILHA_CONCLUIDA,
                         etapas_restantes=0)
    proxima = pendentes[0]
    template = MENSAGEM_INATIVO if situacao.inativo else MENSAGEM_ATIVO
    mensagem = template.format(dias=situacao.dias, etapa=proxima.nome, faltam=_faltam(len(pendentes)))
    return Incentivo(inativo=situacao.inativo, dias=situacao.dias, mensagem=mensagem,
                     proxima_etapa=proxima.competencia_id, etapas_restantes=len(pendentes))
