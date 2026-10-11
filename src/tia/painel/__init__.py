"""
Backend do painel do docente/instituição (EAP 1.4.5): consultas somente de
leitura sobre os dados dos três agentes e da orquestração.

    modelos.py   respostas das rotas /painel e /conteudo (Pydantic)
    consultas.py alertas de risco, desempenho por competência, revisão docente,
                 exportação CSV, ementa e perfis

As telas ficam em src/tia/web/static/painel/ (servidas em /app/painel/) e as
rotas em tia.api.rotas_painel. A única rota de escrita usada pelo painel é a
do veto docente, que já existia (PATCH /tutor/dialogo/{id}/veto).
Sem login: TODO 1.4.6.

Não é executável; dados de demonstração:
    python -m tia.web.dados_painel

Pré-requisitos:
    - tabelas criadas/migradas: python -m tia.core.database
"""
