"""
Testes do primeiro acesso (Agente 1): diagnóstico inicial (regras puras e
persistência), onboarding conversacional (regras e LLM mockado) e o percurso
completo pelas rotas até a matrícula, inclusive LGPD (exportação e eliminação).

Como rodar:
    ./run_tests.sh tests/test_primeiro_acesso.py
"""

import pytest
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
import tia.agentes.planejador.onboarding as onboarding
import tia.api.rotas_primeiro_acesso as rotas
from tia.agentes.planejador import diagnostico
from tia.agentes.planejador.planejar import carregar_ementa
from tia.api.main import app
from tia.core import auditoria
from tia.seguranca import titular

client = TestClient(app)
ITENS = diagnostico.carregar_itens()
GABARITO = {i["id"]: i["indice_correto"] for i in ITENS}


def errado(item_id: str) -> int:
    return (GABARITO[item_id] + 1) % 4


@pytest.fixture(autouse=True)
def sem_llm(monkeypatch):
    monkeypatch.setattr(onboarding, "ONBOARDING_USA_LLM", False)
    monkeypatch.setattr(justificar, "chamar_llm", lambda prompt, **kwargs: "")


# --- diagnóstico: regras puras ---

def test_topicos_do_diagnostico_sao_base_comum_e_etapa1_com_itens():
    ementa = carregar_ementa()
    base = ["variaveis_tipos", "condicionais", "repeticao", "funcoes", "listas_strings", "recursao"]
    assert diagnostico.topicos_do_diagnostico("dev", ementa, ITENS) == base + ["dev_01", "dev_02"]
    assert diagnostico.topicos_do_diagnostico("defesa_cibernetica", ementa, ITENS) == base + ["cib_01", "cib_02"]


def test_niveis_1_2_3_param_no_primeiro_erro_e_dao_a_nota():
    estado = diagnostico.iniciar("dev", carregar_ementa(), ITENS)
    vistos = []
    # tópico 1: acerta tudo (nota 1); 2: erra o nível 1 (0); 3: acerta 1 e erra 2 (1/3); 4: acerta 1, 2 e erra 3 (2/3)
    roteiro = [True, True, True, False, True, False, True, True, False]
    for acerto in roteiro:
        vistos.append(estado.item_atual_id)
        estado = diagnostico.avancar(estado, ITENS, acerto)
    assert estado.notas == {"variaveis_tipos": 1.0, "condicionais": 0.0, "repeticao": 0.3333, "funcoes": 0.6667}
    assert all(next(i for i in ITENS if i["id"] == v)["uso"] == "diagnostico" for v in vistos)
    while not estado.concluido:
        estado = diagnostico.avancar(estado, ITENS, False)
    assert len(estado.notas) == 8 and estado.item_atual_id is None
    with pytest.raises(diagnostico.RespostaForaDeOrdem):
        diagnostico.avancar(estado, ITENS, True)


# --- onboarding: regras e LLM ---

def conversar(falas, prazo=None):
    sessao, _ = onboarding.nova_sessao("O-001")
    resposta = None
    for fala in falas:
        resposta = onboarding.processar(sessao, fala, prazo, usar_llm=False)
    return sessao, resposta


def test_onboarding_por_regras_completo_e_minimiza_o_historico():
    sessao, resposta = conversar(["não sei, qual a diferença?", "acho que segurança",
                                  "umas 2h por dia, menos no fim de semana", "estágio em segurança", "sim"], prazo=8)
    assert resposta.concluido and resposta.origem == "regras"
    assert sessao.dados == {"trilha": "defesa_cibernetica", "horas_semana": 10.0,
                            "dias_disponiveis": ["seg", "ter", "qua", "qui", "sex"],
                            "objetivo": "estágio em segurança"}
    assert sessao.historico == []  # R08: a conversa some quando o cadastro termina


def test_onboarding_aceita_correcao_e_recusa_horas_absurdas():
    sessao, resposta = conversar(["dev", "100 horas por semana"])
    assert "horas_semana" not in sessao.dados and resposta.proxima_pergunta == "horas"
    sessao, resposta = conversar(["dev", "4", "pular", "não, são 6 horas por semana"])
    assert not resposta.concluido and sessao.dados["horas_semana"] == 6
    assert onboarding.processar(sessao, "sim", usar_llm=False).concluido


def test_onboarding_com_llm_e_queda_para_regras(monkeypatch):
    monkeypatch.setattr(onboarding, "chamar_llm",
                        lambda prompt, **kw: '<think>x</think>{"trilha": "dev", "horas_semana": 7.5, "objetivo": null}')
    sessao, _ = onboarding.nova_sessao("O-002")
    resposta = onboarding.processar(sessao, "quero programar, umas 7 horas e meia", usar_llm=True)
    assert (resposta.origem, sessao.dados) == ("LLM", {"trilha": "dev", "horas_semana": 7.5})

    def fora_do_ar(prompt, **kw):
        raise ConnectionError("Ollama parado")
    monkeypatch.setattr(onboarding, "chamar_llm", fora_do_ar)
    sessao, _ = onboarding.nova_sessao("O-003")
    resposta = onboarding.processar(sessao, "defesa cibernética", usar_llm=True)
    assert (resposta.origem, sessao.dados) == ("regras", {"trilha": "defesa_cibernetica"})


# --- percurso pelas rotas ---

def percorrer(aluno: str, trilha_fala: str, acertar_base: bool) -> dict:
    assert client.post(f"/aluno/{aluno}/onboarding/iniciar").status_code == 200
    for fala in (trilha_fala, "3 horas por semana", "pular", "sim"):
        corpo = client.post(f"/aluno/{aluno}/onboarding/mensagem", json={"texto": fala}).json()
    assert corpo["concluido"]
    assert client.get(f"/aluno/{aluno}/primeiro-acesso").json()["passo"] == "diagnostico"
    situacao = client.post(f"/aluno/{aluno}/diagnostico/iniciar").json()
    while not situacao["concluido"]:
        p = situacao["pergunta"]
        base = p["competencia_id"] in ("variaveis_tipos", "condicionais", "repeticao", "funcoes",
                                       "listas_strings", "recursao")
        indice = GABARITO[p["item_id"]] if (acertar_base and base) else errado(p["item_id"])
        situacao = client.post(f"/aluno/{aluno}/diagnostico/responder",
                               json={"item_id": p["item_id"], "indice_escolhido": indice}).json()
    return situacao


def test_percurso_completo_ate_a_matricula_no_piloto(monkeypatch):
    monkeypatch.setattr(rotas, "PILOTO_PRAZO_DIAS", 8)
    monkeypatch.setattr(rotas, "PILOTO_ESCOPO", "piloto")
    final = percorrer("P-001", "desenvolvimento", acertar_base=True)
    assert final["notas"]["funcoes"] == 1.0 and final["notas"]["dev_01"] == 0.0
    assert client.get("/aluno/P-001/primeiro-acesso").json()["passo"] == "concluir"
    resultado = client.post("/aluno/P-001/primeiro-acesso/concluir")
    assert resultado.status_code == 200, resultado.text
    trilha = resultado.json()["trilha"]
    # base dominada (6 x 3) e etapa 1 no nível 1 (2 x 0): P = 2,25 -> intermediário
    assert (trilha["perfil_id"], trilha["pontuacao_enquadramento"], trilha["trilha"]) == ("intermediario", 2.25, "dev")
    assert [e["competencia_id"] for e in trilha["etapas"]] == ["dev_01", "dev_02"]
    assert trilha["prazo_dias"] == 8 and trilha["cabe_no_prazo"] is True
    # depois da matrícula, o primeiro acesso está fechado
    assert client.get("/aluno/P-001/primeiro-acesso").json()["passo"] == "matriculado"
    assert client.post("/aluno/P-001/diagnostico/iniciar").status_code == 409
    assert client.post("/aluno/P-001/onboarding/iniciar").status_code == 409
    # auditoria (R11): cadastro e cada resposta do diagnóstico, sem o texto do aluno
    tipos = [r["tipo"] for r in auditoria.listar("P-001")]
    assert "onboarding" in tipos and tipos.count("diagnostico") >= 8
    assert not any("pular" in (r.get("motivo") or "") for r in auditoria.listar("P-001"))


def test_iniciante_completo_vai_pela_base_comum():
    percorrer("P-002", "segurança", acertar_base=False)
    trilha = client.post("/aluno/P-002/primeiro-acesso/concluir").json()["trilha"]
    assert (trilha["perfil_id"], trilha["pontuacao_enquadramento"]) == ("iniciante", 0.0)
    assert trilha["etapas"][0]["competencia_id"] == "variaveis_tipos"
    assert trilha["etapas"][0]["nivel_inicial"] == 1


def test_ordem_e_pre_condicoes_das_rotas():
    assert client.post("/aluno/P-003/onboarding/mensagem", json={"texto": "dev"}).status_code == 404
    client.post("/aluno/P-003/onboarding/iniciar")
    assert client.post("/aluno/P-003/diagnostico/iniciar").status_code == 409  # cadastro não concluído
    assert client.post("/aluno/P-003/primeiro-acesso/concluir").status_code == 409
    for fala in ("dev", "3", "pular", "sim"):
        client.post("/aluno/P-003/onboarding/mensagem", json={"texto": fala})
    situacao = client.post("/aluno/P-003/diagnostico/iniciar").json()
    fora = client.post("/aluno/P-003/diagnostico/responder", json={"item_id": "dev_01_n1_001", "indice_escolhido": 0})
    assert fora.status_code == 409  # não é a questão atual
    assert situacao["pergunta"]["competencia_id"] == "variaveis_tipos" and "indice_correto" not in situacao["pergunta"]
    assert client.post("/aluno/P-003/primeiro-acesso/concluir").status_code == 409  # diagnóstico em andamento


def test_lgpd_exporta_e_elimina_cadastro_e_diagnostico():
    percorrer("P-004", "dev", acertar_base=True)
    dados = titular.exportar("P-004")
    assert dados["onboarding"] and dados["diagnostico_inicial"]
    titular.eliminar("P-004", "P-004")
    assert onboarding.ler("P-004") is None and diagnostico.ler("P-004") is None
