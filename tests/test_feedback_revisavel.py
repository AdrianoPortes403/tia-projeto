"""
Testes do feedback revisável (R12) e da correção da R3, com o TestClient,
banco temporário (conftest) e o LLM mockado:

- gravação do texto do feedback (tutor_feedbacks) na mesma transação da resposta;
- LGPD: o texto só aparece nas rotas do docente e do próprio aluno, nunca nas agregadas;
- veto do feedback das questões (aprovar, vetar, retirar), o que o aluno vê e a auditoria;
- filtros da revisão do painel (tipo, origem, competência, situação);
- exportação (CSV dos indicadores e CSV da amostra);
- determinismo e estratificação da amostra (python -m tia.painel.amostra);
- R3: quem concluiu a trilha não recebe incentivo nem é marcado como inativo.

Como rodar:
    ./run_tests.sh tests/test_feedback_revisavel.py
"""

import csv
import io
from datetime import datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

import tia.agentes.tutor as tutor
import tia.core.llm_client as llm_client
from tia import orquestrador
from tia.agentes.relatorio import gerar_relatorio_aluno
from tia.agentes.relatorio.modelos import Engajamento
from tia.agentes.relatorio.repositorio import ler_dados_aluno
from tia.agentes.tutor.feedback import ResultadoFeedback, montar_veredito
from tia.agentes.tutor.repositorio import carregar_itens, registrar_dialogo
from tia.api.main import app
from tia.core.database import obter_conexao
from tia.orquestrador import regras
from tia.painel import amostra
from tia.web import dados_painel

client = TestClient(app)
ALUNO = "A2026-F01"
ITENS = {i["id"]: i for i in carregar_itens()}
TEXTO_LLM = "A função devolve o valor com return e encerra ali."


def falha_imediata(*args, **kwargs):
    raise requests.ConnectionError("teste sem LLM")


@pytest.fixture
def feedback_llm(monkeypatch):
    """O feedback do Tutor sai como se o LLM tivesse escrito (com fonte)."""
    def gerar(item, indice, materiais, modo=None):
        return ResultadoFeedback(montar_veredito(item, indice), TEXTO_LLM, ["provisorio_funcoes.txt"], "LLM")
    monkeypatch.setattr(tutor, "gerar_feedback", gerar)


@pytest.fixture
def turma(monkeypatch):
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    dados_painel.criar_turma(datetime.now())


def responder(aluno_id: str = ALUNO, acertar: bool = True) -> dict:
    """Abre uma sessão de funções pelo Tutor e responde a primeira pergunta."""
    sessao = client.post("/tutor/sessao", json={"aluno_id": aluno_id, "competencia_id": "funcoes"}).json()
    pergunta = sessao["pergunta"]
    correto = ITENS[pergunta["item_id"]]["indice_correto"]
    resposta = client.post("/tutor/resposta", json={
        "sessao_id": sessao["sessao_id"], "aluno_id": aluno_id, "item_id": pergunta["item_id"],
        "indice_escolhido": correto if acertar else (correto + 1) % 4})
    assert resposta.status_code == 200
    return {**resposta.json(), "sessao_id": sessao["sessao_id"], "item_id": pergunta["item_id"]}


def linha_feedback(resposta_id: int) -> dict | None:
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT * FROM tutor_feedbacks WHERE resposta_id = ?", (resposta_id,)).fetchone()
    finally:
        conexao.close()
    return None if linha is None else dict(linha)


def vetar(resposta_id: int, **corpo):
    return client.patch(f"/tutor/feedback/{resposta_id}/veto", json=corpo)


# --- 1. gravação do texto ---

def test_texto_do_feedback_e_gravado_com_origem_fontes_item_e_sessao(feedback_llm):
    feedback = responder(acertar=False)
    assert feedback["resposta_id"] is not None and feedback["explicacao"] == TEXTO_LLM
    linha = linha_feedback(feedback["resposta_id"])
    assert linha["explicacao"] == TEXTO_LLM and linha["veredito"] == feedback["veredito"]
    assert (linha["origem"], linha["fontes"]) == ("LLM", '["provisorio_funcoes.txt"]')
    assert (linha["aluno_id"], linha["item_id"], linha["sessao_id"], linha["competencia_id"]) == (
        ALUNO, feedback["item_id"], feedback["sessao_id"], "funcoes")
    assert linha["vetada"] == 0 and linha["correcao_docente"] is None


def test_fallback_grava_o_texto_do_item(monkeypatch):
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    monkeypatch.setattr("tia.agentes.tutor.feedback.buscar_contexto", lambda consulta, k=3, fontes=None: [])
    feedback = responder()
    linha = linha_feedback(feedback["resposta_id"])
    assert linha["origem"] == "fallback" and linha["explicacao"] == ITENS[feedback["item_id"]]["explicacao"]


def test_texto_barrado_pela_guarda_fica_so_para_o_docente(monkeypatch):
    def gerar(item, indice, materiais, modo=None):
        return ResultadoFeedback(montar_veredito(item, indice), item["explicacao"], [], "guarda",
                                 motivo_descarte="número fora do item: 42", explicacao_descartada="Resultado: 42.")
    monkeypatch.setattr(tutor, "gerar_feedback", gerar)
    feedback = responder()
    assert "42" not in feedback["explicacao"]
    linha = linha_feedback(feedback["resposta_id"])
    assert (linha["explicacao_descartada"], linha["motivo_descarte"]) == ("Resultado: 42.", "número fora do item: 42")
    visto_pelo_aluno = client.get(f"/alunos/{ALUNO}/feedbacks").json()[0]
    assert "Resultado: 42." not in str(visto_pelo_aluno)
    revisao = client.get("/painel/revisao?tipo=feedback").json()["itens"][0]
    assert revisao["explicacao_descartada"] == "Resultado: 42." and revisao["origem"] == "guarda"


def test_resposta_antiga_sem_texto_nao_e_revisavel():
    conexao = obter_conexao()
    with conexao:
        cursor = conexao.execute("""INSERT INTO historico_respostas (aluno_id, topico, acertou, timestamp, nivel)
                                    VALUES ('A2026-F02', 'funcoes', 1, '2026-09-01T10:00:00', 1)""")
    conexao.close()
    assert vetar(cursor.lastrowid, vetada=False).status_code == 404
    revisao = client.get("/painel/revisao?tipo=feedback&situacao=todas").json()
    assert revisao["itens"] == [] and revisao["feedbacks_sem_texto"] == 1


# --- LGPD: texto só nas telas do docente (e do próprio aluno) ---

def test_texto_nunca_aparece_nas_visoes_agregadas(feedback_llm):
    for n in range(5):
        responder(f"A2026-L0{n}")
    assert all("explicacao" not in r for r in ler_dados_aluno("A2026-L00").respostas)  # o Agente 3 não lê o texto
    for rota in ("/relatorio/turma?narrativa=false", "/painel/competencias", "/painel/exportar/indicadores.csv",
                 "/relatorio/aluno/A2026-L00?narrativa=false"):
        texto = client.get(rota).text
        assert TEXTO_LLM not in texto, rota
    assert TEXTO_LLM in client.get("/painel/revisao?tipo=feedback").text  # tela do docente
    assert TEXTO_LLM in client.get("/alunos/A2026-L00/feedbacks").text   # o próprio aluno


# --- 2. veto do feedback das questões ---

def test_vetar_feedback_troca_o_texto_para_o_aluno_e_preserva_o_original(feedback_llm):
    feedback = responder(acertar=False)
    resposta_id = feedback["resposta_id"]
    assert vetar(resposta_id, vetada=True).status_code == 422  # vetar exige a correção
    resultado = vetar(resposta_id, vetada=True, correcao_docente="  Correção do professor.  ")
    assert resultado.status_code == 200
    assert resultado.json() | {"ts": None} == {
        "resposta_id": resposta_id, "ts": None, "sessao_id": feedback["sessao_id"], "item_id": feedback["item_id"],
        "enunciado": ITENS[feedback["item_id"]]["enunciado"], "competencia_id": "funcoes",
        "veredito": feedback["veredito"], "explicacao": "Correção do professor.", "fontes": [], "origem": "docente",
        "vetada": True}
    # o aluno vê a correção no histórico de feedbacks
    assert client.get(f"/alunos/{ALUNO}/feedbacks").json()[0]["explicacao"] == "Correção do professor."
    # o original fica guardado e aparece na revisão do docente
    assert linha_feedback(resposta_id)["explicacao"] == TEXTO_LLM
    item = client.get("/painel/revisao?tipo=feedback&situacao=vetadas").json()["itens"][0]
    assert (item["resposta"], item["correcao_docente"], item["situacao"]) == (
        TEXTO_LLM, "Correção do professor.", "vetada")
    # indicador 5 do Agente 3
    q = gerar_relatorio_aluno(ALUNO, com_narrativa=False).qualidade_feedback
    assert (q.feedbacks_com_texto, q.feedbacks_vetados, q.taxa_veto_feedback) == (1, 1, 1.0)


def test_aprovar_e_retirar_veto_do_feedback_gravam_auditoria(feedback_llm):
    primeiro, segundo = responder()["resposta_id"], responder("A2026-F03")["resposta_id"]
    assert vetar(primeiro, vetada=False).json()["explicacao"] == TEXTO_LLM  # aprovar não muda o texto
    vetar(segundo, vetada=True, correcao_docente="Correção.")
    vetar(segundo, vetada=False)
    situacoes = {i["id"]: i["situacao"] for i in client.get("/painel/revisao?tipo=feedback&situacao=todas").json()["itens"]}
    assert situacoes == {primeiro: "aprovada", segundo: "aprovada"}
    registros = [x for x in client.get("/painel/auditoria?agente=tutor").json()["registros"]
                 if x["tipo"] == "veto_docente"]
    assert [(x["referencia_id"], x["motivo"]) for x in reversed(registros)] == [
        (f"feedback:{primeiro}", "resposta aprovada"),
        (f"feedback:{segundo}", "resposta vetada e corrigida"),
        (f"feedback:{segundo}", "veto retirado")]
    assert all("Correção" not in (x["motivo"] or "") for x in registros)


def test_veto_de_dialogo_e_de_feedback_com_o_mesmo_numero_nao_se_misturam(feedback_llm):
    resposta_id = responder()["resposta_id"]
    dialogo_id = registrar_dialogo(ALUNO, None, "pergunta", "resposta", [], "LLM", 10)
    assert resposta_id == dialogo_id == 1
    client.patch(f"/tutor/dialogo/{dialogo_id}/veto", json={"vetada": False})
    itens = {i["tipo"]: i["situacao"] for i in client.get("/painel/revisao?situacao=todas").json()["itens"]}
    assert itens == {"dialogo": "aprovada", "feedback": "a_revisar"}


def test_veto_de_feedback_inexistente():
    assert vetar(999, vetada=True, correcao_docente="x").status_code == 404


# --- 3. filtros da revisão ---

def test_filtros_da_revisao(turma):
    def itens(consulta: str) -> list[dict]:
        r = client.get(f"/painel/revisao?por_pagina=100&{consulta}").json()
        assert r["total"] == len(r["itens"]) or r["total"] > 100
        return r["itens"]

    todos = itens("situacao=todas")
    assert {i["tipo"] for i in todos} == {"dialogo", "feedback"}
    assert all(i["tipo"] == "feedback" for i in itens("situacao=todas&tipo=feedback"))
    guarda = itens("situacao=todas&origem=guarda")
    assert guarda and all(i["origem"] == "guarda" for i in guarda)
    assert all(i["explicacao_descartada"] for i in guarda if i["tipo"] == "feedback")  # o diálogo não guarda o descarte
    listas = itens("situacao=todas&competencia_id=listas_strings&tipo=feedback")
    assert listas and all(i["competencia_id"] == "listas_strings" and i["pergunta"] for i in listas)
    assert all(i["veredito"] and i["acertou"] is not None and i["nivel"] for i in listas)
    combinado = itens("tipo=feedback&origem=LLM&competencia_id=funcoes")
    assert combinado and all((i["tipo"], i["origem"], i["competencia_id"], i["situacao"]) ==
                             ("feedback", "LLM", "funcoes", "a_revisar") for i in combinado)
    vetar(combinado[0]["id"], vetada=True, correcao_docente="Correção.")
    assert [i["id"] for i in itens("situacao=vetadas&tipo=feedback")] == [combinado[0]["id"]]
    assert combinado[0]["id"] not in [i["id"] for i in itens("tipo=feedback&origem=LLM&competencia_id=funcoes")]
    datas = [i["ts"] for i in todos]
    assert datas == sorted(datas, reverse=True)


# --- exportação ---

def test_csv_de_indicadores_tem_o_veto_de_feedback(turma):
    item = client.get("/painel/revisao?tipo=feedback&origem=LLM").json()["itens"][0]
    vetar(item["id"], vetada=True, correcao_docente="Correção.")
    linhas = list(csv.reader(io.StringIO(client.get("/painel/exportar/indicadores.csv").text.lstrip("﻿")),
                             delimiter=";"))
    linha = next(x for x in linhas if x[1] == "veto docente (feedback das questões)")
    assert linha[6] == "1 vetado(s)" and linha[5].startswith("0,")


def test_csv_da_amostra(turma, tmp_path):
    destino, sorteados = amostra.exportar(20, semente=7, caminho=str(tmp_path / "amostra.csv"))
    conteudo = destino.read_text(encoding="utf-8")
    assert conteudo.startswith("﻿")
    linhas = list(csv.reader(io.StringIO(conteudo.lstrip("﻿")), delimiter=";"))
    assert linhas[0] == amostra.COLUNAS and linhas[0][-2:] == ["adequado (S/N)", "observacao"]
    assert len(linhas) == 21 and all(linha[-2:] == ["", ""] for linha in linhas[1:])
    assert all(linha[9] == "LLM" and linha[8] for linha in linhas[1:])
    assert "DEMO-P" not in conteudo  # sem código de aluno
    # a exportação vai para a auditoria
    registro = client.get("/painel/auditoria?agente=painel").json()["registros"][0]
    assert registro["referencia_id"] == "amostra" and "semente=7" in registro["motivo"]


# --- 4. amostra: determinismo e estratificação ---

def test_amostra_e_deterministica(turma):
    textos = amostra.candidatos()
    a = [(t["tipo"], t["id"]) for t in amostra.sortear(textos, 30, semente=11)]
    b = [(t["tipo"], t["id"]) for t in amostra.sortear(amostra.candidatos(), 30, semente=11)]
    c = [(t["tipo"], t["id"]) for t in amostra.sortear(textos, 30, semente=12)]
    assert a == b and a != c and len(a) == len(set(a)) == 30


def test_amostra_so_llm_estratificada_por_competencia(turma):
    textos = amostra.candidatos()
    assert textos and all(t["origem"] == "LLM" for t in textos)
    por_competencia = {}
    for t in textos:
        por_competencia[t["competencia_id"]] = por_competencia.get(t["competencia_id"], 0) + 1
    sorteados = amostra.sortear(textos, 20, semente=3)
    contagem = {}
    for t in sorteados:
        contagem[t["competencia_id"]] = contagem.get(t["competencia_id"], 0) + 1
    assert len(sorteados) == 20
    assert set(contagem) == set(por_competencia)  # toda competência com texto aparece
    assert contagem == amostra.alocar(por_competencia, 20)
    # pedido maior que o total: todos os textos, uma vez cada
    assert len(amostra.sortear(textos, 10_000)) == len(textos)
    assert {t["tipo"] for t in amostra.candidatos("dialogo")} == {"dialogo"}


@pytest.mark.parametrize("tamanhos, n, esperado", [
    ({"a": 50, "b": 30, "c": 20}, 10, {"a": 5, "b": 3, "c": 2}),
    ({"a": 90, "b": 5, "c": 5}, 10, {"a": 8, "b": 1, "c": 1}),     # pelo menos 1 por estrato
    ({"a": 3, "b": 1}, 10, {"a": 3, "b": 1}),                     # menos textos que n: todos
    ({"a": 10, "b": 10, "c": 10}, 2, {"a": 1, "b": 1, "c": 0}),    # n menor que os estratos: maiores restos
    ({"a": 1, "b": 99}, 50, {"a": 1, "b": 49}),
])
def test_alocacao_por_estrato(tamanhos, n, esperado):
    cotas = amostra.alocar(tamanhos, n)
    assert cotas == esperado and sum(cotas.values()) == min(n, sum(tamanhos.values()))
    assert all(cotas[k] <= tamanhos[k] for k in tamanhos)


# --- 5. R3: trilha concluída ---

def engajamento(dias: int) -> Engajamento:
    return Engajamento(sessoes=3, sessoes_concluidas=3, respostas=12, perguntas_dialogo=0, dias_ativos=3,
                       ultima_interacao="2026-09-01T10:00:00", dias_inativo=dias, inativo=True)


@pytest.mark.parametrize("dias", [3, 10, 30])
def test_regra_r3_ignora_quem_concluiu_a_trilha(dias):
    avaliacao = regras.regra_inatividade(engajamento(dias), None, None, trilha_concluida=True)
    assert (avaliacao.dispara, avaliacao.acao) == (False, "nenhuma") and "concluída" in avaliacao.motivo
    assert regras.regra_inatividade(engajamento(dias), None, None).dispara  # sem concluir, continua valendo


def test_r3_no_orquestrador_consistente_com_o_painel(turma):
    """DEMO-P02 concluiu a trilha e está parado há 12 dias: nem incentivo, nem inativo, nem risco."""
    decisoes = orquestrador.repositorio.listar_decisoes("DEMO-P02")
    assert [d["acao"] for d in decisoes if d["regra"] == "inatividade"] == ["nenhuma"]
    assert "Trilha concluída" in decisoes[-1]["motivo"]
    estado = client.get("/aluno/DEMO-P02/estado").json()
    assert estado["concluido"] is True and estado["inativo"] is False and estado["dias_inativo"] >= 12
    assert estado["replanejamento_pendente"] is None
    assert "DEMO-P02" not in [a["aluno_id"] for a in client.get("/painel/alunos-em-risco").json()["alunos"]]
    # quem não concluiu continua recebendo: DEMO-P04 (9 dias) e DEMO-P11 (5 dias)
    for aluno in ("DEMO-P04", "DEMO-P11"):
        assert "incentivar" in [d["acao"] for d in orquestrador.repositorio.listar_decisoes(aluno)]
        assert client.get(f"/aluno/{aluno}/estado").json()["inativo"] is True
    # rodar a verificação de novo, mais tarde, continua sem incentivo para quem concluiu
    resultado = orquestrador.verificar_inatividade(datetime.now() + timedelta(days=30))
    p02 = next(d for d in resultado.decisoes if d.aluno_id == "DEMO-P02")
    assert p02.decisao.acao == "nenhuma"
