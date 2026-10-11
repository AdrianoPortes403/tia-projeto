"""
Aplicação web standalone do aluno (EAP 1.4.4): HTML, CSS e JavaScript puros
em src/tia/web/static/, servidos pelo FastAPI em /app (sem Node, sem build).

    static/index.html  telas: entrada, trilha, estudo, diálogo livre, relatório
    static/tema.css    SÓ variáveis de tema (trocar pelo visual do EBAULA)
    static/estilo.css  layout, usando só as variáveis do tema
    static/app.js      chamadas às rotas da API e montagem das telas (textContent)

As respostas de /app levam cabeçalhos de segurança (CSP só com a própria
origem, sem script inline). Sem login: TODO 1.4.6.

Como rodar (a partir da raiz, com o venv ativo):
    python -m tia.web.dados_demo        # alunos fictícios DEMO-W01..W03 (opcional)
    uvicorn tia.api.main:app --reload
    # abrir http://localhost:8000/app/

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

    app.mount(PREFIXO, StaticFiles(directory=PASTA_ESTATICA, html=True), name="web")

    @app.middleware("http")
    async def cabecalhos_seguranca(request: Request, chamar_proximo):
        resposta = await chamar_proximo(request)
        if request.url.path == PREFIXO or request.url.path.startswith(PREFIXO + "/"):
            resposta.headers.update(CABECALHOS_SEGURANCA)
        return resposta
