"""
Testes do painel do docente (EAP 1.4.5), com o TestClient, banco temporário
(conftest) e sem LLM, sobre a turma fictícia de python -m tia.web.dados_painel:

- /app/painel e os arquivos estáticos (tipo, cabeçalhos de segurança, aviso de protótipo);
- o JavaScript: sem innerHTML/console/eval, ids existentes, rótulos, cores só no tema;
- contrato: os campos e valores que painel.js lê existem nos modelos;
- rotas novas de leitura: ementa, perfis, alunos em risco, competências, revisão,
  auditoria filtrável e exportação CSV;
- regra do grupo mínimo (nenhum grupo abaixo de RELATORIO_MIN_GRUPO e nenhum
  código de aluno nas visões agregadas);
- escape: texto da API chega cru no JSON (o front usa textContent) e o CSV não
  deixa fórmula entrar na planilha;
- auditoria: cada consulta de risco e de revisão grava um registro; aprovar e
  vetar gravam "veto_docente".

Como rodar:
    ./run_tests.sh tests/test_painel.py
"""

import csv
import io
import json
import re
from datetime import datetime
from typing import get_args

import pytest
import requests
from fastapi.testclient import TestClient

import tia.core.llm_client as llm_client
from tia.agentes.relatorio import modelos as relatorio
from tia.api.main import app
from tia.core import auditoria
from tia.core.config import RELATORIO_MIN_GRUPO
from tia.core.database import obter_conexao
from tia.painel import consultas
from tia.painel import modelos as painel
from tia.web import PASTA_ESTATICA, dados_painel

client = TestClient(app)
PASTA_PAINEL = PASTA_ESTATICA / "painel"
ESTATICOS = {"": "text/html", "index.html": "text/html", "painel.js": "javascript", "painel.css": "text/css"}


def ler(nome: str) -> str:
    return (PASTA_PAINEL / nome).read_text(encoding="utf-8")


def sem_comentarios(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


@pytest.fixture
def turma(monkeypatch):
    """A turma fictícia de 12 alunos, criada sem LLM (falha imediata, textos padrão)."""
    def falha_imediata(*args, **kwargs):
        raise requests.ConnectionError("teste sem LLM")
    monkeypatch.setattr(llm_client.requests, "post", falha_imediata)
    criados = dados_painel.criar_turma(datetime.now())
    assert len(criados) == 12
    return criados


def consultas_auditadas(referencia: str) -> list[dict]:
    conexao = obter_conexao()
    try:
        linhas = conexao.execute("SELECT * FROM auditoria WHERE tipo = 'consulta_painel' AND referencia_id = ?",
                                 (referencia,)).fetchall()
    finally:
        conexao.close()
    return [dict(linha) for linha in linhas]


# --- rotas estáticas ---

def test_painel_sem_barra_redireciona():
    resposta = client.get("/app/painel", follow_redirects=False)
    assert resposta.status_code == 307 and resposta.headers["location"] == "/app/painel/"


@pytest.mark.parametrize("arquivo, tipo", ESTATICOS.items())
def test_arquivos_do_painel(arquivo, tipo):
    resposta = client.get(f"/app/painel/{arquivo}")
    assert resposta.status_code == 200
    assert tipo in resposta.headers["content-type"]
    assert "default-src 'self'" in resposta.headers["content-security-policy"]
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_pagina_do_painel_reaproveita_tema_e_utilidades():
    html = client.get("/app/painel/").text
    assert '<html lang="pt-BR">' in html
    assert 'id="form-login"' in html and 'type="password"' in html
    assert re.search(r'id="aviso-dev"[^>]*hidden', html) and "TODO 1.4.6" not in html
    for caminho in ('href="../tema.css"', 'href="../estilo.css"', 'href="painel.css"'):
        assert caminho in html, caminho
    assert html.index('src="../comum.js"') < html.index('src="painel.js"')
    # os caminhos relativos resolvem para arquivos que existem
    for arquivo in ("tema.css", "estilo.css", "comum.js"):
        assert client.get(f"/app/{arquivo}").status_code == 200


def test_tela_de_risco_avisa_que_a_consulta_e_auditada():
    html = ler("index.html")
    tela = html[html.index('id="tela-risco"'):html.index('id="tela-competencias"')]
    assert "códigos de aluno (nunca nomes)" in tela and "auditoria em seu nome" in tela


# --- segurança e acessibilidade do front (análise do código) ---

def test_js_do_painel_nao_usa_innerhtml_console_nem_eval():
    js = sem_comentarios(ler("painel.js"))
    for proibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "console.", "eval(",
                     "new Function", "localStorage"):
        assert proibido not in js, proibido
    for proibido in ("http://", "https://", "password", "11434", "document.cookie"):
        assert proibido not in js.lower(), proibido
    assert not re.search(r"""\b(senha|token|csrf)\w*\s*[:=]\s*["'][^"']{6,}["']""", js.lower())


def test_ids_usados_pelo_painel_existem_no_html():
    html = ler("index.html")
    js = ler("painel.js") + (PASTA_ESTATICA / "comum.js").read_text(encoding="utf-8")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    usados = set(re.findall(r'\$\("([^"]+)"\)', js))
    telas = re.search(r"const TELAS = \[([^\]]+)\]", js).group(1)
    usados |= {"tela-" + t for t in re.findall(r'"(\w+)"', telas)}
    assert usados and usados <= ids_html, usados - ids_html


def test_campos_e_tabelas_acessiveis():
    html, js = ler("index.html"), ler("painel.js")
    for campo in re.findall(r'<(?:input|select|textarea)[^>]*id="([^"]+)"', html):
        assert f'for="{campo}"' in html, campo
    # gráficos: SVG decorativo, valor também em texto; tabelas com caption e cabeçalhos com scope
    assert '"aria-hidden": "true"' in js and "visualmente-oculto" in js
    assert 'el("caption"' in js and 'scope: "col"' in js


def test_cores_so_no_tema_e_css_de_impressao():
    css = ler("painel.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", css), "cor fixa em painel.css; use var(--...)"
    assert "@media print" in css and ".nao-imprimir" in css
    assert "@media print" in (PASTA_ESTATICA / "tema.css").read_text(encoding="utf-8")


# --- contrato: campos e valores que painel.js lê ---

CAMPOS_USADOS = {
    relatorio.RelatorioTurma: {"gerado_em", "alunos", "min_grupo", "suprimido", "progresso_medio",
                               "alunos_com_trilha", "desempenho_por_nivel", "engajamento", "pontos_fracos",
                               "itens_fracos", "qualidade_feedback", "alertas", "narrativa"},
    relatorio.Contagem: {"texto"},
    relatorio.GrupoTaxa: {"chave", "alunos", "suprimido", "respostas", "taxa"},
    relatorio.EngajamentoTurma: {"media_sessoes", "media_dias_ativos", "media_perguntas_dialogo", "inativos"},
    relatorio.AlertaTurma: {"tipo", "descricao", "alunos"},
    relatorio.QualidadeFeedback: {"por_origem", "taxa_por_origem", "vetados", "dialogos", "taxa_veto",
                                  "feedbacks_vetados", "feedbacks_com_texto", "taxa_veto_feedback"},
    relatorio.Narrativa: {"texto", "origem", "falha_llm"},
    painel.CompetenciaEmenta: {"id", "nome"},
    painel.PerfilResumo: {"id", "nome"},
    painel.ConsultaRisco: {"criterios", "alunos_avaliados", "alunos", "auditoria_id", "gerado_em"},
    painel.AlunoEmRisco: {"aluno_id", "motivos", "dias_inativo", "taxa_acerto", "respostas", "tendencia",
                          "progresso"},
    painel.MotivoRisco: {"tipo", "descricao"},
    painel.DesempenhoCompetencias: {"alunos", "min_grupo", "suprimido", "competencias", "itens_fracos"},
    painel.CompetenciaTurma: {"nome", "taxa", "suprimido", "alunos", "respostas", "tendencia"},
    painel.ItemTurma: {"item_id", "nome_competencia", "nivel", "enunciado", "taxa_erro", "alunos_com_erro",
                       "respostas"},
    painel.ListaRevisao: {"dialogo", "feedback", "feedbacks_sem_texto", "auditoria_id", "itens", "pagina", "total",
                          "por_pagina", "feedbacks_por_origem"},
    painel.ResumoRevisao: {"taxa_veto", "vetados", "total", "aprovados", "a_revisar"},
    painel.ItemRevisao: {"tipo", "id", "aluno_id", "competencia_id", "ts", "situacao", "vetada", "pergunta",
                         "item_id", "nivel", "acertou", "veredito", "resposta", "origem", "falha_llm", "fontes",
                         "explicacao_descartada", "motivo_descarte", "correcao_docente"},
    painel.PaginaAuditoria: {"total", "registros", "pagina", "por_pagina"},
    painel.RegistroPainel: {"ts", "agentes", "tipo", "aluno_id", "origem", "origem_justificativas",
                            "referencia_id", "motivo", "fontes"},
}


@pytest.mark.parametrize("modelo", CAMPOS_USADOS, ids=lambda m: m.__name__)
def test_campos_que_o_painel_le_existem(modelo):
    assert CAMPOS_USADOS[modelo] <= set(modelo.model_fields), CAMPOS_USADOS[modelo] - set(modelo.model_fields)


def test_valores_que_o_painel_traduz():
    """Cada valor possível da API tem texto no painel (motivos, tendência, alertas, tipos, agentes)."""
    js, html = ler("painel.js"), ler("index.html")
    valores = (list(get_args(painel.TipoRisco)) + list(get_args(relatorio.Direcao))
               + list(get_args(relatorio.AlertaTurma.model_fields["tipo"].annotation)) + list(auditoria.TIPOS)
               + list(auditoria.AGENTES) + ["a_revisar", "aprovada", "vetada"])
    for valor in valores:
        assert re.search(rf"\b{valor}:", js), valor
    for valor in (list(get_args(painel.TipoRisco)) + list(get_args(painel.SituacaoRevisao)) + list(auditoria.AGENTES)
                  + list(get_args(painel.TipoRevisao))):
        assert f'value="{valor}"' in html, valor


# --- rotas de leitura: conteúdo ---

def test_ementa_e_perfis():
    ementa = client.get("/conteudo/ementa").json()
    assert [c["id"] for c in ementa][:2] == ["variaveis_tipos", "condicionais"]
    assert all(set(c) == {"id", "nome", "prerequisitos"} for c in ementa)
    assert {p["id"] for p in client.get("/conteudo/perfis").json()} == {"iniciante", "intermediario"}


# --- alertas de risco (com códigos) e auditoria da consulta ---

def test_alunos_em_risco_e_motivos(turma):
    r = client.get("/painel/alunos-em-risco").json()
    motivos = {a["aluno_id"]: {m["tipo"] for m in a["motivos"]} for a in r["alunos"]}
    assert motivos == {
        "DEMO-P03": {"desempenho_em_queda"},
        "DEMO-P04": {"inatividade"},
        "DEMO-P05": {"inatividade"},
        "DEMO-P06": {"desempenho_baixo"},
        "DEMO-P08": {"desempenho_em_queda", "desempenho_baixo"},
        "DEMO-P11": {"inatividade"},
    }
    assert r["alunos"][0]["aluno_id"] == "DEMO-P08"  # mais motivos primeiro
    assert r["alunos_avaliados"] == 12
    # concluiu a trilha e está parado há 12 dias: não é risco; recém-matriculado sem atividade também não
    assert "DEMO-P02" not in motivos and "DEMO-P10" not in motivos
    assert all(m["descricao"] for a in r["alunos"] for m in a["motivos"])


def test_cada_consulta_de_risco_vai_para_a_auditoria(turma):
    assert consultas_auditadas("alunos_em_risco") == []
    primeira = client.get("/painel/alunos-em-risco").json()
    client.get("/painel/alunos-em-risco?perfil_id=iniciante")
    registros = consultas_auditadas("alunos_em_risco")
    assert len(registros) == 2
    assert registros[0]["id"] == primeira["auditoria_id"]
    assert registros[0]["aluno_id"] is None and registros[0]["origem"] == "painel"
    for codigo in ("DEMO-P08", "DEMO-P05"):
        assert codigo in registros[0]["motivo"]  # quais códigos foram exibidos
    assert "perfil=iniciante" in registros[1]["motivo"] and "DEMO-P08" not in registros[1]["motivo"]
    # e aparecem na auditoria do painel, filtradas pelo agente "painel"
    pagina = client.get("/painel/auditoria?agente=painel").json()
    assert pagina["total"] == 2 and all(x["tipo"] == "consulta_painel" for x in pagina["registros"])


# --- regra do grupo mínimo (R08) ---

def test_competencias_respeitam_o_grupo_minimo(turma):
    r = client.get("/painel/competencias").json()
    assert r["min_grupo"] == RELATORIO_MIN_GRUPO and not r["suprimido"]
    por_id = {c["competencia_id"]: c for c in r["competencias"]}
    assert not por_id["funcoes"]["suprimido"] and por_id["funcoes"]["alunos"]["valor"] == 8
    assert not por_id["listas_strings"]["suprimido"]
    for c in r["competencias"]:
        if c["suprimido"]:
            assert (c["alunos"]["valor"], c["taxa"], c["respostas"], c["tendencia"]) == (None, None, None, None)
            assert c["alunos"]["texto"] == f"menos de {RELATORIO_MIN_GRUPO}"
        else:
            assert c["alunos"]["valor"] >= RELATORIO_MIN_GRUPO
            # contagens da tendência: número só a partir do mínimo (ou zero)
            for contagem in c["tendencia"].values():
                assert contagem["valor"] is None or contagem["valor"] == 0 or contagem["valor"] >= RELATORIO_MIN_GRUPO
    assert por_id["recursao"]["suprimido"] and por_id["variaveis_tipos"]["suprimido"]


def test_itens_fracos_so_com_pelo_menos_cinco_alunos(turma):
    itens = client.get("/painel/competencias").json()["itens_fracos"]
    assert itens and itens[0]["item_id"] == "funcoes_n2a" and itens[0]["enunciado"]
    conexao = obter_conexao()
    try:
        for item in itens:
            alunos = conexao.execute("SELECT COUNT(DISTINCT aluno_id) FROM historico_respostas WHERE item_id = ?",
                                     (item["item_id"],)).fetchone()[0]
            assert alunos >= max(RELATORIO_MIN_GRUPO, 5), item["item_id"]
    finally:
        conexao.close()


def test_grupo_abaixo_do_minimo_nao_mostra_nada(turma):
    """Perfil iniciante: 4 alunos (abaixo de 5). Nenhum número sai em nenhuma visão agregada."""
    competencias = client.get("/painel/competencias?perfil_id=iniciante").json()
    assert competencias["suprimido"] and competencias["competencias"] == [] and competencias["itens_fracos"] == []
    assert competencias["alunos"] == {"valor": None, "texto": f"menos de {RELATORIO_MIN_GRUPO}"}
    turma_iniciante = client.get("/relatorio/turma?perfil_id=iniciante&narrativa=false").json()
    assert turma_iniciante["suprimido"] and turma_iniciante["desempenho_por_competencia"] == []
    linhas = list(csv.reader(io.StringIO(
        client.get("/painel/exportar/indicadores.csv?perfil_id=iniciante").text.lstrip("﻿")), delimiter=";"))
    assert len(linhas) == 3 and "suprimido" in linhas[2][-1]


def test_visoes_agregadas_nunca_mostram_codigos(turma):
    textos = [client.get("/painel/competencias").text, client.get("/relatorio/turma?narrativa=false").text,
              client.get("/painel/exportar/indicadores.csv").text]
    for texto in textos:
        assert "DEMO-P" not in texto


# --- revisão docente (R12) ---

def dialogo_por_texto(itens: list[dict], trecho: str) -> dict:
    return next(i for i in itens if trecho in i["pergunta"])


def test_revisao_lista_aprova_e_veta_pela_rota_existente(turma):
    r = client.get("/painel/revisao?situacao=todas&tipo=dialogo").json()
    resumo = r["dialogo"]
    assert (resumo["total"], resumo["vetados"], resumo["aprovados"], resumo["a_revisar"]) == (10, 1, 0, 9)
    assert resumo["taxa_veto"] == 0.1
    vetada = next(i for i in r["itens"] if i["vetada"])
    assert vetada["situacao"] == "vetada" and vetada["correcao_docente"] and "[demonstração]" in vetada["resposta"]

    a_revisar = client.get("/painel/revisao?origem=LLM&tipo=dialogo").json()["itens"]
    assert a_revisar and all(i["origem"] == "LLM" and i["situacao"] == "a_revisar" for i in a_revisar)
    aprovar = dialogo_por_texto(a_revisar, "range(3)")
    vetar = dialogo_por_texto(a_revisar, "parâmetro e argumento")

    assert client.patch(f"/tutor/dialogo/{aprovar['id']}/veto", json={"vetada": False}).status_code == 200
    assert client.patch(f"/tutor/dialogo/{vetar['id']}/veto",
                        json={"vetada": True, "correcao_docente": "Não são a mesma coisa."}).status_code == 200

    depois = client.get("/painel/revisao?situacao=todas").json()["dialogo"]
    assert (depois["vetados"], depois["aprovados"], depois["a_revisar"], depois["taxa_veto"]) == (2, 1, 7, 0.2)
    aprovadas = client.get("/painel/revisao?situacao=aprovadas&tipo=dialogo").json()["itens"]
    assert [i["id"] for i in aprovadas] == [aprovar["id"]]
    vetadas = client.get("/painel/revisao?situacao=vetadas&tipo=dialogo").json()["itens"]
    assert vetar["id"] in [i["id"] for i in vetadas]
    # o aluno vê a correção; a revisão continua mostrando a original
    historico = client.get(f"/alunos/{vetar['aluno_id']}/dialogo").json()
    assert any(i["resposta"] == "Não são a mesma coisa." for i in historico)

    vetos = client.get("/painel/auditoria?agente=tutor").json()["registros"]
    revisoes = [x for x in vetos if x["tipo"] == "veto_docente"]
    assert {x["origem"] for x in revisoes} == {"aprovada", "vetada"}
    assert all(x["motivo"] and "Não são" not in x["motivo"] for x in revisoes)  # sem o texto da correção


def test_retirar_veto_fica_registrado(turma):
    vetada = client.get("/painel/revisao?situacao=vetadas&tipo=dialogo").json()["itens"][0]
    client.patch(f"/tutor/dialogo/{vetada['id']}/veto", json={"vetada": False})
    ultimo = client.get(f"/painel/auditoria?aluno_id={vetada['aluno_id']}").json()["registros"][0]
    assert (ultimo["tipo"], ultimo["motivo"]) == ("veto_docente", "veto retirado")


def test_consulta_de_revisao_e_auditada_e_paginada(turma):
    pagina1 = client.get("/painel/revisao?situacao=todas&tipo=dialogo&por_pagina=4").json()
    pagina3 = client.get("/painel/revisao?situacao=todas&tipo=dialogo&por_pagina=4&pagina=3").json()
    assert (pagina1["total"], len(pagina1["itens"]), len(pagina3["itens"])) == (10, 4, 2)
    assert len(consultas_auditadas("revisao")) == 2
    assert sum(pagina1["feedbacks_por_origem"].values()) > 0


def test_revisao_valida_filtros():
    assert client.get("/painel/revisao?situacao=qualquer").status_code == 422
    assert client.get("/painel/revisao?origem=docente").status_code == 422
    assert client.get("/painel/revisao?pagina=0").status_code == 422
    assert client.get("/painel/revisao?tipo=outro").status_code == 422
    assert client.get("/painel/revisao?competencia_id=a b").status_code == 422


# --- auditoria filtrável (R11) ---

def test_auditoria_filtra_por_agente_aluno_e_periodo(turma):
    tudo = client.get("/painel/auditoria?por_pagina=100").json()
    assert tudo["total"] > 100 and len(tudo["registros"]) == 100
    datas = [x["ts"] for x in tudo["registros"]]
    assert datas == sorted(datas, reverse=True)  # mais recente primeiro

    planejador = client.get("/painel/auditoria?agente=planejador&por_pagina=100").json()
    # 12 matrículas + 1 trilha refeita por inatividade (DEMO-P05)
    assert planejador["total"] == 13
    assert all("planejador" in x["agentes"] and x["origem_justificativas"] for x in planejador["registros"])

    aluno = client.get("/painel/auditoria?aluno_id=DEMO-P03&por_pagina=100").json()
    assert aluno["total"] > 0 and {x["aluno_id"] for x in aluno["registros"]} == {"DEMO-P03"}
    assert {"orquestrador", "tutor"} <= {a for x in aluno["registros"] for a in x["agentes"]}

    hoje = datetime.now().date().isoformat()
    so_hoje = client.get(f"/painel/auditoria?desde={hoje}&ate={hoje}&por_pagina=100").json()
    assert 0 < so_hoje["total"] < tudo["total"] and all(x["ts"].startswith(hoje) for x in so_hoje["registros"])
    assert client.get("/painel/auditoria?ate=2000-01-01").json()["total"] == 0

    segunda = client.get("/painel/auditoria?por_pagina=100&pagina=2").json()
    assert len(segunda["registros"]) == tudo["total"] - 100
    assert not {x["id"] for x in segunda["registros"]} & {x["id"] for x in tudo["registros"]}


@pytest.mark.parametrize("consulta", ["agente=outro", "aluno_id=nome com espaço", "desde=11/10/2026",
                                      "por_pagina=1000", "pagina=0"])
def test_auditoria_valida_filtros(consulta):
    assert client.get(f"/painel/auditoria?{consulta}").status_code == 422


def test_registro_de_auditoria_antigo_continua_valido():
    """GET /auditoria/{id} aceita os tipos novos (veto_docente, consulta_painel)."""
    from tia.agentes.tutor.repositorio import registrar_dialogo
    dialogo_id = registrar_dialogo("A2026-P01", None, "pergunta", "resposta", [], "LLM", 10)
    client.patch(f"/tutor/dialogo/{dialogo_id}/veto", json={"vetada": False})
    tipos = [x["tipo"] for x in client.get("/auditoria/A2026-P01").json()]
    assert tipos == ["dialogo", "veto_docente"]


# --- escape de texto ---

def test_texto_com_html_chega_cru_no_json():
    """A API não escapa nem interpreta: o texto vai como está e o painel o põe por textContent."""
    from tia.agentes.tutor.repositorio import registrar_dialogo
    malicioso = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    registrar_dialogo("A2026-P02", None, malicioso, malicioso + " resposta", [], "LLM", 10)
    item = client.get("/painel/revisao").json()["itens"][0]
    assert item["pergunta"] == malicioso and item["resposta"].startswith(malicioso)
    js = sem_comentarios(ler("painel.js"))
    assert "textContent" in (PASTA_ESTATICA / "comum.js").read_text(encoding="utf-8") and "innerHTML" not in js


@pytest.mark.parametrize("valor, esperado", [
    ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"), ("+1", "'+1"), ("-1+2", "'-1+2"), ("@SOMA(A1)", "'@SOMA(A1)"),
    ("Funções", "Funções"), (0.125, "0,125"), (5, "5"), (None, ""),
])
def test_celula_csv_sem_formula(valor, esperado):
    assert consultas.celula(valor) == esperado


# --- exportação ---

def test_exportar_csv(turma):
    resposta = client.get("/painel/exportar/indicadores.csv")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/csv")
    assert 'filename="indicadores_tia.csv"' in resposta.headers["content-disposition"]
    assert resposta.text.startswith("﻿")
    linhas = list(csv.reader(io.StringIO(resposta.text.lstrip("﻿")), delimiter=";"))
    assert linhas[0] == ["indicador", "grupo", "alunos", "respostas", "medida", "valor", "observacao"]
    indicadores = {linha[0] for linha in linhas[1:]}
    for numero in ("1.", "2.", "3.", "4.", "5."):
        assert any(i.startswith(numero) for i in indicadores), numero
    funcoes = next(linha for linha in linhas if linha[1] == "Funções e modularização" and linha[0].startswith("2."))
    assert funcoes[2] == "8" and "," in funcoes[5]
    assert 'filename="indicadores_tia_intermediario.csv"' in client.get(
        "/painel/exportar/indicadores.csv?perfil_id=intermediario").headers["content-disposition"]
    assert client.get('/painel/exportar/indicadores.csv?perfil_id=a"b').status_code == 422


# --- dados de demonstração ---

def test_dados_painel_nao_duplica(turma, capsys):
    assert dados_painel.criar_turma() == []
    assert capsys.readouterr().out.count("já existe no banco") == 12


def test_dados_painel_sem_nomes():
    codigos = [aluno[0] for aluno in dados_painel.ALUNOS]
    assert len(codigos) == 12 and all(re.fullmatch(r"DEMO-P\d\d", c) for c in codigos)
    assert all("[demonstração]" in d[1] for d in dados_painel.DIALOGOS)
    assert json.dumps(dados_painel.DIALOGOS, ensure_ascii=False).count("@") == 0
