"""
Testes do primeiro acesso (Agente 1): diagnóstico inicial (regras puras e
persistência), onboarding conversacional (regras e LLM mockado) e o percurso
completo pelas rotas até a matrícula, inclusive LGPD (exportação, eliminação e
retenção do cadastro abandonado e do objetivo) e o limite de mensagens e de
chamadas ao LLM. A autenticação dessas rotas está em tests/test_seguranca.py.

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
    # só o campo da pergunta da vez (trilha): as horas ditas junto são descartadas e perguntadas depois
    assert (resposta.origem, sessao.dados, resposta.proxima_pergunta) == ("LLM", {"trilha": "dev"}, "horas")

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


# --- LGPD e limite (ajustes de integração, 15/10/2026) ---

def _recuar_cadastro(aluno: str, dias: int):
    from tia.core.database import obter_conexao
    conexao = obter_conexao()
    with conexao:
        conexao.execute("UPDATE planejador_onboarding SET criado_em = strftime('%Y-%m-%dT%H:%M:%S', 'now', ?), "
                        "atualizado_em = strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) WHERE aluno_id = ?",
                        (f"-{dias} days", f"-{dias} days", aluno))
    conexao.close()


def test_retencao_apaga_cadastro_abandonado_e_o_objetivo_no_prazo_do_dialogo():
    from tia.core.config import RETENCAO_DIALOGO_DIAS
    from tia.seguranca import retencao
    # P-010: abandonou o cadastro no meio da conversa (texto livre no histórico)
    client.post("/aluno/P-010/onboarding/iniciar")
    client.post("/aluno/P-010/onboarding/mensagem", json={"texto": "quero dev, sou da turma B"})
    # P-011: concluiu, com objetivo em texto livre
    client.post("/aluno/P-011/onboarding/iniciar")
    for fala in ("dev", "3 horas por semana", "estágio numa empresa de software", "sim"):
        client.post("/aluno/P-011/onboarding/mensagem", json={"texto": fala})
    assert onboarding.ler("P-011").dados["objetivo"] == "estágio numa empresa de software"
    # dentro do prazo, nada muda
    retencao.executar(simular=False)
    assert onboarding.ler("P-010").historico and "objetivo" in onboarding.ler("P-011").dados
    for aluno in ("P-010", "P-011"):
        _recuar_cadastro(aluno, RETENCAO_DIALOGO_DIAS + 1)
    simulado = retencao.executar(simular=True)
    afetadas = {o.descricao: o.linhas for o in simulado.operacoes if o.tabela == "planejador_onboarding"}
    assert list(afetadas.values()) == [1, 1]
    assert onboarding.ler("P-010") is not None  # a simulação não altera nada
    retencao.executar(simular=False)
    assert onboarding.ler("P-010") is None
    concluido = onboarding.ler("P-011")
    assert concluido.concluido and "objetivo" not in concluido.dados and concluido.dados["trilha"] == "dev"
    # idempotente: rodar de novo não acha mais nada
    assert all(o.linhas == 0 for o in retencao.executar(simular=True).operacoes if o.tabela == "planejador_onboarding")


def test_limite_de_mensagens_e_de_chamadas_ao_llm(monkeypatch):
    import tia.core.config as config
    monkeypatch.setattr(config, "ONBOARDING_MAX_MENSAGENS", 3)
    monkeypatch.setattr(onboarding, "ONBOARDING_USA_LLM", True)
    chamadas = []

    def llm(prompt, **kwargs):
        chamadas.append(1)
        return "{}"  # nada extraído: a pergunta se repete

    monkeypatch.setattr(onboarding, "chamar_llm", llm)
    client.post("/aluno/P-012/onboarding/iniciar")
    for _ in range(3):
        assert client.post("/aluno/P-012/onboarding/mensagem", json={"texto": "hum"}).status_code == 200
    excedeu = client.post("/aluno/P-012/onboarding/mensagem", json={"texto": "hum"})
    assert excedeu.status_code == 409 and "Limite de 3 mensagens" in excedeu.json()["detail"]
    assert len(chamadas) == 3
    # recomeçar libera novas mensagens, mas o LLM já gastou a cota deste aluno: segue por regras
    client.post("/aluno/P-012/onboarding/iniciar")
    resposta = client.post("/aluno/P-012/onboarding/mensagem", json={"texto": "dev"}).json()
    assert resposta["origem"] == "regras" and resposta["dados"]["trilha"] == "dev"
    assert len(chamadas) == 3


# --- correção de 01/11/2026: o LLM só sugere; o código ancora no texto e decide ---
# (docs/relatorios/correcao_onboarding.md). LLMs simulados com os defeitos vistos no qwen3:1.7b.

TUDO_DE_UMA_VEZ = ('{"trilha": "defesa_cibernetica", "horas_semana": 10, "dias_disponiveis": ["seg", "ter", "qua", '
                   '"qui", "sex", "sab"], "objetivo": "aprender sobre segurança e redes", "confirmou": true}')


def llm_simulado(monkeypatch, resposta: str) -> list[str]:
    """Liga o LLM do onboarding com uma resposta fixa; devolve a lista dos prompts recebidos."""
    prompts = []

    def llm(prompt, **kwargs):
        prompts.append(prompt)
        return resposta
    monkeypatch.setattr(onboarding, "ONBOARDING_USA_LLM", True)
    monkeypatch.setattr(onboarding, "chamar_llm", llm)
    return prompts


def falar(sessao, fala):
    return onboarding.processar(sessao, fala)


def test_llm_que_devolve_todos_os_campos_de_uma_vez_nao_grava_nada_alem_da_pergunta(monkeypatch):
    """(a) O caso do teste funcional: "não sei" virava trilha, horas, dias e objetivo inventados."""
    prompts = llm_simulado(monkeypatch, TUDO_DE_UMA_VEZ)
    sessao, _ = onboarding.nova_sessao("O-101")
    r = falar(sessao, "ainda não sei, qual a diferença entre as duas?")
    assert sessao.dados == {} and (r.proxima_pergunta, r.resposta) == ("trilha", onboarding.EXPLICACAO_TRILHAS)
    r = falar(sessao, "vou de desenvolvimento de software")
    assert sessao.dados == {"trilha": "dev"} and r.proxima_pergunta == "horas"  # o LLM disse cyber: descartado
    r = falar(sessao, "umas 2h por dia, menos no fim de semana")
    assert sessao.dados == {"trilha": "dev", "horas_semana": 10.0, "dias_disponiveis": ["seg", "ter", "qua", "qui", "sex"]}
    r = falar(sessao, "quero conseguir um estágio")
    # dias e objetivo são do código: o "sab" e o objetivo do LLM não entram
    assert sessao.dados["dias_disponiveis"] == ["seg", "ter", "qua", "qui", "sex"]
    assert sessao.dados["objetivo"] == "quero conseguir um estágio" and r.proxima_pergunta == "confirmacao"
    assert not r.concluido  # o "confirmou": true do LLM não confirma nada
    assert falar(sessao, "sim").concluido
    # o LLM só é consultado nas perguntas de trilha e de horas, e só sobre o campo da vez
    assert len(prompts) == 3 and all("objetivo" not in p for p in prompts)


def test_llm_com_a_trilha_errada_nao_troca_a_escolha_do_aluno(monkeypatch):
    """(b) O LLM devolve a outra trilha: vale o que o aluno escreveu. Pelas rotas, até a matrícula em Dev."""
    llm_simulado(monkeypatch, '{"trilha": "defesa_cibernetica", "duvida_trilha": false}')
    sessao, _ = onboarding.nova_sessao("O-102")
    r = falar(sessao, "quero dev")
    assert (sessao.dados, r.origem) == ({"trilha": "dev"}, "regras")
    sessao, _ = onboarding.nova_sessao("O-103")
    assert falar(sessao, "não quero segurança, prefiro programar").proxima_pergunta == "horas"
    assert sessao.dados == {"trilha": "dev"}  # "não quero segurança" não conta como escolha
    # citou as duas: o LLM desempata, porque a escolha dele está ancorada no texto
    sessao, _ = onboarding.nova_sessao("O-104")
    assert (falar(sessao, "programação de software para segurança").origem, sessao.dados) == (
        "LLM", {"trilha": "defesa_cibernetica"})
    percorrer("P-101", "quero a trilha de desenvolvimento", acertar_base=True)
    trilha = client.post("/aluno/P-101/primeiro-acesso/concluir").json()["trilha"]
    assert trilha["trilha"] == "dev"


def test_llm_que_copia_o_exemplo_do_prompt_nao_inventa_horas(monkeypatch):
    """(c) O LLM devolve as 10 h do exemplo para uma resposta sem número: nada gravado, pergunta de novo.
    Com número no texto que as regras não entendem, a sugestão ancorada é aceita."""
    llm_simulado(monkeypatch, '{"horas_semana": 10}')
    sessao, _ = onboarding.nova_sessao("O-105")
    falar(sessao, "dev")
    r = falar(sessao, "ainda não sei, depende da semana")
    assert "horas_semana" not in sessao.dados and (r.proxima_pergunta, r.resposta) == ("horas", onboarding.HORAS_DE_NOVO)
    r = falar(sessao, "duas horinhas nos dias de semana")  # 2 x 5 dias = 10: ancorado
    assert (r.origem, sessao.dados["horas_semana"], sessao.dados["dias_disponiveis"]) == (
        "LLM", 10.0, ["seg", "ter", "qua", "qui", "sex"])
    assert onboarding.horas_ancoradas(10, "3 horas por semana") is False
    assert onboarding.horas_ancoradas(10, "2 horas por dia de segunda a sexta") is True


def test_llm_com_texto_vazio_segue_pelas_regras(monkeypatch):
    """(d) Resposta vazia (sem JSON): regras, do começo ao fim."""
    llm_simulado(monkeypatch, "")
    sessao, _ = onboarding.nova_sessao("O-106")
    respostas = [falar(sessao, f) for f in ("dev", "3 horas por semana", "pular", "sim")]
    assert respostas[-1].concluido and {r.origem for r in respostas} == {"regras"}
    assert sessao.dados == {"trilha": "dev", "horas_semana": 3.0, "objetivo": ""}


def test_confirmacao_exige_sim_explicito_e_nao_volta_as_perguntas():
    sessao, r = conversar(["dev", "3 horas por semana", "pular"])
    assert r.proxima_pergunta == "confirmacao"
    for vago in ("hmm", "sim, não precisa mudar"):  # sem resposta clara, nada de matrícula
        r = onboarding.processar(sessao, vago, usar_llm=False)
        assert not r.concluido and r.resposta.startswith(onboarding.CONFIRMACAO_DE_NOVO)
    r = onboarding.processar(sessao, "não", usar_llm=False)
    assert (sessao.dados, r.proxima_pergunta, r.concluido) == ({}, "trilha", False)
    assert r.resposta.startswith(onboarding.REFAZER)
    for fala in ("segurança", "4", "pular"):
        r = onboarding.processar(sessao, fala, usar_llm=False)
    assert r.proxima_pergunta == "confirmacao"  # o objetivo é perguntado de novo
    assert onboarding.processar(sessao, "sim", usar_llm=False).concluido
    assert sessao.dados == {"trilha": "defesa_cibernetica", "horas_semana": 4.0, "objetivo": ""}


def test_rotas_nao_matriculam_sem_o_sim():
    aluno = "P-102"
    client.post(f"/aluno/{aluno}/onboarding/iniciar")
    for fala in ("dev", "3 horas por semana", "pular", "talvez"):
        corpo = client.post(f"/aluno/{aluno}/onboarding/mensagem", json={"texto": fala}).json()
    assert corpo["concluido"] is False and corpo["proxima_pergunta"] == "confirmacao"
    assert client.post(f"/aluno/{aluno}/diagnostico/iniciar").status_code == 409
    recusa = client.post(f"/aluno/{aluno}/primeiro-acesso/concluir")
    assert recusa.status_code == 409 and '"sim"' in recusa.json()["detail"]


def test_onboarding_sem_llm_do_comeco_ao_fim(monkeypatch):
    """ONBOARDING_USA_LLM=0: o LLM nunca é chamado, e o percurso vai até a matrícula em Dev."""
    def proibido(*args, **kwargs):
        raise AssertionError("o LLM não pode ser chamado com ONBOARDING_USA_LLM=0")
    monkeypatch.setattr(onboarding, "ONBOARDING_USA_LLM", False)
    monkeypatch.setattr(onboarding, "chamar_llm", proibido)
    aluno = "P-103"
    client.post(f"/aluno/{aluno}/onboarding/iniciar")
    for fala in ("não sei, qual a diferença?", "desenvolvimento", "umas 2h por dia, menos no fim de semana",
                 "estágio em backend", "sim"):
        corpo = client.post(f"/aluno/{aluno}/onboarding/mensagem", json={"texto": fala}).json()
        assert corpo["origem"] == "regras"
    assert corpo["concluido"] and corpo["dados"]["trilha"] == "dev" and corpo["dados"]["horas_semana"] == 10.0
    situacao = client.post(f"/aluno/{aluno}/diagnostico/iniciar").json()
    while not situacao["concluido"]:
        p = situacao["pergunta"]
        situacao = client.post(f"/aluno/{aluno}/diagnostico/responder",
                               json={"item_id": p["item_id"], "indice_escolhido": GABARITO[p["item_id"]]}).json()
    assert client.post(f"/aluno/{aluno}/primeiro-acesso/concluir").json()["trilha"]["trilha"] == "dev"


def test_limite_de_mensagens_vale_tambem_depois_do_nao(monkeypatch):
    import tia.core.config as config
    monkeypatch.setattr(config, "ONBOARDING_MAX_MENSAGENS", 5)
    sessao, _ = conversar(["dev", "3", "pular", "não"])  # o "não" volta ao começo, mas a conta continua
    onboarding.processar(sessao, "dev", usar_llm=False)
    with pytest.raises(onboarding.ErroOnboarding, match="Limite de 5 mensagens"):
        onboarding.processar(sessao, "3", usar_llm=False)


# --- justificativas do Planejador: cópia do prompt não vale como texto do LLM ---

def matricular_com_justificativas(monkeypatch, aluno: str, resposta_llm) -> dict:
    monkeypatch.setattr(justificar, "chamar_llm", resposta_llm)
    percorrer(aluno, "desenvolvimento", acertar_base=False)
    return client.post(f"/aluno/{aluno}/primeiro-acesso/concluir").json()


def test_justificativa_que_copia_o_prompt_cai_no_texto_padrao(monkeypatch):
    def ecoa(prompt, **kwargs):  # o que o qwen3:1.7b fez: repetiu o detalhe de cada linha do prompt
        linhas = [l for l in prompt.splitlines() if l[:1].isdigit()]
        return "\n".join(f"{l.split('. ', 1)[0]}. {l[l.index(' ('):].strip()}" for l in linhas)
    corpo = matricular_com_justificativas(monkeypatch, "P-104", ecoa)
    etapas = corpo["trilha"]["etapas"]
    assert {e["origem_justificativa"] for e in etapas} == {"fallback"}
    assert not any("nota no diagnóstico" in e["justificativa"] and e["justificativa"].startswith("(")
                   for e in etapas)
    assert corpo["trilha"]["falha_llm"] == "copia_do_prompt"
    assert corpo["decisao"]["origem_justificativas"] == "fallback"


def test_justificativa_genuina_continua_como_llm_e_copias_parciais_saem(monkeypatch):
    def misto(prompt, **kwargs):
        n = sum(1 for l in prompt.splitlines() if l[:1].isdigit())
        frases = ["Base para entender como os programas guardam e mudam valores."] * n
        frases[1] = "frase"  # o exemplo do formato
        frases[2] = "escreva UMA frase curta dizendo ao aluno por que estudar aquilo naquele momento"
        return "\n".join(f"{i}. {f}" for i, f in enumerate(frases, 1))
    corpo = matricular_com_justificativas(monkeypatch, "P-105", misto)
    origens = [e["origem_justificativa"] for e in corpo["trilha"]["etapas"]]
    assert origens[0] == "LLM" and origens[1:3] == ["fallback", "fallback"] and origens[3] == "LLM"
    assert corpo["decisao"]["origem_justificativas"] == "parcial"
    from tia.agentes.planejador.justificar import copia_do_prompt
    prompt = "1. Funções e modularização (nota no diagnóstico: 0.33; 1.5 h)"
    assert copia_do_prompt("Funções e modularização", prompt, "Funções e modularização")
    assert not copia_do_prompt("Funções organizam o código em partes reutilizáveis.", prompt)
