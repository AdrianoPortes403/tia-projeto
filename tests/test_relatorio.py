"""
Testes do Agente 3 (Relatório): cada indicador com dados fixos, regra do
grupo mínimo (R08), narrativa com fallback e guarda de números, rotas e
auditoria (R11). llm_client mockado; banco temporário (conftest).

Como rodar:
    ./run_tests.sh tests/test_relatorio.py
"""

import json
import logging
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import tia.agentes.relatorio.narrativa as narrativa
from tia.agentes.planejador.modelos import EtapaTrilha, Trilha
from tia.agentes.relatorio import gerar_relatorio_aluno, gerar_relatorio_turma, indicadores
from tia.agentes.relatorio.__main__ import ALUNOS_DEMO, popular_dados_sinteticos
from tia.agentes.relatorio.repositorio import DadosAluno
from tia.api.main import app
from tia.core.database import obter_conexao

client = TestClient(app)

AGORA = datetime(2026, 10, 10, 12, 0, 0)
NOMES = {"a": "Comp A", "b": "Comp B", "c": "Comp C"}


def ts(dias_atras: float, minutos: int = 0) -> str:
    return (AGORA - timedelta(days=dias_atras) + timedelta(minutes=minutos)).isoformat(timespec="seconds")


def resposta(competencia: str, acertou: bool, nivel: int = 1, dias_atras: float = 1, minutos: int = 0,
             origem: str | None = "LLM") -> dict:
    return {"competencia_id": competencia, "nivel": nivel, "acertou": acertou, "ts": ts(dias_atras, minutos),
            "origem": origem}


def trilha(*competencias: str) -> Trilha:
    return Trilha(aluno_id="T1", perfil_id="iniciante", etapas=[
        EtapaTrilha(ordem=n, competencia_id=c, nome=NOMES[c], horas=4, semana_inicio=n, justificativa="")
        for n, c in enumerate(competencias, 1)])


def dados(respostas=(), sessoes=(), dialogos=(), com_trilha=True, aluno_id="T1", trilha_criada_em=None) -> DadosAluno:
    return DadosAluno(aluno_id=aluno_id, perfil_id="iniciante", trilha=trilha("a", "b", "c") if com_trilha else None,
                      trilha_criada_em=trilha_criada_em, respostas=list(respostas), sessoes=list(sessoes),
                      dialogos=list(dialogos))


def sessao(competencia: str, nivel: int, concluida: bool, dias_atras: float) -> dict:
    return {"competencia_id": competencia, "nivel": nivel, "concluida": concluida,
            "criado_em": ts(dias_atras), "atualizado_em": ts(dias_atras, 10)}


# --- 1. progresso ---

def test_progresso_percentual_e_nivel_atual_da_sessao_mais_recente():
    d = dados(sessoes=[sessao("a", 3, True, 5), sessao("b", 3, False, 4), sessao("b", 1, False, 2)])
    p = indicadores.progresso(d, NOMES)
    assert (p.tem_trilha, p.etapas, p.concluidas, p.percentual) == (True, 3, 1, 0.333)
    assert [(c.competencia_id, c.nome, c.concluida, c.nivel_atual) for c in p.por_competencia] == [
        ("a", "Comp A", True, 3), ("b", "Comp B", False, 1), ("c", "Comp C", False, None)]


def test_progresso_sem_trilha():
    p = indicadores.progresso(dados(sessoes=[sessao("b", 2, False, 1)], com_trilha=False), NOMES)
    assert (p.tem_trilha, p.etapas, p.percentual) == (False, 0, None)
    assert [c.competencia_id for c in p.por_competencia] == ["b"]


# --- 2. desempenho ---

def test_desempenho_por_competencia_e_por_nivel():
    respostas = [resposta("a", True, 1), resposta("a", False, 2), resposta("a", True, 2), resposta("b", False, 1)]
    d = indicadores.desempenho(respostas)
    assert (d.geral.respostas, d.geral.acertos, d.geral.taxa) == (4, 2, 0.5)
    assert [(t.chave, t.respostas, t.acertos, t.taxa) for t in d.por_competencia] == [("a", 3, 2, 0.667),
                                                                                     ("b", 1, 0, 0.0)]
    assert [(t.chave, t.taxa) for t in d.por_nivel] == [("1", 0.5), ("2", 0.5)]


@pytest.mark.parametrize("sequencia, direcao, variacao", [
    ("111" + "10000", "caindo", -0.8),        # 3 anteriores a 100%, últimas 5 a 20%
    ("000" + "11111", "subindo", 1.0),
    ("101" + "10101", "estavel", -0.067),     # 60% x 66,7%
    ("11" + "00000", "insuficiente", None),   # só 2 anteriores (mínimo 3)
    ("1111", "insuficiente", None),           # nem 5 recentes
])
def test_tendencia_ultimas_respostas_contra_anteriores(sequencia, direcao, variacao):
    respostas = [resposta("a", c == "1", minutos=n) for n, c in enumerate(sequencia)]
    t = indicadores.tendencia(respostas)
    assert (t.direcao, t.variacao) == (direcao, variacao)


def test_desempenho_sem_respostas():
    d = indicadores.desempenho([])
    assert (d.geral.respostas, d.geral.taxa, d.tendencia.direcao) == (0, None, "insuficiente")


# --- 3. engajamento ---

def test_engajamento_dias_ativos_e_inatividade():
    d = dados(respostas=[resposta("a", True, dias_atras=5), resposta("a", True, dias_atras=5, minutos=3),
                         resposta("b", False, dias_atras=4)],
              sessoes=[sessao("a", 2, True, 5)],
              dialogos=[{"competencia_id": "a", "origem": "LLM", "vetada": False, "ts": ts(4)}])
    e = indicadores.engajamento(d, AGORA)
    assert (e.sessoes, e.sessoes_concluidas, e.respostas, e.perguntas_dialogo, e.dias_ativos) == (1, 1, 3, 1, 2)
    assert (e.dias_inativo, e.inativo) == (4, True)  # INATIVIDADE_DIAS = 3
    assert indicadores.engajamento(d, AGORA - timedelta(days=2)).inativo is False


def test_engajamento_sem_interacao_conta_da_trilha_ou_e_inativo():
    so_trilha = indicadores.engajamento(dados(trilha_criada_em=ts(1)), AGORA)
    assert (so_trilha.dias_inativo, so_trilha.inativo, so_trilha.dias_ativos) == (1, False, 0)
    nada = indicadores.engajamento(dados(com_trilha=False), AGORA)
    assert (nada.dias_inativo, nada.inativo, nada.ultima_interacao) == (None, True, None)


# --- 4. pontos fracos ---

def test_pontos_fracos_erro_repetido_sequencia_e_dialogo():
    respostas = ([resposta("a", c == "1", minutos=n) for n, c in enumerate("0010")]        # 3 erros/4, seq 2
                 + [resposta("b", c == "1", minutos=n) for n, c in enumerate("01111")]     # 1 erro: não
                 + [resposta("c", c == "1", minutos=n) for n, c in enumerate("00111")])    # 2/5 = 40%: não
    dialogos = [{"competencia_id": "a", "origem": "LLM", "vetada": False, "ts": ts(1)}] * 2
    (fraco,) = indicadores.pontos_fracos(respostas, dialogos, NOMES)
    assert (fraco.competencia_id, fraco.nome, fraco.respostas, fraco.erros, fraco.taxa_erro,
            fraco.maior_sequencia_erros, fraco.perguntas_dialogo) == ("a", "Comp A", 4, 3, 0.75, 2, 2)


def test_pontos_fracos_ordenados_pela_taxa_de_erro():
    respostas = ([resposta("a", c == "1", minutos=n) for n, c in enumerate("010")]
                 + [resposta("b", False, minutos=n) for n in range(2)])
    assert [p.competencia_id for p in indicadores.pontos_fracos(respostas, [], NOMES)] == ["b", "a"]


# --- 5. qualidade do feedback ---

def test_qualidade_do_feedback_origens_e_veto():
    respostas = [resposta("a", True, origem="LLM"), resposta("a", True, origem="guarda"),
                 resposta("a", True, origem=None)]
    dialogos = [{"competencia_id": "a", "origem": o, "vetada": v, "ts": ts(1)}
                for o, v in [("LLM", True), ("fallback", False), ("LLM", False), ("LLM", False)]]
    q = indicadores.qualidade_feedback(respostas, dialogos)
    assert (q.respostas_com_origem, q.respostas_sem_registro) == (2, 1)
    assert q.por_origem == {"LLM": 4, "guarda": 1, "fallback": 1}
    assert q.taxa_por_origem == {"LLM": 0.667, "guarda": 0.167, "fallback": 0.167}
    assert (q.dialogos, q.vetados, q.taxa_veto) == (4, 1, 0.25)


def test_qualidade_sem_dados():
    q = indicadores.qualidade_feedback([], [])
    assert q.taxa_por_origem == {"LLM": None, "guarda": None, "fallback": None} and q.taxa_veto is None


# --- grupo mínimo (R08) ---

def aluno_turma(i: int, competencias: str = "ab", queda: bool = False, dias_atras: float = 1) -> DadosAluno:
    sequencia = "11110000" if queda else "1101"
    respostas = [resposta(c, s == "1", nivel=1, dias_atras=dias_atras, minutos=10 * k + n)
                 for k, c in enumerate(competencias) for n, s in enumerate(sequencia)]
    return dados(respostas=respostas, sessoes=[sessao(c, 2, False, dias_atras) for c in competencias],
                 aluno_id=f"T{i}")


def test_contagem_abaixo_do_minimo_nao_mostra_o_numero():
    assert indicadores.contagem(3, 5).model_dump() == {"valor": None, "texto": "menos de 5"}
    assert indicadores.contagem(5, 5).model_dump() == {"valor": 5, "texto": "5"}
    assert indicadores.contagem(0, 5).model_dump() == {"valor": 0, "texto": "0"}


def test_turma_com_menos_alunos_que_o_minimo_e_suprimida():
    campos = indicadores.agregar_turma([aluno_turma(i) for i in range(4)], AGORA, 5, NOMES)
    assert campos == {"alunos": indicadores.contagem(4, 5), "suprimido": True}


def test_grupo_de_competencia_abaixo_do_minimo_e_suprimido():
    # 5 alunos em "a"; só 2 em "b"
    turma = [aluno_turma(i, "a") for i in range(3)] + [aluno_turma(i, "ab") for i in range(3, 5)]
    campos = indicadores.agregar_turma(turma, AGORA, 5, NOMES)
    grupos = {g.chave: g for g in campos["desempenho_por_competencia"]}
    assert (grupos["a"].suprimido, grupos["a"].alunos.valor, grupos["a"].respostas, grupos["a"].taxa) == (
        False, 5, 20, 0.75)
    assert (grupos["b"].suprimido, grupos["b"].alunos.texto, grupos["b"].respostas, grupos["b"].taxa) == (
        True, "menos de 5", None, None)


def test_alertas_da_turma_sao_contagens_agregadas():
    turma = ([aluno_turma(i, "a", queda=True, dias_atras=10) for i in range(5)]
             + [aluno_turma(i, "a") for i in range(5, 7)])
    campos = indicadores.agregar_turma(turma, AGORA, 5, NOMES)
    alertas = {a.tipo: a for a in campos["alertas"]}
    assert alertas["inatividade"].alunos.valor == 5
    assert alertas["desempenho_em_queda"].alunos.valor == 5
    assert campos["engajamento"].inativos.valor == 5
    # 7 alunos em "a": 5 x 50% e 2 x 75% -> 4+... = acerto agregado 0.571 (não abaixo de 50%): sem alerta de erro
    assert "competencia_com_erro_alto" not in alertas

    poucos_em_queda = [aluno_turma(0, "a", queda=True)] + [aluno_turma(i, "a") for i in range(1, 6)]
    alerta = next(a for a in indicadores.agregar_turma(poucos_em_queda, AGORA, 5, NOMES)["alertas"]
                  if a.tipo == "desempenho_em_queda")
    assert alerta.alunos.model_dump() == {"valor": None, "texto": "menos de 5"}


# --- relatórios no banco (dados sintéticos da demonstração) ---

@pytest.fixture
def demo():
    popular_dados_sinteticos(AGORA)


@pytest.fixture
def llm(monkeypatch):
    """LLM falso: registra os prompts e devolve o texto configurado."""
    estado = {"resposta": "Seu progresso está indo bem.", "prompts": []}

    def falso(prompt, **kwargs):
        estado["prompts"].append((prompt, kwargs))
        if isinstance(estado["resposta"], Exception):
            raise estado["resposta"]
        return estado["resposta"]

    monkeypatch.setattr(narrativa, "chamar_llm", falso)
    return estado


def test_relatorio_do_aluno_completo_com_narrativa_do_llm(demo, llm):
    rel = gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    assert rel.narrativa.model_dump() == {"texto": "Seu progresso está indo bem.", "origem": "LLM",
                                          "motivo_descarte": ""}
    assert (rel.progresso.concluidas, rel.progresso.etapas) == (1, 6)
    assert (rel.desempenho.geral.acertos, rel.desempenho.geral.respostas) == (9, 13)
    assert rel.desempenho.tendencia.direcao == "caindo"
    assert rel.engajamento.dias_inativo == 2 and rel.engajamento.inativo is False
    assert [p.competencia_id for p in rel.pontos_fracos] == ["repeticao"]
    prompt, kwargs = llm["prompts"][0]
    assert "DEMO-R02" not in prompt  # o LLM não recebe o código do aluno
    assert "69%" in prompt and "1 de 6 etapas" in prompt
    assert kwargs["temperatura"] == narrativa.RELATORIO_TEMPERATURA and kwargs["seed"] == narrativa.RELATORIO_SEED


def test_relatorio_funciona_completo_sem_llm(demo, llm):
    llm["resposta"] = TimeoutError("Ollama fora do ar")
    rel = gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    assert (rel.narrativa.texto, rel.narrativa.origem) == (narrativa.FALLBACK_ALUNO, "fallback")
    assert rel.desempenho.geral.respostas == 13 and rel.progresso.etapas == 6  # indicadores intactos
    turma = gerar_relatorio_turma(agora=AGORA)
    assert (turma.narrativa.texto, turma.narrativa.origem) == (narrativa.FALLBACK_TURMA, "fallback")
    assert turma.desempenho_por_competencia


def test_sem_narrativa_nao_chama_o_llm(demo, llm):
    rel = gerar_relatorio_aluno("DEMO-R02", agora=AGORA, com_narrativa=False)
    assert rel.narrativa.origem == "fallback" and llm["prompts"] == []


@pytest.mark.parametrize("texto, motivo", [
    ("Você acertou 87% das questões.", "número inventado: 87"),      # 87 não está nos indicadores
    ("Você concluiu 5 de 6 etapas.", "número inventado: 5"),         # (concluiu 1)
    ("Segundo as instruções abaixo, você vai bem.", "referência ao prompt"),
])
def test_guarda_descarta_numero_que_nao_esta_nos_indicadores(demo, llm, texto, motivo):
    llm["resposta"] = texto
    rel = gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    assert (rel.narrativa.texto, rel.narrativa.origem) == (narrativa.FALLBACK_ALUNO, "guarda")
    assert rel.narrativa.motivo_descarte.startswith(motivo)


def test_limite_conhecido_da_guarda_numero_existente_em_outro_contexto(demo, llm):
    # a guarda confere se o número EXISTE nos indicadores, não se está no lugar certo:
    # "2" aparece em "2 dias desde a última atividade", então passa (limite documentado)
    llm["resposta"] = "Você concluiu 2 de 6 etapas."
    assert gerar_relatorio_aluno("DEMO-R02", agora=AGORA).narrativa.origem == "LLM"


def test_guarda_aceita_numeros_dos_indicadores(demo, llm):
    llm["resposta"] = "Você concluiu 1 de 6 etapas e acertou 69% das 13 respostas, mas o acerto está caindo."
    assert gerar_relatorio_aluno("DEMO-R02", agora=AGORA).narrativa.origem == "LLM"


def test_relatorio_da_turma_so_agregado_sem_identificador(demo, llm):
    turma = gerar_relatorio_turma(agora=AGORA)
    assert (turma.suprimido, turma.alunos.valor, turma.min_grupo) == (False, 6, 5)
    texto_json = json.dumps(turma.model_dump(), ensure_ascii=False)
    assert all(aluno_id not in texto_json for aluno_id, *_ in ALUNOS_DEMO)
    assert all(aluno_id not in llm["prompts"][0][0] for aluno_id, *_ in ALUNOS_DEMO)
    grupos = {g.chave: g for g in turma.desempenho_por_competencia}
    assert grupos["repeticao"].suprimido is False and grupos["repeticao"].alunos.valor == 5
    assert grupos["funcoes"].suprimido is True and grupos["funcoes"].taxa is None
    assert {a.tipo for a in turma.alertas} == {"inatividade", "desempenho_em_queda"}


def test_perfil_com_poucos_alunos_e_suprimido_sem_chamar_llm(demo, llm):
    turma = gerar_relatorio_turma("intermediario", agora=AGORA)
    assert (turma.suprimido, turma.alunos.texto, turma.narrativa.texto) == (
        True, "menos de 5", narrativa.SUPRIMIDO_TURMA)
    assert turma.desempenho_por_competencia == [] and turma.qualidade_feedback is None
    assert llm["prompts"] == []


def test_logs_do_relatorio_sem_codigo_do_aluno(demo, llm, caplog):
    llm["resposta"] = TimeoutError("x")
    with caplog.at_level(logging.DEBUG):
        gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    assert caplog.records and "DEMO-R02" not in caplog.text


# --- auditoria (R11) ---

def linhas_auditoria(tipo: str) -> list:
    conexao = obter_conexao()
    linhas = conexao.execute("SELECT * FROM auditoria WHERE tipo = ? ORDER BY id", (tipo,)).fetchall()
    conexao.close()
    return linhas


def test_toda_geracao_de_relatorio_entra_na_auditoria(demo, llm):
    gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    gerar_relatorio_turma(agora=AGORA)
    gerar_relatorio_turma("intermediario", agora=AGORA)
    (aluno,) = linhas_auditoria("relatorio_aluno")
    assert (aluno["aluno_id"], aluno["origem"]) == ("DEMO-R02", "LLM")
    turma = linhas_auditoria("relatorio_turma")
    assert [(t["aluno_id"], t["referencia_id"], t["origem"]) for t in turma] == [
        (None, None, "LLM"), (None, "intermediario", "fallback")]
    tipos = [r["tipo"] for r in client.get("/auditoria/DEMO-R02").json()]
    assert "relatorio_aluno" in tipos


def test_gerar_relatorio_nao_conta_como_atividade_do_aluno(demo, llm):
    from tia.agentes.tutor.repositorio import ultima_interacao
    antes = ultima_interacao("DEMO-R03")
    gerar_relatorio_aluno("DEMO-R03")
    assert ultima_interacao("DEMO-R03") == antes


# --- rotas ---

def test_rota_relatorio_do_aluno(demo, llm):
    resposta = client.get("/relatorio/aluno/DEMO-R04")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo) >= {"aluno_id", "progresso", "desempenho", "engajamento", "pontos_fracos",
                          "qualidade_feedback", "narrativa", "provisorio"}
    assert corpo["provisorio"] is True and corpo["pontos_fracos"][0]["competencia_id"] == "repeticao"
    assert corpo["qualidade_feedback"]["vetados"] == 1


def test_rota_relatorio_do_aluno_erros(demo, llm):
    assert client.get("/relatorio/aluno/NAO-EXISTE").status_code == 404
    assert client.get("/relatorio/aluno/Maria Souza").status_code == 422


def test_rota_relatorio_da_turma_e_narrativa_false(demo, llm):
    corpo = client.get("/relatorio/turma", params={"narrativa": "false"}).json()
    assert corpo["suprimido"] is False and corpo["alunos"]["valor"] == 6
    assert corpo["narrativa"]["origem"] == "fallback" and llm["prompts"] == []
    perfil = client.get("/relatorio/turma", params={"perfil_id": "iniciante"}).json()
    assert perfil["suprimido"] is True and perfil["alunos"] == {"valor": None, "texto": "menos de 5"}


def test_versao_em_texto(demo, llm):
    rel = gerar_relatorio_aluno("DEMO-R02", agora=AGORA)
    texto = narrativa.formatar_texto_aluno(rel)
    assert "1 de 6 etapas concluídas (17%)" in texto and "Laços de repetição: 25% (1 de 4)" in texto
    assert "Tendência: caindo" in texto
    turma = narrativa.formatar_texto_turma(gerar_relatorio_turma(agora=AGORA))
    assert "funcoes: suprimido (alunos: menos de 5)" in turma and "DEMO-" not in turma
