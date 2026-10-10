"""
Orquestração (EAP 1.3.5): fluxo único ponta a ponta para um aluno,
coordenando os três agentes pelas interfaces públicas deles.

    1. matricular/iniciar: aluno + perfil -> Planejador gera a trilha;
    2. estudar: o Tutor conduz a sessão da competência atual;
    3. replanejar pelo Planejador quando uma regra dispara (regras.py):
       conclusão da competência, desempenho em queda ou inatividade
       (detecção pelas regras do Relatório);
    4. relatórios do aluno e da turma sob demanda (Agente 3, /relatorio/...).

Módulos:
    modelos.py     contratos Pydantic (EstadoAluno, EventoTutor, DecisaoReplanejamento...)
    regras.py      TODAS as regras de replanejamento (limiares em core/config.py; PROVISÓRIO)
    fluxo.py       iniciar, estado, próxima ação, replanejar
    eventos.py     eventos do Tutor, com idempotência por evento_id
    repositorio.py matrícula, eventos, decisões (+ auditoria, R11)

Como rodar a demonstração (aluno fictício, banco temporário):
    python -m tia.orquestrador --demo [--sem-llm]

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, textos fixos)
"""

from tia.orquestrador.eventos import EventoConflitante, processar_evento
from tia.orquestrador.fluxo import AlunoNaoMatriculado, ErroOrquestracao, JaMatriculado, estado, iniciar, proxima

__all__ = ["AlunoNaoMatriculado", "ErroOrquestracao", "EventoConflitante", "JaMatriculado", "estado", "iniciar",
           "processar_evento", "proxima"]
