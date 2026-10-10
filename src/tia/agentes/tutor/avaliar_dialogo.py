"""
Avaliação do portão de cobertura do diálogo do Tutor (parte 2b).

Usa tests/dados/perguntas_avaliacao.json (perguntas cobertas e fora do
material, divididas em "ajuste" e "validacao"). Para cada pergunta, busca
os trechos reais no RAG e aplica o portão (dialogo.avaliar_cobertura).

    1. varre TUTOR_COBERTURA_MIN SÓ no conjunto de ajuste e escolhe o valor:
       entre os que deixam 0 pergunta "fora" chegar ao LLM, o que deixa mais
       perguntas cobertas chegarem (empate: o meio do intervalo);
    2. aplica o valor escolhido (ou --minimo) aos dois conjuntos e imprime,
       separados: perguntas fora que chegariam ao LLM (meta: 0) e perguntas
       cobertas que chegariam ao LLM (meta: >= 80%), com a lista dos erros;
    3. com --com-llm, roda o diálogo de ponta a ponta com o LLM local e conta
       as respostas de origem "LLM" (as barradas pela guarda vão como trecho
       transcrito, origem "guarda");
    4. com --gravar, salva os trechos recuperados e os termos genéricos em
       tests/dados/trechos_avaliacao.json, usados pelo teste offline
       (tests/test_dialogo.py). Regravar quando o material mudar.

Nada é gravado no banco e nenhum aluno é usado (R08).

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.tutor.avaliar_dialogo [--minimo 0.5] [--com-llm] [--gravar]

Pré-requisitos:
    - Ollama rodando com EMBED_MODEL (e CHAT_MODEL, com --com-llm)
    - Material indexado: python -m tia.rag.ingest
"""

import argparse
import json
import logging
import time
from pathlib import Path

from tia.agentes.tutor.dialogo import (avaliar_cobertura, buscar_trechos_dialogo, gerar_resposta,
                                       termos_genericos)
from tia.agentes.tutor.repositorio import materiais_da_competencia, palavras_chave
from tia.core.config import CHAT_MODEL, TUTOR_COBERTURA_MIN, TUTOR_DISTANCIA_MAXIMA

PERGUNTAS = Path("tests/dados/perguntas_avaliacao.json")
INSTANTANEO = Path("tests/dados/trechos_avaliacao.json")
META_COBERTAS = 0.8


def carregar_perguntas(caminho: Path = PERGUNTAS) -> list[dict]:
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)["perguntas"]


def recuperar(perguntas: list[dict]) -> list[dict]:
    """Trechos relevantes (já filtrados pela distância) de cada pergunta."""
    for p in perguntas:
        materiais = materiais_da_competencia(p["competencia_id"]) if p["competencia_id"] else None
        p["trechos"] = buscar_trechos_dialogo(p["pergunta"], materiais)
    return perguntas


def aplicar_portao(perguntas: list[dict], genericos: frozenset[str], minimo: float) -> list[dict]:
    """Decisão do portão por pergunta: chega ao LLM? (sem trecho, não chega)."""
    resultados = []
    for p in perguntas:
        cobertura = avaliar_cobertura(p["pergunta"], [t["texto"] for t in p["trechos"]], genericos,
                                      palavras_chave(p["competencia_id"]), minimo)
        resultados.append({**p, "chega_ao_llm": bool(p["trechos"]) and cobertura.passou,
                           "fracao": cobertura.fracao, "termos": cobertura.termos, "cobertos": cobertura.cobertos})
    return resultados


def contar(resultados: list[dict]) -> tuple[list[dict], list[dict], int]:
    """(fora que chegam ao LLM, cobertas barradas, total de cobertas)."""
    fora = [r for r in resultados if not r["coberta"] and r["chega_ao_llm"]]
    barradas = [r for r in resultados if r["coberta"] and not r["chega_ao_llm"]]
    return fora, barradas, sum(r["coberta"] for r in resultados)


def escolher_minimo(ajuste: list[dict], genericos: frozenset[str]) -> tuple[float, list[tuple]]:
    """Varre o mínimo de 0,05 em 0,05 SÓ no ajuste; devolve o escolhido e a tabela."""
    tabela = []
    for passo in range(1, 21):
        minimo = round(passo * 0.05, 2)
        fora, barradas, total = contar(aplicar_portao(ajuste, genericos, minimo))
        tabela.append((minimo, len(fora), total - len(barradas), total))
    sem_fora = [linha for linha in tabela if linha[1] == 0]
    if not sem_fora:  # metas incompatíveis: fica com o que menos deixa passar "fora"
        menor = min(linha[1] for linha in tabela)
        sem_fora = [linha for linha in tabela if linha[1] == menor]
    melhor = max(linha[2] for linha in sem_fora)
    empatados = [linha[0] for linha in sem_fora if linha[2] == melhor]
    return round((min(empatados) + max(empatados)) / 2, 2), tabela


def relatar(nome: str, resultados: list[dict]):
    fora, barradas, total = contar(resultados)
    n_fora = sum(not r["coberta"] for r in resultados)
    chegam = total - len(barradas)
    print(f"\n[{nome}] fora do material que chegariam ao LLM: {len(fora)}/{n_fora} (meta: 0)")
    for r in fora:
        print(f"    ERRO {r['id']} [{r['competencia_id']}] {r['pergunta']}  "
              f"(cobertura {r['fracao']:.2f}; termos {r['termos']}; cobertos {r['cobertos']})")
    print(f"[{nome}] cobertas que chegariam ao LLM: {chegam}/{total} = {chegam / total:.0%} "
          f"(meta: >= {META_COBERTAS:.0%})")
    for r in barradas:
        motivo = "sem trecho relevante" if not r["trechos"] else (
            f"cobertura {r['fracao']:.2f}; termos {r['termos']}; cobertos {r['cobertos']}")
        print(f"    ERRO {r['id']} [{r['competencia_id']}] {r['pergunta']}  ({motivo})")


def avaliar_com_llm(resultados: list[dict]):
    """Diálogo de ponta a ponta com o LLM local (sem gravar no banco)."""
    print(f"\nPonta a ponta com o LLM local ({CHAT_MODEL}):")
    for conjunto in ("ajuste", "validacao"):
        do_conjunto = [r for r in resultados if r["conjunto"] == conjunto]
        for r in do_conjunto:
            materiais = materiais_da_competencia(r["competencia_id"]) if r["competencia_id"] else None
            inicio = time.perf_counter()
            saida = gerar_resposta(r["pergunta"], materiais, palavras_chave(r["competencia_id"]))
            r["origem_final"] = saida.origem
            print(f"  [{conjunto}] {r['id']} {'coberta' if r['coberta'] else 'fora   '} -> {saida.origem:8s} "
                  f"{time.perf_counter() - inicio:5.1f} s  {saida.motivo_descarte or ''}", flush=True)
            print(f"      {saida.resposta[:160]}")
        fora_llm = [r["id"] for r in do_conjunto if not r["coberta"] and r["origem_final"] == "LLM"]
        cobertas = [r for r in do_conjunto if r["coberta"]]
        cob_llm = sum(r["origem_final"] == "LLM" for r in cobertas)
        print(f"  [{conjunto}] respondidas pelo LLM: fora {len(fora_llm)} {fora_llm} | "
              f"cobertas {cob_llm}/{len(cobertas)} = {cob_llm / len(cobertas):.0%}")


def gravar_instantaneo(perguntas: list[dict], genericos: frozenset[str], caminho: Path = INSTANTANEO):
    dados = {
        "_nota": ("Gerado por python -m tia.agentes.tutor.avaliar_dialogo --gravar: trechos que o RAG "
                  "real recuperou para cada pergunta de perguntas_avaliacao.json e os termos genéricos "
                  "do índice. Usado pelo teste offline do portão. Regravar quando o material mudar."),
        "distancia_maxima": TUTOR_DISTANCIA_MAXIMA,
        "termos_genericos": sorted(genericos),
        "trechos": {p["id"]: [{"texto": t["texto"], "fonte": t["fonte"], "indice": t.get("indice", 0),
                               "distancia": round(t["distancia"], 1)} for t in p["trechos"]]
                    for p in perguntas},
    }
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nInstantâneo gravado em {caminho}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Avalia o portão de cobertura do diálogo do Tutor.")
    parser.add_argument("--minimo", type=float, help="usa este mínimo em vez do escolhido no ajuste")
    parser.add_argument("--com-llm", action="store_true", help="roda também o diálogo com o LLM local")
    parser.add_argument("--gravar", action="store_true", help=f"grava {INSTANTANEO} para o teste offline")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)  # ruído da telemetria do Chroma

    perguntas = recuperar(carregar_perguntas())
    genericos = termos_genericos()
    print(f"Termos genéricos do índice (> metade dos trechos): {sorted(genericos)}")
    ajuste = [p for p in perguntas if p["conjunto"] == "ajuste"]
    validacao = [p for p in perguntas if p["conjunto"] == "validacao"]

    escolhido, tabela = escolher_minimo(ajuste, genericos)
    print("\nVarredura de TUTOR_COBERTURA_MIN no AJUSTE (mínimo | fora que chegam | cobertas que chegam):")
    for minimo, fora, cobertas, total in tabela:
        print(f"    {minimo:.2f} | {fora} | {cobertas}/{total}")
    minimo = args.minimo if args.minimo is not None else escolhido
    print(f"\nEscolhido no ajuste: {escolhido:.2f}. Em uso: {minimo:.2f} (config atual: {TUTOR_COBERTURA_MIN:.2f}).")

    resultados = aplicar_portao(perguntas, genericos, minimo)
    relatar("AJUSTE", [r for r in resultados if r["conjunto"] == "ajuste"])
    relatar("VALIDAÇÃO", [r for r in resultados if r["conjunto"] == "validacao"])
    if args.gravar:
        gravar_instantaneo(perguntas, genericos)
    if args.com_llm:
        avaliar_com_llm(resultados)
