"""
Testes do Agente 2 (Tutor), parte 2b: diálogo livre com RAG, auditoria
(R11), veto docente (R12) e incentivo por inatividade. llm_client e
retrieve mockados; banco temporário (conftest).

Como rodar:
    ./run_tests.sh tests/test_dialogo.py
"""

import json
import logging
from datetime import datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

import tia.agentes.tutor.dialogo as dialogo
from tia.agentes.planejador.modelos import EtapaTrilha, Trilha
from tia.agentes.planejador.repositorio import salvar_trilha
from tia.agentes.tutor import incentivo
from tia.api.main import app
from tia.core.database import obter_conexao

client = TestClient(app)

ALUNO = "A2026-011"
TRECHO = {"texto": "No for ou no while, o break interrompe o laço imediatamente; o continue pula para a "
                   "próxima repetição.", "fonte": "repeticao.txt", "indice": 2, "distancia": 210.0}
PERGUNTA = "Para que serve o break dentro de um for?"
DO_MATERIAL = "Do material: " + TRECHO["texto"]


@pytest.fixture(autouse=True)
def sem_indice_real(monkeypatch):
    """Termos genéricos sem ler o Chroma de verdade (cada teste define os seus)."""
    monkeypatch.setattr(dialogo, "termos_genericos", lambda: frozenset())
    monkeypatch.setattr(dialogo, "textos_do_indice", lambda: ())


def mockar(monkeypatch, trechos: list[dict], resposta_llm="O break encerra o laço na hora."):
    """Substitui retrieve e LLM; devolve as listas de chamadas de cada um."""
    buscas, prompts = [], []

    def buscar_falso(consulta, k=3, fontes=None):
        buscas.append((consulta, fontes))
        return trechos

    def llm_falso(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        if isinstance(resposta_llm, Exception):
            raise resposta_llm
        return resposta_llm

    monkeypatch.setattr(dialogo, "buscar_contexto", buscar_falso)
    monkeypatch.setattr(dialogo, "chamar_llm", llm_falso)
    return buscas, prompts


def perguntar(pergunta: str = PERGUNTA, competencia_id: str | None = None, aluno_id: str = ALUNO):
    corpo = {"aluno_id": aluno_id, "pergunta": pergunta}
    if competencia_id is not None:
        corpo["competencia_id"] = competencia_id
    return client.post("/tutor/perguntar", json=corpo)


def linhas_dialogo() -> list:
    conexao = obter_conexao()
    linhas = conexao.execute("SELECT * FROM tutor_dialogo ORDER BY id").fetchall()
    conexao.close()
    return linhas


# --- diálogo livre ---

def test_pergunta_com_trecho_responde_com_fonte_dos_metadados_e_grava(monkeypatch):
    buscas, prompts = mockar(monkeypatch, [TRECHO], "<think></think>O break encerra o laço na hora. "
                                                    "Fonte: inventada.txt")
    resposta = perguntar(competencia_id="repeticao")
    assert resposta.status_code == 200
    r = resposta.json()
    assert r["origem"] == "LLM" and r["fontes"] == ["repeticao.txt"]
    assert r["resposta"] == "O break encerra o laço na hora."  # frase sem ponto final descartada
    assert buscas[0][1] == ["repeticao.txt"]  # busca restrita à competência

    prompt, kwargs = prompts[0]
    assert TRECHO["texto"] in prompt and PERGUNTA in prompt and ALUNO not in prompt
    assert "Use APENAS as informações do APOIO" in prompt and dialogo.SINAL_SEM_RESPOSTA in prompt
    assert dialogo.REGRAS_ANCORADAS in prompt  # mesmas regras do prompt ancorado do feedback
    assert (kwargs["temperatura"], kwargs["seed"]) == (dialogo.TUTOR_TEMPERATURA, dialogo.TUTOR_SEED)

    (linha,) = linhas_dialogo()
    assert (linha["aluno_id"], linha["pergunta"], linha["resposta"], linha["origem"]) == (
        ALUNO, PERGUNTA, r["resposta"], "LLM")
    assert json.loads(linha["fontes"]) == ["repeticao.txt"]
    assert (linha["vetada"], linha["correcao_docente"]) == (0, None) and linha["ts"]
    assert r["dialogo_id"] == linha["id"]


def test_sem_competencia_busca_em_todo_o_material(monkeypatch):
    buscas, _ = mockar(monkeypatch, [TRECHO])
    assert perguntar().json()["origem"] == "LLM"
    assert buscas[0][1] is None


@pytest.mark.parametrize("trechos", [
    [],                                          # nada indexado
    [{**TRECHO, "distancia": 999.0}],            # distante demais
])
def test_pergunta_sem_trecho_resposta_fixa_sem_chamar_llm(monkeypatch, trechos):
    _, prompts = mockar(monkeypatch, trechos)
    r = perguntar("Como conecto o Python a um banco de dados?").json()
    assert r["resposta"] == "Não encontrei isso no material disponível; vale perguntar ao professor."
    assert (r["fontes"], r["origem"]) == ([], "fallback")
    assert prompts == []  # não chamou o LLM
    assert linhas_dialogo()[0]["origem"] == "fallback"


def test_trecho_de_outra_competencia_e_ignorado(monkeypatch):
    _, prompts = mockar(monkeypatch, [{**TRECHO, "fonte": "funcoes.txt"}])
    r = perguntar(competencia_id="repeticao").json()
    assert (r["origem"], r["fontes"]) == ("fallback", []) and prompts == []


def test_llm_diz_que_material_nao_cobre_vira_resposta_fixa(monkeypatch):
    mockar(monkeypatch, [TRECHO], "SEM_RESPOSTA")
    r = perguntar().json()
    assert (r["resposta"], r["fontes"], r["origem"]) == (dialogo.MENSAGEM_SEM_MATERIAL, [], "fallback")


@pytest.mark.parametrize("resposta_llm", [requests.Timeout("demorou"), "<think>só pensou</think>"])
def test_llm_falho_ou_vazio_resposta_fixa_sem_fonte(monkeypatch, resposta_llm):
    mockar(monkeypatch, [TRECHO], resposta_llm)
    r = perguntar().json()
    assert (r["resposta"], r["fontes"], r["origem"]) == (dialogo.MENSAGEM_SEM_RESPOSTA, [], "fallback")
    assert r["falha_llm"] == ("timeout" if isinstance(resposta_llm, Exception) else None)


@pytest.mark.parametrize("resposta_llm, motivo", [
    ("O laço para depois de 7 voltas.", "número inventado: 7"),
    ("Segundo o material, o break encerra o laço.", "referência ao prompt"),
    ("O \"break\" é incorreto aqui, mas o \"break\" funciona corretamente.", "contradição interna"),
])
def test_guarda_aplicada_no_dialogo_devolve_trecho_transcrito(monkeypatch, resposta_llm, motivo):
    mockar(monkeypatch, [TRECHO], resposta_llm)
    resultado = dialogo.gerar_resposta(PERGUNTA, None)
    assert (resultado.resposta, resultado.fontes, resultado.origem) == (
        DO_MATERIAL, ["repeticao.txt"], "guarda")
    assert motivo in resultado.motivo_descarte
    r = perguntar().json()
    assert (r["resposta"], r["fontes"], r["origem"]) == (DO_MATERIAL, ["repeticao.txt"], "guarda")


@pytest.mark.parametrize("texto, esperado", [
    ("nício ou o fim da lista. Listas são mutáveis. Strings não po", "Listas são mutáveis."),
    ("O for percorre a lista.\n  O while repete.", "O for percorre a lista. O while repete."),
    ("Começo sem fim", "Começo sem fim"),       # nenhuma frase inteira: vai tudo
])
def test_trecho_transcrito_so_com_frases_inteiras(texto, esperado):
    assert dialogo.frases_inteiras(texto) == esperado


def test_guarda_transcreve_o_trecho_mais_relevante(monkeypatch):
    longe = {"texto": "O while repete\n  enquanto a condição for verdadeira.", "fonte": "a.txt", "indice": 0,
             "distancia": 300.0}
    perto = {"texto": "O break   interrompe o for\nna hora.", "fonte": "b.txt", "indice": 5, "distancia": 150.0}
    mockar(monkeypatch, [longe, perto], "O break usa `sys.exit()` para sair.")
    resultado = dialogo.gerar_resposta(PERGUNTA, None, [])
    # menor distância, espaços normalizados, só a fonte dele, sem segunda chamada ao LLM
    assert (resultado.resposta, resultado.fontes) == ("Do material: O break interrompe o for na hora.", ["b.txt"])


@pytest.mark.parametrize("resposta_llm, nome", [
    ("Use `psycopg2.connect()` para abrir a conexão.", "psycopg2"),
    ("Chame requests.get(url) e leia o resultado.", "requests"),
    ("Depois use cursor.execute(sql) no laço.", "cursor"),
    ("O `break` chama `encerrar_laco()` por baixo.", "encerrar_laco"),
    ("Instale a biblioteca psycopg2 antes.", "psycopg2"),
])
def test_guarda_descarta_identificador_fora_do_material(monkeypatch, resposta_llm, nome):
    mockar(monkeypatch, [TRECHO], resposta_llm)
    resultado = dialogo.gerar_resposta(PERGUNTA, None, [])
    assert resultado.origem == "guarda" and resultado.resposta == DO_MATERIAL
    assert resultado.motivo_descarte == f"identificador fora do material: {nome}"


@pytest.mark.parametrize("resposta", [
    "O `break` interrompe o `for` na hora.",                 # nomes que estão no trecho
    "Num `for i in range(5)`, o break para o laço.",        # palavra reservada e nome de uma letra
    "O `print(\"fim\")` não roda depois do break.",         # literal entre aspas não conta
    "O break interrompe o laço, por exemplo no for.",        # prosa sem código
    "Em range(5), o break para o for antes do fim.",         # range está na pergunta
])
def test_guarda_de_identificadores_aceita_nomes_do_contexto(resposta):
    contexto = ["Para que serve o break em range(5)?", TRECHO["texto"] + " Exemplo: print(x)."]
    assert dialogo.identificador_inventado(resposta, contexto) is None


def test_guarda_aceita_numero_que_veio_da_pergunta(monkeypatch):
    mockar(monkeypatch, [TRECHO], "Com break, o for de range(10) para antes de chegar ao 10.")
    assert dialogo.gerar_resposta("O break para um for de range(10)?", None).origem == "LLM"


def test_pergunta_limitada_a_500_caracteres(monkeypatch):
    _, prompts = mockar(monkeypatch, [TRECHO])
    longa = PERGUNTA + " break" * 100  # coberta pelo trecho, para chegar ao LLM
    assert perguntar(longa[:500]).status_code == 200
    assert perguntar(longa[:501]).status_code == 422
    assert perguntar("   ").status_code == 422  # vazia depois de tirar espaços
    assert len(prompts) == 1 and len(linhas_dialogo()) == 1  # recusadas não chegam ao LLM nem ao banco


def test_validacoes_do_dialogo(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    assert perguntar(aluno_id="Maria Souza").status_code == 422  # nome no lugar do código (R08)
    resposta = perguntar(competencia_id="astrologia")
    assert resposta.status_code == 422 and "astrologia" in resposta.json()["detail"]


def test_texto_livre_do_aluno_nunca_vai_para_log(monkeypatch, caplog):
    segredo = "minha senha é 1234 e moro na rua X"
    for trechos, resposta_llm in ([[TRECHO], requests.Timeout("x")],   # falha do LLM
                                  [[TRECHO], f"Você disse: {segredo}."],  # LLM ecoando a pergunta
                                  [[], "nunca"]):                       # sem trecho
        mockar(monkeypatch, trechos, resposta_llm)
        with caplog.at_level(logging.DEBUG):
            perguntar(segredo)
    assert caplog.records
    assert "1234" not in caplog.text and "rua X" not in caplog.text and ALUNO not in caplog.text


# --- auditoria (R11) ---

def auditoria(aluno_id: str = ALUNO) -> list[dict]:
    resposta = client.get(f"/auditoria/{aluno_id}")
    assert resposta.status_code == 200
    return resposta.json()


def test_auditoria_do_dialogo_sem_texto_livre(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    dialogo_id = perguntar().json()["dialogo_id"]
    mockar(monkeypatch, [])
    perguntar("Pergunta fora do material?")

    registros = auditoria()
    assert [(r["tipo"], r["referencia_id"], r["origem"], r["fontes"]) for r in registros] == [
        ("dialogo", str(dialogo_id), "LLM", ["repeticao.txt"]),
        ("dialogo", str(dialogo_id + 1), "fallback", []),
    ]
    assert all(r["ts"] for r in registros)
    assert PERGUNTA not in json.dumps(registros, ensure_ascii=False)  # sem texto livre
    assert auditoria("B2026-999") == []  # outro aluno não vê nada


def test_auditoria_da_resposta_de_item(monkeypatch):
    import tia.agentes.tutor.feedback as feedback
    from tia.agentes.tutor.repositorio import carregar_itens

    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [TRECHO])
    monkeypatch.setattr(feedback, "chamar_llm", lambda prompt, **kwargs: "O laço termina antes do fim.")
    sessao = client.post("/tutor/sessao", json={"aluno_id": ALUNO, "competencia_id": "repeticao"}).json()
    item = next(i for i in carregar_itens() if i["id"] == sessao["pergunta"]["item_id"])
    client.post("/tutor/resposta", json={"sessao_id": sessao["sessao_id"], "aluno_id": ALUNO,
                                         "item_id": item["id"], "indice_escolhido": item["indice_correto"]})

    (registro,) = auditoria()
    conexao = obter_conexao()
    historico_id = conexao.execute("SELECT id FROM historico_respostas").fetchone()["id"]
    conexao.close()
    assert (registro["tipo"], registro["referencia_id"], registro["origem"], registro["fontes"]) == (
        "resposta_item", str(historico_id), "LLM", ["repeticao.txt"])


def test_auditoria_valida_codigo_do_aluno():
    assert client.get("/auditoria/Maria Souza").status_code == 422


# --- veto docente (R12) ---

def historico(aluno_id: str = ALUNO) -> list[dict]:
    resposta = client.get(f"/alunos/{aluno_id}/dialogo")
    assert resposta.status_code == 200
    return resposta.json()


def vetar(dialogo_id: int, **corpo):
    return client.patch(f"/tutor/dialogo/{dialogo_id}/veto", json=corpo)


def test_veto_substitui_a_resposta_no_historico_sem_apagar_a_original(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    vetado = perguntar().json()["dialogo_id"]
    mantido = perguntar("E o continue?").json()["dialogo_id"]
    correcao = "O break encerra o laço; o continue só pula para a próxima repetição."

    resposta = vetar(vetado, vetada=True, correcao_docente=correcao)
    assert resposta.status_code == 200
    assert (resposta.json()["resposta"], resposta.json()["origem"]) == (correcao, "docente")

    h = {d["dialogo_id"]: d for d in historico()}
    assert (h[vetado]["resposta"], h[vetado]["fontes"], h[vetado]["origem"], h[vetado]["vetada"]) == (
        correcao, [], "docente", True)
    assert h[vetado]["pergunta"] == PERGUNTA
    assert (h[mantido]["resposta"], h[mantido]["origem"]) == ("O break encerra o laço na hora.", "LLM")

    linha = next(l for l in linhas_dialogo() if l["id"] == vetado)
    assert linha["resposta"] == "O break encerra o laço na hora."  # original preservada
    assert (linha["vetada"], linha["correcao_docente"]) == (1, correcao)


def test_retirar_veto_volta_a_resposta_original(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    dialogo_id = perguntar().json()["dialogo_id"]
    vetar(dialogo_id, vetada=True, correcao_docente="Correção.")
    resposta = vetar(dialogo_id, vetada=False)
    assert resposta.status_code == 200
    (d,) = historico()
    assert (d["resposta"], d["origem"], d["vetada"]) == ("O break encerra o laço na hora.", "LLM", False)
    assert d["fontes"] == ["repeticao.txt"]
    assert linhas_dialogo()[0]["correcao_docente"] == "Correção."  # nada apagado


def test_validacoes_do_veto(monkeypatch):
    mockar(monkeypatch, [TRECHO])
    dialogo_id = perguntar().json()["dialogo_id"]
    assert vetar(dialogo_id, vetada=True).status_code == 422          # vetar exige correção
    assert vetar(dialogo_id, vetada=True, correcao_docente="  ").status_code == 422
    assert vetar(9999, vetada=True, correcao_docente="x").status_code == 404
    assert historico("B2026-999") == []
    assert client.get("/alunos/Maria Souza/dialogo").status_code == 422


# --- incentivo por inatividade (relógio injetado) ---

ULTIMA = datetime(2026, 10, 1, 14, 0, 0)


def criar_trilha(aluno_id: str = ALUNO):
    etapas = [EtapaTrilha(ordem=n, competencia_id=c, nome=nome, horas=4, semana_inicio=n, justificativa="")
              for n, (c, nome) in enumerate([("condicionais", "Estruturas condicionais"),
                                              ("repeticao", "Laços de repetição"),
                                              ("funcoes", "Funções e modularização")], 1)]
    salvar_trilha(Trilha(aluno_id=aluno_id, perfil_id="iniciante", etapas=etapas), horas_semanais=6)


def gravar_interacao(ts: datetime, aluno_id: str = ALUNO):
    conexao = obter_conexao()
    with conexao:
        conexao.execute("""INSERT INTO tutor_dialogo (aluno_id, ts, pergunta, resposta, origem)
                           VALUES (?, ?, 'p', 'r', 'LLM')""", (aluno_id, ts.isoformat(timespec="seconds")))
    conexao.close()


def concluir_competencia(competencia_id: str, aluno_id: str = ALUNO):
    conexao = obter_conexao()
    with conexao:
        conexao.execute("""INSERT INTO tutor_sessoes (id, aluno_id, competencia_id, concluida, atualizado_em)
                           VALUES (?, ?, ?, 1, ?)""",
                        (f"s-{competencia_id}", aluno_id, competencia_id, ULTIMA.isoformat(timespec="seconds")))
    conexao.close()


@pytest.mark.parametrize("passado, inativo, dias", [
    (timedelta(days=2, hours=23), False, 2),   # antes do limite (3 dias)
    (timedelta(days=3), True, 3),              # no limite
    (timedelta(days=10), True, 10),            # depois do limite
])
def test_inatividade_com_relogio_injetado(passado, inativo, dias):
    gravar_interacao(ULTIMA - timedelta(days=5))  # interação antiga não conta
    gravar_interacao(ULTIMA)
    situacao = incentivo.verificar_inatividade(ALUNO, agora=ULTIMA + passado)
    assert (situacao.inativo, situacao.dias) == (inativo, dias)


def test_limite_vem_da_config(monkeypatch):
    gravar_interacao(ULTIMA)
    monkeypatch.setattr(incentivo, "INATIVIDADE_DIAS", 7)
    assert incentivo.verificar_inatividade(ALUNO, agora=ULTIMA + timedelta(days=5)).inativo is False
    assert incentivo.verificar_inatividade(ALUNO, agora=ULTIMA + timedelta(days=7)).inativo is True


def test_qualquer_acao_do_aluno_conta_como_interacao(monkeypatch):
    concluir_competencia("condicionais")  # sessão do questionário (atualizado_em = ULTIMA)
    assert incentivo.verificar_inatividade(ALUNO, agora=ULTIMA + timedelta(days=1)).dias == 1
    mockar(monkeypatch, [TRECHO])
    perguntar()  # diálogo agora
    assert incentivo.verificar_inatividade(ALUNO).dias == 0


def test_incentivo_cita_proxima_etapa_pendente_e_quantas_faltam():
    criar_trilha()
    concluir_competencia("condicionais")
    gravar_interacao(ULTIMA)

    inativo = incentivo.montar_incentivo(ALUNO, agora=ULTIMA + timedelta(days=4))
    assert (inativo.inativo, inativo.dias, inativo.proxima_etapa, inativo.etapas_restantes) == (
        True, 4, "repeticao", 2)
    assert inativo.mensagem == ("Faz 4 dias que você não estuda por aqui. Que tal retomar pela etapa "
                                "\"Laços de repetição\"? Faltam 2 etapas para concluir a sua trilha.")

    ativo = incentivo.montar_incentivo(ALUNO, agora=ULTIMA + timedelta(days=1))
    assert ativo.inativo is False
    assert ativo.mensagem == ("Bom ritmo! Sua próxima etapa é \"Laços de repetição\". "
                              "Faltam 2 etapas para concluir a sua trilha.")

    concluir_competencia("repeticao")
    assert "Falta 1 etapa para" in incentivo.montar_incentivo(ALUNO, agora=ULTIMA).mensagem
    concluir_competencia("funcoes")
    fim = incentivo.montar_incentivo(ALUNO, agora=ULTIMA)
    assert (fim.mensagem, fim.proxima_etapa, fim.etapas_restantes) == (
        incentivo.MENSAGEM_TRILHA_CONCLUIDA, None, 0)


def test_aluno_sem_trilha_recebe_sugestao_de_gerar(monkeypatch):
    sem_nada = incentivo.montar_incentivo("B2026-404", agora=ULTIMA)
    assert (sem_nada.inativo, sem_nada.dias, sem_nada.mensagem, sem_nada.proxima_etapa) == (
        True, None, incentivo.MENSAGEM_SEM_TRILHA, None)

    gravar_interacao(ULTIMA, aluno_id="B2026-405")  # usa o Tutor, mas sem trilha
    so_dialogo = incentivo.montar_incentivo("B2026-405", agora=ULTIMA + timedelta(days=1))
    assert (so_dialogo.inativo, so_dialogo.dias, so_dialogo.mensagem) == (False, 1, incentivo.MENSAGEM_SEM_TRILHA)


def test_quem_nunca_usou_o_tutor_conta_desde_a_trilha():
    criar_trilha()  # criada agora
    situacao = incentivo.verificar_inatividade(ALUNO, agora=datetime.now() + timedelta(days=3, minutes=1))
    assert (situacao.inativo, situacao.dias) == (True, 3)


def test_rota_de_incentivo_sem_llm_e_auditada(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("o incentivo não usa LLM")

    monkeypatch.setattr(dialogo, "chamar_llm", proibido)
    criar_trilha()
    resposta = client.get(f"/tutor/incentivo/{ALUNO}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["inativo"], corpo["dias"], corpo["proxima_etapa"], corpo["etapas_restantes"]) == (
        False, 0, "condicionais", 3)
    assert "Estruturas condicionais" in corpo["mensagem"]

    (registro,) = auditoria()
    assert (registro["tipo"], registro["referencia_id"], registro["origem"], registro["fontes"]) == (
        "incentivo", "condicionais", "template", [])
    # consultar o incentivo não conta como atividade do aluno
    assert incentivo.verificar_inatividade(ALUNO, agora=datetime.now() + timedelta(days=3, minutes=1)).inativo
    assert client.get("/tutor/incentivo/Maria Souza").status_code == 422



# --- portão de cobertura lexical ---

def test_normalizar_tira_acento_pontuacao_e_plural():
    assert dialogo.normalizar("Funções, Listas e EXCEÇÕES; valores (materiais)!") == [
        "funcao", "lista", "e", "excecao", "valor", "material"]


def test_termos_genericos_por_idf():
    textos = ["o laço for repete", "o while repete", "o if decide", "a função retorna"]
    # "o" está em 3 de 4 (> metade); "repete" em 2 de 4 (= metade, não passa de metade)
    assert dialogo.calcular_termos_genericos(textos) == {"o"}


@pytest.mark.parametrize("pergunta, passou, fracao", [
    ("Para que serve o break dentro de um for?", True, 1.0),     # break e for nos trechos
    ("O que é um dicionário em Python?", False, 0.0),             # só "dicionario" sobra
    ("Como faço um SELECT no banco de dados com o for?", False, 1 / 4),
    ("Como funciona?", False, 0.0),                               # sem termo de conteúdo
    ("O que é isso em Python?", False, 0.0),
])
def test_portao_de_cobertura(pergunta, passou, fracao):
    cobertura = dialogo.avaliar_cobertura(pergunta, [TRECHO["texto"]], set(), [], minimo=0.42)
    assert (cobertura.passou, round(cobertura.fracao, 2)) == (passou, round(fracao, 2))


def test_portao_ignora_termos_genericos_do_indice():
    trecho = ["o laço repete"]
    assert dialogo.avaliar_cobertura("laço e variável", trecho, set(), [], 0.6).passou is False  # 1/2
    assert dialogo.avaliar_cobertura("laço e variável", trecho, {"variavel"}, [], 0.6).passou is True  # 1/1


def test_portao_aceita_sinonimo_da_ementa():
    grupos = [["laço", "loop"], ["caso base", "parada"]]
    assert dialogo.avaliar_cobertura("Como sair de um loop?", ["o break encerra o laço"], set(), grupos, 0.5).passou
    assert not dialogo.avaliar_cobertura("Como sair de um loop?", ["o break encerra"], set(), grupos, 0.5).passou
    # membro de várias palavras: todas precisam estar nos trechos
    assert dialogo.avaliar_cobertura("Qual a parada?", ["todo caso base"], set(), grupos, 1.0).passou
    assert not dialogo.avaliar_cobertura("Qual a parada?", ["todo caso"], set(), grupos, 1.0).passou


def test_portao_barrado_nao_chama_llm_e_responde_fixo(monkeypatch):
    _, prompts = mockar(monkeypatch, [TRECHO])
    r = perguntar("Como conecto o Python a um banco de dados PostgreSQL?").json()
    assert (r["resposta"], r["fontes"], r["origem"]) == (
        "Não encontrei isso no material disponível; vale perguntar ao professor.", [], "fallback")
    assert prompts == []


def test_portao_usa_sinonimos_da_competencia_da_pergunta(monkeypatch):
    _, prompts = mockar(monkeypatch, [{**TRECHO, "texto": "O laço for percorre a lista."}])
    assert perguntar("O loop percorre o quê?", competencia_id="repeticao").json()["origem"] == "LLM"
    assert perguntar("O loop percorre o quê?", competencia_id="funcoes").json()["origem"] == "fallback"
    assert len(prompts) == 1  # funcoes não tem "loop" como sinônimo de "laço": barrado antes do LLM


# --- regra do termo mais raro ---

INDICE = ["o for percorre a lista", "a lista guarda valores", "a lista tem append", "o while repete"]


def test_termo_raro_barra_quando_o_termo_mais_raro_falta():
    # o caso da fora_09: "list" (sinônimo de "lista", em 3 trechos do índice) coberto,
    # "comprehension" (em nenhum) não. Pela fração (1/2) passa; pela regra, não.
    grupos = [["lista", "list"]]
    sem_regra = dialogo.avaliar_cobertura("list comprehension", ["a lista guarda"], set(), grupos, 0.42)
    com_regra = dialogo.avaliar_cobertura("list comprehension", ["a lista guarda"], set(), grupos, 0.42,
                                          textos_indice=INDICE)
    assert (sem_regra.passou, sem_regra.fracao, sem_regra.raros) == (True, 0.5, None)
    assert (com_regra.passou, com_regra.raros) == (False, ["comprehension"])


def test_termo_raro_coberto_passa_e_frequencia_conta_sinonimos():
    grupos = [["laço", "loop"]]
    # "loop" não aparece no índice, mas o sinônimo "laço" aparece em 1 trecho; "lista" em 3
    indice = ["o laço repete", "a lista guarda", "a lista muda", "a lista cresce"]
    cobertura = dialogo.avaliar_cobertura("loop na lista", ["o laço percorre a lista"], set(), grupos, 0.42,
                                          textos_indice=indice)
    assert cobertura.raros == ["loop"] and cobertura.passou is True


def test_termo_raro_empatado_exige_todos():
    cobertura = dialogo.avaliar_cobertura("enumerate e zip no for", ["o for repete"], set(), [], 0.3,
                                          textos_indice=INDICE)
    assert cobertura.raros == ["enumerate", "zip"] and cobertura.passou is False


def test_regra_do_termo_raro_so_vale_com_a_config(monkeypatch):
    trecho = {**TRECHO, "texto": "No for, o break interrompe a lista."}
    monkeypatch.setattr(dialogo, "textos_do_indice", lambda: ("o for repete", "o for e a lista", "a lista"))
    _, prompts = mockar(monkeypatch, [trecho])
    monkeypatch.setattr(dialogo, "TUTOR_EXIGE_TERMO_RARO", False)
    assert dialogo.gerar_resposta("O for com enumerate?", None, []).origem == "LLM"     # 1/2 passa pela fração
    monkeypatch.setattr(dialogo, "TUTOR_EXIGE_TERMO_RARO", True)
    assert dialogo.gerar_resposta("O for com enumerate?", None, []).origem == "fallback"  # "enumerate" é o raro
    assert len(prompts) == 1


# --- conjuntos de avaliação (instantâneo do RAG real, LLM mockado) ---

def _carregar(perguntas: str, instantaneo: str) -> list[tuple[dict, dict]]:
    with open(perguntas, encoding="utf-8") as arquivo:
        lista = json.load(arquivo)["perguntas"]
    with open(instantaneo, encoding="utf-8") as arquivo:
        inst = json.load(arquivo)
    return [(p, inst) for p in lista]


AVALIACAO = (_carregar("tests/dados/perguntas_avaliacao.json", "tests/dados/trechos_avaliacao.json")
             + _carregar("tests/dados/perguntas_avaliacao_v2.json", "tests/dados/trechos_avaliacao_v2.json"))

# Erros conhecidos, medidos em 10/10 e NÃO usados para ajustar nada. Chave:
# (regra do termo raro ligada?, id). strict=True: se o portão passar a acertar,
# o teste avisa para tirar daqui.
ERROS_CONHECIDOS = {
    # regra desligada (padrão): empate de cobertura 0,50 com perguntas cobertas de dois termos
    (False, "fora_09"): "'list' casa com o sinônimo 'lista', 'comprehension' não: 0,50",
    (False, "v2_fora_05"): "'for' coberto, 'enumerate' não: 0,50",
    (False, "v2_fora_07"): "'strings' coberto, 'formatar' não: 0,50 ('f' de f-string tem 1 letra)",
    (False, "v2_cob_07"): "o RAG não trouxe trecho a menos de TUTOR_DISTANCIA_MAXIMA",
    # regra ligada: o termo mais raro é uma palavra comum ausente do material
    (True, "cob_11"): "raro: 'alterada' (o material diz 'mutáveis'/'imutáveis')",
    (True, "cob_14"): "raro: 'fatiamento', ausente dos trechos recuperados (está em outro trecho)",
    (True, "v2_cob_06"): "raro: 'juntar', ausente do material",
    (True, "v2_cob_07"): "o RAG não trouxe trecho a menos de TUTOR_DISTANCIA_MAXIMA",
    (True, "v2_cob_10"): "raro: 'causa', ausente do material",
}


def _casos(coberta: bool):
    for termo_raro in (False, True):
        for pergunta, inst in AVALIACAO:
            if pergunta["coberta"] != coberta:
                continue
            motivo = ERROS_CONHECIDOS.get((termo_raro, pergunta["id"]))
            marcas = [pytest.mark.xfail(strict=True, reason=motivo)] if motivo else []
            yield pytest.param(pergunta, inst, termo_raro, marks=marcas,
                               id=f"{pergunta['id']}-{'raro' if termo_raro else 'padrao'}")


def responder_do_instantaneo(monkeypatch, pergunta: dict, inst: dict, termo_raro: bool):
    from tia.agentes.tutor.repositorio import materiais_da_competencia, palavras_chave
    monkeypatch.setattr(dialogo, "termos_genericos", lambda: frozenset(inst["termos_genericos"]))
    monkeypatch.setattr(dialogo, "textos_do_indice", lambda: tuple(inst["textos_indice"]))
    monkeypatch.setattr(dialogo, "TUTOR_DISTANCIA_MAXIMA", inst["distancia_maxima"])
    monkeypatch.setattr(dialogo, "TUTOR_EXIGE_TERMO_RARO", termo_raro)
    _, prompts = mockar(monkeypatch, inst["trechos"][pergunta["id"]])
    materiais = materiais_da_competencia(pergunta["competencia_id"]) if pergunta["competencia_id"] else None
    return dialogo.gerar_resposta(pergunta["pergunta"], materiais, palavras_chave(pergunta["competencia_id"])), prompts


@pytest.mark.parametrize("pergunta, inst, termo_raro", _casos(coberta=False))
def test_pergunta_fora_do_material_nao_chama_o_llm(monkeypatch, pergunta, inst, termo_raro):
    resultado, prompts = responder_do_instantaneo(monkeypatch, pergunta, inst, termo_raro)
    assert prompts == []
    assert (resultado.resposta, resultado.fontes, resultado.origem) == (dialogo.MENSAGEM_SEM_MATERIAL, [], "fallback")


@pytest.mark.parametrize("pergunta, inst, termo_raro", _casos(coberta=True))
def test_pergunta_coberta_chega_ao_llm(monkeypatch, pergunta, inst, termo_raro):
    _, prompts = responder_do_instantaneo(monkeypatch, pergunta, inst, termo_raro)
    assert len(prompts) == 1


def test_conjuntos_de_avaliacao():
    v1 = [p for p, _ in AVALIACAO if not p["id"].startswith("v2_")]
    v2 = [p for p, _ in AVALIACAO if p["id"].startswith("v2_")]
    assert len(v1) == 30 and sum(p["coberta"] for p in v1) == 14
    validacao = [p for p in v1 if p["conjunto"] == "validacao"]
    assert len(validacao) == 10 and {p["coberta"] for p in validacao} == {True, False}
    assert len(v2) == 20 and sum(p["coberta"] for p in v2) == 10
    assert {p["conjunto"] for p in v2} == {"teste_v2"}
    assert len({p["id"] for p, _ in AVALIACAO}) == 50
    for pergunta, inst in AVALIACAO:
        assert pergunta["id"] in inst["trechos"] and inst["textos_indice"]
