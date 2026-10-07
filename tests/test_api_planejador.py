"""
Testes das rotas do Agente 1 (Planejador), com o llm_client mockado.

Como rodar:
    ./run_tests.sh tests/test_api_planejador.py
"""

import pytest
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
from tia.api.main import app

client = TestClient(app)

PEDIDO = {
    "aluno_id": "A2026-001",
    "perfil_id": "intermediario",
    "diagnostico": {"variaveis_tipos": 0.95, "condicionais": 0.4},
    "horas_semanais": 6,
}


@pytest.fixture(autouse=True)
def llm_falso(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm", lambda prompt, **kwargs: "1. Frase do LLM.")


def test_post_gera_salva_e_get_le():
    resposta = client.post("/planejador/trilha", json=PEDIDO)
    assert resposta.status_code == 200
    trilha = resposta.json()
    assert trilha["aluno_id"] == "A2026-001"
    assert "variaveis_tipos" not in [e["competencia_id"] for e in trilha["etapas"]]
    assert trilha["etapas"][0]["justificativa"] == "Frase do LLM."

    lida = client.get("/alunos/A2026-001/trilha")
    assert lida.status_code == 200
    assert lida.json() == trilha


def test_post_de_novo_substitui_trilha_anterior():
    client.post("/planejador/trilha", json=PEDIDO)
    client.post("/planejador/trilha", json={**PEDIDO, "diagnostico": {}})
    etapas = client.get("/alunos/A2026-001/trilha").json()["etapas"]
    assert len(etapas) == 6
    assert [e["ordem"] for e in etapas] == list(range(1, 7))


def test_get_aluno_sem_trilha_retorna_404():
    assert client.get("/alunos/NINGUEM-999/trilha").status_code == 404


def test_post_com_perfil_inexistente_retorna_422():
    resposta = client.post("/planejador/trilha", json={**PEDIDO, "perfil_id": "avancado"})
    assert resposta.status_code == 422
    assert "avancado" in resposta.json()["detail"]


def test_post_recusa_nome_no_lugar_do_codigo():
    resposta = client.post("/planejador/trilha", json={**PEDIDO, "aluno_id": "Maria Souza"})
    assert resposta.status_code == 422
