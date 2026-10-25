"""
Ponto de entrada do backend do Sistema TIA.

Como rodar (a partir da raiz do projeto):
    uvicorn tia.api.main:app --reload

Depois, abra http://localhost:8000/app/ para a aplicação web standalone
(tia.web) e http://localhost:8000/app/painel/ para o painel do docente. A
documentação interativa (http://localhost:8000/docs) só existe com
API_DOCS=1, padrão em TIA_AMBIENTE=desenvolvimento (core/config.py).

Segurança (1.4.6): toda resposta leva cabeçalhos de segurança (CSP,
X-Content-Type-Options, Referrer-Policy; tia.web para /app). Erro de
validação (422) não devolve o valor enviado (que pode ser senha ou texto do
aluno). Com TIA_AMBIENTE=producao (padrão), a API não sobe com configuração
insegura (config.problemas_de_configuracao).

Ou, equivalente:
    python -m tia.api.main

Pré-requisitos:
    - pip install -e . (na raiz, com o venv ativo)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import tia.core.config as config

from tia.api.rotas_auditoria import router as rotas_auditoria
from tia.api.rotas_auth import router as rotas_auth
from tia.api.rotas_auth import router_admin as rotas_admin
from tia.api.rotas_orquestrador import router as rotas_orquestrador
from tia.api.rotas_orquestrador import router_sistema as rotas_orquestrador_sistema
from tia.api.rotas_painel import router as rotas_painel
from tia.api.rotas_painel import router_conteudo as rotas_conteudo
from tia.api.rotas_primeiro_acesso import router as rotas_primeiro_acesso
from tia.api.rotas_planejador import router as rotas_planejador
from tia.api.rotas_relatorio import router as rotas_relatorio
from tia.api.rotas_tutor import router as rotas_tutor
from tia.core.database import criar_tabelas
from tia.seguranca import limpeza
from tia import web

log = logging.getLogger(__name__)


async def limpar_periodicamente(minutos: int):
    """Retenção das tabelas de segurança (seguranca.limpeza) ao subir e a cada `minutos`."""
    while True:
        try:
            await asyncio.to_thread(limpeza.limpar)
        except Exception as erro:  # a limpeza nunca derruba a API; tenta de novo na próxima volta
            log.warning("Limpeza de segurança falhou: %s", type(erro).__name__)
        await asyncio.sleep(minutos * 60)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Executado uma vez, ao iniciar o servidor: confere a configuração (em
    # produção), garante que as tabelas existem e liga a limpeza periódica
    # (1.4.6; AUTH_LIMPEZA_MINUTOS=0 desliga).
    problemas = config.problemas_de_configuracao()
    if config.EM_PRODUCAO and problemas:
        raise RuntimeError("A API não sobe com configuração insegura em produção (TIA_AMBIENTE=producao): "
                           + "; ".join(problemas) + ". Corrija o .env ou, só na máquina de desenvolvimento, "
                           "use TIA_AMBIENTE=desenvolvimento.")
    criar_tabelas()
    tarefa = None
    if config.AUTH_LIMPEZA_MINUTOS > 0:
        tarefa = asyncio.create_task(limpar_periodicamente(config.AUTH_LIMPEZA_MINUTOS))
    yield
    if tarefa:
        tarefa.cancel()


# Respostas da API (JSON): nada de conteúdo ativo, de iframe, de referer nem de cache
CABECALHOS_API = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
# /docs (só com API_DOCS=1): a página do Swagger carrega script e estilo do CDN do FastAPI
CABECALHOS_DOCS = {
    **CABECALHOS_API,
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
                                "frame-ancestors 'none'"),
}
ROTAS_DOCS = ("/docs", "/docs/oauth2-redirect")


def cabecalhos_para(caminho: str) -> dict[str, str]:
    if caminho == web.PREFIXO or caminho.startswith(web.PREFIXO + "/"):
        return web.cabecalhos_app()
    return CABECALHOS_DOCS if caminho in ROTAS_DOCS else CABECALHOS_API


def criar_app() -> FastAPI:
    """Monta a API com a configuração atual (os testes criam outra com API_DOCS diferente)."""
    app = FastAPI(title="Sistema TIA — API", version="0.1.0", lifespan=ciclo_de_vida,
                  docs_url="/docs" if config.API_DOCS else None, redoc_url=None,
                  openapi_url="/openapi.json" if config.API_DOCS else None)
    app.include_router(rotas_auth)
    app.include_router(rotas_admin)
    app.include_router(rotas_planejador)
    app.include_router(rotas_tutor)
    app.include_router(rotas_auditoria)
    app.include_router(rotas_relatorio)
    app.include_router(rotas_orquestrador)
    app.include_router(rotas_orquestrador_sistema)
    app.include_router(rotas_painel)
    app.include_router(rotas_conteudo)
    app.include_router(rotas_primeiro_acesso)
    web.montar(app)  # aplicação web standalone em /app (EAP 1.4.4) e painel em /app/painel (1.4.5)

    @app.middleware("http")
    async def cabecalhos_seguranca(request: Request, chamar_proximo):
        resposta = await chamar_proximo(request)
        resposta.headers.update(cabecalhos_para(request.url.path))
        return resposta

    @app.exception_handler(RequestValidationError)
    async def erro_de_validacao(request: Request, erro: RequestValidationError) -> JSONResponse:
        # o padrão do FastAPI devolve o valor recebido ("input"), que pode ser a
        # senha ou o texto do aluno: aqui só onde e por quê (R08)
        detalhes = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
                    for e in erro.errors()]
        return JSONResponse(status_code=422, content={"detail": detalhes})

    @app.get("/health")
    def health_check():
        """Endpoint simples para confirmar que o serviço está no ar."""
        return {"status": "ok"}

    return app


app = criar_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tia.api.main:app", reload=True)
