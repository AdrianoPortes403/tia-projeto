"""
Comparação dos modos de feedback do Tutor ("ancorado" x "livre") para
revisão pedagógica (Pessoa 4).

Para TODOS os itens do banco, simula o aluno marcando uma alternativa
errada (a seguinte à correta, como na demonstração), gera o feedback nos
modos pedidos com o LLM local e grava, lado a lado, em
docs/evidencias/tutor_feedback_<AAAA-MM-DD>.md: enunciado, resposta
marcada, gabarito, explicação verificada, veredito, saída de cada modo (com
origem LLM/guarda/fallback, fontes e tempo), o motivo e o texto descartado
quando a guarda barra o LLM, e um campo vazio "Avaliação do revisor".

Não usa sessão nem aluno_id: nenhum dado pessoal vai para o arquivo (R08).
Com 36 itens e 2 modos são 72 chamadas ao LLM; em CPU leva ~20 min.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.tutor.comparar_modos [--modos ancorado livre] [--saida caminho.md] [--itens id1 ...]
    (só a guarda no modo padrão: --modos ancorado --saida docs/evidencias/tutor_feedback_guarda_<data>.md)

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL
    - Material indexado: python -m tia.rag.ingest
"""

import argparse
import logging
import time
from datetime import date
from pathlib import Path

from tia.agentes.tutor.feedback import MODOS, ORIGENS, gerar_feedback, montar_veredito
from tia.agentes.tutor.repositorio import carregar_itens, materiais_da_competencia
from tia.core.config import CHAT_MODEL, TUTOR_MAX_TOKENS, TUTOR_NUM_TRECHOS

PASTA_EVIDENCIAS = Path("docs/evidencias")


def _alternativa(item: dict, indice: int) -> str:
    return f"{chr(65 + indice)}) {item['alternativas'][indice]}"


def _celula(texto: str) -> str:
    """Texto seguro dentro de uma célula de tabela Markdown."""
    return " ".join(texto.split()).replace("|", "\\|")


def comparar_item(item: dict, modos: tuple[str, ...] = MODOS) -> dict:
    """Feedback do item em cada modo, para uma resposta errada."""
    indice_marcado = (item["indice_correto"] + 1) % len(item["alternativas"])
    materiais = materiais_da_competencia(item["competencia_id"]) or []
    saidas = {}
    for modo in modos:
        inicio = time.perf_counter()
        resultado = gerar_feedback(item, indice_marcado, materiais, modo=modo)
        saidas[modo] = {
            "explicacao": resultado.explicacao,
            "fontes": resultado.fontes,
            "origem": resultado.origem,
            "motivo_descarte": resultado.motivo_descarte,
            "explicacao_descartada": resultado.explicacao_descartada,
            "tempo_s": time.perf_counter() - inicio,
        }
    return {"item": item, "indice_marcado": indice_marcado, "saidas": saidas}


def formatar_item(numero: int, resultado: dict) -> str:
    item, saidas = resultado["item"], resultado["saidas"]
    modos = list(saidas)
    linhas = [
        f"## {numero}. `{item['id']}` ({item['competencia_id']}, nível {item['nivel']})",
        "",
        "**Enunciado:**",
        "",
        "```",
        item["enunciado"],
        "```",
        "",
        "**Alternativas:** " + " · ".join(_alternativa(item, i) for i in range(len(item["alternativas"]))),
        "",
        f"**Resposta marcada pelo aluno:** {_alternativa(item, resultado['indice_marcado'])}",
        "",
        f"**Gabarito:** {_alternativa(item, item['indice_correto'])}",
        "",
        f"**Explicação verificada (banco de itens):** {item['explicacao']}",
        "",
        f"**Veredito (fixo, gerado por código):** {montar_veredito(item, resultado['indice_marcado'])}",
        "",
        "| | " + " | ".join(f"Modo {m}" for m in modos) + " |",
        "|---|" + "---|" * len(modos),
    ]

    def linha(rotulo: str, valor) -> str:
        return f"| {rotulo} | " + " | ".join(valor(saidas[m]) for m in modos) + " |"

    linhas += [
        linha("**Saída**", lambda s: _celula(s["explicacao"])),
        linha("Origem", lambda s: s["origem"]),
        linha("Fontes", lambda s: ", ".join(s["fontes"]) or "(nenhuma)"),
        linha("Tempo", lambda s: f"{s['tempo_s']:.1f} s"),
    ]
    if any(s["origem"] == "guarda" for s in saidas.values()):
        linhas += [
            linha("Motivo do descarte", lambda s: _celula(s["motivo_descarte"]) or "-"),
            linha("Texto do LLM descartado", lambda s: _celula(s["explicacao_descartada"]) or "-"),
        ]
    linhas += [
        "",
        "**Avaliação do revisor:**",
        "",
        "> ",
        "",
        "---",
        "",
    ]
    return "\n".join(linhas)


def formatar_relatorio(resultados: list[dict], hoje: date) -> str:
    modos = list(resultados[0]["saidas"]) if resultados else list(MODOS)

    def contar(modo: str, origem: str) -> int:
        return sum(r["saidas"][modo]["origem"] == origem for r in resultados)

    descricao = {
        "ancorado": "- **Ancorado** (padrão): o LLM reformula a explicação verificada do item, apoiado nos "
                    "trechos do material, proibido de calcular ou inventar valores e de citar o próprio prompt.",
        "livre": "- **Livre** (só para comparação): o LLM explica a partir dos trechos do material, sem a "
                 "explicação verificada.",
    }
    contagens = ". ".join(
        f"{m.capitalize()}: " + ", ".join(f"{contar(m, o)} {'do LLM' if o == 'LLM' else o}" for o in ORIGENS)
        for m in modos)
    cabecalho = [
        f"# Feedback do Tutor: {' x '.join(f'modo {m}' for m in modos)} ({hoje.isoformat()})",
        "",
        "Evidência para a revisão pedagógica (Pessoa 4). Gerado por "
        f"`python -m tia.agentes.tutor.comparar_modos --modos {' '.join(modos)}`.",
        "",
        "**PROVISÓRIO:** banco de itens e material de apoio são provisórios (A3), "
        "até a entrega do conteúdo real.",
        "",
        f"- Modelo: `{CHAT_MODEL}` (local, via Ollama). Limite: {TUTOR_MAX_TOKENS} tokens, "
        f"até {TUTOR_NUM_TRECHOS} trechos do RAG.",
        "- Em todos os itens, o aluno simulado marcou uma alternativa **errada** (a seguinte à correta).",
        "- **Veredito**: texto fixo gerado por código; o LLM o recebe pronto e não o decide nem o repete.",
        *(descricao[m] for m in modos),
        "- **Guarda**: a explicação do LLM foi descartada (número que não está no item nem nos trechos, "
        "referência ao prompt ou contradição com o veredito); o aluno recebe a explicação verificada, sem fonte.",
        "- **Fallback**: quando não há trecho relevante ou o LLM falha, o aluno recebe a "
        "explicação verificada, sem fonte.",
        f"- Itens: {len(resultados)}. {contagens}.",
        f"- **Total de descartes pela guarda:** "
        + ", ".join(f"{m} {contar(m, 'guarda')}" for m in modos) + ".",
        "",
        "Na **Avaliação do revisor**, indicar por item: a saída está correta? "
        + ("Qual modo é melhor? " if len(modos) > 1 else "O descarte da guarda foi justo? ")
        + "Algum erro conceitual?",
        "",
        "---",
        "",
    ]
    corpo = [formatar_item(n, r) for n, r in enumerate(resultados, 1)]
    return "\n".join(cabecalho) + "\n".join(corpo)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compara os modos de feedback do Tutor.")
    parser.add_argument("--modos", nargs="+", choices=MODOS, default=list(MODOS),
                        help="modos a gerar (padrão: todos)")
    parser.add_argument("--saida", help="arquivo .md (padrão: docs/evidencias/tutor_feedback_<data>.md)")
    parser.add_argument("--itens", nargs="*", help="só estes ids (padrão: todos os itens do banco)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)  # ruído da telemetria do Chroma

    hoje = date.today()
    saida = Path(args.saida) if args.saida else PASTA_EVIDENCIAS / f"tutor_feedback_{hoje.isoformat()}.md"
    itens = [i for i in carregar_itens() if not args.itens or i["id"] in args.itens]

    inicio, resultados = time.perf_counter(), []
    for n, item in enumerate(itens, 1):
        resultado = comparar_item(item, tuple(args.modos))
        resultados.append(resultado)
        tempos = " | ".join(f"{m} {s['origem']} {s['tempo_s']:.1f} s"
                            + (f" ({s['motivo_descarte']})" if s["motivo_descarte"] else "")
                            for m, s in resultado["saidas"].items())
        print(f"[{n}/{len(itens)}] {item['id']}: {tempos}", flush=True)

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(formatar_relatorio(resultados, hoje), encoding="utf-8")
    print(f"\nGravado em {saida} ({len(resultados)} itens, {time.perf_counter() - inicio:.0f} s no total).")
