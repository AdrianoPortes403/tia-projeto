"""
Testes do Agente 1 (Planejador) com a base pedagógica alinhada à EAP:
trilhas (base comum + dev/defesa_cibernetica), enquadramento automático do
perfil pelo diagnóstico (1.2.3), dominados, revisões, desafios, nível
inicial, prazo e escopo do piloto, persistência e matrícula no orquestrador.

Como rodar:
    ./run_tests.sh tests/test_planejador_eap.py
"""

import pytest
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
from tia.agentes.planejador import planejar_e_salvar
from tia.agentes.planejador.modelos import EntradaPlanejador
from tia.agentes.planejador.planejar import CompetenciaInexistente, carregar_ementa, gerar_trilha
from tia.agentes.planejador.repositorio import ler_trilha
from tia.api.main import app
from tia.orquestrador import repositorio as repo_orquestrador

client = TestClient(app)
BASE = ["variaveis_tipos", "condicionais", "repeticao", "funcoes", "listas_strings", "recursao"]
BASE_DOMINADA = {c: 1.0 for c in BASE}


@pytest.fixture(autouse=True)
def llm_falso(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm", lambda prompt, **kwargs: "")


def entrada(**campos) -> EntradaPlanejador:
    dados = {"aluno_id": "E-001", "horas_semanais": 6}
    dados.update(campos)
    return EntradaPlanejador(**dados)


def ids(trilha) -> list[str]:
    return [e.competencia_id for e in trilha.etapas if not e.concluida]


def test_trilha_traz_base_comum_mais_a_trilha_escolhida():
    ementa = carregar_ementa()
    dev = ids(gerar_trilha(entrada(trilha="dev")))
    cib = ids(gerar_trilha(entrada(trilha="defesa_cibernetica")))
    so_base = ids(gerar_trilha(entrada()))
    assert so_base == BASE
    assert set(dev) == set(BASE) | {c["id"] for c in ementa if c["trilha"] == "dev"}
    assert set(cib) == set(BASE) | {c["id"] for c in ementa if c["trilha"] == "defesa_cibernetica"}
    # pré-requisitos ligando a trilha à base comum: repeticao antes de dev_01
    assert dev.index("repeticao") < dev.index("dev_01")
    assert cib.index("funcoes") < cib.index("cib_13")


def test_enquadramento_pelo_diagnostico():
    sem = gerar_trilha(entrada(trilha="dev"))
    assert (sem.perfil_id, sem.pontuacao_enquadramento, sem.perfil_automatico) == ("iniciante", None, True)
    # base dominada (6 x 3) e etapa 1 no nível 1 (2 x 0): P = 18/8 = 2,25 -> intermediário
    forte = gerar_trilha(entrada(trilha="dev", diagnostico={**BASE_DOMINADA, "dev_01": 0.0, "dev_02": 0.0}))
    assert (forte.perfil_id, forte.pontuacao_enquadramento) == ("intermediario", 2.25)
    # P exatamente 1,5 é intermediário; abaixo, iniciante
    limiar = gerar_trilha(entrada(trilha="dev", diagnostico={"dev_01": 1.0, "dev_02": 0.0}))
    assert (limiar.perfil_id, limiar.pontuacao_enquadramento) == ("intermediario", 1.5)
    fraco = gerar_trilha(entrada(trilha="dev", diagnostico={"dev_01": 2 / 3, "dev_02": 0.0}))
    assert (fraco.perfil_id, fraco.pontuacao_enquadramento) == ("iniciante", 1.0)
    # perfil informado é respeitado (compatibilidade)
    fixo = gerar_trilha(entrada(trilha="dev", perfil_id="intermediario"))
    assert (fixo.perfil_id, fixo.perfil_automatico, fixo.pontuacao_enquadramento) == ("intermediario", False, None)


def test_dominado_sai_e_nivel_inicial_vem_do_diagnostico():
    trilha = gerar_trilha(entrada(trilha="dev", diagnostico={
        "variaveis_tipos": 1.0, "condicionais": 2 / 3, "repeticao": 1 / 3, "funcoes": 0.0}))
    assert "variaveis_tipos" not in ids(trilha)
    nivel = {e.competencia_id: e.nivel_inicial for e in trilha.etapas}
    assert (nivel["condicionais"], nivel["repeticao"], nivel["funcoes"]) == (3, 2, 1)
    # P = 3 x (1 + 2/3 + 1/3 + 0) / 4 = 1,5 -> intermediário: não diagnosticado começa no nível 2
    assert (trilha.perfil_id, nivel["recursao"]) == ("intermediario", 2)
    inter = gerar_trilha(entrada(trilha="dev", perfil_id="intermediario"))
    assert {e.nivel_inicial for e in inter.etapas} == {2}  # nada diagnosticado: padrão do intermediário


def test_iniciante_revisa_pre_requisitos_e_intermediario_recebe_desafios():
    ini = gerar_trilha(entrada(trilha="dev", perfil_id="iniciante"))
    por_id = {e.competencia_id: e for e in ini.etapas}
    assert por_id["funcoes"].revisar_antes == ["repeticao"]  # funcoes é "medio"
    assert por_id["condicionais"].revisar_antes == []          # condicionais é "facil"
    assert not any(e.desafio_pratico for e in ini.etapas)
    inter = gerar_trilha(entrada(trilha="dev", perfil_id="intermediario"))
    assert not any(e.revisar_antes for e in inter.etapas)
    com_desafio = [e.competencia_id for e in inter.etapas if e.desafio_pratico]
    assert "dev_07" in com_desafio  # último tópico da etapa 1 da trilha dev
    assert len(com_desafio) == 6     # um por etapa da trilha (a base comum não tem desafio)


def test_prazo_e_escopo_do_piloto():
    piloto = gerar_trilha(entrada(trilha="dev", horas_semanais=3, prazo_dias=8, escopo="piloto",
                                  diagnostico={"dev_01": 0.0, "dev_02": 0.0}))
    assert ids(piloto) == ["dev_01", "dev_02"]
    assert piloto.cabe_no_prazo is True and piloto.opcoes_prazo is None
    assert any("repeticao" in a for a in piloto.avisos)  # pré-requisito fora do escopo e não dominado
    sem_aviso = gerar_trilha(entrada(trilha="dev", horas_semanais=3, prazo_dias=8, escopo="piloto",
                                     diagnostico={**BASE_DOMINADA, "dev_01": 0.0}))
    assert sem_aviso.avisos == []
    longa = gerar_trilha(entrada(trilha="dev", horas_semanais=3, prazo_dias=14))
    assert longa.cabe_no_prazo is False
    assert longa.opcoes_prazo.horas_semanais_necessarias > 3
    # 3 h/semana x 2 semanas = 6 h: cabe só variaveis_tipos (6 h)
    assert longa.opcoes_prazo.recorte_que_cabe == ["variaveis_tipos"]


def test_diagnostico_de_outra_trilha_e_recusado():
    with pytest.raises(CompetenciaInexistente, match="cib_01"):
        gerar_trilha(entrada(trilha="dev", diagnostico={"cib_01": 1.0}))


def test_campos_novos_sao_gravados_e_lidos_iguais():
    trilha = planejar_e_salvar(entrada(trilha="defesa_cibernetica", horas_semanais=3, prazo_dias=14,
                                       diagnostico={"variaveis_tipos": 1.0, "cib_01": 1 / 3}))
    lida = ler_trilha("E-001")
    assert lida.model_dump(exclude={"falha_llm"}) == trilha.model_dump(exclude={"falha_llm"})
    assert lida.trilha == "defesa_cibernetica" and lida.cabe_no_prazo is False and lida.opcoes_prazo


def test_matricula_sem_perfil_grava_o_perfil_enquadrado():
    resposta = client.post("/aluno/M-001/iniciar", json={
        "trilha": "dev", "horas_semanais": 3, "prazo_dias": 8, "escopo": "piloto",
        "diagnostico": {**BASE_DOMINADA, "dev_01": 0.0, "dev_02": 0.0}})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["trilha"]["perfil_id"] == "intermediario"
    assert [e["competencia_id"] for e in corpo["trilha"]["etapas"]] == ["dev_01", "dev_02"]
    assert "enquadrado pelo diagnóstico (P = 2.25)" in corpo["decisao"]["motivo"]
    matricula = repo_orquestrador.ler_matricula("M-001")
    assert (matricula["perfil_id"], matricula["trilha"], matricula["prazo_dias"], matricula["escopo"]) == \
        ("intermediario", "dev", 8, "piloto")
    estado = client.get("/aluno/M-001/estado").json()
    assert (estado["trilha"], estado["prazo_dias"], estado["escopo"]) == ("dev", 8, "piloto")
    assert estado["competencia_atual"] == "dev_01"
