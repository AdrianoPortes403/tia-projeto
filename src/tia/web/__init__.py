"""
Aplicação web standalone do aluno (EAP 1.4.4) e painel do docente (EAP 1.4.5):
HTML, CSS e JavaScript puros em src/tia/web/static/, servidos pelo FastAPI em
/app e /app/painel (sem Node, sem build).

    static/index.html  telas do aluno: entrada, trilha, estudo, diálogo livre, relatório
    static/tema.css    SÓ variáveis de tema (trocar pelo visual do EBAULA)
    static/estilo.css  layout, usando só as variáveis do tema
    static/comum.js    utilidades compartilhadas: el/svg (textContent), chamar (contador), erros
    static/app.js      chamadas às rotas da API e montagem das telas do aluno
    static/painel/     painel do docente: index.html, painel.css, painel.js
    static/plugin/     plug-in do EBAULA (1.4.3): tia-ebaula.js e tia-ebaula.css, em /app/plugin/

As respostas de /app levam cabeçalhos de segurança (CSP só com a própria
origem, sem script inline). Login (1.4.6): as duas telas pedem usuário e
senha (rotas /auth); com TIA_AUTH=desligada, mostram o aviso do modo de
desenvolvimento.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.web.dados_demo        # alunos fictícios DEMO-W01..W03 (opcional)
    python -m tia.web.dados_painel      # turma fictícia DEMO-P01..P12 para o painel (opcional)
    uvicorn tia.api.main:app --reload
    # abrir http://localhost:8000/app/ (aluno) e http://localhost:8000/app/painel/ (docente)

Pré-requisitos:
    - pip install -e . (na raiz)
    - Ollama rodando com CHAT_MODEL e EMBED_MODEL (sem ele, os agentes usam os textos fixos)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import tia.core.config as config

PASTA_ESTATICA = Path(__file__).parent / "static"
PREFIXO = "/app"
PAINEL = PREFIXO + "/painel"

# CSP: tudo da própria origem; sem script/estilo inline nem eval; sem iframe de terceiros
_CSP_BASE = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
             "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; ")
CABECALHOS_SEGURANCA = {
    "Content-Security-Policy": _CSP_BASE + "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def cabecalhos_app() -> dict[str, str]:
    """Cabeçalhos das respostas de /app. Igual a CABECALHOS_SEGURANCA, mas com o frame-ancestors
    liberado para as origens de TIA_FRAME_ANCESTORS (plug-in EBAULA, EAP 1.4.3). Lido a cada
    pedido, para os testes e o .env valerem sem reiniciar o módulo."""
    origens = config.origens_iframe(config.FRAME_ANCESTORS)[0]
    if not origens:
        return CABECALHOS_SEGURANCA
    return {**CABECALHOS_SEGURANCA, "Content-Security-Policy": _CSP_BASE + "frame-ancestors " + " ".join(origens)}


def montar(app: FastAPI) -> None:
    """Serve a aplicação em /app (os cabeçalhos de segurança são postos por tia.api.main)."""

    @app.get(PREFIXO, include_in_schema=False)
    def raiz_app() -> RedirectResponse:
        # caminhos relativos do index.html (tema.css, app.js) exigem a barra final
        return RedirectResponse(url=PREFIXO + "/")

    @app.get(PAINEL, include_in_schema=False)
    def raiz_painel() -> RedirectResponse:
        return RedirectResponse(url=PAINEL + "/")

    app.mount(PREFIXO, StaticFiles(directory=PASTA_ESTATICA, html=True), name="web")
    # os CABECALHOS_SEGURANCA vão nas respostas de /app pelo middleware de tia.api.main
