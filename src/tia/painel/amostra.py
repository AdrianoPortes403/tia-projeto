"""
Amostra de textos gerados pelo LLM para a avaliação docente (R12, critério de
sucesso). Protocolo: docs/avaliacao/protocolo_amostra.md.

Sorteia, com semente fixa, até N textos com origem "LLM" (explicações do
feedback das questões e respostas do diálogo), ESTRATIFICADOS por
competência: cada competência com texto recebe pelo menos 1 vaga (se N
permitir) e o resto é dividido na proporção do número de textos dela (maiores
restos). Mesmo banco + mesma semente = mesma amostra.

Exporta um CSV (";", UTF-8 com BOM, para o Excel em pt-BR) com o texto, o
item, a origem e as fontes, mais as colunas vazias "adequado (S/N)" e
"observacao" para o docente preencher. Sem código de aluno (R08). A pergunta
do diálogo é texto livre do aluno: o arquivo é de uso interno da avaliação e
fica em data/ (fora do git). A exportação é registrada na auditoria.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.painel.amostra --n 100 [--semente 2026] [--tipo feedback|dialogo] [--saida arquivo.csv]

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - textos gravados (tutor_feedbacks e tutor_dialogo); para testar: python -m tia.web.dados_painel
"""

import argparse
import csv
import io
import json
import math
import random
import time
from pathlib import Path

from tia.agentes.planejador.planejar import carregar_ementa
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core.config import DB_PATH
from tia.core.database import obter_conexao
from tia.painel.consultas import auditar_consulta, celula

SEMENTE_PADRAO = 2026
SEM_COMPETENCIA = "(sem competência)"
COLUNAS = ["amostra", "tipo", "id", "competencia", "item_id", "nivel", "pergunta_ou_enunciado", "veredito",
           "texto_avaliado", "origem", "fontes", "data", "adequado (S/N)", "observacao"]


def candidatos(tipo: str | None = None) -> list[dict]:
    """Textos com origem LLM (o ORIGINAL, mesmo se depois vetado), sem aluno_id.
    Ordem estável (tipo, id), para o sorteio ser reprodutível."""
    conexao = obter_conexao()
    try:
        feedbacks = conexao.execute(
            """SELECT 'feedback' AS tipo, resposta_id AS id, ts, competencia_id, item_id, NULL AS pergunta,
                      veredito, explicacao AS texto, origem, fontes
               FROM tutor_feedbacks WHERE origem = 'LLM'""").fetchall()
        dialogos = conexao.execute(
            """SELECT 'dialogo' AS tipo, id, ts, competencia_id, NULL AS item_id, pergunta, NULL AS veredito,
                      resposta AS texto, origem, fontes
               FROM tutor_dialogo WHERE origem = 'LLM'""").fetchall()
    finally:
        conexao.close()
    banco = {i["id"]: i for i in carregar_itens()}
    textos = []
    for linha in list(feedbacks) + list(dialogos):
        if tipo is not None and linha["tipo"] != tipo:
            continue
        item = banco.get(linha["item_id"], {})
        textos.append({"tipo": linha["tipo"], "id": linha["id"], "ts": linha["ts"],
                       "competencia_id": linha["competencia_id"] or SEM_COMPETENCIA, "item_id": linha["item_id"],
                       "nivel": item.get("nivel"),
                       "pergunta": linha["pergunta"] if linha["tipo"] == "dialogo" else item.get("enunciado", ""),
                       "veredito": linha["veredito"], "texto": linha["texto"], "origem": linha["origem"],
                       "fontes": json.loads(linha["fontes"] or "[]")})
    return sorted(textos, key=lambda t: (t["tipo"], t["id"]))


def alocar(tamanhos: dict[str, int], n: int) -> dict[str, int]:
    """Vagas por estrato: pelo menos 1 por estrato (se n >= número de estratos)
    e o resto proporcional ao tamanho, pelo método dos maiores restos, sem
    passar do tamanho de cada um. Determinístico (empates pela chave)."""
    if n >= sum(tamanhos.values()):
        return dict(tamanhos)
    cotas = {k: 0 for k in tamanhos}
    if n >= len([t for t in tamanhos.values() if t]):
        cotas = {k: min(1, t) for k, t in tamanhos.items()}
    while sum(cotas.values()) < n:
        livres = {k: tamanhos[k] - cotas[k] for k in tamanhos if tamanhos[k] > cotas[k]}
        faltam = n - sum(cotas.values())
        total_livre = sum(livres.values())
        ideais = {k: faltam * livre / total_livre for k, livre in livres.items()}
        inteiros = {k: min(livres[k], math.floor(v)) for k, v in ideais.items()}
        if sum(inteiros.values()) == 0:  # sobra menor que um por estrato: maiores restos
            for k in sorted(livres, key=lambda k: (-(ideais[k] - math.floor(ideais[k])), k))[:faltam]:
                cotas[k] += 1
        else:
            for k, v in inteiros.items():
                cotas[k] += v
    return cotas


def sortear(textos: list[dict], n: int, semente: int = SEMENTE_PADRAO) -> list[dict]:
    """Amostra estratificada por competência, na ordem da ementa e do id."""
    estratos: dict[str, list[dict]] = {}
    for texto in textos:
        estratos.setdefault(texto["competencia_id"], []).append(texto)
    cotas = alocar({k: len(v) for k, v in estratos.items()}, n)
    sorteio = random.Random(semente)
    ordem = {c["id"]: i for i, c in enumerate(carregar_ementa())}
    amostra = []
    for competencia in sorted(estratos, key=lambda c: (ordem.get(c, len(ordem)), c)):
        escolhidos = sorteio.sample(estratos[competencia], cotas[competencia])
        amostra += sorted(escolhidos, key=lambda t: (t["tipo"], t["id"]))
    return amostra


def para_csv(amostra: list[dict]) -> str:
    nomes = {c["id"]: c["nome"] for c in carregar_ementa()}
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUNAS)
    for numero, t in enumerate(amostra, start=1):
        escritor.writerow([celula(v) for v in (
            numero, t["tipo"], t["id"], nomes.get(t["competencia_id"], t["competencia_id"]), t["item_id"],
            t["nivel"], t["pergunta"], t["veredito"], t["texto"], t["origem"], ", ".join(t["fontes"]), t["ts"],
            "", "")])
    return "﻿" + saida.getvalue()


def exportar(n: int, semente: int = SEMENTE_PADRAO, caminho: str | None = None,
             tipo: str | None = None) -> tuple[Path, list[dict]]:
    """Sorteia, grava o CSV e registra a exportação na auditoria."""
    textos = candidatos(tipo)
    amostra = sortear(textos, n, semente)
    destino = Path(caminho or Path(DB_PATH).parent / "avaliacao" / f"amostra_llm_s{semente}_n{n}.csv")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(para_csv(amostra), encoding="utf-8")
    auditar_consulta("amostra", f"semente={semente}; n={n}; tipo={tipo or 'todos'}; {len(amostra)} de "
                                 f"{len(textos)} texto(s) LLM exportado(s) (sem código de aluno)")
    return destino, amostra


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Amostra estratificada de textos do LLM para avaliação docente.")
    parser.add_argument("--n", type=int, default=100, help="tamanho máximo da amostra (padrão 100)")
    parser.add_argument("--semente", type=int, default=SEMENTE_PADRAO, help=f"padrão {SEMENTE_PADRAO}")
    parser.add_argument("--tipo", choices=["feedback", "dialogo"], help="só um tipo de texto (padrão: os dois)")
    parser.add_argument("--saida", help="arquivo CSV (padrão: data/avaliacao/amostra_llm_s<semente>_n<n>.csv)")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n precisa ser pelo menos 1")
    inicio = time.perf_counter()
    destino, amostra = exportar(args.n, args.semente, args.saida, args.tipo)
    por_competencia: dict[str, int] = {}
    for t in amostra:
        por_competencia[t["competencia_id"]] = por_competencia.get(t["competencia_id"], 0) + 1
    print(f"Banco: {DB_PATH}")
    print(f"Amostra: {len(amostra)} texto(s) (semente {args.semente}); por competência: {por_competencia}")
    print(f"CSV: {destino}")
    print(f"Tempo gasto: {time.perf_counter() - inicio:.1f} s")
