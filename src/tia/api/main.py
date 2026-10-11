"""
Ponto de entrada do backend do Sistema TIA.

Como rodar (a partir da raiz do projeto):
    uvicorn tia.api.main:app --reload

Depois, abra http://localhost:8000/docs para ver a documentação
interativa gerada automaticamente pelo FastAPI, ou
http://localhost:8000/app/ para a aplicação web standalone (tia.web) e
http://localhost:8000/app/painel/ para o painel do docente.

Ou, equivalente:
    python -m tia.api.main

Pré-requisitos:
    - pip install -e . (na raiz, com o venv ativo)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import tia.core.config as config

from tia.api.rotas_auditoria import router as rotas_auditoria
from tia.api.rotas_auth import router as rotas_auth
from tia.api.rotas_auth import router_admin as rotas_admin
from tia.api.rotas_orquestrador import router as rotas_orquestrador
from tia.api.rotas_orquestrador import router_sistema as rotas_orquestrador_sistema
from tia.api.rotas_painel import router as rotas_painel
from tia.api.rotas_painel import router_conteudo as rotas_conteudo
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
    # Executado uma vez, ao iniciar o servidor: garante que as tabelas existem
    # e liga a limpeza periódica (1.4.6; AUTH_LIMPEZA_MINUTOS=0 desliga).
    criar_tabelas()
    tarefa = None
    if config.AUTH_LIMPEZA_MINUTOS > 0:
        tarefa = asyncio.create_task(limpar_periodicamente(config.AUTH_LIMPEZA_MINUTOS))
    yield
    if tarefa:
        tarefa.cancel()


app = FastAPI(title="Sistema TIA — API", version="0.1.0", lifespan=ciclo_de_vida)
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
web.montar(app)  # aplicação web standalone em /app (EAP 1.4.4) e painel em /app/painel (1.4.5)


@app.get("/health")
def health_check():
    """Endpoint simples para confirmar que o serviço está no ar."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tia.api.main:app", reload=True)
