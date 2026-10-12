"""
Fluxo ponta a ponta da Orquestração (EAP 1.3.5). Só COORDENA os agentes
pelas interfaces públicas deles, sem duplicar lógica:

    Agente 1 (Planejador): planejar_e_salvar com as competências concluídas
                           (replanejamento incremental), ler_trilha, carregar_ementa;
    Agente 2 (Tutor):      iniciar_sessao, responder (eventos.py), pausar/retomar
                           sessão, competências concluídas, incentivo, veto (R12);
    Agente 3 (Relatório):  ler_dados_aluno, tendencia e engajamento (detecção de queda
                           e inatividade), relatórios sob demanda (/relatorio/...).

    iniciar(aluno_id, matricula)        matrícula + trilha inicial pelo Planejador
    estado(aluno_id)                    EstadoAluno montado a partir dos três agentes
    proxima(aluno_id)                   próxima ação (regras.proxima_acao)
    abrir_sessao(aluno_id, competencia) só a competência atual ou o reforço decidido
    aplicar(aluno_id, avaliacao)        executa a ação de uma regra e grava a decisão
    verificar_inatividade()             R3 em todos os alunos (chamado por agendador externo)

Toda decisão vai para orquestrador_decisoes e para a auditoria com o motivo
(R11). O relógio ("agora") é injetável para teste.

Não é executável sozinho; demonstração:
    python -m tia.orquestrador --demo

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, os agentes usam os textos fixos)
"""

import time
from datetime import datetime

from tia.agentes import tutor
from tia.agentes.planejador import planejar_e_salvar
from tia.agentes.planejador.modelos import EntradaPlanejador, Trilha
from tia.agentes.planejador.planejar import carregar_ementa, gerar_trilha
from tia.agentes.planejador.repositorio import ler_trilha
from tia.agentes.relatorio import indicadores
from tia.agentes.relatorio.repositorio import ler_dados_aluno
from tia.agentes.tutor.incentivo import montar_incentivo
from tia.agentes.tutor.modelos import IniciarSessao
from tia.orquestrador import regras, repositorio
from tia.orquestrador.modelos import (DecisaoDeAluno, DecisaoReplanejamento, EstadoAluno, EtapaEstado, Matricula,
                                      ProximaAcao, Reforco, ResultadoMatricula, ResultadoVerificacao,
                                      SessaoOrquestrada)
from tia.orquestrador.regras import Avaliacao


class ErroOrquestracao(ValueError):
    """Erro do fluxo (mensagem pensada para o usuário)."""


class AlunoNaoMatriculado(ErroOrquestracao):
    pass


class JaMatriculado(ErroOrquestracao):
    pass


class SessaoRecusada(ErroOrquestracao):
    """Pedido de sessão fora da competência atual ou do reforço (registrado na auditoria)."""


def instante(agora: datetime | None) -> datetime:
    """O "agora" injetado (testes) ou o relógio, sem microssegundos."""
    return (agora or datetime.now()).replace(microsecond=0)


def _decisao(dados: dict) -> DecisaoReplanejamento:
    return DecisaoReplanejamento(**dados)


def _nomes() -> dict[str, str]:
    return {c["id"]: c["nome"] for c in carregar_ementa()}


def exigir_matricula(aluno_id: str) -> dict:
    matricula = repositorio.ler_matricula(aluno_id)
    if matricula is None:
        raise AlunoNaoMatriculado(f"Aluno '{aluno_id}' não está matriculado no fluxo; use POST /aluno/{{id}}/iniciar.")
    return matricula


def _prazo_restante(matricula: dict, agora: datetime | None) -> int | None:
    """Dias que faltam do prazo da matrícula (mínimo 1); None sem prazo."""
    prazo = matricula.get("prazo_dias")
    if not prazo:
        return None
    criado = matricula.get("criado_em")
    decorridos = (instante(agora) - datetime.fromisoformat(criado)).days if criado else 0
    return max(1, prazo - max(0, decorridos))


def _entrada(aluno_id: str, matricula: dict, concluidas: list[str] | None = None,
             agora: datetime | None = None) -> EntradaPlanejador:
    """Pedido ao Planejador a partir da matrícula (perfil, trilha, diagnóstico, prazo)."""
    return EntradaPlanejador(
        aluno_id=aluno_id, perfil_id=matricula.get("perfil_id"), trilha=matricula.get("trilha"),
        diagnostico=matricula["diagnostico"], horas_semanais=matricula["horas_semanais"],
        concluidas=concluidas or [], prazo_dias=_prazo_restante(matricula, agora),
        escopo=matricula.get("escopo") or "completa")


def competencias_originais(aluno_id: str, matricula: dict) -> set[str]:
    """Competências da trilha original: a que o Planejador monta com o perfil e o
    diagnóstico da matrícula, sem nenhuma concluída (determinístico, sem LLM)."""
    trilha = gerar_trilha(_entrada(aluno_id, matricula))
    return {e.competencia_id for e in trilha.etapas}


def _planejar(aluno_id: str, matricula: dict, agora: datetime | None = None) -> tuple[Trilha, dict]:
    """Aciona o Planejador com as competências já concluídas (só planeja o
    que falta). Devolve a trilha e o resumo para a decisão: origem das
    justificativas (só das etapas que faltam), motivo de falha e tempo.

    Só passam as concluídas que pertencem à trilha original: um reforço (R2) de
    pré-requisito que o aluno tinha dispensado no diagnóstico é concluído no Tutor,
    mas não vira etapa da trilha nem conta no progresso."""
    inicio = time.perf_counter()
    concluidas = tutor.repositorio.competencias_concluidas(aluno_id) & competencias_originais(aluno_id, matricula)
    trilha = planejar_e_salvar(_entrada(aluno_id, matricula, sorted(concluidas), agora))
    origens = {e.origem_justificativa for e in trilha.etapas if not e.concluida}
    origem = None if not origens else "LLM" if origens == {"LLM"} else \
        "fallback" if origens <= {"fallback", None} else "parcial"
    return trilha, {"origem_justificativas": origem, "falha_llm": trilha.falha_llm,
                    "tempo_planejador_ms": round((time.perf_counter() - inicio) * 1000)}


def iniciar(aluno_id: str, matricula: Matricula, agora: datetime | None = None) -> ResultadoMatricula:
    """Matrícula no fluxo: o Planejador gera a trilha inicial. Erros do
    Planejador (perfil ou competência inexistente) sobem como ErroPlanejador."""
    agora = instante(agora)
    if repositorio.ler_matricula(aluno_id) is not None:
        raise JaMatriculado(f"Aluno '{aluno_id}' já está matriculado; o replanejamento é feito pelas regras.")
    dados = {"perfil_id": matricula.perfil_id, "horas_semanais": matricula.horas_semanais,
             "diagnostico": matricula.diagnostico, "trilha": matricula.trilha,
             "prazo_dias": matricula.prazo_dias, "escopo": matricula.escopo}
    trilha, planejador = _planejar(aluno_id, dados, agora)  # valida perfil e competências antes de gravar
    # grava o perfil em uso: o informado ou o enquadrado pelo Planejador a partir do diagnóstico
    if not repositorio.salvar_matricula(aluno_id, trilha.perfil_id, matricula.horas_semanais,
                                        matricula.diagnostico, agora, matricula.trilha, matricula.prazo_dias,
                                        matricula.escopo):
        raise JaMatriculado(f"Aluno '{aluno_id}' já está matriculado.")
    como = (f"enquadrado pelo diagnóstico (P = {trilha.pontuacao_enquadramento})"
            if trilha.perfil_automatico and trilha.pontuacao_enquadramento is not None
            else "sem diagnóstico" if trilha.perfil_automatico else "informado")
    trilha_txt = f" na trilha '{matricula.trilha}'" if matricula.trilha else ""
    decisao = repositorio.registrar_decisao(
        aluno_id, "matricula", "planejar", None,
        f"Matrícula{trilha_txt} no perfil '{trilha.perfil_id}' ({como}): trilha inicial com "
        f"{len(trilha.etapas)} etapas.",
        True, None, agora, planejador=planejador)
    return ResultadoMatricula(trilha=trilha, decisao=_decisao(decisao), proxima=proxima(aluno_id, agora))


def _ultima(aluno_id: str, acao: str) -> str | None:
    decisoes = repositorio.listar_decisoes(aluno_id, acao)
    return decisoes[-1]["ts"] if decisoes else None


def _etapas(aluno_id: str) -> list[EtapaEstado]:
    """Etapas da trilha atual, em ordem, com a conclusão do Planejador ou do Tutor."""
    trilha = ler_trilha(aluno_id)
    concluidas = tutor.repositorio.competencias_concluidas(aluno_id)
    return [EtapaEstado(ordem=e.ordem, competencia_id=e.competencia_id, nome=e.nome,
                        concluida=e.concluida or e.competencia_id in concluidas)
            for e in sorted(trilha.etapas, key=lambda e: e.ordem)] if trilha else []


def trilha_concluida(aluno_id: str) -> bool:
    """Tem trilha, todas as etapas concluídas e nenhum reforço em curso."""
    etapas = _etapas(aluno_id)
    return bool(etapas) and all(e.concluida for e in etapas) and repositorio.reforco_ativo(aluno_id) is None


def avaliar_inatividade(aluno_id: str, dados, agora: datetime) -> Avaliacao:
    """R3 com o engajamento do Relatório e as últimas ações por inatividade;
    quem concluiu a trilha não entra."""
    return regras.regra_inatividade(indicadores.engajamento(dados, agora), _ultima(aluno_id, "incentivar"),
                                    _ultima(aluno_id, "refazer_trilha"), trilha_concluida=trilha_concluida(aluno_id))


def estado(aluno_id: str, agora: datetime | None = None) -> EstadoAluno:
    """Estado do aluno, a partir da matrícula e dos dados dos três agentes."""
    agora = instante(agora)
    matricula = exigir_matricula(aluno_id)
    dados = ler_dados_aluno(aluno_id)
    etapas = _etapas(aluno_id)
    atual = next((e.competencia_id for e in etapas if not e.concluida), None)
    reforco = repositorio.reforco_ativo(aluno_id)
    engajamento = indicadores.engajamento(dados, agora)
    inatividade = avaliar_inatividade(aluno_id, dados, agora)
    concluiu = bool(etapas) and atual is None and reforco is None
    decisoes = repositorio.listar_decisoes(aluno_id)
    return EstadoAluno(
        aluno_id=aluno_id,
        perfil_id=matricula["perfil_id"],
        horas_semanais=matricula["horas_semanais"],
        diagnostico=matricula["diagnostico"],
        trilha=matricula.get("trilha"),
        prazo_dias=matricula.get("prazo_dias"),
        escopo=matricula.get("escopo") or "completa",
        etapas=etapas,
        competencia_atual=atual,
        sessao_aberta_id=tutor.repositorio.sessao_aberta(aluno_id, atual) if atual else None,
        reforco=Reforco(**{k: reforco[k] for k in ("competencia_original", "sessao_original_id",
                                                    "competencia_reforco", "sessao_reforco_id", "estado")})
        if reforco else None,
        concluido=atual is None and reforco is None,
        tendencia=indicadores.tendencia(dados.respostas).direcao,
        inativo=engajamento.inativo and not concluiu,  # R3: quem concluiu a trilha não é inativo
        dias_inativo=engajamento.dias_inativo,
        replanejamento_pendente=inatividade.motivo if inatividade.dispara else None,
        replanejamentos=sum(d["replanejou"] and d["regra"] != "matricula" for d in decisoes),
        ultima_decisao=_decisao(decisoes[-1]) if decisoes else None,
        dialogos=len(dados.dialogos),
        dialogos_vetados=sum(d["vetada"] for d in dados.dialogos),
        rotas={
            "abrir_sessao": f"/aluno/{aluno_id}/sessao",
            "historico_dialogo": f"/alunos/{aluno_id}/dialogo",
            "veto_docente": "/tutor/dialogo/{dialogo_id}/veto",
            "relatorio": f"/relatorio/aluno/{aluno_id}",
            "auditoria": f"/auditoria/{aluno_id}",
        },
    )


def proxima(aluno_id: str, agora: datetime | None = None) -> ProximaAcao:
    """Próxima ação; em "continuar_sessao", com a pergunta em aberto da sessão
    (o cliente retoma a sessão sem ter guardado a pergunta, ex.: após recarregar
    a página ou na volta de um reforço)."""
    acao = regras.proxima_acao(estado(aluno_id, agora))
    if acao.acao == "continuar_sessao" and acao.sessao_id:
        acao.pergunta = tutor.pergunta_atual(acao.sessao_id, aluno_id)
    return acao


def _registrar(aluno_id: str, avaliacao: Avaliacao, acao: str, motivo: str, evento_id: str | None,
               agora: datetime, replanejou: bool = False, planejador: dict | None = None,
               aviso: str | None = None) -> DecisaoReplanejamento:
    return _decisao(repositorio.registrar_decisao(aluno_id, avaliacao.regra, acao, avaliacao.competencia_id, motivo,
                                                  replanejou, evento_id, agora, avaliacao.sessao_id, planejador, aviso))


def aplicar(aluno_id: str, avaliacao: Avaliacao, evento_id: str | None = None,
            agora: datetime | None = None) -> DecisaoReplanejamento:
    """Executa a ação da regra e grava a decisão com o motivo (R11). Se a
    regra não disparou, grava "nenhuma"."""
    agora = instante(agora)
    if not avaliacao.dispara:
        return _registrar(aluno_id, avaliacao, "nenhuma", avaliacao.motivo, evento_id, agora)
    matricula = exigir_matricula(aluno_id)
    nomes = _nomes()

    if avaliacao.acao in ("avancar", "refazer_trilha"):
        trilha_antes = ler_trilha(aluno_id)
        antes = [e.competencia_id for e in trilha_antes.etapas if not e.concluida] if trilha_antes else []
        trilha, planejador = _planejar(aluno_id, matricula, agora)
        depois = [e.competencia_id for e in trilha.etapas if not e.concluida]
        motivo = avaliacao.motivo + (f" A fazer: {', '.join(antes) or '-'} -> {', '.join(depois) or '-'}."
                                     if antes != depois else " Etapas a fazer sem mudança; semanas recontadas.")
        if avaliacao.acao == "avancar":
            aviso = regras.aviso_conclusao(nomes.get(avaliacao.competencia_id, avaliacao.competencia_id),
                                           nomes.get(depois[0]) if depois else None)
        else:
            aviso = montar_incentivo(aluno_id, agora).mensagem
        return _registrar(aluno_id, avaliacao, avaliacao.acao, motivo, evento_id, agora, True, planejador, aviso)

    if avaliacao.acao == "revisar_material":
        from tia.agentes.tutor.repositorio import materiais_da_competencia  # import tardio: evita ciclo
        arquivos = materiais_da_competencia(avaliacao.competencia_id) or []
        aviso = regras.AVISO_MATERIAL.format(
            competencia=nomes.get(avaliacao.competencia_id, avaliacao.competencia_id),
            materiais=(" (" + ", ".join(arquivos) + ")") if arquivos else "")
        return _registrar(aluno_id, avaliacao, "revisar_material", avaliacao.motivo, evento_id, agora, aviso=aviso)

    if avaliacao.acao == "incentivar":
        incentivo = montar_incentivo(aluno_id, agora)
        tutor.repositorio.registrar_incentivo(aluno_id, incentivo.proxima_etapa)
        return _registrar(aluno_id, avaliacao, "incentivar", avaliacao.motivo, evento_id, agora,
                          aviso=incentivo.mensagem)

    # reforcar: pausa a sessão original e cria o reforço do pré-requisito direto
    if not tutor.repositorio.pausar_sessao(avaliacao.sessao_id, aluno_id):
        return _registrar(aluno_id, avaliacao, "nenhuma",
                          avaliacao.motivo + " Mas a sessão não pôde ser pausada (concluída ou já pausada).",
                          evento_id, agora)
    original, reforco = avaliacao.competencia_id, avaliacao.competencia_reforco
    decisao = _registrar(aluno_id, avaliacao, "reforcar", avaliacao.motivo, evento_id, agora,
                         aviso=regras.AVISO_REFORCO.format(reforco=nomes.get(reforco, reforco),
                                                           original=nomes.get(original, original)))
    repositorio.criar_reforco(aluno_id, original, avaliacao.sessao_id, reforco, decisao.decisao_id, agora)
    return decisao


def concluir_reforco(aluno_id: str, sessao_id: str, evento_id: str | None,
                     agora: datetime | None = None) -> DecisaoReplanejamento | None:
    """Se a sessão concluída é a de um reforço em andamento: encerra o reforço
    e retoma a sessão original no nível em que parou. None se não é reforço."""
    agora = instante(agora)
    reforco = repositorio.reforco_ativo(aluno_id)
    if reforco is None or reforco["sessao_reforco_id"] != sessao_id:
        return None
    repositorio.concluir_reforco(reforco["id"], agora)
    tutor.repositorio.retomar_sessao(reforco["sessao_original_id"], aluno_id)
    original = tutor.repositorio.ler_sessao(reforco["sessao_original_id"], aluno_id)
    nomes = _nomes()
    avaliacao = Avaliacao("reforco", True, "retomar_original", reforco["competencia_original"],
                          f"Reforço de '{reforco['competencia_reforco']}' concluído: retomar "
                          f"'{reforco['competencia_original']}' no nível {original.nivel}, sem zerar.",
                          reforco["sessao_original_id"])
    aviso = regras.AVISO_RETOMADA.format(reforco=nomes.get(reforco["competencia_reforco"]),
                                         original=nomes.get(reforco["competencia_original"]), nivel=original.nivel)
    return _registrar(aluno_id, avaliacao, "retomar_original", avaliacao.motivo, evento_id, agora, aviso=aviso)


def abrir_sessao(aluno_id: str, competencia_id: str, agora: datetime | None = None) -> SessaoOrquestrada:
    """Abre sessão do Tutor só para a competência atual ou para o reforço
    decidido pelo orquestrador. Recusa (SessaoRecusada) qualquer outra, com
    registro na auditoria."""
    agora = instante(agora)
    exigir_matricula(aluno_id)
    prox = proxima(aluno_id, agora)
    if prox.acao == "iniciar_sessao" and competencia_id == prox.competencia_id:
        # nível inicial do diagnóstico (Planejador); reforço sempre do nível 1
        trilha = None if prox.reforco else ler_trilha(aluno_id)
        etapa = next((e for e in trilha.etapas if e.competencia_id == competencia_id), None) if trilha else None
        nivel = etapa.nivel_inicial if etapa and etapa.nivel_inicial else None
        sessao = tutor.iniciar_sessao(IniciarSessao(aluno_id=aluno_id, competencia_id=competencia_id,
                                                    nivel_inicial=nivel))
        if prox.reforco:
            repositorio.vincular_sessao_reforco(repositorio.reforco_ativo(aluno_id)["id"], sessao.sessao_id)
        tipo = "reforço" if prox.reforco else "competência atual"
        avaliacao = Avaliacao("sessao", True, "abrir_sessao", competencia_id,
                              f"Sessão aberta em '{competencia_id}' ({tipo}).", sessao.sessao_id)
        decisao = _registrar(aluno_id, avaliacao, "abrir_sessao", avaliacao.motivo, None, agora)
        return SessaoOrquestrada(sessao=sessao, reforco=prox.reforco, decisao=decisao)

    if prox.acao == "concluido":
        motivo = f"Trilha concluída: não há sessão a abrir (pedido: '{competencia_id}')."
    elif prox.acao == "continuar_sessao" and competencia_id == prox.competencia_id:
        motivo = f"Já há sessão em andamento em '{competencia_id}' (sessao_id {prox.sessao_id}); continue-a."
    else:
        motivo = (f"Sessão recusada: agora só é possível estudar '{prox.competencia_id}' "
                  f"({'reforço' if prox.reforco else 'competência atual'}); pedido: '{competencia_id}'.")
    _registrar(aluno_id, Avaliacao("sessao", False, "recusar_sessao", competencia_id, motivo), "recusar_sessao",
               motivo, None, agora)
    raise SessaoRecusada(motivo)


def verificar_inatividade(agora: datetime | None = None) -> ResultadoVerificacao:
    """Avalia a R3 em todos os alunos matriculados e registra cada decisão
    (inclusive "nenhuma"). Feito para ser chamado por agendador externo
    (cron/timer na VM); repetir no mesmo dia não duplica incentivo nem
    replanejamento (cada ação vale uma vez por período sem atividade)."""
    agora = instante(agora)
    decisoes = []
    for aluno_id in repositorio.listar_matriculas():
        avaliacao = avaliar_inatividade(aluno_id, ler_dados_aluno(aluno_id), agora)
        decisoes.append(DecisaoDeAluno(aluno_id=aluno_id, decisao=aplicar(aluno_id, avaliacao, None, agora)))
    return ResultadoVerificacao(verificados=len(decisoes), decisoes=decisoes)
