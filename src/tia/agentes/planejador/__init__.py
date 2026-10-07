"""
Agente 1 (Planejador): gera a trilha de estudo do aluno a partir do
diagnóstico, do perfil base e da ementa.

Ponto de entrada único: planejar_e_salvar (usado pela API e pela demonstração).

Como rodar a demonstração:
    python -m tia.agentes.planejador

Pré-requisitos:
    - Ollama rodando com CHAT_MODEL (opcional: sem ele, justificativas padrão)
"""

from tia.agentes.planejador.justificar import justificar_trilha
from tia.agentes.planejador.modelos import EntradaPlanejador, Trilha
from tia.agentes.planejador.planejar import gerar_trilha
from tia.agentes.planejador.repositorio import salvar_trilha


def planejar_e_salvar(entrada: EntradaPlanejador) -> Trilha:
    """Gera a trilha (determinística), pede as justificativas ao LLM e salva."""
    trilha = justificar_trilha(gerar_trilha(entrada), entrada.diagnostico)
    salvar_trilha(trilha, entrada.horas_semanais)
    return trilha
