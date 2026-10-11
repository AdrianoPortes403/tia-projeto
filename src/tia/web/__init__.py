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

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

PASTA_ESTATICA = Path(__file__).parent / "static"
PREFIXO = "/app"
PAINEL = PREFIXO + "/painel"

# CSP: tudo da própria origem; sem script/estilo inline nem eval; sem iframe de terceiros
CABECALHOS_SEGURANCA = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                                "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def montar(app: FastAPI) -> None:
    """Serve a aplicação em /app e acrescenta os cabeçalhos de segurança às respostas dela."""

    @app.get(PREFIXO, include_in_schema=False)
    def raiz_app() -> RedirectResponse:
        # caminhos relativos do index.html (tema.css, app.js) exigem a barra final
        return RedirectResponse(url=PREFIXO + "/")

    @app.get(PAINEL, include_in_schema=False)
    def raiz_painel() -> RedirectResponse:
        return RedirectResponse(url=PAINEL + "/")

    app.mount(PREFIXO, StaticFiles(directory=PASTA_ESTATICA, html=True), name="web")

    @app.middleware("http")
    async def cabecalhos_seguranca(request: Request, chamar_proximo):
        resposta = await chamar_proximo(request)
        if request.url.path == PREFIXO or request.url.path.startswith(PREFIXO + "/"):
            resposta.headers.update(CABECALHOS_SEGURANCA)
        return resposta
