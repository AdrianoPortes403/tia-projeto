"""
Testes das rotas do Agente 2 (Tutor), com o retrieve e o llm_client
mockados e o banco de itens PROVISÓRIO de conteudo/.

Como rodar:
    ./run_tests.sh tests/test_api_tutor.py
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

import tia.agentes.tutor.feedback as feedback
from tia.agentes.tutor.repositorio import carregar_itens
from tia.api.main import app
from tia.core.database import obter_conexao

client = TestClient(app)

ALUNO = "A2026-007"
COMPETENCIA = "repeticao"
MATERIAL = "provisorio_repeticao.txt"
ITENS = {i["id"]: i for i in carregar_itens()}


@pytest.fixture(autouse=True)
def rag_e_llm_falsos(monkeypatch):
    def buscar_falso(consulta, k=3, fontes=None):
        return [{"texto": "range(4) produz 0, 1, 2 e 3.", "fonte": MATERIAL, "distancia": 250.0}]

    monkeypatch.setattr(feedback, "buscar_contexto", buscar_falso)
    monkeypatch.setattr(feedback, "chamar_llm", lambda prompt, **kwargs: "Explicação gerada pelo LLM.")


def iniciar(aluno_id: str = ALUNO, competencia_id: str = COMPETENCIA):
    return client.post("/tutor/sessao", json={"aluno_id": aluno_id, "competencia_id": competencia_id})


def responder(sessao: dict, pergunta: dict, correta: bool, aluno_id: str = ALUNO):
    item = ITENS[pergunta["item_id"]]
    indice = item["indice_correto"] if correta else (item["indice_correto"] + 1) % 4
    return client.post("/tutor/resposta", json={
        "sessao_id": sessao["sessao_id"], "aluno_id": aluno_id,
        "item_id": pergunta["item_id"], "indice_escolhido": indice,
    })


def assert_sem_gabarito(pergunta: dict):
    assert set(pergunta) == {"item_id", "competencia_id", "nivel", "enunciado", "alternativas"}
    assert ITENS[pergunta["item_id"]]["explicacao"] not in json.dumps(pergunta, ensure_ascii=False)


def test_inicia_sessao_no_nivel_1_sem_vazar_gabarito():
    resposta = iniciar()
    assert resposta.status_code == 200
    sessao = resposta.json()
    assert sessao["nivel_atual"] == 1
    assert sessao["pergunta"]["competencia_id"] == COMPETENCIA
    assert_sem_gabarito(sessao["pergunta"])


def test_resposta_correta_sobe_nivel_cita_fonte_e_grava_historico():
    sessao = iniciar().json()
    resposta = responder(sessao, sessao["pergunta"], correta=True)
    assert resposta.status_code == 200
    fb = resposta.json()
    assert fb["acertou"] is True
    assert fb["indice_correto"] == ITENS[sessao["pergunta"]["item_id"]]["indice_correto"]
    assert fb["veredito"] == "Você acertou."
    assert fb["explicacao"] == "Explicação gerada pelo LLM." and fb["origem"] == "LLM"
    assert fb["fontes"] == [MATERIAL]
    assert fb["nivel_atual"] == 2 and fb["proxima_pergunta"]["nivel"] == 2
    assert fb["concluida"] is False and fb["tempo_ms"] >= 0
    assert_sem_gabarito(fb["proxima_pergunta"])

    conexao = obter_conexao()
    linhas = conexao.execute("SELECT * FROM historico_respostas").fetchall()
    conexao.close()
    assert len(linhas) == 1
    linha = linhas[0]
    assert (linha["aluno_id"], linha["topico"], linha["nivel"], linha["acertou"]) == (ALUNO, COMPETENCIA, 1, 1)
    assert json.loads(linha["fontes"]) == [MATERIAL] and linha["tempo_ms"] is not None


def test_resposta_incorreta_nao_passa_do_nivel_1():
    sessao = iniciar().json()
    fb = responder(sessao, sessao["pergunta"], correta=False).json()
    assert fb["acertou"] is False and fb["nivel_atual"] == 1
    assert fb["proxima_pergunta"]["item_id"] != sessao["pergunta"]["item_id"]


def test_fim_da_competencia_e_resposta_depois_do_fim():
    sessao = iniciar().json()
    pergunta, vistas = sessao["pergunta"], []
    for _ in range(4):  # caminho 1-2-3-3
        vistas.append(pergunta["item_id"])
        fb = responder(sessao, pergunta, correta=True).json()
        pergunta = fb["proxima_pergunta"]
    assert fb["concluida"] is True and fb["proxima_pergunta"] is None and fb["nivel_atual"] == 3
    assert len(set(vistas)) == 4
    assert responder(sessao, {"item_id": vistas[-1]}, correta=True).status_code == 409


def test_envio_duplicado_e_recusado_sem_gravar_de_novo():
    sessao = iniciar().json()
    assert responder(sessao, sessao["pergunta"], correta=True).status_code == 200
    assert responder(sessao, sessao["pergunta"], correta=True).status_code == 409
    conexao = obter_conexao()
    assert conexao.execute("SELECT COUNT(*) FROM historico_respostas").fetchone()[0] == 1
    conexao.close()


def test_feedback_sem_trecho_pela_api_usa_texto_do_item(monkeypatch):
    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    sessao = iniciar().json()
    fb = responder(sessao, sessao["pergunta"], correta=False).json()
    assert fb["explicacao"] == ITENS[sessao["pergunta"]["item_id"]]["explicacao"]
    assert fb["fontes"] == [] and fb["origem"] == "fallback"
    assert fb["veredito"].startswith("Você marcou: ") and "A resposta correta é: " in fb["veredito"]


def test_validacoes():
    assert iniciar(aluno_id="Maria Souza").status_code == 422  # nome no lugar do código (R08)
    resposta = iniciar(competencia_id="astrologia")
    assert resposta.status_code == 422 and "astrologia" in resposta.json()["detail"]

    sessao = iniciar().json()
    assert responder(sessao, sessao["pergunta"], correta=True, aluno_id="Maria Souza").status_code == 422
    # sessão de outro aluno: não existe para ele
    assert responder(sessao, sessao["pergunta"], correta=True, aluno_id="B2026-999").status_code == 404
    assert responder({"sessao_id": "nao-existe"}, sessao["pergunta"], correta=True).status_code == 404


def test_logs_nao_registram_aluno_id(monkeypatch, caplog):
    def llm_fora_do_ar(prompt, **kwargs):
        raise TimeoutError("demorou")

    monkeypatch.setattr(feedback, "chamar_llm", llm_fora_do_ar)
    with caplog.at_level(logging.DEBUG):
        sessao = iniciar().json()
        responder(sessao, sessao["pergunta"], correta=False)
    assert caplog.records  # o aviso de falha do LLM foi registrado...
    assert ALUNO not in caplog.text  # ...sem o código do aluno
