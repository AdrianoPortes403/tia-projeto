"""
Testes do plug-in do EBAULA (EAP 1.4.3): arquivos servidos em /app/plugin/, liberação do iframe
pela variável TIA_FRAME_ANCESTORS e análise estática do JavaScript. O comportamento do plug-in no
navegador (DOM simulado) é testado em plugin-ebaula/teste/ (Node + jsdom).

Como rodar:
    ./run_tests.sh tests/test_plugin_ebaula.py
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tia.core.config as config
from tia.api.main import app

client = TestClient(app)
PASTA = Path(__file__).resolve().parent.parent / "src" / "tia" / "web" / "static" / "plugin"
ORIGEM = "https://ebaula.exemplo.eb.mil.br"


def csp(caminho: str) -> str:
    return client.get(caminho).headers["content-security-policy"]


# --- arquivos servidos ---

@pytest.mark.parametrize("arquivo,tipo", [("tia-ebaula.js", "javascript"), ("tia-ebaula.css", "text/css")])
def test_arquivos_do_plugin_sao_servidos(arquivo, tipo):
    r = client.get(f"/app/plugin/{arquivo}")
    assert r.status_code == 200
    assert tipo in r.headers["content-type"]
    assert r.text == (PASTA / arquivo).read_text(encoding="utf-8")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_plugin_nao_exige_login(auth_ligada):
    # o script é carregado pela página do EBAULA antes de qualquer login do TIA
    assert client.get("/app/plugin/tia-ebaula.js").status_code == 200


# --- frame-ancestors ---

def test_por_padrao_ninguem_pode_embutir_o_tia(monkeypatch):
    monkeypatch.setattr(config, "FRAME_ANCESTORS", "")
    for caminho in ("/app/", "/app/plugin/tia-ebaula.js", "/health"):
        assert "frame-ancestors 'none'" in csp(caminho), caminho


def test_origem_do_ebaula_e_liberada_so_em_app(monkeypatch):
    monkeypatch.setattr(config, "FRAME_ANCESTORS", ORIGEM)
    c = csp("/app/")
    assert f"frame-ancestors {ORIGEM}" in c and "frame-ancestors 'none'" not in c
    assert "script-src 'self'" in c and "unsafe-inline" not in c  # o resto da CSP não muda
    # a API (JSON) continua sem poder ser embutida
    assert "frame-ancestors 'none'" in csp("/health")
    assert "frame-ancestors 'none'" in csp("/auth/eu")


def test_varias_origens(monkeypatch):
    monkeypatch.setattr(config, "FRAME_ANCESTORS", f"{ORIGEM}, https://*.eb.mil.br http://localhost:8080")
    c = csp("/app/")
    assert f"frame-ancestors {ORIGEM} https://*.eb.mil.br http://localhost:8080" in c


@pytest.mark.parametrize("valor", [
    "*", "https://*", "http://ebaula.exemplo.eb.mil.br", "https://a.com/caminho", "'self'",
    "https://a.com; script-src *", "https://a.com\r\nX-Evil: 1", "javascript:alert(1)", "data:",
])
def test_valor_invalido_nunca_chega_a_csp(monkeypatch, valor):
    monkeypatch.setattr(config, "FRAME_ANCESTORS", valor)
    validas, _ = config.origens_iframe(valor)
    c = csp("/app/")
    assert "frame-ancestors 'none'" in c or all(v in c for v in validas)
    assert "script-src *" not in c and "*;" not in c.replace("https://*.", "")
    assert "x-evil" not in client.get("/app/").headers


def test_origens_iframe_separa_validas_e_recusadas():
    validas, recusadas = config.origens_iframe(f"{ORIGEM} HTTPS://Outro.Exemplo.org *  http://x.com")
    assert validas == [ORIGEM, "https://outro.exemplo.org"]
    assert recusadas == ["*", "http://x.com"]
    assert config.origens_iframe("") == ([], [])


def test_aviso_de_configuracao_para_origem_recusada(monkeypatch):
    monkeypatch.setattr(config, "FRAME_ANCESTORS", f"{ORIGEM} *")
    assert any("TIA_FRAME_ANCESTORS" in a and "*" in a for a in config.avisos_de_configuracao())
    monkeypatch.setattr(config, "FRAME_ANCESTORS", ORIGEM)
    assert not any("TIA_FRAME_ANCESTORS" in a for a in config.avisos_de_configuracao())


# --- análise estática do plug-in (roda dentro da página do EBAULA: nada de brechas) ---

def js_sem_comentarios() -> str:
    js = (PASTA / "tia-ebaula.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


@pytest.mark.parametrize("proibido", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                                      "eval(", "new Function", "localStorage", "document.cookie", "XMLHttpRequest",
                                      "fetch("])
def test_plugin_nao_usa_apis_perigosas(proibido):
    assert proibido not in js_sem_comentarios()


def test_plugin_cuida_do_que_importa():
    js = js_sem_comentarios()
    assert 'setAttribute("sandbox"' in js and "referrerpolicy" in js
    assert "e.origin !== destino.origem" in js and "e.source !== estado.iframe.contentWindow" in js
    assert 'rel = "noopener noreferrer"' in js
    assert "https:" in js and "ehLocal" in js           # só https (ou http em localhost)
    assert "origem=ebaula" in js                         # a URL não leva dado de aluno (R08)
    assert "textContent" in js
