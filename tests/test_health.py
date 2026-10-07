"""
Teste básico: confirma que o backend sobe e o endpoint /health responde.

Como rodar:
    pytest tests/test_health.py
"""

from fastapi.testclient import TestClient

from tia.api.main import app

client = TestClient(app)


def test_health_check():
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
