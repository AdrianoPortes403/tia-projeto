"""
Testes das regras da base pedagógica (1.2.5) na orquestração: lacuna de
aprendizagem (reforço do pré-requisito ou material-base), nível inicial vindo
do diagnóstico e itens do diagnóstico evitados no questionário.

Como rodar:
    ./run_tests.sh tests/test_regras_eap.py
"""

import pytest
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
import tia.agentes.planejador.onboarding as onboarding
import tia.agentes.tutor.feedback as feedback
from tia.agentes.planejador import diagnostico
from tia.agentes.tutor.repositorio import carregar_itens
from tia.api.main import app
from tia.orquestrador import regras

client = TestClient(app)
GABARITO = {i["id"]: i["indice_correto"] for i in carregar_itens()}
contador = iter(range(1, 10_000))


@pytest.fixture(autouse=True)
def sem_llm(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm", lambda prompt, **kwargs: "")
    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    monkeypatch.setattr(onboarding, "ONBOARDING_USA_LLM", False)


def matricular(aluno: str, diagnostico_: dict, trilha: str | None = None):
    corpo = {"horas_semanais": 6, "diagnostico": diagnostico_}
    if trilha:
        corpo["trilha"] = trilha
    resposta = client.post(f"/aluno/{aluno}/iniciar", json=corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def abrir(aluno: str) -> tuple[str, dict]:
    proxima = client.get(f"/aluno/{aluno}/proximo").json()
    sessao = client.post(f"/aluno/{aluno}/sessao", json={"competencia_id": proxima["competencia_id"]}).json()["sessao"]
    return sessao["sessao_id"], sessao["pergunta"]


def responder(aluno: str, sessao_id: str, pergunta: dict, acerta: bool) -> dict:
    correto = GABARITO[pergunta["item_id"]]
    return client.post(f"/aluno/{aluno}/evento", json={
        "evento_id": f"r-{next(contador)}", "tipo": "resposta", "sessao_id": sessao_id,
        "item_id": pergunta["item_id"], "indice_escolhido": correto if acerta else (correto + 1) % 4}).json()


# --- regra pura ---

def test_regra_lacuna():
    com_pre = regras.regra_lacuna("funcoes", "s1", "repeticao")
    assert (com_pre.dispara, com_pre.acao, com_pre.competencia_reforco) == (True, "reforcar", "repeticao")
    sem_pre = regras.regra_lacuna("variaveis_tipos", "s1", None)
    assert (sem_pre.dispara, sem_pre.acao) == (True, "revisar_material")
    ja = regras.regra_lacuna("funcoes", "s1", "repeticao", sessao_ja_reforcada=True)
    assert ja.acao == "revisar_material"
    no_reforco = regras.regra_lacuna("repeticao", "s2", "condicionais", em_reforco=True)
    assert (no_reforco.dispara, no_reforco.acao) == (False, "nenhuma")


# --- pelas rotas ---

def test_dois_erros_no_nivel_1_reforcam_o_pre_requisito():
    # base dominada até repetição; funcoes no nível 1 (nota 0) e com pré-requisito direto 'repeticao'
    matricular("L-001", {"variaveis_tipos": 1.0, "condicionais": 1.0, "repeticao": 1.0, "funcoes": 0.0})
    sessao_id, pergunta = abrir("L-001")
    assert pergunta["competencia_id"] == "funcoes" and pergunta["nivel"] == 1
    primeira = responder("L-001", sessao_id, pergunta, False)
    assert primeira["feedback"]["lacuna"] is False and primeira["decisoes"] == []
    segunda = responder("L-001", sessao_id, primeira["feedback"]["proxima_pergunta"], False)
    assert segunda["feedback"]["lacuna"] is True
    (decisao,) = segunda["decisoes"]
    assert (decisao["regra"], decisao["acao"]) == ("lacuna", "reforcar")
    proxima = client.get("/aluno/L-001/proximo").json()
    assert (proxima["competencia_id"], proxima["reforco"]) == ("repeticao", True)


def test_lacuna_sem_pre_requisito_indica_o_material_base():
    matricular("L-002", {})  # começa em variaveis_tipos, que não tem pré-requisito
    sessao_id, pergunta = abrir("L-002")
    primeira = responder("L-002", sessao_id, pergunta, False)
    segunda = responder("L-002", sessao_id, primeira["feedback"]["proxima_pergunta"], False)
    (decisao,) = segunda["decisoes"]
    assert (decisao["regra"], decisao["acao"]) == ("lacuna", "revisar_material")
    assert "provisorio_variaveis_tipos.txt" in decisao["aviso"]
    assert client.get("/aluno/L-002/proximo").json()["acao"] == "continuar_sessao"  # a sessão segue


def test_sessao_comeca_no_nivel_do_diagnostico():
    matricular("L-003", {"variaveis_tipos": 2 / 3})
    _, pergunta = abrir("L-003")
    assert (pergunta["competencia_id"], pergunta["nivel"]) == ("variaveis_tipos", 3)


def test_questionario_evita_os_itens_ja_vistos_no_diagnostico():
    aluno = "L-004"
    client.post(f"/aluno/{aluno}/onboarding/iniciar")
    for fala in ("desenvolvimento", "3 horas por semana", "pular", "sim"):
        client.post(f"/aluno/{aluno}/onboarding/mensagem", json={"texto": fala})
    situacao = client.post(f"/aluno/{aluno}/diagnostico/iniciar").json()
    while not situacao["concluido"]:  # erra tudo: cada tópico só mostra o item de nível 1
        p = situacao["pergunta"]
        situacao = client.post(f"/aluno/{aluno}/diagnostico/responder", json={
            "item_id": p["item_id"], "indice_escolhido": (GABARITO[p["item_id"]] + 1) % 4}).json()
    vistos = diagnostico.itens_respondidos(aluno)
    assert "variaveis_tipos_n1a" in vistos
    client.post(f"/aluno/{aluno}/primeiro-acesso/concluir")
    _, pergunta = abrir(aluno)
    assert pergunta["competencia_id"] == "variaveis_tipos"
    assert pergunta["item_id"] not in vistos and pergunta["item_id"] == "variaveis_tipos_n1b"
