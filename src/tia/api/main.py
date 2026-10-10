"""
Ponto de entrada do backend do Sistema TIA.

Como rodar (a partir da raiz do projeto):
    uvicorn tia.api.main:app --reload

Depois, abra http://localhost:8000/docs para ver a documentação
interativa gerada automaticamente pelo FastAPI.

Ou, equivalente:
    python -m tia.api.main

Pré-requisitos:
    - pip install -e . (na raiz, com o venv ativo)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from tia.api.rotas_planejador import router as rotas_planejador
from tia.api.rotas_tutor import router as rotas_tutor
from tia.core.database import criar_tabelas


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Executado uma vez, ao iniciar o servidor: garante que as tabelas existem.
    criar_tabelas()
    yield
    # (nada a fazer ao encerrar, por enquanto)


app = FastAPI(title="Sistema TIA — API", version="0.1.0", lifespan=ciclo_de_vida)
app.include_router(rotas_planejador)
app.include_router(rotas_tutor)


@app.get("/health")
def health_check():
    """Endpoint simples para confirmar que o serviço está no ar."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tia.api.main:app", reload=True)
