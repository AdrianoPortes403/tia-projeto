"""
Lógica determinística do Agente 1 (Planejador): monta a trilha de estudo.

Passos de gerar_trilha:
    1. ordena as competências da ementa pelos pré-requisitos (ordenação
       topológica; empate desfeito pela ordem do arquivo da ementa);
    2. remove as competências que o perfil permite pular e em que o aluno
       tirou nota >= limiar no diagnóstico;
    3. ajusta as horas pelo ritmo do perfil e distribui as etapas em
       semanas conforme as horas semanais do aluno.

Não usa LLM: mesma entrada, mesma trilha. As frases de justificativa
geradas aqui são o texto padrão; justificar.py tenta melhorá-las com o LLM.

Como rodar (demonstração completa, com LLM):
    python -m tia.agentes.planejador

Pré-requisitos:
    - conteudo/ementa/ementa.json e conteudo/perfis/perfis.json
      (caminhos em tia.core.config; ambos PROVISÓRIOS até a entrega da Pessoa 4)
"""

import json

from tia.agentes.planejador.modelos import EntradaPlanejador, EtapaTrilha, Trilha
from tia.core.config import EMENTA_PATH, PERFIS_PATH


class ErroPlanejador(ValueError):
    """Erro de dados ao montar a trilha (mensagem pensada para o usuário)."""


class PerfilInexistente(ErroPlanejador):
    pass


class CompetenciaInexistente(ErroPlanejador):
    pass


class CicloPrerequisitos(ErroPlanejador):
    pass


def carregar_ementa(caminho: str = EMENTA_PATH) -> list[dict]:
    """Lê a lista de competências do arquivo de ementa."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["competencias"]


def carregar_perfis(caminho: str = PERFIS_PATH) -> list[dict]:
    """Lê a lista de perfis base do arquivo de perfis."""
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["perfis"]


def ordenar_por_prerequisitos(competencias: list[dict]) -> list[dict]:
    """Ordenação topológica (algoritmo de Kahn). Entre competências liberadas
    ao mesmo tempo, mantém a ordem em que aparecem na ementa.
    Levanta CompetenciaInexistente ou CicloPrerequisitos."""
    por_id = {c["id"]: c for c in competencias}
    pendentes = {}
    for c in competencias:
        for pre in c.get("prerequisitos", []):
            if pre not in por_id:
                raise CompetenciaInexistente(
                    f"A competência '{c['id']}' tem como pré-requisito '{pre}', que não existe na ementa."
                )
        pendentes[c["id"]] = set(c.get("prerequisitos", []))

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


def gerar_trilha(entrada: EntradaPlanejador, ementa: list[dict] | None = None,
                 perfis: list[dict] | None = None) -> Trilha:
    """Gera a trilha do aluno. ementa/perfis podem ser passados (ex.: testes);
    se omitidos, são lidos dos arquivos em conteudo/."""
    ementa = carregar_ementa() if ementa is None else ementa
    perfis = carregar_perfis() if perfis is None else perfis

    perfil = next((p for p in perfis if p["id"] == entrada.perfil_id), None)
    if perfil is None:
        disponiveis = ", ".join(p["id"] for p in perfis)
        raise PerfilInexistente(f"Perfil '{entrada.perfil_id}' não existe. Perfis disponíveis: {disponiveis}.")

    ids_ementa = {c["id"] for c in ementa}
    desconhecidas = sorted(set(entrada.diagnostico) - ids_ementa)
    if desconhecidas:
        raise CompetenciaInexistente(
            f"Diagnóstico cita competência(s) fora da ementa: {', '.join(desconhecidas)}."
        )

    limiares = perfil.get("competencias_dispensaveis", {})
    etapas = []
    horas_acumuladas = 0.0
    for competencia in ordenar_por_prerequisitos(ementa):
        cid = competencia["id"]
        nota = entrada.diagnostico.get(cid, 0.0)
        if cid in limiares and nota >= limiares[cid]:
            continue  # aluno já domina: o perfil permite pular

        horas = round(competencia["horas_estimadas"] * perfil["ritmo"], 1)
        semana_inicio = int(horas_acumuladas // entrada.horas_semanais) + 1
        horas_acumuladas += horas

        if competencia.get("prerequisitos"):
            motivo = "vem depois de " + ", ".join(competencia["prerequisitos"])
        else:
            motivo = "é base para as demais competências"
        etapas.append(EtapaTrilha(
            ordem=len(etapas) + 1,
            competencia_id=cid,
            nome=competencia["nome"],
            materiais=competencia.get("materiais", []),
            horas=horas,
            semana_inicio=semana_inicio,
            justificativa=f"Nota no diagnóstico {nota:.2f}; {motivo}.",
        ))

    return Trilha(aluno_id=entrada.aluno_id, perfil_id=entrada.perfil_id, etapas=etapas)
