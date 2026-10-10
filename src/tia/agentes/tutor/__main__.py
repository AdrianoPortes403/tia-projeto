"""
Demonstração do Agente 2 (Tutor), parte 2a, com o LLM local de verdade.

Simula um aluno fictício (código DEMO-002) que erra e acerta
alternadamente numa competência, até ela terminar. Para cada resposta
imprime nível, acerto, veredito, origem da explicação (LLM; guarda, quando
a guarda de saída barrou o LLM; ou fallback, sem trecho/LLM falhou; nos
dois últimos vai o texto do item), fontes citadas, explicação e o tempo da
interação (referência: R09, até 15 s, a medir na VM).

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.tutor [competencia_id] [--modo ancorado|livre]
    (padrão: repeticao, modo de TUTOR_MODO_FEEDBACK)

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL
    - Material indexado: python -m tia.rag.ingest
"""

import argparse
import logging

from tia.agentes.tutor import iniciar_sessao, responder
from tia.agentes.tutor.feedback import MODOS, ORIGENS
from tia.agentes.tutor.modelos import IniciarSessao, RespostaAluno
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core.config import CHAT_MODEL, TUTOR_MODO_FEEDBACK
from tia.core.database import criar_tabelas

LIMITE_R09_MS = 15_000

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demonstração do Agente 2 (Tutor).")
    parser.add_argument("competencia_id", nargs="?", default="repeticao")
    parser.add_argument("--modo", choices=MODOS, default=TUTOR_MODO_FEEDBACK,
                        help="modo do feedback (padrão: TUTOR_MODO_FEEDBACK)")
    args = parser.parse_args()
    competencia_id = args.competencia_id

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)  # ruído da telemetria do Chroma
    criar_tabelas()
    itens = {i["id"]: i for i in carregar_itens()}  # só o "aluno" simulado e o relatório usam

    aluno_id = "DEMO-002"  # código fictício, nunca nome (R08)
    sessao = iniciar_sessao(IniciarSessao(aluno_id=aluno_id, competencia_id=competencia_id))
    print(f"\nSessão {sessao.sessao_id[:8]}… em '{competencia_id}' (modelo {CHAT_MODEL}, modo {args.modo})\n")

    pergunta, acertar, tempos, origens = sessao.pergunta, False, [], []
    while pergunta is not None:
        correto = itens[pergunta.item_id]["indice_correto"]
        indice = correto if acertar else (correto + 1) % 4
        fb = responder(RespostaAluno(sessao_id=sessao.sessao_id, aluno_id=aluno_id,
                                     item_id=pergunta.item_id, indice_escolhido=indice), modo=args.modo)
        tempos.append(fb.tempo_ms)
        origens.append(fb.origem)
        print(f"{len(tempos)}. [{pergunta.item_id}] nível {pergunta.nivel} -> "
              f"{'ACERTOU' if fb.acertou else 'errou'} -> nível {fb.nivel_atual} | {fb.tempo_ms / 1000:.2f} s")
        print(f"   veredito: {fb.veredito}")
        print(f"   origem: {fb.origem}")
        print(f"   fontes: {', '.join(fb.fontes) or '(nenhuma: texto do item)'}")
        print(f"   explicação: {fb.explicacao}\n")
        pergunta, acertar = fb.proxima_pergunta, not acertar

    print(f"Competência concluída após {len(tempos)} respostas "
          f"({', '.join(f'{origens.count(o)} {o}' for o in ORIGENS)}).")
    print(f"Tempo do feedback: máx {max(tempos) / 1000:.2f} s, médio {sum(tempos) / len(tempos) / 1000:.2f} s "
          f"(R09: até {LIMITE_R09_MS / 1000:.0f} s) -> "
          f"{'OK' if max(tempos) <= LIMITE_R09_MS else 'ACIMA DO LIMITE'}")
