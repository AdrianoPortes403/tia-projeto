"""
Testes ponta a ponta da Orquestração (EAP 1.3.5), pela API, com o LLM
mockado (Planejador, Tutor e Relatório) e banco temporário (conftest):
fluxo completo, replanejamento por conclusão, queda e inatividade,
idempotência, aluno inexistente, auditoria de cada decisão e as regras
puras.

Como rodar:
    ./run_tests.sh tests/test_orquestrador.py
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
import tia.agentes.relatorio.narrativa as narrativa
import tia.agentes.tutor.feedback as feedback
from tia.agentes.relatorio.modelos import Engajamento, Taxa, Tendencia
from tia.agentes.tutor.repositorio import carregar_itens
from tia.api.main import app
from tia.core.database import obter_conexao
from tia.orquestrador import regras
from tia.orquestrador.__main__ import recuar_horarios
from tia.orquestrador.modelos import EstadoAluno

client = TestClient(app)
GABARITO = {i["id"]: i["indice_correto"] for i in carregar_itens()}
ALUNO = "A2026-030"
# perfil intermediário dispensa variáveis, condicionais e repetição: trilha funcoes -> listas_strings -> recursao
DIAGNOSTICO_QUEDA = {"variaveis_tipos": 0.9, "condicionais": 0.8, "repeticao": 0.9,
                     "funcoes": 0.2, "listas_strings": 0.2, "recursao": 0.0}
# só recursao fica na trilha (as outras são dispensáveis com nota alta)
DIAGNOSTICO_CURTO = {"variaveis_tipos": 1, "condicionais": 1, "repeticao": 1, "funcoes": 1, "listas_strings": 1}


@pytest.fixture(autouse=True)
def llm_mockado(monkeypatch):
    """Planejador e Relatório com LLM falso; Tutor sem trecho do RAG (texto do item)."""
    chamadas = {"planejador": 0}

    def planejador_falso(prompt, **kwargs):
        chamadas["planejador"] += 1
        return "1. Etapa justificada."

    monkeypatch.setattr(justificar, "chamar_llm", planejador_falso)
    monkeypatch.setattr(narrativa, "chamar_llm", lambda prompt, **kwargs: "Você está indo bem.")
    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    return chamadas


contador = iter(range(1, 10_000))


def iniciar(aluno_id: str = ALUNO, diagnostico: dict | None = None, perfil_id: str = "intermediario"):
    return client.post(f"/aluno/{aluno_id}/iniciar", json={
        "perfil_id": perfil_id, "horas_semanais": 6,
        "diagnostico": DIAGNOSTICO_QUEDA if diagnostico is None else diagnostico})


def evento(corpo: dict, aluno_id: str = ALUNO):
    corpo = {"evento_id": f"e-{next(contador)}", **corpo}
    return client.post(f"/aluno/{aluno_id}/evento", json=corpo)


def proximo(aluno_id: str = ALUNO) -> dict:
    return client.get(f"/aluno/{aluno_id}/proximo").json()


def estado(aluno_id: str = ALUNO) -> dict:
    return client.get(f"/aluno/{aluno_id}/estado").json()


def abrir_sessao(aluno_id: str = ALUNO) -> tuple[str, dict]:
    p = proximo(aluno_id)
    assert p["acao"] == "iniciar_sessao", p
    sessao = client.post("/tutor/sessao", json={"aluno_id": aluno_id, "competencia_id": p["competencia_id"]}).json()
    return sessao["sessao_id"], sessao["pergunta"]


def responder(sessao_id: str, pergunta: dict, acerta: bool, aluno_id: str = ALUNO, evento_id: str | None = None):
    correto = GABARITO[pergunta["item_id"]]
    corpo = {"tipo": "resposta", "sessao_id": sessao_id, "item_id": pergunta["item_id"],
             "indice_escolhido": correto if acerta else (correto + 1) % 4}
    if evento_id:
        corpo["evento_id"] = evento_id
    return evento(corpo, aluno_id)


def estudar(sequencia: str, aluno_id: str = ALUNO) -> list[dict]:
    """Abre a sessão da competência atual e responde ("1" acerta, "0" erra)."""
    sessao_id, pergunta = abrir_sessao(aluno_id)
    resultados = []
    for c in sequencia:
        resultado = responder(sessao_id, pergunta, c == "1", aluno_id).json()
        resultados.append(resultado)
        pergunta = resultado["feedback"]["proxima_pergunta"]
        if pergunta is None:
            break
    return resultados


def decisoes(aluno_id: str = ALUNO) -> list:
    conexao = obter_conexao()
    linhas = conexao.execute("SELECT * FROM orquestrador_decisoes WHERE aluno_id = ? ORDER BY id",
                             (aluno_id,)).fetchall()
    conexao.close()
    return linhas


def etapas(aluno_id: str = ALUNO) -> list[str]:
    return [e["competencia_id"] for e in estado(aluno_id)["etapas"]]


# --- fluxo completo ---

def test_fluxo_completo_da_matricula_ao_relatorio(llm_mockado):
    resposta = iniciar(diagnostico=DIAGNOSTICO_CURTO)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["competencia_id"] for e in corpo["trilha"]["etapas"]] == ["recursao"]
    assert corpo["decisao"]["regra"] == "matricula" and corpo["decisao"]["acao"] == "planejar"
    assert corpo["proxima"] == {"acao": "iniciar_sessao", "competencia_id": "recursao", "sessao_id": None,
                                "motivo": corpo["proxima"]["motivo"]}
    assert llm_mockado["planejador"] == 1  # o Planejador (com LLM) gerou a trilha

    resultados = estudar("1111")
    assert resultados[-1]["feedback"]["concluida"] is True
    (decisao,) = resultados[-1]["decisoes"]
    assert (decisao["regra"], decisao["acao"], decisao["competencia_id"], decisao["replanejou"]) == (
        "conclusao", "avancar", "recursao", True)
    assert resultados[-1]["proxima"]["acao"] == "concluido"
    assert all(r["decisoes"] == [] for r in resultados[:-1])  # respostas comuns não geram decisão
    assert llm_mockado["planejador"] == 2  # replanejamento pelo Planejador

    final = estado()
    assert final["concluido"] is True and final["competencia_atual"] is None and final["replanejamentos"] == 1
    relatorio = client.get(f"/relatorio/aluno/{ALUNO}").json()
    assert relatorio["progresso"]["percentual"] == 1.0


def test_sessao_aberta_vira_continuar_sessao():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    sessao_id, pergunta = abrir_sessao()
    responder(sessao_id, pergunta, True)
    p = proximo()
    assert (p["acao"], p["competencia_id"], p["sessao_id"]) == ("continuar_sessao", "recursao", sessao_id)


# --- replanejamento por conclusão ---

def test_evento_conclusao_confere_no_banco_e_nao_repete():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    nao_concluida = evento({"tipo": "conclusao", "competencia_id": "recursao"}).json()
    assert [(d["regra"], d["acao"], d["replanejou"]) for d in nao_concluida["decisoes"]] == [
        ("conclusao", "nenhuma", False)]
    estudar("1111")  # conclui e replaneja (avancar)
    de_novo = evento({"tipo": "conclusao", "competencia_id": "recursao"}).json()
    assert [(d["acao"], d["replanejou"]) for d in de_novo["decisoes"]] == [("nenhuma", False)]
    assert "já foi tratada" in de_novo["decisoes"][0]["motivo"]
    assert sum(d["acao"] == "avancar" for d in decisoes()) == 1


# --- replanejamento por queda ---

def test_queda_reforca_e_traz_de_volta_o_prerequisito_dispensado():
    iniciar()
    assert etapas() == ["funcoes", "listas_strings", "recursao"]
    estudar("1111")  # conclui funcoes
    resultados = estudar("000")  # 3 erros em listas_strings
    (decisao,) = resultados[-1]["decisoes"]
    assert (decisao["regra"], decisao["acao"], decisao["competencia_id"]) == ("queda", "reforcar", "listas_strings")
    assert "repeticao, funcoes, listas_strings, recursao" in decisao["motivo"]
    atual = estado()
    assert etapas() == ["repeticao", "funcoes", "listas_strings", "recursao"]
    assert atual["competencia_atual"] == "repeticao"  # o pré-requisito vem antes
    assert atual["diagnostico"]["repeticao"] == 0.0 and atual["diagnostico"]["listas_strings"] == 0.0
    assert resultados[-1]["proxima"]["acao"] == "iniciar_sessao"


def test_queda_replaneja_uma_vez_por_sessao():
    iniciar()
    estudar("1111")
    sessao_id, pergunta = abrir_sessao()
    for _ in range(5):  # erra 5 vezes na mesma sessão
        resultado = responder(sessao_id, pergunta, False).json()
        pergunta = resultado["feedback"]["proxima_pergunta"]
    assert sum(d["acao"] == "reforcar" for d in decisoes()) == 1


def test_queda_nao_dispara_sem_tendencia():
    iniciar()
    resultados = estudar("000")  # só uma sessão: sem "anteriores" para comparar
    assert all(r["decisoes"] == [] for r in resultados)


# --- replanejamento por inatividade ---

def test_inatividade_replaneja_uma_vez_por_periodo():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    sessao_id, pergunta = abrir_sessao()
    responder(sessao_id, pergunta, True)
    ativo = evento({"tipo": "inatividade"}).json()
    assert [(d["regra"], d["acao"], d["replanejou"]) for d in ativo["decisoes"]] == [("inatividade", "nenhuma", False)]

    recuar_horarios(5)  # 5 dias sem atividade (limite 3)
    p = proximo()
    assert p["acao"] == "replanejar" and "Inatividade" in p["motivo"]
    inativo = evento({"tipo": "inatividade"}).json()
    assert [(d["acao"], d["replanejou"]) for d in inativo["decisoes"]] == [("retomar", True)]
    assert inativo["proxima"]["acao"] == "continuar_sessao"  # tratada: volta ao estudo
    de_novo = evento({"tipo": "inatividade"}).json()
    assert [(d["acao"], d["replanejou"]) for d in de_novo["decisoes"]] == [("nenhuma", False)]
    assert estado()["inativo"] is True and estado()["replanejamento_pendente"] is None


# --- idempotência ---

def test_evento_repetido_nao_processa_de_novo():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    sessao_id, pergunta = abrir_sessao()
    primeiro = responder(sessao_id, pergunta, True, evento_id="dup-1")
    segundo = responder(sessao_id, pergunta, True, evento_id="dup-1")
    assert primeiro.status_code == segundo.status_code == 200
    assert (primeiro.json()["repetido"], segundo.json()["repetido"]) == (False, True)
    assert segundo.json()["feedback"] == primeiro.json()["feedback"]
    conexao = obter_conexao()
    assert conexao.execute("SELECT COUNT(*) FROM historico_respostas").fetchone()[0] == 1
    conexao.close()
    # o mesmo id com outro tipo é conflito
    assert evento({"evento_id": "dup-1", "tipo": "inatividade"}).status_code == 409


def test_evento_que_falha_pode_ser_reenviado():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    sessao_id, pergunta = abrir_sessao()
    errado = evento({"evento_id": "re-1", "tipo": "resposta", "sessao_id": sessao_id,
                     "item_id": "outro_item", "indice_escolhido": 0})
    assert errado.status_code == 409  # resposta fora de ordem no Tutor
    assert responder(sessao_id, pergunta, True, evento_id="re-1").json()["repetido"] is False


# --- aluno inexistente e validações ---

def test_aluno_inexistente_e_validacoes():
    for resposta in (client.get("/aluno/B2026-404/estado"), client.get("/aluno/B2026-404/proximo"),
                     evento({"tipo": "inatividade"}, aluno_id="B2026-404")):
        assert resposta.status_code == 404 and "não está matriculado" in resposta.json()["detail"]
    assert client.get("/aluno/Maria Souza/estado").status_code == 422  # nome no lugar do código (R08)
    assert iniciar(perfil_id="astronauta").status_code == 422
    assert client.get(f"/aluno/{ALUNO}/estado").status_code == 404  # perfil inválido não matricula
    assert iniciar().status_code == 200 and iniciar().status_code == 409
    assert evento({"tipo": "resposta", "sessao_id": "x"}).status_code == 422  # faltam item e índice
    assert evento({"tipo": "conclusao"}).status_code == 422
    assert evento({"tipo": "resposta", "sessao_id": "nao-existe", "item_id": "i",
                   "indice_escolhido": 0}).status_code == 404


# --- auditoria de cada decisão e veto docente ---

def test_cada_decisao_vai_para_a_auditoria_com_motivo():
    iniciar()
    estudar("1111")
    estudar("000")
    evento({"tipo": "inatividade"})
    registros = [r for r in client.get(f"/auditoria/{ALUNO}").json() if r["tipo"] == "decisao_orquestrador"]
    tomadas = decisoes()
    assert [r["referencia_id"] for r in registros] == [str(d["id"]) for d in tomadas]
    assert [r["origem"] for r in registros] == ["planejar", "avancar", "reforcar", "nenhuma"]
    assert all(r["motivo"].startswith(f"[{d['regra']}] ") for r, d in zip(registros, tomadas))
    assert "Desempenho em queda" in registros[2]["motivo"]


def test_veto_docente_acessivel_pelo_fluxo(monkeypatch):
    import tia.agentes.tutor.dialogo as dialogo
    monkeypatch.setattr(dialogo, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    dialogo_id = client.post("/tutor/perguntar", json={"aluno_id": ALUNO, "pergunta": "O que é caso base?"}
                             ).json()["dialogo_id"]
    atual = estado()
    assert atual["dialogos"] == 1 and atual["dialogos_vetados"] == 0
    rota_veto = atual["rotas"]["veto_docente"].replace("{dialogo_id}", str(dialogo_id))
    assert client.patch(rota_veto, json={"vetada": True, "correcao_docente": "Correção."}).status_code == 200
    assert estado()["dialogos_vetados"] == 1
    assert client.get(estado()["rotas"]["historico_dialogo"]).json()[0]["resposta"] == "Correção."


# --- regras (puras) ---

def tendencia(direcao: str, recentes: float = 0.2, anteriores: float = 0.9) -> Tendencia:
    return Tendencia(base="sessao", recentes=Taxa(chave="r", respostas=3, acertos=0, taxa=recentes),
                     anteriores=Taxa(chave="a", respostas=4, acertos=4, taxa=anteriores), variacao=-0.7,
                     direcao=direcao)


@pytest.mark.parametrize("direcao, desde, ja_reforcada, dispara", [
    ("caindo", None, False, True),     # primeira queda
    ("caindo", 5, False, True),        # 5 respostas desde o último reforço (mínimo 5)
    ("caindo", 4, False, False),       # cedo demais
    ("caindo", None, True, False),     # esta sessão já foi tratada
    ("estavel", None, False, False),
    ("insuficiente", None, False, False),
])
def test_regra_queda(direcao, desde, ja_reforcada, dispara):
    avaliacao = regras.regra_queda(tendencia(direcao), "a", desde, "S1", ja_reforcada)
    assert (avaliacao.dispara, avaliacao.acao) == (dispara, "reforcar" if dispara else "nenhuma")
    assert avaliacao.sessao_id == "S1"


def engajamento(inativo: bool, ultima: str | None = "2026-10-01T10:00:00", dias: int | None = 9) -> Engajamento:
    return Engajamento(sessoes=1, sessoes_concluidas=0, respostas=1, perguntas_dialogo=0, dias_ativos=1,
                       ultima_interacao=ultima, dias_inativo=dias, inativo=inativo)


@pytest.mark.parametrize("eng, ultimo_retomar, dispara", [
    (engajamento(False, dias=1), None, False),
    (engajamento(True), None, True),
    (engajamento(True), "2026-10-05T00:00:00", False),     # já tratada depois da última atividade
    (engajamento(True), "2026-09-20T00:00:00", True),      # tratada antes; o aluno voltou e sumiu de novo
    (engajamento(True, ultima=None, dias=None), None, True),
    (engajamento(True, ultima=None, dias=None), "2026-09-20T00:00:00", False),
])
def test_regra_inatividade(eng, ultimo_retomar, dispara):
    assert regras.regra_inatividade(eng, ultimo_retomar).dispara is dispara


def test_regra_conclusao():
    assert regras.regra_conclusao("a", {"a"}, ja_avancou=False).acao == "avancar"
    assert regras.regra_conclusao("a", {"a"}, ja_avancou=True).dispara is False
    assert regras.regra_conclusao("a", set(), ja_avancou=False).dispara is False


def test_novo_diagnostico():
    base = {"a": 0.9, "pre1": 0.9, "pre2": 0.9}
    reforco = regras.novo_diagnostico("reforcar", base, "a", 0.25, ["pre1", "pre2"], concluidas={"pre2"})
    assert reforco == {"a": 0.25, "pre1": 0.0, "pre2": 0.9}  # pré-requisito concluído não muda
    assert base == {"a": 0.9, "pre1": 0.9, "pre2": 0.9}      # não altera o recebido
    assert regras.novo_diagnostico("avancar", base, "a", 1.0, ["pre1"], set()) == base
    assert regras.novo_diagnostico("retomar", base, None, None, [], set()) == base


def estado_puro(**campos) -> EstadoAluno:
    padrao = dict(aluno_id="X", perfil_id="p", horas_semanais=6, diagnostico={}, etapas=[], competencia_atual="a",
                  sessao_aberta_id=None, concluido=False, tendencia="estavel", inativo=False, dias_inativo=0,
                  replanejamento_pendente=None, replanejamentos=0, dialogos=0, dialogos_vetados=0)
    return EstadoAluno(**{**padrao, **campos})


def test_proxima_acao_por_prioridade():
    assert regras.proxima_acao(estado_puro(replanejamento_pendente="inativo", concluido=True)).acao == "replanejar"
    assert regras.proxima_acao(estado_puro(concluido=True, competencia_atual=None)).acao == "concluido"
    assert regras.proxima_acao(estado_puro(sessao_aberta_id="S1")).acao == "continuar_sessao"
    assert regras.proxima_acao(estado_puro()).acao == "iniciar_sessao"


def test_estado_com_relogio_injetado():
    from tia.orquestrador import estado as estado_fluxo
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    futuro = estado_fluxo(ALUNO, agora=datetime.now().replace(year=datetime.now().year + 1))
    assert futuro.inativo is True and futuro.replanejamento_pendente is not None


# --- origem das justificativas e do feedback, com aviso de timeout ---

def test_decisao_mostra_origem_e_tempo_do_planejador():
    corpo = iniciar(diagnostico=DIAGNOSTICO_CURTO).json()  # 1 etapa; o LLM falso dá a frase "1."
    assert corpo["trilha"]["etapas"][0]["origem_justificativa"] == "LLM" and corpo["trilha"]["falha_llm"] is None
    decisao = corpo["decisao"]
    assert (decisao["origem_justificativas"], decisao["falha_llm"]) == ("LLM", None)
    assert decisao["tempo_planejador_ms"] >= 0


def test_timeout_do_llm_aparece_na_decisao_e_no_feedback(monkeypatch):
    import requests

    def estoura(prompt, **kwargs):
        raise requests.ReadTimeout("demorou")

    monkeypatch.setattr(justificar, "chamar_llm", estoura)
    # trecho do material da competência (recursao -> exemplo_recursao.txt): o feedback chama o LLM
    monkeypatch.setattr(feedback, "buscar_contexto",
                        lambda consulta, k=3, fontes=None: [{"texto": "t", "fonte": "exemplo_recursao.txt",
                                                             "distancia": 1.0}])
    monkeypatch.setattr(feedback, "chamar_llm", estoura)
    corpo = iniciar(diagnostico=DIAGNOSTICO_CURTO).json()
    assert (corpo["decisao"]["origem_justificativas"], corpo["decisao"]["falha_llm"]) == ("fallback", "timeout")
    assert corpo["trilha"]["etapas"][0]["origem_justificativa"] == "fallback"

    sessao_id, pergunta = abrir_sessao()
    fb = responder(sessao_id, pergunta, True).json()["feedback"]
    assert (fb["origem"], fb["falha_llm"]) == ("fallback", "timeout")
    tomadas = decisoes()
    assert (tomadas[0]["origem_justificativas"], tomadas[0]["falha_llm"]) == ("fallback", "timeout")
