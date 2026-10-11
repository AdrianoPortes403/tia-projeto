"""
Demonstração do Agente 2 (Tutor), parte 2a, com o LLM local de verdade.

Simula um aluno fictício (código DEMO-002) que erra e acerta
alternadamente numa competência, até ela terminar. Para cada resposta
imprime nível, acerto, veredito, origem da explicação (LLM; guarda, quando
a guarda de saída barrou o LLM; ou fallback, sem trecho/LLM falhou; nos
dois últimos vai o texto do item), fontes citadas, explicação e o tempo da
interação (referência: R09, até 15 s, a medir na VM).

Com --dialogo, demonstra o diálogo livre (parte 2b) com o aluno fictício
DEMO-003: três perguntas, uma coberta pelo material, uma fora dele
(resposta fixa, sem LLM) e uma em que a guarda descarta a resposta do
LLM, mostrando origem, fontes e tempo de cada uma.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.tutor [competencia_id] [--modo ancorado|livre]
    (padrão: repeticao, modo de TUTOR_MODO_FEEDBACK)
    python -m tia.agentes.tutor --dialogo

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL
    - Material indexado: python -m tia.rag.ingest
"""

import argparse
import logging

from tia.agentes.tutor import iniciar_sessao, responder
from tia.agentes.tutor.dialogo import perguntar
from tia.agentes.tutor.feedback import MODOS, ORIGENS
from tia.agentes.tutor.modelos import IniciarSessao, PerguntaAluno, RespostaAluno
from tia.agentes.tutor.repositorio import carregar_itens
from tia.core.config import CHAT_MODEL, TUTOR_MODO_FEEDBACK
from tia.core.database import criar_tabelas

LIMITE_R09_MS = 15_000

# (competência, pergunta, o que se espera); perguntas fictícias da demonstração.
# A da guarda depende do modelo e da TUTOR_SEED: com qwen3:1.7b e seed 42, o LLM
# calcula o último valor do range (19), que não está na pergunta nem no material.
PERGUNTAS_DIALOGO = [
    ("repeticao", "Qual a diferença entre while e for?", "coberta pelo material: LLM com fonte"),
    ("condicionais", "Qual a capital da França?", "fora do material: resposta fixa, sem LLM"),
    ("repeticao", "Quantas vezes roda um for i in range(2, 20, 3)?", "guarda descarta número calculado"),
]


def demonstrar_dialogo():
    """Três perguntas livres, com origem, fontes e tempo de cada resposta."""
    aluno_id = "DEMO-003"  # código fictício, nunca nome (R08)
    print(f"\nDiálogo livre com o Tutor (modelo {CHAT_MODEL})\n")
    tempos = []
    for n, (competencia_id, pergunta, esperado) in enumerate(PERGUNTAS_DIALOGO, 1):
        r = perguntar(PerguntaAluno(aluno_id=aluno_id, pergunta=pergunta, competencia_id=competencia_id))
        tempos.append(r.tempo_ms)
        print(f"{n}. [{competencia_id}] {pergunta}")
        print(f"   esperado: {esperado}")
        print(f"   origem: {r.origem} | {r.tempo_ms / 1000:.2f} s")
        print(f"   fontes: {', '.join(r.fontes) or '(nenhuma: resposta fixa)'}")
        print(f"   resposta: {r.resposta}\n")
    print(f"Tempo do diálogo: máx {max(tempos) / 1000:.2f} s, médio {sum(tempos) / len(tempos) / 1000:.2f} s "
          f"(R09: até {LIMITE_R09_MS / 1000:.0f} s, a medir na VM)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demonstração do Agente 2 (Tutor).")
    parser.add_argument("competencia_id", nargs="?", default="repeticao")
    parser.add_argument("--modo", choices=MODOS, default=TUTOR_MODO_FEEDBACK,
                        help="modo do feedback (padrão: TUTOR_MODO_FEEDBACK)")
    parser.add_argument("--dialogo", action="store_true", help="demonstra o diálogo livre (parte 2b)")
    args = parser.parse_args()
    competencia_id = args.competencia_id

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    criar_tabelas()
    if args.dialogo:
        demonstrar_dialogo()
        raise SystemExit(0)
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
