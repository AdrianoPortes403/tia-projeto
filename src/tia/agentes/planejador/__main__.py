"""
Demonstração do Agente 1 (Planejador) com o LLM local de verdade.

Gera a trilha de um aluno fictício (código DEMO-001), pede as
justificativas ao Ollama, salva no banco, relê e imprime a trilha com o
tempo total (referência: R09, até 15 s por interação).

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.agentes.planejador

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (ex.: ollama pull qwen3:1.7b)
"""

import logging
import time

from tia.agentes.planejador import planejar_e_salvar
from tia.agentes.planejador.modelos import EntradaPlanejador
from tia.agentes.planejador.repositorio import ler_trilha
from tia.core.config import CHAT_MODEL
from tia.core.database import criar_tabelas

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    criar_tabelas()

    entrada = EntradaPlanejador(
        aluno_id="DEMO-001",  # código fictício, nunca nome (R08)
        perfil_id="intermediario",
        diagnostico={"variaveis_tipos": 0.9, "condicionais": 0.75, "repeticao": 0.5,
                     "funcoes": 0.4, "listas_strings": 0.3, "recursao": 0.1},
        horas_semanais=6,
    )

    inicio = time.perf_counter()
    planejar_e_salvar(entrada)
    tempo_total = time.perf_counter() - inicio

    trilha = ler_trilha(entrada.aluno_id)  # relê do banco para provar a persistência
    print(f"\nTrilha de {trilha.aluno_id} (perfil {trilha.perfil_id}, {entrada.horas_semanais} h/semana, modelo {CHAT_MODEL}):\n")
    for etapa in trilha.etapas:
        materiais = ", ".join(etapa.materiais) or "(material pendente)"
        print(f"{etapa.ordem}. [semana {etapa.semana_inicio}] {etapa.nome} — {etapa.horas} h")
        print(f"   materiais: {materiais}")
        print(f"   por quê: {etapa.justificativa}")
    horas = sum(e.horas for e in trilha.etapas)
    print(f"\n{len(trilha.etapas)} etapas, {horas:.1f} h no total.")
    print(f"Tempo total (gerar + LLM + salvar): {tempo_total:.2f} s")
