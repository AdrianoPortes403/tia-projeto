"""
Agente 3 (Relatório), EAP 1.3.4: relatórios com 5 indicadores.

Pontos de entrada (usados pela API e pela demonstração):
    gerar_relatorio_aluno(aluno_id, agora=None, com_narrativa=True) -> RelatorioAluno | None
    gerar_relatorio_turma(perfil_id=None, agora=None, com_narrativa=True) -> RelatorioTurma

Os indicadores são calculados por código (indicadores.py); o LLM só redige
o parágrafo de interpretação, com guarda e texto fixo de fallback
(narrativa.py). Toda geração entra na auditoria (R11). O relatório da
turma só traz agregados, sem grupos com menos de RELATORIO_MIN_GRUPO
alunos (R08). O relógio ("agora") é injetável para teste.

Módulos:
    modelos.py     Pydantic (JSON para o dashboard 1.4.5)
    repositorio.py leitura dos dados dos Agentes 1 e 2 e auditoria
    indicadores.py os 5 indicadores e a agregação da turma (funções puras)
    narrativa.py   parágrafo do LLM com guarda e versão em texto

Como rodar a demonstração (dados sintéticos, banco temporário):
    python -m tia.agentes.relatorio --demo

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, texto fixo)
"""

from datetime import datetime

from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.relatorio import indicadores, narrativa, repositorio
from tia.agentes.relatorio.modelos import Narrativa, RelatorioAluno, RelatorioTurma
from tia.core.config import RELATORIO_MIN_GRUPO


def _nomes() -> dict[str, str]:
    return {c["id"]: c["nome"] for c in carregar_ementa()}


def _agora_texto(agora: datetime) -> str:
    return agora.isoformat(timespec="seconds")


def gerar_relatorio_aluno(aluno_id: str, agora: datetime | None = None,
                          com_narrativa: bool = True) -> RelatorioAluno | None:
    """Relatório do aluno; None se o código não existe. Registrado na auditoria."""
    agora = agora or datetime.now()
    dados = repositorio.ler_dados_aluno(aluno_id)
    if dados is None:
        return None
    nomes = _nomes()
    relatorio = RelatorioAluno(
        aluno_id=aluno_id,
        gerado_em=_agora_texto(agora),
        progresso=indicadores.progresso(dados, nomes),
        desempenho=indicadores.desempenho(dados.respostas),
        engajamento=indicadores.engajamento(dados, agora),
        pontos_fracos=indicadores.pontos_fracos(dados.respostas, dados.dialogos, nomes),
        itens_fracos=indicadores.itens_fracos(dados.respostas),
        qualidade_feedback=indicadores.qualidade_feedback(dados.respostas, dados.dialogos),
        narrativa=Narrativa(texto=narrativa.FALLBACK_ALUNO, origem="fallback"),
    )
    if com_narrativa:
        relatorio.narrativa = narrativa.redigir(narrativa.resumo_aluno(relatorio), "aluno")
    repositorio.registrar_relatorio("relatorio_aluno", aluno_id, None, relatorio.narrativa.origem)
    return relatorio


def gerar_relatorio_turma(perfil_id: str | None = None, agora: datetime | None = None,
                          com_narrativa: bool = True, min_grupo: int = RELATORIO_MIN_GRUPO) -> RelatorioTurma:
    """Relatório agregado da instituição (ou de um perfil). Registrado na
    auditoria sem aluno_id. Grupo abaixo do mínimo: nada além da contagem."""
    agora = agora or datetime.now()
    dados = [d for d in (repositorio.ler_dados_aluno(a) for a in repositorio.listar_alunos(perfil_id)) if d]
    campos = indicadores.agregar_turma(dados, agora, min_grupo, _nomes())
    relatorio = RelatorioTurma(gerado_em=_agora_texto(agora), perfil_id=perfil_id, min_grupo=min_grupo,
                               narrativa=Narrativa(texto=narrativa.FALLBACK_TURMA, origem="fallback"), **campos)
    if relatorio.suprimido:
        relatorio.narrativa = Narrativa(texto=narrativa.SUPRIMIDO_TURMA, origem="fallback")
    elif com_narrativa:
        relatorio.narrativa = narrativa.redigir(narrativa.resumo_turma(relatorio), "turma")
    repositorio.registrar_relatorio("relatorio_turma", None, perfil_id, relatorio.narrativa.origem)
    return relatorio
