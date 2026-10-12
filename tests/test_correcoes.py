"""
Testes das correções pequenas da etapa 1.4.6 (parte A), com o TestClient,
banco temporário e sem LLM:

- A1: evento reenviado (mesmo evento_id) depois do veto do docente devolve a
  correção, nunca o texto vetado;
- A2: quem concluiu a trilha não conta como inativo no indicador do Agente 3,
  na visão geral do painel (relatório da turma) e em GET /tutor/incentivo.

Como rodar:
    ./run_tests.sh tests/test_correcoes.py
"""

from datetime import datetime

import pytest
import requests
from fastapi.testclient import TestClient

import tia.agentes.tutor as tutor
import tia.core.llm_client as llm_client
from tia.agentes.relatorio import gerar_relatorio_turma, indicadores
from tia.agentes.relatorio.repositorio import ler_dados_aluno, listar_alunos
from tia.agentes.tutor.feedback import ResultadoFeedback, montar_veredito
from tia.agentes.tutor.incentivo import MENSAGEM_TRILHA_CONCLUIDA
from tia.agentes.tutor.repositorio import carregar_itens
from tia.api.main import app
from tia.web import dados_painel

client = TestClient(app)
ALUNO = "A2026-C01"
ITENS = {i["id"]: i for i in carregar_itens()}
TEXTO_LLM = "Explicação original do LLM sobre funções."


def falha_imediata(*args, **kwargs):
    raise requests.ConnectionError("teste sem LLM")


@pytest.fixture
def turma(monkeypatch):
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    dados_painel.criar_turma(datetime.now())


# --- A1: reenvio depois do veto ---

@pytest.fixture
def evento_respondido(monkeypatch):
    """Aluno matriculado que respondeu a primeira pergunta por evento; devolve (corpo do evento, resultado)."""
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    monkeypatch.setattr(tutor, "gerar_feedback", lambda item, indice, materiais, modo=None: ResultadoFeedback(
        montar_veredito(item, indice), TEXTO_LLM, ["provisorio_funcoes.txt"], "LLM"))
    client.post(f"/aluno/{ALUNO}/iniciar", json={"perfil_id": "intermediario", "horas_semanais": 6, "diagnostico": {
        "variaveis_tipos": 1.0, "condicionais": 1.0, "repeticao": 1.0}})
    sessao = client.post(f"/aluno/{ALUNO}/sessao", json={"competencia_id": "funcoes"}).json()["sessao"]
    corpo = {"evento_id": "evento-a1", "tipo": "resposta", "sessao_id": sessao["sessao_id"],
             "item_id": sessao["pergunta"]["item_id"], "indice_escolhido": 0}
    resultado = client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()
    assert resultado["feedback"]["explicacao"] == TEXTO_LLM and resultado["feedback"]["resposta_id"]
    return corpo, resultado


def test_reenvio_sem_veto_devolve_o_resultado_gravado(evento_respondido):
    corpo, original = evento_respondido
    repetido = client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()
    assert repetido["repetido"] is True and repetido["feedback"] == original["feedback"]


def test_reenvio_depois_do_veto_devolve_a_correcao(evento_respondido):
    corpo, original = evento_respondido
    resposta_id = original["feedback"]["resposta_id"]
    assert client.patch(f"/tutor/feedback/{resposta_id}/veto",
                        json={"vetada": True, "correcao_docente": "Correção do professor."}).status_code == 200
    repetido = client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()
    feedback = repetido["feedback"]
    assert repetido["repetido"] is True
    assert (feedback["explicacao"], feedback["origem"], feedback["fontes"]) == ("Correção do professor.", "docente", [])
    assert TEXTO_LLM not in str(repetido)
    # o resto do resultado não muda (veredito, nível, próxima pergunta)
    for campo in ("acertou", "veredito", "indice_correto", "nivel_atual", "proxima_pergunta", "resposta_id"):
        assert feedback[campo] == original["feedback"][campo], campo
    # retirado o veto, o reenvio volta ao texto original
    client.patch(f"/tutor/feedback/{resposta_id}/veto", json={"vetada": False})
    assert client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()["feedback"]["explicacao"] == TEXTO_LLM


# --- A2: trilha concluída não é inatividade ---

def test_agente3_nao_marca_inativo_quem_concluiu(turma):
    relatorio = client.get("/relatorio/aluno/DEMO-P02?narrativa=false").json()
    engajamento = relatorio["engajamento"]
    assert relatorio["progresso"]["concluidas"] == relatorio["progresso"]["etapas"] == 3
    assert engajamento["dias_inativo"] >= 12  # o dado continua lá
    assert (engajamento["inativo"], engajamento["trilha_concluida"]) == (False, True)
    # quem não concluiu continua inativo
    p04 = client.get("/relatorio/aluno/DEMO-P04?narrativa=false").json()["engajamento"]
    assert (p04["inativo"], p04["trilha_concluida"]) == (True, False)


def test_visao_geral_conta_inativos_sem_quem_concluiu(turma):
    agora = datetime.now()
    inativos = {a for a in listar_alunos() if indicadores.engajamento(ler_dados_aluno(a), agora).inativo}
    assert inativos == {"DEMO-P04", "DEMO-P05", "DEMO-P11"}
    # relatório da turma (o que a visão geral do painel mostra), com grupo mínimo 1 para ver o número
    turma = gerar_relatorio_turma(agora=agora, com_narrativa=False, min_grupo=1)
    assert turma.engajamento.inativos.valor == 3
    alerta = next(a for a in turma.alertas if a.tipo == "inatividade")
    assert alerta.alunos.valor == 3
    # pela rota, com o grupo mínimo de verdade: 3 < 5
    visao = client.get("/relatorio/turma?narrativa=false").json()
    assert visao["engajamento"]["inativos"]["texto"] == "menos de 5"


def test_incentivo_de_quem_concluiu(turma):
    incentivo = client.get("/tutor/incentivo/DEMO-P02").json()
    assert incentivo["inativo"] is False and incentivo["mensagem"] == MENSAGEM_TRILHA_CONCLUIDA
    assert incentivo["dias"] >= 12 and incentivo["etapas_restantes"] == 0
    pendente = client.get("/tutor/incentivo/DEMO-P04").json()
    assert pendente["inativo"] is True and "Faz 9 dias" in pendente["mensagem"]
