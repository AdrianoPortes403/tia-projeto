"""
Fluxo ponta a ponta da Orquestração (EAP 1.3.5). Só COORDENA os agentes
pelas interfaces públicas deles, sem duplicar lógica:

    Agente 1 (Planejador): planejar_e_salvar (trilha inicial e replanejamento),
                           ler_trilha, carregar_ementa (pré-requisitos);
    Agente 2 (Tutor):      iniciar_sessao/responder (eventos.py), competencias_concluidas,
                           sessao_aberta, histórico do diálogo e veto docente (R12);
    Agente 3 (Relatório):  ler_dados_aluno, tendencia e engajamento (detecção de queda
                           e inatividade), relatórios sob demanda (/relatorio/...).

    iniciar(aluno_id, matricula)  matrícula + trilha inicial pelo Planejador
    estado(aluno_id)              EstadoAluno montado a partir dos três agentes
    proxima(aluno_id)             próxima ação (regras.proxima_acao)
    replanejar(...)               aciona o Planejador com o estado atual (regras.novo_diagnostico)

Toda decisão (planejar, replanejar ou "nenhuma") vai para orquestrador_decisoes
e para a auditoria com o motivo (R11). O relógio ("agora") é injetável para teste.

Não é executável sozinho; demonstração:
    python -m tia.orquestrador --demo

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, os agentes usam os textos fixos)
"""

import time
from datetime import datetime

from tia.agentes.planejador import planejar_e_salvar
from tia.agentes.planejador.modelos import EntradaPlanejador, Trilha
from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.planejador.repositorio import ler_trilha
from tia.agentes.relatorio import indicadores
from tia.agentes.relatorio.repositorio import ler_dados_aluno
from tia.agentes.tutor import repositorio as repositorio_tutor
from tia.orquestrador import regras
from tia.orquestrador import repositorio
from tia.orquestrador.modelos import (DecisaoReplanejamento, EstadoAluno, EtapaEstado, Matricula, ProximaAcao,
                                      ResultadoMatricula)
from tia.orquestrador.regras import Avaliacao


class ErroOrquestracao(ValueError):
    """Erro do fluxo (mensagem pensada para o usuário)."""


class AlunoNaoMatriculado(ErroOrquestracao):
    pass


class JaMatriculado(ErroOrquestracao):
    pass


def instante(agora: datetime | None) -> datetime:
    """O "agora" injetado (testes) ou o relógio, sem microssegundos."""
    return (agora or datetime.now()).replace(microsecond=0)


def _decisao(dados: dict) -> DecisaoReplanejamento:
    return DecisaoReplanejamento(**dados)


def exigir_matricula(aluno_id: str) -> dict:
    matricula = repositorio.ler_matricula(aluno_id)
    if matricula is None:
        raise AlunoNaoMatriculado(f"Aluno '{aluno_id}' não está matriculado no fluxo; use POST /aluno/{{id}}/iniciar.")
    return matricula


def _planejar(aluno_id: str, matricula: dict, diagnostico: dict[str, float]) -> tuple[Trilha, dict]:
    """Aciona o Planejador (com as justificativas do LLM, ou o texto padrão).
    Devolve a trilha e um resumo para a decisão: origem das justificativas,
    motivo de falha e tempo gasto."""
    inicio = time.perf_counter()
    trilha = planejar_e_salvar(EntradaPlanejador(aluno_id=aluno_id, perfil_id=matricula["perfil_id"],
                                                 diagnostico=diagnostico, horas_semanais=matricula["horas_semanais"]))
    origens = {e.origem_justificativa for e in trilha.etapas}
    origem = "LLM" if origens == {"LLM"} else "fallback" if origens <= {"fallback", None} else "parcial"
    return trilha, {"origem_justificativas": origem, "falha_llm": trilha.falha_llm,
                    "tempo_planejador_ms": round((time.perf_counter() - inicio) * 1000)}


def iniciar(aluno_id: str, matricula: Matricula, agora: datetime | None = None) -> ResultadoMatricula:
    """Matrícula no fluxo: o Planejador gera a trilha inicial. Erros do
    Planejador (perfil ou competência inexistente) sobem como ErroPlanejador."""
    agora = instante(agora)
    if repositorio.ler_matricula(aluno_id) is not None:
        raise JaMatriculado(f"Aluno '{aluno_id}' já está matriculado; o replanejamento é feito pelos eventos.")
    dados = {"perfil_id": matricula.perfil_id, "horas_semanais": matricula.horas_semanais}
    trilha, planejador = _planejar(aluno_id, dados, matricula.diagnostico)  # valida perfil e competências antes de gravar
    if not repositorio.salvar_matricula(aluno_id, matricula.perfil_id, matricula.horas_semanais,
                                        matricula.diagnostico, agora):
        raise JaMatriculado(f"Aluno '{aluno_id}' já está matriculado.")
    decisao = repositorio.registrar_decisao(
        aluno_id, "matricula", "planejar", None,
        f"Matrícula no perfil '{matricula.perfil_id}': trilha inicial com {len(trilha.etapas)} etapas.",
        True, None, agora, planejador=planejador)
    return ResultadoMatricula(trilha=trilha, decisao=_decisao(decisao), proxima=proxima(aluno_id, agora))


def avaliar_inatividade(aluno_id: str, dados, agora: datetime) -> Avaliacao:
    """R3 com o engajamento do Relatório e o último replanejamento por inatividade."""
    retomadas = repositorio.listar_decisoes(aluno_id, "retomar")
    return regras.regra_inatividade(indicadores.engajamento(dados, agora), retomadas[-1]["ts"] if retomadas else None)


def estado(aluno_id: str, agora: datetime | None = None) -> EstadoAluno:
    """Estado do aluno, a partir da matrícula e dos dados dos três agentes."""
    agora = instante(agora)
    matricula = exigir_matricula(aluno_id)
    dados = ler_dados_aluno(aluno_id)
    trilha = ler_trilha(aluno_id)
    concluidas = repositorio_tutor.competencias_concluidas(aluno_id)
    etapas = [EtapaEstado(ordem=e.ordem, competencia_id=e.competencia_id, nome=e.nome,
                          concluida=e.competencia_id in concluidas)
              for e in sorted(trilha.etapas, key=lambda e: e.ordem)] if trilha else []
    atual = next((e.competencia_id for e in etapas if not e.concluida), None)
    engajamento = indicadores.engajamento(dados, agora)
    inatividade = avaliar_inatividade(aluno_id, dados, agora)
    decisoes = repositorio.listar_decisoes(aluno_id)
    return EstadoAluno(
        aluno_id=aluno_id,
        perfil_id=matricula["perfil_id"],
        horas_semanais=matricula["horas_semanais"],
        diagnostico=matricula["diagnostico"],
        etapas=etapas,
        competencia_atual=atual,
        sessao_aberta_id=repositorio_tutor.sessao_aberta(aluno_id, atual) if atual else None,
        concluido=trilha is not None and atual is None,
        tendencia=indicadores.tendencia(dados.respostas).direcao,
        inativo=engajamento.inativo,
        dias_inativo=engajamento.dias_inativo,
        replanejamento_pendente=inatividade.motivo if inatividade.dispara else None,
        replanejamentos=sum(d["replanejou"] and d["regra"] != "matricula" for d in decisoes),
        ultima_decisao=_decisao(decisoes[-1]) if decisoes else None,
        dialogos=len(dados.dialogos),
        dialogos_vetados=sum(d["vetada"] for d in dados.dialogos),
        rotas={
            "historico_dialogo": f"/alunos/{aluno_id}/dialogo",
            "veto_docente": "/tutor/dialogo/{dialogo_id}/veto",
            "relatorio": f"/relatorio/aluno/{aluno_id}",
            "auditoria": f"/auditoria/{aluno_id}",
        },
    )


def proxima(aluno_id: str, agora: datetime | None = None) -> ProximaAcao:
    return regras.proxima_acao(estado(aluno_id, agora))


def replanejar(aluno_id: str, avaliacao: Avaliacao, evento_id: str | None,
               agora: datetime | None = None) -> DecisaoReplanejamento:
    """Aciona o Planejador com o estado atual (diagnóstico ajustado pela ação)
    e grava a decisão com o motivo. Se a regra não disparou, grava "nenhuma"."""
    agora = instante(agora)
    if not avaliacao.dispara:
        return _decisao(repositorio.registrar_decisao(aluno_id, avaliacao.regra, "nenhuma", avaliacao.competencia_id,
                                                      avaliacao.motivo, False, evento_id, agora, avaliacao.sessao_id))
    matricula = exigir_matricula(aluno_id)
    dados = ler_dados_aluno(aluno_id)
    concluidas = repositorio_tutor.competencias_concluidas(aluno_id)
    c = avaliacao.competencia_id
    da_competencia = [r for r in dados.respostas if r["competencia_id"] == c]
    taxa = sum(r["acertou"] for r in da_competencia) / len(da_competencia) if da_competencia else None
    prerequisitos = next((comp.get("prerequisitos", []) for comp in carregar_ementa() if comp["id"] == c), [])
    diagnostico = regras.novo_diagnostico(avaliacao.acao, matricula["diagnostico"], c, taxa, prerequisitos, concluidas)

    antes = [e.competencia_id for e in sorted(ler_trilha(aluno_id).etapas, key=lambda e: e.ordem)]
    trilha, planejador = _planejar(aluno_id, matricula, diagnostico)
    depois = [e.competencia_id for e in trilha.etapas]
    repositorio.atualizar_diagnostico(aluno_id, diagnostico, agora)
    mudanca = (f" Trilha: {', '.join(antes)} -> {', '.join(depois)}." if antes != depois
               else " Trilha com as mesmas etapas, refeita a partir de hoje.")
    return _decisao(repositorio.registrar_decisao(aluno_id, avaliacao.regra, avaliacao.acao, c,
                                                  avaliacao.motivo + mudanca, True, evento_id, agora,
                                                  avaliacao.sessao_id, planejador))
