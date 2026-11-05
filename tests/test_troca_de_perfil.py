"""
Testes do logout e da troca de perfil no mesmo navegador (docente -> aluno e
aluno -> docente), EAP 1.4.6.

- servidor: POST /auth/logout encerra a sessão no banco e apaga o cookie
  (mesmo nome, Path=/, HttpOnly, SameSite=Strict); o token antigo deixa de
  valer; depois dele, o mesmo cliente entra com o outro perfil;
- login por cima de uma sessão aberta (sem sair antes): o login bem-sucedido
  encerra a sessão anterior do cookie, com auditoria; senha errada não mexe
  nela; cookie inválido ou vencido não atrapalha; mesmo usuário = uma sessão;
- páginas (/app e /app/painel): com sessão de outro perfil, a tela de login
  mostra "Você está conectado como X. Sair para entrar como Y." e um botão
  Sair que chama o logout (o menu, com o Sair de sempre, some no login);
- comum.js executado de verdade no gjs (motor JavaScript do GNOME), com um
  DOM mínimo simulado: a mensagem, o logout com o token anti-CSRF, o 401
  tratado como "já saiu" e o erro que não finge que saiu. Sem gjs, esses
  testes são pulados.

Como rodar:
    ./run_tests.sh tests/test_troca_de_perfil.py
"""

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tia.api.main import app
from tia.core.database import obter_conexao
from tia.seguranca import sessoes, usuarios
from tia.web import PASTA_ESTATICA

SENHA = "senha-de-teste-123"
CSRF_LOGIN = {"X-CSRF-Token": "login"}


@pytest.fixture(autouse=True)
def ligada(auth_ligada):
    """Autenticação ligada em todos os testes deste arquivo."""


@pytest.fixture
def pessoas():
    usuarios.criar("A2026-T01", "aluno", SENHA, "A2026-T01", temporaria=False)
    usuarios.criar("DOC-T01", "docente", SENHA, temporaria=False)


def entrar(c: TestClient, login: str) -> dict:
    resposta = c.post("/auth/login", json={"login": login, "senha": SENHA}, headers=CSRF_LOGIN)
    assert resposta.status_code == 200, resposta.text
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def ler(nome: str) -> str:
    return (PASTA_ESTATICA / nome).read_text(encoding="utf-8")


# --- servidor ---

def test_logout_encerra_a_sessao_e_apaga_o_cookie(pessoas):
    c = TestClient(app)
    csrf = entrar(c, "DOC-T01")
    token = c.cookies.get("tia_sessao")
    assert sessoes.ler_sessao(token) is not None
    resposta = c.post("/auth/logout", headers=csrf)
    assert resposta.status_code == 204
    cookie = resposta.headers["set-cookie"]
    # o navegador só apaga se nome, Path (e Domain) baterem com o cookie do login
    assert cookie.startswith('tia_sessao=""') and "Max-Age=0" in cookie and "Path=/" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "tia_sessao" not in c.cookies
    assert sessoes.ler_sessao(token) is None                  # encerrada no servidor, não só no navegador
    velho = TestClient(app, cookies={"tia_sessao": token})   # quem guardou o token não volta com ele
    assert velho.get("/auth/eu").json()["usuario"] is None
    assert velho.get("/painel/alunos").status_code == 401


def test_logout_sem_sessao_responde_401(pessoas):
    """A página trata este 401 como "já tinha saído" (comum.js), sem aviso de sessão terminada."""
    assert TestClient(app).post("/auth/logout", headers=CSRF_LOGIN).status_code == 401


@pytest.mark.parametrize("primeiro, segundo, rota_do_segundo", [
    ("DOC-T01", "A2026-T01", "/alunos/A2026-T01/dialogo"),
    ("A2026-T01", "DOC-T01", "/painel/alunos"),
])
def test_trocar_de_perfil_no_mesmo_navegador(pessoas, primeiro, segundo, rota_do_segundo):
    c = TestClient(app)  # um só pote de cookies, como um navegador
    csrf = entrar(c, primeiro)
    assert c.get("/auth/eu").json()["usuario"]["id"] == primeiro
    assert c.post("/auth/logout", headers=csrf).status_code == 204
    assert c.get("/auth/eu").json()["usuario"] is None
    entrar(c, segundo)
    eu = c.get("/auth/eu").json()["usuario"]
    assert eu["id"] == segundo
    assert c.get(rota_do_segundo).status_code == 200


def test_perfis_continuam_separados(pessoas):
    """A troca não abre brecha: cada sessão continua com o seu papel."""
    docente, aluno = TestClient(app), TestClient(app)
    entrar(docente, "DOC-T01")
    entrar(aluno, "A2026-T01")
    assert docente.get("/painel/alunos").status_code == 200
    assert aluno.get("/painel/alunos").status_code == 403
    assert TestClient(app).get("/painel/alunos").status_code == 401


# --- login por cima de uma sessão aberta ---

def sessoes_do(usuario_id: str) -> int:
    conexao = obter_conexao()
    try:
        return conexao.execute("SELECT COUNT(*) FROM auth_sessoes WHERE usuario_id = ?", (usuario_id,)).fetchone()[0]
    finally:
        conexao.close()


def saidas_auditadas() -> list[dict]:
    conexao = obter_conexao()
    try:
        return [dict(l) for l in conexao.execute(
            "SELECT usuario_id, usuario_papel, origem, motivo FROM auditoria WHERE tipo = 'logout' ORDER BY id")]
    finally:
        conexao.close()


@pytest.mark.parametrize("primeiro, papel, segundo, rota_do_primeiro, rota_do_segundo", [
    ("DOC-T01", "docente", "A2026-T01", "/painel/alunos", "/alunos/A2026-T01/dialogo"),
    ("A2026-T01", "aluno", "DOC-T01", "/alunos/A2026-T01/dialogo", "/painel/alunos"),
])
def test_login_de_outro_perfil_encerra_a_sessao_anterior(pessoas, primeiro, papel, segundo,
                                                          rota_do_primeiro, rota_do_segundo):
    c = TestClient(app)
    entrar(c, primeiro)
    antigo = c.cookies.get("tia_sessao")
    entrar(c, segundo)  # sem POST /auth/logout antes
    assert sessoes.ler_sessao(antigo) is None and sessoes_do(primeiro) == 0
    assert TestClient(app, cookies={"tia_sessao": antigo}).get(rota_do_primeiro).status_code == 401
    assert c.get("/auth/eu").json()["usuario"]["id"] == segundo
    assert c.get(rota_do_segundo).status_code == 200
    assert saidas_auditadas() == [{"usuario_id": primeiro, "usuario_papel": papel, "origem": "sessao",
                                   "motivo": "sessão anterior encerrada por um novo login neste navegador"}]


def test_senha_errada_nao_encerra_a_sessao_existente(pessoas):
    c = TestClient(app)
    entrar(c, "DOC-T01")
    token = c.cookies.get("tia_sessao")
    errada = c.post("/auth/login", json={"login": "A2026-T01", "senha": "senha-errada-999"}, headers=CSRF_LOGIN)
    assert errada.status_code == 401
    assert c.cookies.get("tia_sessao") == token and sessoes.ler_sessao(token) is not None
    assert c.get("/painel/alunos").status_code == 200
    assert saidas_auditadas() == []


def test_mesmo_usuario_fica_com_uma_sessao(pessoas):
    c = TestClient(app)
    entrar(c, "DOC-T01")
    antigo = c.cookies.get("tia_sessao")
    csrf = entrar(c, "DOC-T01")
    assert sessoes_do("DOC-T01") == 1 and sessoes.ler_sessao(antigo) is None
    assert c.post("/auth/logout", headers=csrf).status_code == 204  # o anti-CSRF novo é o que vale
    assert sessoes_do("DOC-T01") == 0


@pytest.mark.parametrize("cookie", ["token-inventado", "", "x" * 500])
def test_cookie_invalido_nao_quebra_o_login(pessoas, cookie):
    c = TestClient(app, cookies={"tia_sessao": cookie})
    entrar(c, "A2026-T01")
    assert c.get("/auth/eu").json()["usuario"]["id"] == "A2026-T01"
    assert saidas_auditadas() == []


def test_cookie_de_sessao_vencida_nao_quebra_o_login(pessoas):
    vencido, _ = sessoes.criar_sessao("DOC-T01", agora=datetime.now() - timedelta(days=30))
    assert sessoes.ler_sessao(vencido) is None
    c = TestClient(app, cookies={"tia_sessao": vencido})
    entrar(c, "A2026-T01")
    assert c.get("/auth/eu").json()["usuario"]["id"] == "A2026-T01"
    assert saidas_auditadas() == []


# --- páginas (leitura do HTML/JS) ---

PAGINAS = [("index.html", "app.js", "aluno"), ("painel/index.html", "painel/painel.js", "docente")]


@pytest.mark.parametrize("html, js, papel_da_pagina", PAGINAS)
def test_login_com_outro_perfil_tem_mensagem_e_botao_sair(html, js, papel_da_pagina):
    html, js = ler(html), ler(js)
    tela_login = re.search(r'<section[^>]*id="tela-login".*?</section>', html, re.S).group(0)
    # o botão fica dentro da tela de login (o menu, com o Sair de sempre, some no login)
    assert 'id="login-outro-papel"' in tela_login and 'id="sair-outro-papel"' in tela_login
    assert '$("sair-outro-papel").addEventListener("click", encerrarSessao)' in js
    assert '$("sair").addEventListener("click", encerrarSessao)' in js
    assert f'TIA.mensagemOutroPapel(situacao.usuario.papel, "{papel_da_pagina}")' in js
    assert '$("login-outro-papel").hidden' in js


@pytest.mark.parametrize("js", ["app.js", "painel/painel.js"])
def test_sair_chama_o_logout_e_volta_ao_login(js):
    js = ler(js)
    corpo = re.search(r"async function encerrarSessao\(\) \{(.*?)\n  \}", js, re.S).group(1)
    assert "TIA.sair()" in corpo and 'mostrarLogin("Você saiu.")' in corpo
    assert "return;" in corpo  # se o logout falhar, não finge que saiu


def test_comum_chama_o_endpoint_de_logout():
    comum = ler("comum.js")
    assert 'chamar("POST", "/auth/logout"' in comum
    assert "document.cookie" not in comum  # o cookie é HttpOnly: quem apaga é o servidor


# --- comum.js executado no gjs ---

GJS = shutil.which("gjs")

# DOM, temporizadores e fetch mínimos para o comum.js rodar fora do navegador
STUBS = r"""
globalThis.window = globalThis;
const elementos = {};
function no(id) {
  if (!elementos[id]) elementos[id] = { id, hidden: true, textContent: "", disabled: false, dataset: {},
    focus() {}, setAttribute() {}, getAttribute() { return null; } };
  return elementos[id];
}
globalThis.document = { getElementById: no, querySelectorAll: () => [], body: { setAttribute() {} } };
globalThis.Node = function () {};
let temporizadores = [];
globalThis.setTimeout = (f) => { temporizadores.push(f); return 1; };
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 2;
globalThis.clearInterval = () => {};
globalThis.AbortController = class { constructor() { this.signal = {}; } abort() {} };
const pedidos = [];
let respostas = [];
globalThis.fetch = async (url, opcoes) => {
  pedidos.push({ url, metodo: opcoes.method, csrf: (opcoes.headers || {})["X-CSRF-Token"] || null });
  const r = respostas.shift();
  if (r === "rede") throw new TypeError("sem rede");
  return { ok: r.status < 300, status: r.status,
           json: async () => { if (r.corpo === undefined) throw new Error("sem corpo"); return r.corpo; } };
};
"""

CENARIOS = r"""
let exigiuLogin = 0;
TIA.configurar({ aoExigirLogin: () => { exigiuLogin += 1; } });
const SESSAO = { status: 200, corpo: { autenticacao: "ligada", csrf: "csrf-da-sessao",
                                       usuario: { id: "DOC-T01", papel: "docente", aluno_id: null } } };
async function rodarTemporizadores() { const t = temporizadores; temporizadores = []; t.forEach((f) => f()); }
async function ultimoCsrfDepoisDeUmaEscrita() {
  respostas.push({ status: 200, corpo: {} });
  await TIA.chamar("POST", "/qualquer", {});
  return pedidos[pedidos.length - 1].csrf;
}
(async () => {
  const r = {};
  r.mensagens = [TIA.mensagemOutroPapel("docente", "aluno"), TIA.mensagemOutroPapel("aluno", "docente"),
                 TIA.mensagemOutroPapel("admin", "aluno")];

  respostas.push(SESSAO); await TIA.obterSessao();
  respostas.push({ status: 204 }); await TIA.sair();
  const logout = pedidos[pedidos.length - 1];
  r.logout = { url: logout.url, metodo: logout.metodo, csrf: logout.csrf };
  r.csrf_depois_de_sair = await ultimoCsrfDepoisDeUmaEscrita();

  respostas.push(SESSAO); await TIA.obterSessao();
  respostas.push({ status: 401, corpo: { detail: "Faça login para continuar." } });
  try { await TIA.sair(); r.sair_401 = "resolveu"; } catch (e) { r.sair_401 = "lançou"; }
  await rodarTemporizadores();
  r.exigiu_login_no_401_do_logout = exigiuLogin;

  for (const falha of [{ status: 403, corpo: { detail: "anti-CSRF" } }, "rede"]) {
    respostas.push(SESSAO); await TIA.obterSessao();
    respostas.push(falha);
    try { await TIA.sair(); r["sair_" + (falha.status || falha)] = "resolveu"; }
    catch (e) { r["sair_" + (falha.status || falha)] = "lançou"; }
    r["csrf_depois_de_" + (falha.status || falha)] = await ultimoCsrfDepoisDeUmaEscrita();
  }

  respostas.push({ status: 401, corpo: { detail: "Faça login." } });
  try { await TIA.chamar("GET", "/painel/alunos"); } catch (_) { /* esperado */ }
  await rodarTemporizadores();
  r.exigiu_login_em_outra_rota = exigiuLogin;
  print(JSON.stringify(r));
})().catch((e) => print(JSON.stringify({ erro: String(e) })));
"""


@pytest.fixture(scope="module")
def resultado_gjs(tmp_path_factory) -> dict:
    if not GJS:
        pytest.skip("gjs não instalado: o comportamento do comum.js não foi executado")
    script = tmp_path_factory.mktemp("gjs") / "cenarios.js"
    script.write_text(STUBS + ler("comum.js") + CENARIOS, encoding="utf-8")
    saida = subprocess.run([GJS, str(script)], capture_output=True, text=True, timeout=30)
    assert saida.returncode == 0, saida.stderr
    resultado = json.loads(saida.stdout.strip().splitlines()[-1])
    assert "erro" not in resultado, resultado
    return resultado


def test_gjs_mensagem_de_outro_perfil(resultado_gjs):
    assert resultado_gjs["mensagens"] == [
        "Você está conectado como docente. Sair para entrar como aluno.",
        "Você está conectado como aluno. Sair para entrar como docente.",
        "Você está conectado como administrador. Sair para entrar como aluno.",
    ]


def test_gjs_sair_manda_o_logout_com_o_anti_csrf_e_esquece_o_token(resultado_gjs):
    assert resultado_gjs["logout"] == {"url": "/auth/logout", "metodo": "POST", "csrf": "csrf-da-sessao"}
    assert resultado_gjs["csrf_depois_de_sair"] is None


def test_gjs_logout_com_sessao_ja_vencida_conta_como_saida(resultado_gjs):
    assert resultado_gjs["sair_401"] == "resolveu"
    assert resultado_gjs["exigiu_login_no_401_do_logout"] == 0  # sem o aviso "sua sessão terminou" por cima
    assert resultado_gjs["exigiu_login_em_outra_rota"] == 1     # nas outras rotas o aviso continua


@pytest.mark.parametrize("falha", ["403", "rede"])
def test_gjs_logout_que_falha_nao_finge_que_saiu(resultado_gjs, falha):
    assert resultado_gjs[f"sair_{falha}"] == "lançou"
    assert resultado_gjs[f"csrf_depois_de_{falha}"] == "csrf-da-sessao"  # a sessão segue utilizável
