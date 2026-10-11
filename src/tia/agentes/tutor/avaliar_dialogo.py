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
    2b. --termo-raro sim|nao liga/desliga a regra do termo mais raro
       (padrão: TUTOR_EXIGE_TERMO_RARO);
    3. com --com-llm, roda o diálogo de ponta a ponta com o LLM local e conta
       as respostas de origem "LLM" (as barradas pela guarda vão como trecho
       transcrito, origem "guarda");
    4. com --gravar, salva os trechos recuperados e os termos genéricos em
       tests/dados/trechos_avaliacao.json, usados pelo teste offline
       (tests/test_dialogo.py). Regravar quando o material mudar.

Nada é gravado no banco e nenhum aluno é usado (R08).

Num conjunto de teste sem perguntas de "ajuste" (ex.: perguntas_avaliacao_v2.json),
nada é varrido: usa TUTOR_COBERTURA_MIN (ou --minimo) e só mede.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.tutor.avaliar_dialogo [--minimo 0.5] [--com-llm] [--gravar]
    python -m tia.agentes.tutor.avaliar_dialogo --perguntas tests/dados/perguntas_avaliacao_v2.json \
        --instantaneo tests/dados/trechos_avaliacao_v2.json [--gravar]

Pré-requisitos:
    - Ollama rodando com EMBED_MODEL (e CHAT_MODEL, com --com-llm)
    - Material indexado: python -m tia.rag.ingest
"""

import argparse
import json
import logging
import time
from pathlib import Path

import tia.agentes.tutor.dialogo as dialogo
from tia.agentes.tutor.dialogo import (avaliar_cobertura, buscar_trechos_dialogo, gerar_resposta,
                                       termos_genericos, textos_do_indice)
from tia.agentes.tutor.repositorio import materiais_da_competencia, palavras_chave
from tia.core.config import CHAT_MODEL, TUTOR_COBERTURA_MIN, TUTOR_DISTANCIA_MAXIMA, TUTOR_EXIGE_TERMO_RARO

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


def aplicar_portao(perguntas: list[dict], genericos: frozenset[str], minimo: float,
                   textos_indice: tuple[str, ...] | None = None) -> list[dict]:
    """Decisão do portão por pergunta: chega ao LLM? (sem trecho, não chega).
    textos_indice: liga a regra do termo mais raro."""
    resultados = []
    for p in perguntas:
        cobertura = avaliar_cobertura(p["pergunta"], [t["texto"] for t in p["trechos"]], genericos,
                                      palavras_chave(p["competencia_id"]), minimo, textos_indice)
        resultados.append({**p, "chega_ao_llm": bool(p["trechos"]) and cobertura.passou,
                           "fracao": cobertura.fracao, "termos": cobertura.termos, "cobertos": cobertura.cobertos,
                           "raros": cobertura.raros})
    return resultados


def contar(resultados: list[dict]) -> tuple[list[dict], list[dict], int]:
    """(fora que chegam ao LLM, cobertas barradas, total de cobertas)."""
    fora = [r for r in resultados if not r["coberta"] and r["chega_ao_llm"]]
    barradas = [r for r in resultados if r["coberta"] and not r["chega_ao_llm"]]
    return fora, barradas, sum(r["coberta"] for r in resultados)


def escolher_minimo(ajuste: list[dict], genericos: frozenset[str],
                    textos_indice: tuple[str, ...] | None = None) -> tuple[float, list[tuple]]:
    """Varre o mínimo de 0,05 em 0,05 SÓ no ajuste; devolve o escolhido e a tabela."""
    tabela = []
    for passo in range(1, 21):
        minimo = round(passo * 0.05, 2)
        fora, barradas, total = contar(aplicar_portao(ajuste, genericos, minimo, textos_indice))
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
              f"(cobertura {r['fracao']:.2f}; termos {r['termos']}; cobertos {r['cobertos']}; raros {r['raros']})")
    print(f"[{nome}] cobertas que chegariam ao LLM: {chegam}/{total} = {chegam / total:.0%} "
          f"(meta: >= {META_COBERTAS:.0%})")
    for r in barradas:
        motivo = "sem trecho relevante" if not r["trechos"] else (
            f"cobertura {r['fracao']:.2f}; termos {r['termos']}; cobertos {r['cobertos']}; raros {r['raros']}")
        print(f"    ERRO {r['id']} [{r['competencia_id']}] {r['pergunta']}  ({motivo})")


def avaliar_com_llm(resultados: list[dict]):
    """Diálogo de ponta a ponta com o LLM local (sem gravar no banco)."""
    print(f"\nPonta a ponta com o LLM local ({CHAT_MODEL}):")
    for conjunto in dict.fromkeys(r["conjunto"] for r in resultados):
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
                  "real recuperou para cada pergunta do conjunto de avaliação e os termos genéricos "
                  "do índice. Usado pelo teste offline do portão. Regravar quando o material mudar."),
        "distancia_maxima": TUTOR_DISTANCIA_MAXIMA,
        "termos_genericos": sorted(genericos),
        "textos_indice": list(textos_do_indice()),
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
    parser.add_argument("--gravar", action="store_true", help="grava o instantâneo para o teste offline")
    parser.add_argument("--termo-raro", choices=("sim", "nao"),
                        help="liga/desliga a regra do termo mais raro (padrão: TUTOR_EXIGE_TERMO_RARO)")
    parser.add_argument("--perguntas", type=Path, default=PERGUNTAS, help=f"padrão: {PERGUNTAS}")
    parser.add_argument("--instantaneo", type=Path, default=INSTANTANEO, help=f"padrão: {INSTANTANEO}")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    perguntas = recuperar(carregar_perguntas(args.perguntas))
    genericos = termos_genericos()
    print(f"Termos genéricos do índice (> metade dos trechos): {sorted(genericos)}")
    ajuste = [p for p in perguntas if p["conjunto"] == "ajuste"]
    termo_raro = TUTOR_EXIGE_TERMO_RARO if args.termo_raro is None else args.termo_raro == "sim"
    dialogo.TUTOR_EXIGE_TERMO_RARO = termo_raro  # vale também para --com-llm
    textos_indice = textos_do_indice() if termo_raro else None
    print(f"Regra do termo mais raro: {'LIGADA' if termo_raro else 'desligada'}.")

    if ajuste:
        escolhido, tabela = escolher_minimo(ajuste, genericos, textos_indice)
        print("\nVarredura de TUTOR_COBERTURA_MIN no AJUSTE (mínimo | fora que chegam | cobertas que chegam):")
        for minimo, fora, cobertas, total in tabela:
            print(f"    {minimo:.2f} | {fora} | {cobertas}/{total}")
        print(f"\nEscolhido no ajuste: {escolhido:.2f}.")
    else:
        escolhido = TUTOR_COBERTURA_MIN
        print("\nConjunto sem perguntas de ajuste: só medição, nada é varrido.")
    minimo = args.minimo if args.minimo is not None else escolhido
    print(f"Em uso: {minimo:.2f} (config atual: {TUTOR_COBERTURA_MIN:.2f}).")

    resultados = aplicar_portao(perguntas, genericos, minimo, textos_indice)
    for conjunto in dict.fromkeys(r["conjunto"] for r in resultados):
        relatar(conjunto.upper(), [r for r in resultados if r["conjunto"] == conjunto])
    if args.gravar:
        gravar_instantaneo(perguntas, genericos, args.instantaneo)
    if args.com_llm:
        avaliar_com_llm(resultados)
