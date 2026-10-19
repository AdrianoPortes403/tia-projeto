"""
Orquestração (EAP 1.3.5): fluxo único ponta a ponta para um aluno,
coordenando os três agentes pelas interfaces públicas deles.

    1. matricular/iniciar: aluno + perfil -> Planejador gera a trilha;
    2. estudar: o Tutor conduz a sessão da competência atual;
    3. regras (regras.py; detecção pelas regras do Relatório): conclusão
       (avança e replaneja só o que falta), queda (pausa a sessão e reforça
       o pré-requisito direto; ao concluir, retoma sem zerar) e inatividade
       (incentivo; trilha refeita só após ORQ_INATIVIDADE_REFAZER_DIAS),
       esta avaliada por verificar_inatividade, chamada por agendador externo;
    4. relatórios do aluno e da turma sob demanda (Agente 3, /relatorio/...).

No fluxo gerenciado, a sessão é aberta por abrir_sessao (só a competência
atual ou o reforço); /tutor/sessao continua para uso standalone.

Módulos:
    modelos.py     contratos Pydantic (EstadoAluno, EventoTutor, DecisaoReplanejamento...)
    regras.py      TODAS as regras de replanejamento (limiares em core/config.py)
    fluxo.py       iniciar, estado, próxima ação, abrir sessão, aplicar decisão, verificar inatividade
    eventos.py     eventos do Tutor, com idempotência por evento_id
    repositorio.py matrícula, eventos, decisões (+ auditoria, R11)

Como rodar a demonstração (aluno fictício, banco temporário):
    python -m tia.orquestrador --demo [--sem-llm]
Verificação de inatividade (para o agendador externo; usa o banco configurado):
    python -m tia.orquestrador --verificar-inatividade

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (opcional: sem ele, textos fixos)
"""

from tia.orquestrador.eventos import EventoConflitante, processar_evento
from tia.orquestrador.fluxo import (AlunoNaoMatriculado, ErroOrquestracao, JaMatriculado, SessaoRecusada,
                                    abrir_sessao, estado, iniciar, proxima, verificar_inatividade)

__all__ = ["AlunoNaoMatriculado", "ErroOrquestracao", "EventoConflitante", "JaMatriculado", "SessaoRecusada",
           "abrir_sessao", "estado", "iniciar", "processar_evento", "proxima", "verificar_inatividade"]
