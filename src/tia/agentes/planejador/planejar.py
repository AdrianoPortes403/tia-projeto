"""
Lógica determinística do Agente 1 (Planejador): monta a trilha de estudo.

Passos de gerar_trilha:
    1. seleciona os tópicos: base comum (etapa 0, Python) + a trilha escolhida
       (dev ou defesa_cibernetica); sem trilha, só a base comum. No escopo
       "piloto", só os tópicos marcados no_piloto (1.5.1);
    2. enquadra o perfil (1.2.3) quando ele não é informado: P = média de
       nota x 3 nos tópicos diagnosticados da base comum e da etapa 1;
       P >= limiar -> intermediário, senão iniciante;
    3. ordena pelos pré-requisitos (ordenação topológica; empate desfeito
       pela ordem do arquivo da ementa). Pré-requisito fora da seleção (ex.:
       no escopo piloto) conta como cumprido e gera um aviso;
    4. competências já concluídas (entrada.concluidas, replanejamento
       incremental) entram marcadas como concluídas, sem horas nem semana:
       nunca voltam a ficar pendentes e contam como pré-requisito cumprido;
    5. remove os tópicos dominados no diagnóstico (nota 1), em qualquer perfil;
    6. ajusta as horas pelo ritmo do perfil e distribui só as etapas que
       faltam em semanas, a partir da semana 1, conforme as horas semanais;
    7. marca, por perfil: pré-requisitos a revisar (iniciante, antes de tópico
       médio ou difícil) e desafio prático no fim de cada etapa (intermediário);
    8. com prazo: diz se cabe e, se não couber, as duas opções (mais horas por
       semana ou o recorte de tópicos que cabe).

Não usa LLM: mesma entrada, mesma trilha. As frases de justificativa
geradas aqui são o texto padrão; justificar.py tenta melhorá-las com o LLM.

Como rodar (demonstração completa, com LLM):
    python -m tia.agentes.planejador

Pré-requisitos:
    - conteudo/ementa/ementa.json e conteudo/perfis/perfis.json
      (caminhos em tia.core.config; base pedagógica 1.2.3 e 1.2.4 alinhada à EAP)
"""

import json
import math

from tia.agentes.planejador.modelos import EntradaPlanejador, EtapaTrilha, OpcoesPrazo, Trilha
from tia.core.config import EMENTA_PATH, PERFIS_PATH

BASE_COMUM = "base_comum"
NOTA_DOMINADO = 1.0
LIMIAR_PADRAO = 1.5          # usado se perfis.json não trouxer regras_enquadramento
EPS = 1e-6


class ErroPlanejador(ValueError):
    """Erro de dados ao montar a trilha (mensagem pensada para o usuário)."""


class PerfilInexistente(ErroPlanejador):
    pass


class CompetenciaInexistente(ErroPlanejador):
    pass


class CicloPrerequisitos(ErroPlanejador):
    pass


def carregar_ementa(caminho: str = EMENTA_PATH) -> list[dict]:
    """Lê a lista de competências (tópicos) do arquivo de ementa."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["competencias"]


def carregar_perfis(caminho: str = PERFIS_PATH) -> list[dict]:
    """Lê a lista de perfis base do arquivo de perfis."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["perfis"]


def carregar_regras_enquadramento(caminho: str = PERFIS_PATH) -> dict:
    """Regras de enquadramento do perfil (1.2.3); {} se o arquivo não tiver."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo).get("regras_enquadramento", {})


def trilha_da(competencia: dict) -> str:
    """Trilha do tópico; ementas sem o campo (antigas, testes) contam como base comum."""
    return competencia.get("trilha", BASE_COMUM)


def selecionar(ementa: list[dict], trilha: str | None) -> list[dict]:
    """Base comum + tópicos da trilha escolhida (sem trilha: só a base comum)."""
    return [c for c in ementa if trilha_da(c) in (BASE_COMUM, trilha)]


def ordenar_por_prerequisitos(competencias: list[dict], conhecidas: set[str] | None = None) -> list[dict]:
    """Ordenação topológica (algoritmo de Kahn). Entre competências liberadas
    ao mesmo tempo, mantém a ordem em que aparecem na ementa. Pré-requisito
    que está em 'conhecidas' mas fora da lista conta como cumprido.
    Levanta CompetenciaInexistente ou CicloPrerequisitos."""
    por_id = {c["id"]: c for c in competencias}
    conhecidas = conhecidas or set()
    pendentes = {}
    for c in competencias:
        for pre in c.get("prerequisitos", []):
            if pre not in por_id and pre not in conhecidas:
                raise CompetenciaInexistente(
                    f"A competência '{c['id']}' tem como pré-requisito '{pre}', que não existe na ementa."
                )
        pendentes[c["id"]] = {p for p in c.get("prerequisitos", []) if p in por_id}

    ordenadas = []
    while pendentes:
        liberadas = [c["id"] for c in competencias if c["id"] in pendentes and not pendentes[c["id"]]]
        if not liberadas:
            raise CicloPrerequisitos(
                "Ciclo de pré-requisitos na ementa envolvendo: " + ", ".join(sorted(pendentes))
            )
        proxima = liberadas[0]
        ordenadas.append(por_id[proxima])
        del pendentes[proxima]
        for requisitos in pendentes.values():
            requisitos.discard(proxima)
    return ordenadas


def enquadrar(diagnostico: dict[str, float], selecionadas: list[dict], perfis: list[dict],
              regras: dict) -> tuple[str, float | None]:
    """Perfil pelo diagnóstico (1.2.3). Devolve (perfil_id, P). Sem tópico
    diagnosticado na base comum nem na etapa 1: perfil 'sem_diagnostico' e P None."""
    limiar = regras.get("limiar_intermediario", LIMIAR_PADRAO)
    ids = [p["id"] for p in perfis]
    iniciante = "iniciante" if "iniciante" in ids else ids[0]
    intermediario = "intermediario" if "intermediario" in ids else ids[-1]
    cobertos = [c["id"] for c in selecionadas if c.get("etapa", 0) in (0, 1)]
    notas = [diagnostico[cid] for cid in cobertos if cid in diagnostico]
    if not notas:
        return regras.get("sem_diagnostico", iniciante), None
    pontuacao = round(3 * sum(notas) / len(notas), 2)
    return (intermediario if pontuacao >= limiar - EPS else iniciante), pontuacao


def nivel_inicial(cid: str, diagnostico: dict[str, float], perfil_id: str) -> int:
    """Nível inicial dos itens: pelo diagnóstico (1/3 -> 2, 2/3 -> 3) ou,
    sem diagnóstico do tópico, o padrão do perfil (iniciante 1, intermediário 2)."""
    if cid not in diagnostico:
        return 2 if perfil_id == "intermediario" else 1
    nota = diagnostico[cid]
    return 3 if nota >= 0.66 else 2 if nota >= 0.33 else 1  # tolerância para 1/3 e 2/3 arredondados


def _opcoes_prazo(pendentes: list[EtapaTrilha], horas_semanais: float, prazo_dias: int) -> OpcoesPrazo:
    semanas = prazo_dias / 7
    total = sum(e.horas for e in pendentes)
    capacidade = horas_semanais * semanas
    recorte, acumulado = [], 0.0
    for etapa in pendentes:
        if acumulado + etapa.horas > capacidade + EPS:
            break
        acumulado += etapa.horas
        recorte.append(etapa.competencia_id)
    return OpcoesPrazo(horas_semanais_necessarias=math.ceil(total / semanas * 2) / 2, recorte_que_cabe=recorte)


def gerar_trilha(entrada: EntradaPlanejador, ementa: list[dict] | None = None,
                 perfis: list[dict] | None = None, regras: dict | None = None) -> Trilha:
    """Gera a trilha do aluno. ementa/perfis/regras podem ser passados (ex.:
    testes); se omitidos, são lidos dos arquivos em conteudo/."""
    ementa = carregar_ementa() if ementa is None else ementa
    perfis = carregar_perfis() if perfis is None else perfis
    regras = carregar_regras_enquadramento() if regras is None else regras

    da_trilha = selecionar(ementa, entrada.trilha)
    ids_trilha = {c["id"] for c in da_trilha}
    desconhecidas = sorted(set(entrada.diagnostico) - ids_trilha)
    if desconhecidas:
        raise CompetenciaInexistente(
            f"Diagnóstico cita competência(s) fora da ementa ou da trilha escolhida: {', '.join(desconhecidas)}."
        )
    desconhecidas = sorted(set(entrada.concluidas) - ids_trilha)
    if desconhecidas:
        raise CompetenciaInexistente(
            f"Competência(s) concluída(s) fora da ementa ou da trilha escolhida: {', '.join(desconhecidas)}."
        )

    # perfil: informado ou enquadrado pelo diagnóstico
    automatico = entrada.perfil_id is None
    pontuacao = None
    if automatico:
        perfil_id, pontuacao = enquadrar(entrada.diagnostico, da_trilha, perfis, regras)
    else:
        perfil_id = entrada.perfil_id
    perfil = next((p for p in perfis if p["id"] == perfil_id), None)
    if perfil is None:
        disponiveis = ", ".join(p["id"] for p in perfis)
        raise PerfilInexistente(f"Perfil '{perfil_id}' não existe. Perfis disponíveis: {disponiveis}.")

    selecionadas = da_trilha if entrada.escopo == "completa" else [c for c in da_trilha if c.get("no_piloto")]
    avisos = []
    for c in selecionadas:
        fora = [p for p in c.get("prerequisitos", []) if p in ids_trilha and p not in {s["id"] for s in selecionadas}
                and entrada.diagnostico.get(p, 0.0) < NOTA_DOMINADO - EPS]
        if fora:
            avisos.append(f"'{c['id']}' depende de {', '.join(fora)}, fora do escopo '{entrada.escopo}' "
                          f"e não dominado(s) no diagnóstico.")

    concluidas = set(entrada.concluidas)
    limiares = perfil.get("competencias_dispensaveis", {})  # compatibilidade com perfis antigos
    revisa = perfil.get("revisar_prerequisitos", False)
    desafia = perfil.get("desafio_pratico", False)
    ritmo = perfil.get("ritmo", 1.0)
    ordenadas = ordenar_por_prerequisitos(selecionadas, {c["id"] for c in ementa})

    etapas = []
    horas_acumuladas = 0.0
    for competencia in ordenadas:
        cid = competencia["id"]
        nota = entrada.diagnostico.get(cid, 0.0)
        if cid in concluidas:  # histórico: não é planejada de novo
            etapas.append(EtapaTrilha(
                ordem=len(etapas) + 1, competencia_id=cid, nome=competencia["nome"],
                materiais=competencia.get("materiais", []), horas=0, semana_inicio=0,
                justificativa="Competência já concluída.", concluida=True,
            ))
            continue
        if cid in entrada.diagnostico and nota >= NOTA_DOMINADO - EPS:
            continue  # dominado no diagnóstico: sai da trilha em qualquer perfil
        if cid in limiares and nota >= limiares[cid]:
            continue  # perfis antigos: o perfil permite pular

        horas = round(competencia["horas_estimadas"] * ritmo, 1)
        semana_inicio = int(horas_acumuladas // entrada.horas_semanais) + 1
        horas_acumuladas += horas

        if competencia.get("prerequisitos"):
            motivo = "vem depois de " + ", ".join(competencia["prerequisitos"])
        else:
            motivo = "é base para as demais competências"
        inicio = f"Nota no diagnóstico {nota:.2f}; " if cid in entrada.diagnostico else "Sem diagnóstico; "
        revisar = (list(competencia.get("prerequisitos", []))
                   if revisa and competencia.get("dificuldade_base") in ("medio", "dificil") else [])
        etapas.append(EtapaTrilha(
            ordem=len(etapas) + 1,
            competencia_id=cid,
            nome=competencia["nome"],
            materiais=competencia.get("materiais", []),
            horas=horas,
            semana_inicio=semana_inicio,
            justificativa=f"{inicio}{motivo}.",
            revisar_antes=revisar,
            nivel_inicial=nivel_inicial(cid, entrada.diagnostico, perfil_id),
        ))

    # intermediário: desafio prático (opcional, sem horas) na última etapa pendente de cada etapa da trilha
    if desafia:
        por_id = {c["id"]: c for c in ementa}
        pendentes = [e for e in etapas if not e.concluida]
        for i, etapa in enumerate(pendentes):
            atual = por_id[etapa.competencia_id].get("etapa", 0)
            ultima = i == len(pendentes) - 1 or por_id[pendentes[i + 1].competencia_id].get("etapa", 0) != atual
            if not ultima:
                continue
            desafios = [d for e in pendentes if por_id[e.competencia_id].get("etapa", 0) == atual
                        for d in (por_id[e.competencia_id].get("desafio_pratico") or [])]
            if desafios:
                etapa.desafio_pratico = desafios[0]

    cabe, opcoes = None, None
    if entrada.prazo_dias:
        pendentes = [e for e in etapas if not e.concluida]
        capacidade = entrada.horas_semanais * entrada.prazo_dias / 7
        cabe = sum(e.horas for e in pendentes) <= capacidade + EPS
        if not cabe:
            opcoes = _opcoes_prazo(pendentes, entrada.horas_semanais, entrada.prazo_dias)

    return Trilha(aluno_id=entrada.aluno_id, perfil_id=perfil_id, etapas=etapas, trilha=entrada.trilha,
                  pontuacao_enquadramento=pontuacao, perfil_automatico=automatico, prazo_dias=entrada.prazo_dias,
                  cabe_no_prazo=cabe, opcoes_prazo=opcoes, avisos=avisos)
