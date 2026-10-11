"""
Testes ponta a ponta da Orquestração (EAP 1.3.5), pela API, com o LLM
mockado (Planejador, Tutor e Relatório) e banco temporário (conftest):
fluxo completo, replanejamento incremental (R1), ciclo de queda com pausa,
reforço e retomada (R2), inatividade com datas simuladas dos dois lados do
limiar (R3), abertura de sessão controlada, idempotência, aluno inexistente,
auditoria de cada decisão e as regras puras.

Como rodar:
    ./run_tests.sh tests/test_orquestrador.py
"""

from datetime import datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
import tia.agentes.relatorio.narrativa as narrativa
import tia.agentes.tutor.feedback as feedback
from tia.agentes.relatorio.modelos import Engajamento, Taxa, Tendencia
from tia.agentes.tutor.repositorio import carregar_itens, ler_sessao
from tia.api.main import app
from tia.core.database import obter_conexao
from tia.orquestrador import regras, verificar_inatividade
from tia.orquestrador.modelos import EstadoAluno, Reforco

client = TestClient(app)
GABARITO = {i["id"]: i["indice_correto"] for i in carregar_itens()}
ALUNO = "A2026-030"
# perfil intermediário dispensa variáveis, condicionais e repetição: trilha funcoes -> listas_strings -> recursao
DIAGNOSTICO = {"variaveis_tipos": 0.9, "condicionais": 0.8, "repeticao": 0.9,
               "funcoes": 0.2, "listas_strings": 0.2, "recursao": 0.0}
# só recursao fica na trilha (as outras são dispensáveis com nota alta)
DIAGNOSTICO_CURTO = {"variaveis_tipos": 1, "condicionais": 1, "repeticao": 1, "funcoes": 1, "listas_strings": 1}


@pytest.fixture(autouse=True)
def llm_mockado(monkeypatch):
    """Planejador e Relatório com LLM falso; Tutor sem trecho do RAG (texto do item)."""
    chamadas = {"planejador": 0}

    def planejador_falso(prompt, **kwargs):
        chamadas["planejador"] += 1
        return "\n".join(f"{n}. Etapa justificada." for n in range(1, 7))

    monkeypatch.setattr(justificar, "chamar_llm", planejador_falso)
    monkeypatch.setattr(narrativa, "chamar_llm", lambda prompt, **kwargs: "Você está indo bem.")
    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    return chamadas


contador = iter(range(1, 10_000))


def iniciar(aluno_id: str = ALUNO, diagnostico: dict | None = None, perfil_id: str = "intermediario"):
    return client.post(f"/aluno/{aluno_id}/iniciar", json={
        "perfil_id": perfil_id, "horas_semanais": 6,
        "diagnostico": DIAGNOSTICO if diagnostico is None else diagnostico})


def evento(corpo: dict, aluno_id: str = ALUNO):
    corpo = {"evento_id": f"e-{next(contador)}", **corpo}
    return client.post(f"/aluno/{aluno_id}/evento", json=corpo)


def proximo(aluno_id: str = ALUNO) -> dict:
    return client.get(f"/aluno/{aluno_id}/proximo").json()


def estado(aluno_id: str = ALUNO) -> dict:
    return client.get(f"/aluno/{aluno_id}/estado").json()


def pedir_sessao(competencia_id: str, aluno_id: str = ALUNO):
    return client.post(f"/aluno/{aluno_id}/sessao", json={"competencia_id": competencia_id})


def abrir_sessao(aluno_id: str = ALUNO) -> tuple[str, dict]:
    """Abre, pelo orquestrador, a sessão que o "proximo" indica."""
    p = proximo(aluno_id)
    assert p["acao"] == "iniciar_sessao", p
    resposta = pedir_sessao(p["competencia_id"], aluno_id)
    assert resposta.status_code == 200, resposta.json()
    sessao = resposta.json()["sessao"]
    return sessao["sessao_id"], sessao["pergunta"]


def responder(sessao_id: str, pergunta: dict, acerta: bool, aluno_id: str = ALUNO, evento_id: str | None = None):
    correto = GABARITO[pergunta["item_id"]]
    corpo = {"tipo": "resposta", "sessao_id": sessao_id, "item_id": pergunta["item_id"],
             "indice_escolhido": correto if acerta else (correto + 1) % 4}
    if evento_id:
        corpo["evento_id"] = evento_id
    return evento(corpo, aluno_id)


def responder_varias(sessao_id: str, pergunta: dict, sequencia: str, aluno_id: str = ALUNO) -> list[dict]:
    resultados = []
    for c in sequencia:
        resultado = responder(sessao_id, pergunta, c == "1", aluno_id).json()
        resultados.append(resultado)
        pergunta = resultado["feedback"]["proxima_pergunta"]
        if pergunta is None:
            break
    return resultados


def estudar(sequencia: str, aluno_id: str = ALUNO) -> list[dict]:
    """Abre a sessão indicada e responde ("1" acerta, "0" erra)."""
    sessao_id, pergunta = abrir_sessao(aluno_id)
    return responder_varias(sessao_id, pergunta, sequencia, aluno_id)


def decisoes(aluno_id: str = ALUNO) -> list:
    conexao = obter_conexao()
    linhas = conexao.execute("SELECT * FROM orquestrador_decisoes WHERE aluno_id = ? ORDER BY id",
                             (aluno_id,)).fetchall()
    conexao.close()
    return linhas


def a_fazer(aluno_id: str = ALUNO) -> list[str]:
    return [e["competencia_id"] for e in client.get(f"/alunos/{aluno_id}/trilha").json()["etapas"]
            if not e["concluida"]]


def recuar_atividade(dias: float, aluno_id: str = ALUNO):
    """Simula dias sem atividade recuando os horários das ações do aluno."""
    conexao = obter_conexao()
    with conexao:
        for coluna, tabela in [("timestamp", "historico_respostas"), ("criado_em", "tutor_sessoes"),
                               ("atualizado_em", "tutor_sessoes"), ("ts", "tutor_dialogo"),
                               ("criado_em", "trilha_estudo"), ("ts", "orquestrador_decisoes")]:
            conexao.execute(f"UPDATE {tabela} SET {coluna} = strftime('%Y-%m-%dT%H:%M:%S', {coluna}, ?) "
                            f"WHERE aluno_id = ? AND {coluna} IS NOT NULL", (f"-{dias} days", aluno_id))
    conexao.close()


# --- fluxo completo ---

def test_fluxo_completo_da_matricula_ao_relatorio(llm_mockado):
    resposta = iniciar(diagnostico=DIAGNOSTICO_CURTO)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["competencia_id"] for e in corpo["trilha"]["etapas"]] == ["recursao"]
    assert (corpo["decisao"]["regra"], corpo["decisao"]["acao"]) == ("matricula", "planejar")
    assert (corpo["proxima"]["acao"], corpo["proxima"]["competencia_id"]) == ("iniciar_sessao", "recursao")
    assert llm_mockado["planejador"] == 1

    resultados = estudar("1111")
    final = resultados[-1]
    assert final["feedback"]["concluida"] is True
    (decisao,) = final["decisoes"]
    assert (decisao["regra"], decisao["acao"], decisao["replanejou"]) == ("conclusao", "avancar", True)
    assert final["avisos"] == ["Parabéns! Você concluiu \"Recursão\". Você concluiu todas as etapas da sua trilha."]
    assert final["proxima"]["acao"] == "concluido"
    assert all(r["decisoes"] == [] for r in resultados[:-1])
    assert estado()["concluido"] is True
    assert client.get(f"/relatorio/aluno/{ALUNO}").json()["progresso"]["percentual"] == 1.0


# --- R1: avança e replaneja só o que falta ---

def test_conclusao_avanca_replaneja_so_o_que_falta_e_avisa():
    iniciar()
    assert a_fazer() == ["funcoes", "listas_strings", "recursao"]
    final = estudar("1111")[-1]
    (decisao,) = final["decisoes"]
    assert (decisao["acao"], decisao["competencia_id"]) == ("avancar", "funcoes")
    assert "funcoes, listas_strings, recursao -> listas_strings, recursao" in decisao["motivo"]
    assert final["avisos"] == ["Parabéns! Você concluiu \"Funções e modularização\". "
                               "Próxima etapa: \"Listas e strings\"."]
    assert a_fazer() == ["listas_strings", "recursao"]  # trilha reduzida
    etapas = {e["competencia_id"]: e for e in client.get(f"/alunos/{ALUNO}/trilha").json()["etapas"]}
    assert etapas["funcoes"]["concluida"] is True and etapas["funcoes"]["semana_inicio"] == 0
    assert etapas["listas_strings"]["semana_inicio"] == 1  # o que falta começa na semana 1
    assert (final["proxima"]["acao"], final["proxima"]["competencia_id"]) == ("iniciar_sessao", "listas_strings")


def test_replanejamento_nunca_traz_de_volta_uma_concluida():
    iniciar()
    estudar("1111")  # conclui funcoes
    # inatividade longa refaz a trilha: funcoes continua concluída
    verificar_inatividade(agora=datetime.now() + timedelta(days=20))
    assert "funcoes" not in a_fazer()
    assert [d["acao"] for d in decisoes()][-1] == "refazer_trilha"


def test_evento_conclusao_confere_no_banco_e_nao_repete():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    nao_concluida = evento({"tipo": "conclusao", "competencia_id": "recursao"}).json()
    assert [(d["regra"], d["acao"], d["replanejou"]) for d in nao_concluida["decisoes"]] == [
        ("conclusao", "nenhuma", False)]
    estudar("1111")
    de_novo = evento({"tipo": "conclusao", "competencia_id": "recursao"}).json()
    assert [(d["acao"], d["replanejou"]) for d in de_novo["decisoes"]] == [("nenhuma", False)]
    assert sum(d["acao"] == "avancar" for d in decisoes()) == 1


# --- abertura de sessão pelo orquestrador ---

def auditoria_de(acao: str) -> list[dict]:
    return [r for r in client.get(f"/auditoria/{ALUNO}").json()
            if r["tipo"] == "decisao_orquestrador" and r["origem"] == acao]


def test_sessao_so_para_a_competencia_atual():
    iniciar()
    recusada = pedir_sessao("recursao")
    assert recusada.status_code == 409
    assert "só é possível estudar 'funcoes'" in recusada.json()["detail"]
    (registro,) = auditoria_de("recusar_sessao")
    assert "recursao" in registro["motivo"]

    aceita = pedir_sessao("funcoes")
    assert aceita.status_code == 200 and aceita.json()["reforco"] is False
    assert aceita.json()["sessao"]["nivel_atual"] == 1
    assert len(auditoria_de("abrir_sessao")) == 1

    repetida = pedir_sessao("funcoes")  # já há sessão aberta
    assert repetida.status_code == 409 and "continue-a" in repetida.json()["detail"]
    assert proximo()["acao"] == "continuar_sessao"


def test_sessao_recusada_quando_a_trilha_esta_concluida():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    estudar("1111")
    resposta = pedir_sessao("recursao")
    assert resposta.status_code == 409 and "Trilha concluída" in resposta.json()["detail"]


def test_tutor_sessao_continua_standalone():
    iniciar()
    # /tutor/sessao não passa pelo orquestrador: abre qualquer competência
    assert client.post("/tutor/sessao", json={"aluno_id": ALUNO, "competencia_id": "recursao"}).status_code == 200


# --- R2: queda -> pausa, reforço do pré-requisito direto, retomada sem zerar ---

def pausada(sessao_id: str) -> bool:
    conexao = obter_conexao()
    valor = conexao.execute("SELECT pausada FROM tutor_sessoes WHERE id = ?", (sessao_id,)).fetchone()["pausada"]
    conexao.close()
    return bool(valor)


def test_ciclo_completo_queda_pausa_reforco_e_retomada():
    iniciar()
    estudar("1111")  # conclui funcoes (100%)
    sessao_listas, pergunta = abrir_sessao()
    resultados = responder_varias(sessao_listas, pergunta, "000")  # queda em listas_strings
    (decisao,) = resultados[-1]["decisoes"]
    assert (decisao["regra"], decisao["acao"], decisao["competencia_id"], decisao["sessao_id"]) == (
        "queda", "reforcar", "listas_strings", sessao_listas)
    assert "pré-requisito direto 'repeticao'" in decisao["motivo"]
    assert "Vamos revisar \"Laços de repetição\"" in resultados[-1]["avisos"][0]

    # pausa: a sessão guarda nível e item, e não aceita resposta
    antes = ler_sessao(sessao_listas, ALUNO)
    assert pausada(sessao_listas)
    pergunta_pausada = resultados[-1]["feedback"]["proxima_pergunta"]
    assert responder(sessao_listas, pergunta_pausada, True).status_code == 409
    atual = estado()
    assert atual["reforco"]["competencia_reforco"] == "repeticao" and atual["reforco"]["estado"] == "pendente"

    # reforço: só repeticao pode ser aberta, começando no nível 1
    p = proximo()
    assert (p["acao"], p["competencia_id"], p["reforco"]) == ("iniciar_sessao", "repeticao", True)
    assert pedir_sessao("listas_strings").status_code == 409
    sessao_reforco, pergunta = abrir_sessao()
    assert estado()["reforco"]["estado"] == "em_andamento"
    final = responder_varias(sessao_reforco, pergunta, "1111")[-1]
    assert final["feedback"]["concluida"] is True

    # retomada: volta à sessão original, mesmo nível e mesmo item
    (retomada,) = final["decisoes"]
    assert (retomada["regra"], retomada["acao"], retomada["competencia_id"]) == (
        "reforco", "retomar_original", "listas_strings")
    assert f"no nível {antes.nivel}" in final["avisos"][0]
    depois = ler_sessao(sessao_listas, ALUNO)
    assert (depois.nivel, depois.item_atual_id, depois.itens_usados) == (antes.nivel, antes.item_atual_id,
                                                                         antes.itens_usados)
    assert not pausada(sessao_listas) and estado()["reforco"] is None
    assert final["proxima"]["acao"] == "continuar_sessao" and final["proxima"]["sessao_id"] == sessao_listas
    assert "repeticao" not in a_fazer()  # o reforço não entra na trilha
    # a sessão original volta a aceitar resposta, sem novo reforço pela mesma queda
    seguinte = responder(sessao_listas, pergunta_pausada, True).json()
    assert seguinte["decisoes"] == []


def test_queda_reforca_uma_vez_por_sessao():
    iniciar()
    estudar("1111")
    estudar("000")
    assert sum(d["acao"] == "reforcar" for d in decisoes()) == 1


def test_queda_nao_dispara_sem_tendencia():
    iniciar()
    resultados = estudar("000")  # só uma sessão: sem "anteriores" para comparar
    assert all(r["decisoes"] == [] for r in resultados)


# --- R3: inatividade, dos dois lados dos limiares (datas simuladas) ---

def acoes_de_inatividade(aluno_id: str = ALUNO) -> list[str]:
    return [d["acao"] for d in decisoes(aluno_id) if d["regra"] == "inatividade"]


def test_inatividade_abaixo_do_limite_nao_faz_nada():
    iniciar()
    sessao_id, pergunta = abrir_sessao()
    responder(sessao_id, pergunta, True)
    verificar_inatividade(agora=datetime.now() + timedelta(days=2, hours=23))
    assert acoes_de_inatividade() == ["nenhuma"]


def test_inatividade_de_3_a_13_dias_so_incentiva_sem_refazer_a_trilha(llm_mockado):
    iniciar()
    sessao_id, pergunta = abrir_sessao()
    responder(sessao_id, pergunta, True)
    chamadas_planejador = llm_mockado["planejador"]
    for dias in (3, 13):  # a segunda verificação não repete o incentivo
        verificar_inatividade(agora=datetime.now() + timedelta(days=dias, minutes=1))
    assert acoes_de_inatividade() == ["incentivar", "nenhuma"]
    incentivo = [d for d in decisoes() if d["acao"] == "incentivar"][0]
    assert incentivo["replanejou"] == 0 and "Faz 3 dias" in incentivo["aviso"]
    assert llm_mockado["planejador"] == chamadas_planejador  # o Planejador não foi acionado
    conexao = obter_conexao()
    assert conexao.execute("SELECT COUNT(*) FROM auditoria WHERE tipo = 'incentivo'").fetchone()[0] == 1
    conexao.close()


def test_inatividade_de_14_dias_refaz_a_trilha_uma_vez(llm_mockado):
    iniciar()
    sessao_id, pergunta = abrir_sessao()
    responder(sessao_id, pergunta, True)
    verificar_inatividade(agora=datetime.now() + timedelta(days=13, hours=23))
    assert acoes_de_inatividade() == ["incentivar"]
    chamadas_planejador = llm_mockado["planejador"]
    verificar_inatividade(agora=datetime.now() + timedelta(days=14, minutes=1))
    verificar_inatividade(agora=datetime.now() + timedelta(days=20))
    assert acoes_de_inatividade() == ["incentivar", "refazer_trilha", "nenhuma"]
    refeita = [d for d in decisoes() if d["acao"] == "refazer_trilha"][0]
    assert refeita["replanejou"] == 1 and llm_mockado["planejador"] == chamadas_planejador + 1


def test_aluno_que_volta_e_some_de_novo_recebe_novo_incentivo():
    iniciar()
    sessao_id, pergunta = abrir_sessao()
    pergunta = responder(sessao_id, pergunta, True).json()["feedback"]["proxima_pergunta"]
    recuar_atividade(5)
    verificar_inatividade(agora=datetime.now() - timedelta(hours=1))  # incentivo 1 h antes da volta
    responder(sessao_id, pergunta, True)  # volta agora
    verificar_inatividade(agora=datetime.now() + timedelta(days=4))
    assert acoes_de_inatividade() == ["incentivar", "incentivar"]


def test_rota_de_verificacao_percorre_todos_os_alunos():
    iniciar()
    iniciar(aluno_id="A2026-031")
    recuar_atividade(5, "A2026-031")  # só este fica inativo (trilha criada há 5 dias)
    resposta = client.post("/orquestrador/verificar-inatividade")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["verificados"] == 2
    por_aluno = {d["aluno_id"]: d["decisao"]["acao"] for d in corpo["decisoes"]}
    assert por_aluno == {ALUNO: "nenhuma", "A2026-031": "incentivar"}
    registros = [r for r in client.get("/auditoria/A2026-031").json() if r["tipo"] == "decisao_orquestrador"]
    assert registros[-1]["motivo"].startswith("[inatividade] Inatividade (5 dias")


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
    assert evento({"evento_id": "dup-1", "tipo": "inatividade"}).status_code == 409


def test_evento_que_falha_pode_ser_reenviado():
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    sessao_id, pergunta = abrir_sessao()
    errado = evento({"evento_id": "re-1", "tipo": "resposta", "sessao_id": sessao_id,
                     "item_id": "outro_item", "indice_escolhido": 0})
    assert errado.status_code == 409
    assert responder(sessao_id, pergunta, True, evento_id="re-1").json()["repetido"] is False


# --- aluno inexistente e validações ---

def test_aluno_inexistente_e_validacoes():
    for resposta in (client.get("/aluno/B2026-404/estado"), client.get("/aluno/B2026-404/proximo"),
                     evento({"tipo": "inatividade"}, aluno_id="B2026-404"),
                     pedir_sessao("funcoes", aluno_id="B2026-404")):
        assert resposta.status_code == 404 and "não está matriculado" in resposta.json()["detail"]
    assert client.get("/aluno/Maria Souza/estado").status_code == 422  # nome no lugar do código (R08)
    assert iniciar(perfil_id="astronauta").status_code == 422
    assert client.get(f"/aluno/{ALUNO}/estado").status_code == 404
    assert iniciar().status_code == 200 and iniciar().status_code == 409
    assert evento({"tipo": "resposta", "sessao_id": "x"}).status_code == 422
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
    assert [r["origem"] for r in registros] == ["planejar", "abrir_sessao", "avancar", "abrir_sessao", "reforcar",
                                                "nenhuma"]
    assert all(r["motivo"].startswith(f"[{d['regra']}] ") for r, d in zip(registros, tomadas))


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


# --- origem das justificativas e do feedback, com aviso de timeout ---

def test_decisao_mostra_origem_e_tempo_do_planejador():
    corpo = iniciar(diagnostico=DIAGNOSTICO_CURTO).json()
    assert corpo["trilha"]["etapas"][0]["origem_justificativa"] == "LLM" and corpo["trilha"]["falha_llm"] is None
    decisao = corpo["decisao"]
    assert (decisao["origem_justificativas"], decisao["falha_llm"]) == ("LLM", None)
    assert decisao["tempo_planejador_ms"] >= 0


def test_timeout_do_llm_aparece_na_decisao_e_no_feedback(monkeypatch):
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
    sessao_id, pergunta = abrir_sessao()
    fb = responder(sessao_id, pergunta, True).json()["feedback"]
    assert (fb["origem"], fb["falha_llm"]) == ("fallback", "timeout")


# --- regras (puras) ---

def tendencia(direcao: str) -> Tendencia:
    return Tendencia(base="sessao", recentes=Taxa(chave="r", respostas=3, acertos=0, taxa=0.2),
                     anteriores=Taxa(chave="a", respostas=4, acertos=4, taxa=0.9), variacao=-0.7, direcao=direcao)


@pytest.mark.parametrize("direcao, desde, ja_reforcada, em_reforco, prerequisito, dispara", [
    ("caindo", None, False, False, "p", True),     # primeira queda
    ("caindo", 5, False, False, "p", True),        # 5 respostas desde o último reforço (mínimo 5)
    ("caindo", 4, False, False, "p", False),       # cedo demais
    ("caindo", None, True, False, "p", False),     # esta sessão já foi tratada
    ("caindo", None, False, True, "p", False),     # queda dentro do reforço: não encadeia
    ("caindo", None, False, False, None, False),   # sem pré-requisito direto
    ("estavel", None, False, False, "p", False),
    ("insuficiente", None, False, False, "p", False),
])
def test_regra_queda(direcao, desde, ja_reforcada, em_reforco, prerequisito, dispara):
    avaliacao = regras.regra_queda(tendencia(direcao), "a", desde, "S1", ja_reforcada, em_reforco, prerequisito)
    assert (avaliacao.dispara, avaliacao.acao) == (dispara, "reforcar" if dispara else "nenhuma")
    assert avaliacao.competencia_reforco == (prerequisito if dispara else None)


def engajamento(dias: int | None, ultima: str | None = "2026-10-01T10:00:00") -> Engajamento:
    return Engajamento(sessoes=1, sessoes_concluidas=0, respostas=1, perguntas_dialogo=0, dias_ativos=1,
                       ultima_interacao=ultima, dias_inativo=dias, inativo=dias is None or dias >= 3)


@pytest.mark.parametrize("dias, incentivo, refeita, acao", [
    (2, None, None, "nenhuma"),                       # abaixo de INATIVIDADE_DIAS
    (3, None, None, "incentivar"),                    # limiar do incentivo
    (13, None, None, "incentivar"),                   # abaixo do limiar de refazer
    (13, "2026-10-04T00:00:00", None, "nenhuma"),     # incentivo já dado neste período
    (14, None, None, "refazer_trilha"),               # limiar de refazer
    (14, "2026-10-04T00:00:00", None, "refazer_trilha"),  # incentivo antes não impede refazer
    (20, None, "2026-10-15T00:00:00", "nenhuma"),     # trilha já refeita neste período
    (20, "2026-09-01T00:00:00", "2026-09-02T00:00:00", "refazer_trilha"),  # ações de período anterior
    (None, None, None, "refazer_trilha"),             # sem nenhuma atividade registrada
])
def test_regra_inatividade(dias, incentivo, refeita, acao):
    assert regras.regra_inatividade(engajamento(dias), incentivo, refeita, refazer_dias=14).acao == acao


def test_prerequisito_direto():
    ementa = [{"id": "a", "prerequisitos": []}, {"id": "b", "prerequisitos": ["a"]},
              {"id": "c", "prerequisitos": ["b", "a"]}]
    assert [regras.prerequisito_direto(c, ementa) for c in ("a", "b", "c", "z")] == [None, "a", "b", None]


def test_regra_conclusao():
    assert regras.regra_conclusao("a", {"a"}, ja_avancou=False).acao == "avancar"
    assert regras.regra_conclusao("a", {"a"}, ja_avancou=True).dispara is False
    assert regras.regra_conclusao("a", set(), ja_avancou=False).dispara is False


def estado_puro(**campos) -> EstadoAluno:
    padrao = dict(aluno_id="X", perfil_id="p", horas_semanais=6, diagnostico={}, etapas=[], competencia_atual="a",
                  sessao_aberta_id=None, concluido=False, tendencia="estavel", inativo=False, dias_inativo=0,
                  replanejamento_pendente=None, replanejamentos=0, dialogos=0, dialogos_vetados=0)
    return EstadoAluno(**{**padrao, **campos})


def test_proxima_acao_por_prioridade():
    reforco = dict(competencia_original="a", sessao_original_id="S1", competencia_reforco="p")
    pendente = regras.proxima_acao(estado_puro(sessao_aberta_id="S9", reforco=Reforco(
        **reforco, sessao_reforco_id=None, estado="pendente")))
    assert (pendente.acao, pendente.competencia_id, pendente.reforco) == ("iniciar_sessao", "p", True)
    andamento = regras.proxima_acao(estado_puro(reforco=Reforco(**reforco, sessao_reforco_id="S2",
                                                                estado="em_andamento")))
    assert (andamento.acao, andamento.sessao_id) == ("continuar_sessao", "S2")
    assert regras.proxima_acao(estado_puro(concluido=True, competencia_atual=None)).acao == "concluido"
    assert regras.proxima_acao(estado_puro(sessao_aberta_id="S1")).acao == "continuar_sessao"
    # inatividade não muda a próxima ação do aluno (quem age é a verificação agendada)
    assert regras.proxima_acao(estado_puro(replanejamento_pendente="inativo")).acao == "iniciar_sessao"


def test_estado_com_relogio_injetado():
    from tia.orquestrador import estado as estado_fluxo
    iniciar(diagnostico=DIAGNOSTICO_CURTO)
    futuro = estado_fluxo(ALUNO, agora=datetime.now() + timedelta(days=4))
    assert futuro.inativo is True and futuro.replanejamento_pendente is not None
