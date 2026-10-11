"""
Testes da aplicação web standalone (EAP 1.4.4), com o TestClient e o LLM
mockado (banco temporário do conftest):

- /app e os arquivos estáticos: status, tipo de conteúdo, cabeçalhos de segurança;
- o JavaScript: sem innerHTML, console ou eval, e todo id que ele usa existe no HTML;
- o tema: cores só em tema.css (variáveis), para trocar pelo visual do EBAULA;
- contrato: os campos e valores que o front lê existem nos modelos de resposta,
  e um percurso pelas rotas na ordem em que o front as chama;
- o comando de dados fictícios (python -m tia.web.dados_demo).

Não há roteiro de navegador: o Playwright não está instalado (pendência em
docs/relatorios/web_standalone.md).

Como rodar:
    ./run_tests.sh tests/test_web.py
"""

import re
from typing import get_args

import pytest
import requests
from fastapi.testclient import TestClient

import tia.agentes.planejador.justificar as justificar
import tia.agentes.relatorio.narrativa as narrativa
import tia.agentes.tutor.dialogo as dialogo
import tia.agentes.tutor.feedback as feedback
import tia.core.llm_client as llm_client
from tia.agentes.planejador.modelos import EtapaTrilha, Trilha
from tia.agentes.relatorio import modelos as relatorio
from tia.agentes.tutor import modelos as tutor
from tia.agentes.tutor.repositorio import carregar_itens
from tia.api.main import app
from tia.orquestrador import modelos as orquestracao
from tia.web import PASTA_ESTATICA, dados_demo

client = TestClient(app)
ALUNO = "A2026-W01"
GABARITO = {i["id"]: i["indice_correto"] for i in carregar_itens()}
DIAGNOSTICO = {"variaveis_tipos": 0.9, "condicionais": 0.8, "repeticao": 0.9,
               "funcoes": 0.2, "listas_strings": 0.2, "recursao": 0.0}
ESTATICOS = {"index.html": "text/html", "app.js": "javascript", "tema.css": "text/css", "estilo.css": "text/css"}


def ler(nome: str) -> str:
    return (PASTA_ESTATICA / nome).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def llm_mockado(monkeypatch):
    monkeypatch.setattr(justificar, "chamar_llm", lambda prompt, **kwargs: "1. Etapa justificada.")
    monkeypatch.setattr(narrativa, "chamar_llm", lambda prompt, **kwargs: "Você está indo bem.")
    monkeypatch.setattr(feedback, "buscar_contexto", lambda consulta, k=3, fontes=None: [])
    monkeypatch.setattr(dialogo, "buscar_trechos_dialogo", lambda pergunta, materiais: [])


# --- rotas /app e estáticos ---

def test_app_sem_barra_redireciona_para_a_pagina():
    resposta = client.get("/app", follow_redirects=False)
    assert resposta.status_code == 307 and resposta.headers["location"] == "/app/"


@pytest.mark.parametrize("caminho", ["/app/", "/app/index.html"])
def test_pagina_inicial(caminho):
    resposta = client.get(caminho)
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    html = resposta.text
    assert '<html lang="pt-BR">' in html
    assert "Protótipo, sem login (TODO 1.4.6)" in html
    for arquivo in ESTATICOS:
        if arquivo != "index.html":
            assert f'"{arquivo}"' in html  # caminho relativo: funciona em /app/


@pytest.mark.parametrize("arquivo, tipo", ESTATICOS.items())
def test_arquivos_estaticos(arquivo, tipo):
    resposta = client.get(f"/app/{arquivo}")
    assert resposta.status_code == 200
    assert tipo in resposta.headers["content-type"]
    assert resposta.text == ler(arquivo)


def test_cabecalhos_de_seguranca_so_em_app():
    csp = client.get("/app/").headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert client.get("/app/app.js").headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in client.get("/health").headers


def test_arquivo_inexistente_404():
    assert client.get("/app/nao_existe.js").status_code == 404


def test_rotas_da_api_continuam_funcionando():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200


# --- segurança e acessibilidade do front (análise do código) ---

def sem_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


def test_js_nao_usa_innerhtml_console_nem_eval():
    js = sem_comentarios(ler("app.js"))
    for proibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "console.", "eval(",
                     "new Function"):
        assert proibido not in js, proibido


def test_js_sem_segredos_nem_endereco_fixo():
    js = ler("app.js").lower()
    for proibido in ("api_key", "apikey", "token", "secret", "senha", "password", "http://", "https://", "11434"):
        assert proibido not in js, proibido


def test_ids_usados_pelo_js_existem_no_html():
    html, js = ler("index.html"), ler("app.js")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    usados = set(re.findall(r'\$\("([^"]+)"\)', js))
    usados |= {"tela-" + t for t in re.findall(r'"(entrada|trilha|estudo|dialogo|relatorio)"', js)}
    assert usados and usados <= ids_html, usados - ids_html


def test_campos_do_html_tem_rotulo():
    html = ler("index.html")
    for campo in re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', html):
        assert f'for="{campo}"' in html, campo


def test_cores_e_fontes_so_no_tema():
    estilo = ler("estilo.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", estilo), "cor fixa em estilo.css; use var(--...)"
    assert "font-family: var(" in estilo
    tema = ler("tema.css")
    assert re.search(r":root\s*{", tema) and "--cor-primaria" in tema


# --- contrato: campos e valores que o front lê ---

# modelo -> campos lidos em app.js
CAMPOS_USADOS = {
    orquestracao.EstadoAluno: {"etapas", "competencia_atual", "concluido", "reforco", "ultima_decisao"},
    orquestracao.EtapaEstado: {"ordem", "competencia_id", "nome", "concluida"},
    orquestracao.Reforco: {"competencia_original", "competencia_reforco"},
    orquestracao.DecisaoReplanejamento: {"acao", "aviso", "origem_justificativas", "falha_llm"},
    orquestracao.ProximaAcao: {"acao", "competencia_id", "sessao_id", "reforco", "motivo", "pergunta"},
    orquestracao.SessaoOrquestrada: {"sessao", "reforco"},
    orquestracao.ResultadoEvento: {"feedback", "avisos", "proxima"},
    orquestracao.Matricula: {"perfil_id", "horas_semanais", "diagnostico"},
    orquestracao.EventoTutor: {"evento_id", "tipo", "sessao_id", "item_id", "indice_escolhido"},
    orquestracao.PedidoSessao: {"competencia_id"},
    Trilha: {"etapas"},
    EtapaTrilha: {"competencia_id", "horas", "semana_inicio", "justificativa", "origem_justificativa"},
    tutor.SessaoIniciada: {"sessao_id", "pergunta"},
    tutor.Pergunta: {"item_id", "competencia_id", "nivel", "enunciado", "alternativas"},
    tutor.Feedback: {"acertou", "indice_correto", "veredito", "explicacao", "origem", "falha_llm", "fontes",
                     "nivel_atual", "concluida", "tempo_ms"},
    tutor.PerguntaAluno: {"aluno_id", "pergunta", "competencia_id"},
    tutor.RespostaDialogo: {"resposta", "fontes", "origem", "falha_llm", "tempo_ms"},
    tutor.ItemDialogo: {"pergunta", "resposta", "fontes", "origem", "vetada"},
    relatorio.RelatorioAluno: {"progresso", "desempenho", "engajamento", "pontos_fracos", "itens_fracos",
                               "qualidade_feedback", "narrativa"},
    relatorio.Progresso: {"tem_trilha", "etapas", "concluidas", "percentual", "por_competencia"},
    relatorio.ProgressoCompetencia: {"competencia_id", "nome", "concluida", "nivel_atual"},
    relatorio.Desempenho: {"geral", "por_competencia", "tendencia"},
    relatorio.Taxa: {"chave", "respostas", "acertos", "taxa"},
    relatorio.Tendencia: {"direcao"},
    relatorio.Engajamento: {"sessoes", "sessoes_concluidas", "respostas", "perguntas_dialogo", "dias_ativos",
                            "dias_inativo", "inativo"},
    relatorio.PontoFraco: {"nome", "erros", "respostas"},
    relatorio.QualidadeFeedback: {"respostas_com_origem", "por_origem", "vetados"},
    relatorio.Narrativa: {"texto", "origem", "falha_llm"},
}


@pytest.mark.parametrize("modelo", CAMPOS_USADOS, ids=lambda m: m.__name__)
def test_campos_que_o_front_le_existem(modelo):
    assert CAMPOS_USADOS[modelo] <= set(modelo.model_fields), CAMPOS_USADOS[modelo] - set(modelo.model_fields)


def test_valores_que_o_front_traduz():
    """Cada valor possível da API tem texto no front (origens, ações, tendência)."""
    js = ler("app.js")
    for origem in get_args(tutor.Origem):
        assert re.search(rf"\b{origem}:", js), origem
    for acao in get_args(orquestracao.AcaoProxima):
        assert f'"{acao}"' in js or acao == "iniciar_sessao", acao  # iniciar_sessao é o caso padrão
    for direcao in get_args(relatorio.Direcao):
        assert f"{direcao}:" in js, direcao
    for origem in ("LLM", "parcial", "fallback"):
        assert f"{origem}:" in js, origem


# --- percurso pelas rotas, na ordem do front ---

def test_percurso_do_front_pelas_rotas():
    assert client.get(f"/aluno/{ALUNO}/estado").status_code == 404  # entrada: pede matrícula
    matricula = client.post(f"/aluno/{ALUNO}/iniciar",
                            json={"perfil_id": "intermediario", "horas_semanais": 6, "diagnostico": DIAGNOSTICO})
    assert matricula.status_code == 200

    estado = client.get(f"/aluno/{ALUNO}/estado").json()
    trilha = client.get(f"/alunos/{ALUNO}/trilha").json()
    assert estado["competencia_atual"] == "funcoes"
    assert [e["competencia_id"] for e in estado["etapas"]] == [e["competencia_id"] for e in trilha["etapas"]]
    assert all(e["justificativa"] and e["origem_justificativa"] in ("LLM", "fallback") for e in trilha["etapas"])

    proxima = client.get(f"/aluno/{ALUNO}/proximo").json()
    assert (proxima["acao"], proxima["competencia_id"], proxima["pergunta"]) == ("iniciar_sessao", "funcoes", None)
    sessao = client.post(f"/aluno/{ALUNO}/sessao", json={"competencia_id": "funcoes"}).json()["sessao"]
    pergunta = sessao["pergunta"]
    assert "indice_correto" not in pergunta and "explicacao" not in pergunta

    # recarregar a página no meio da sessão: o "proximo" devolve a mesma pergunta
    continuar = client.get(f"/aluno/{ALUNO}/proximo").json()
    assert (continuar["acao"], continuar["sessao_id"], continuar["pergunta"]) == (
        "continuar_sessao", sessao["sessao_id"], pergunta)

    corpo = {"evento_id": "web-teste-1", "tipo": "resposta", "sessao_id": sessao["sessao_id"],
             "item_id": pergunta["item_id"], "indice_escolhido": GABARITO[pergunta["item_id"]]}
    resultado = client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()
    assert resultado["feedback"]["acertou"] is True and resultado["feedback"]["origem"] == "fallback"
    assert resultado["proxima"]["pergunta"] == resultado["feedback"]["proxima_pergunta"]
    # reenvio depois de erro de rede: mesmo evento_id, resultado gravado
    repetido = client.post(f"/aluno/{ALUNO}/evento", json=corpo).json()
    assert repetido["repetido"] is True and repetido["feedback"] == resultado["feedback"]

    dialogo_resposta = client.post("/tutor/perguntar", json={"aluno_id": ALUNO, "pergunta": "O que é uma lista?",
                                                             "competencia_id": None})
    assert dialogo_resposta.status_code == 200
    assert dialogo_resposta.json()["origem"] == "fallback" and dialogo_resposta.json()["fontes"] == []
    assert client.get(f"/alunos/{ALUNO}/dialogo").json()[0]["pergunta"] == "O que é uma lista?"

    indicadores = client.get(f"/relatorio/aluno/{ALUNO}?narrativa=false").json()
    assert indicadores["progresso"]["etapas"] == 3 and indicadores["desempenho"]["geral"]["respostas"] == 1
    assert client.get(f"/relatorio/aluno/{ALUNO}?narrativa=true").json()["narrativa"]["origem"] == "LLM"


def test_erros_que_o_front_mostra_tem_detail_em_texto():
    """O front mostra "detail" (texto) ou a lista de erros de validação (msg)."""
    assert isinstance(client.get("/aluno/NAO-EXISTE/estado").json()["detail"], str)
    invalido = client.post(f"/aluno/{ALUNO}/iniciar", json={"perfil_id": "x", "horas_semanais": 0}).json()
    assert all("msg" in erro for erro in invalido["detail"])
    assert client.get("/aluno/nome com espaço/estado").status_code in (404, 422)


# --- dados fictícios ---

def test_dados_demo_cria_tres_alunos_e_nao_duplica(monkeypatch, capsys):
    def falha_imediata(*args, **kwargs):
        raise requests.ConnectionError("teste")
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    dados_demo.criar_alunos()
    proximas = {a: client.get(f"/aluno/{a}/proximo").json() for a in dados_demo.ALUNOS}
    assert (proximas["DEMO-W01"]["acao"], proximas["DEMO-W01"]["competencia_id"]) == ("iniciar_sessao", "funcoes")
    assert proximas["DEMO-W02"]["acao"] == "continuar_sessao" and proximas["DEMO-W02"]["pergunta"] is not None
    assert (proximas["DEMO-W03"]["competencia_id"], proximas["DEMO-W03"]["reforco"]) == ("repeticao", True)
    dados_demo.criar_alunos()
    assert capsys.readouterr().out.count("já existe no banco") == 3
