"""
Testes das regras da base pedagógica (1.2.5) na orquestração: lacuna de
aprendizagem (reforço do pré-requisito ou material-base, este uma vez por
sessão), nível inicial vindo do diagnóstico, itens do diagnóstico evitados no
questionário e conclusão sem domínio (itens acabaram: só avança com
ORQ_ACERTO_MIN_AVANCO; abaixo, reforço sem pausa ou material e sessão nova).

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
    assert "variaveis_tipos.txt" in decisao["aviso"]
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


# --- conclusão sem domínio (15/10/2026) e revisar_material uma vez por sessão ---

def responder_sequencia(aluno: str, sessao_id: str, pergunta: dict, sequencia: str) -> list[dict]:
    """Responde ("1" acerta, "0" erra) até a sequência ou a sessão acabar."""
    resultados = []
    for c in sequencia:
        resultado = responder(aluno, sessao_id, pergunta, c == "1")
        resultados.append(resultado)
        pergunta = resultado["feedback"]["proxima_pergunta"]
        if pergunta is None:
            break
    return resultados


def decisoes_de(aluno: str) -> list[tuple]:
    from tia.orquestrador import repositorio
    return [(d["regra"], d["acao"]) for d in repositorio.listar_decisoes(aluno)
            if d["acao"] not in ("planejar", "abrir_sessao")]


def test_regra_sem_dominio_e_uma_vez_por_sessao():
    com_pre = regras.regra_sem_dominio("condicionais", "s1", 0.5, "variaveis_tipos")
    assert (com_pre.regra, com_pre.dispara, com_pre.acao, com_pre.competencia_reforco) == (
        "conclusao", True, "reforcar", "variaveis_tipos")
    assert "50%" in com_pre.motivo and "60%" in com_pre.motivo
    reforcada = regras.regra_sem_dominio("condicionais", "s1", 0.5, "variaveis_tipos", sessao_ja_reforcada=True)
    assert reforcada.acao == "revisar_material"
    tudo = regras.regra_sem_dominio("condicionais", "s1", 0.0, "variaveis_tipos", sessao_ja_reforcada=True,
                                    sessao_ja_com_material=True)
    assert (tudo.dispara, tudo.acao) == (False, "nenhuma")
    assert regras.avanca_sem_dominio(0.6) and not regras.avanca_sem_dominio(0.59)
    assert not regras.avanca_sem_dominio(None)
    # lacuna repetida na mesma sessão não repete o material
    de_novo = regras.regra_lacuna("variaveis_tipos", "s1", None, sessao_ja_com_material=True)
    assert (de_novo.dispara, de_novo.acao) == (False, "nenhuma")


def test_errou_tudo_e_os_itens_acabaram_nao_avanca():
    """variaveis_tipos (sem pré-requisito, 2 itens por nível): errando as 6 questões a sessão
    termina com ressalvas, a trilha não avança e o aluno recomeça a competência."""
    aluno = "L-010"
    matricular(aluno, {})
    sessao_id, pergunta = abrir(aluno)
    resultados = responder_sequencia(aluno, sessao_id, pergunta, "0" * 20)
    final = resultados[-1]
    assert len(resultados) == 6
    assert final["feedback"]["concluida"] is True and final["feedback"]["com_ressalvas"] is True
    assert [d["acao"] for d in final["decisoes"]] == ["nenhuma"]  # material já indicado pela lacuna
    assert "acabaram sem domínio" in final["decisoes"][0]["motivo"] and "0%" in final["decisoes"][0]["motivo"]
    assert ("conclusao", "avancar") not in decisoes_de(aluno)
    assert decisoes_de(aluno) == [("lacuna", "revisar_material"), ("conclusao", "nenhuma")]  # uma vez por sessão
    proxima = client.get(f"/aluno/{aluno}/proximo").json()
    assert (proxima["acao"], proxima["competencia_id"]) == ("iniciar_sessao", "variaveis_tipos")
    progresso = client.get(f"/relatorio/aluno/{aluno}?narrativa=false").json()["progresso"]
    assert progresso["concluidas"] == 0 and progresso["com_ressalvas"] == 1
    (competencia,) = [c for c in progresso["por_competencia"] if c["competencia_id"] == "variaveis_tipos"]
    assert (competencia["concluida"], competencia["com_ressalvas"], competencia["taxa_sem_dominio"]) == (
        False, True, 0.0)
    # o docente vê a ressalva no painel
    risco = client.get("/painel/alunos-em-risco").json()["alunos"]
    (linha,) = [a for a in risco if a["aluno_id"] == aluno]
    assert "conclusao_sem_dominio" in [m["tipo"] for m in linha["motivos"]]
    # a nova sessão recomeça a competência e, acertando tudo, avança (com ressalvas: 100% >= 60%)
    nova_id, pergunta = abrir(aluno)
    assert nova_id != sessao_id
    final = responder_sequencia(aluno, nova_id, pergunta, "1" * 20)[-1]
    (decisao,) = final["decisoes"]
    assert decisao["acao"] == "avancar" and "Concluída com ressalvas" in decisao["motivo"]


def test_sem_dominio_abaixo_do_minimo_reforca_sem_pausa_e_recomeca():
    """condicionais (pré-requisito variaveis_tipos), alternando erro e acerto: 50% de acerto, sem
    duas falhas seguidas no nível 1 (sem lacuna). Reforço do pré-requisito e, depois, sessão nova."""
    aluno = "L-011"
    resposta = client.post(f"/aluno/{aluno}/iniciar", json={
        "perfil_id": "iniciante", "horas_semanais": 6, "diagnostico": {"variaveis_tipos": 1.0}})
    assert resposta.status_code == 200, resposta.text
    sessao_id, pergunta = abrir(aluno)
    assert (pergunta["competencia_id"], pergunta["nivel"]) == ("condicionais", 1)
    final = responder_sequencia(aluno, sessao_id, pergunta, "01" * 10)[-1]
    assert final["feedback"]["com_ressalvas"] is True
    (decisao,) = final["decisoes"]
    assert (decisao["regra"], decisao["acao"]) == ("conclusao", "reforcar")
    assert "50%" in decisao["motivo"] and "sessão nova" in final["avisos"][0]
    proxima = client.get(f"/aluno/{aluno}/proximo").json()
    assert (proxima["competencia_id"], proxima["reforco"]) == ("variaveis_tipos", True)
    reforco_id, pergunta = abrir(aluno)
    fim_reforco = responder_sequencia(aluno, reforco_id, pergunta, "1" * 20)[-1]
    (retomada,) = fim_reforco["decisoes"]
    assert retomada["acao"] == "retomar_original" and "sessão nova" in retomada["aviso"]
    proxima = client.get(f"/aluno/{aluno}/proximo").json()
    assert (proxima["acao"], proxima["competencia_id"], proxima["reforco"]) == (
        "iniciar_sessao", "condicionais", False)
    assert ("conclusao", "avancar") not in decisoes_de(aluno)


def test_lacuna_repetida_indica_o_material_uma_vez_por_sessao():
    """cib_01 (sem pré-requisito, 7 itens por nível, escopo piloto): duas lacunas seguidas no
    nível 1 na mesma sessão, um só aviso de material."""
    aluno = "L-012"
    resposta = client.post(f"/aluno/{aluno}/iniciar", json={
        "perfil_id": "iniciante", "horas_semanais": 6, "diagnostico": {}, "trilha": "defesa_cibernetica",
        "escopo": "piloto"})
    assert resposta.status_code == 200, resposta.text
    sessao_id, pergunta = abrir(aluno)
    assert (pergunta["competencia_id"], pergunta["nivel"]) == ("cib_01", 1)
    resultados = responder_sequencia(aluno, sessao_id, pergunta, "0000")
    assert [r["feedback"]["lacuna"] for r in resultados] == [False, True, False, True]
    assert [r["feedback"]["nivel_atual"] for r in resultados] == [1, 1, 1, 1]
    assert decisoes_de(aluno).count(("lacuna", "revisar_material")) == 1
    assert resultados[1]["avisos"] and not resultados[3]["avisos"]
