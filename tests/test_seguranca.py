"""
Testes da autenticação e dos papéis (EAP 1.4.6, etapa 1), com o TestClient e
banco temporário (conftest). Todos pedem a fixture auth_ligada (o conftest
desliga a autenticação para os demais testes):

- senhas (scrypt com sal) e cadastro de usuários (validações, linha de comando);
- login e logout: cookie HttpOnly/SameSite=Strict/Secure, sessão no servidor e expiração;
- limite de tentativas por usuário e por IP, com atraso e auditoria;
- anti-CSRF nas escritas;
- cada papel nas rotas principais (permitido e negado), sempre com 401/403 auditado;
- auditoria com o usuário (id e papel) em toda ação;
- provedor trocável (contrato Autenticador) e modo de desenvolvimento (TIA_AUTH=desligada);
- nenhuma senha em auditoria, banco (fora do hash) ou log.

Etapa 2 (retenção, pedidos sem login, política e troca de senha, inatividade):
tests/test_seguranca_etapa2.py.

Como rodar:
    ./run_tests.sh tests/test_seguranca.py
"""

import logging
import subprocess
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import tia.api.rotas_auth as rotas_auth
import tia.core.config as config
import tia.core.database as database
from tia.api.main import app
from tia.core import auditoria
from tia.core.database import obter_conexao
from tia.seguranca import autenticador, senhas, sessoes, usuarios
from tia.seguranca.usuarios import Usuario

SENHA = "senha-de-teste-123"
CSRF_LOGIN = {"X-CSRF-Token": "login"}


@pytest.fixture(autouse=True)
def ligada(auth_ligada):
    """Autenticação ligada em todos os testes deste arquivo."""


@pytest.fixture
def pessoas():
    """Aluno A2026-S01, outro aluno A2026-S02, docente DOC-S01 e admin ADM-S01
    (senhas já definitivas: a troca obrigatória é testada na etapa 2)."""
    usuarios.criar("A2026-S01", "aluno", SENHA, "A2026-S01", temporaria=False)
    usuarios.criar("A2026-S02", "aluno", SENHA, "A2026-S02", temporaria=False)
    usuarios.criar("DOC-S01", "docente", SENHA, temporaria=False)
    usuarios.criar("ADM-S01", "admin", SENHA, temporaria=False)


def cliente() -> TestClient:
    return TestClient(app)


def logado(login: str, senha: str = SENHA) -> tuple[TestClient, dict]:
    """Cliente com a sessão aberta e o cabeçalho anti-CSRF dela."""
    c = cliente()
    resposta = c.post("/auth/login", json={"login": login, "senha": senha}, headers=CSRF_LOGIN)
    assert resposta.status_code == 200, resposta.text
    return c, {"X-CSRF-Token": resposta.json()["csrf"]}


def registros(tipo: str | None = None) -> list[dict]:
    conexao = obter_conexao()
    try:
        sql, parametros = "SELECT * FROM auditoria", ()
        if tipo:
            sql, parametros = sql + " WHERE tipo = ?", (tipo,)
        return [dict(l) for l in conexao.execute(sql + " ORDER BY id", parametros).fetchall()]
    finally:
        conexao.close()


# --- senhas e usuários ---

def test_hash_de_senha_scrypt_com_sal():
    primeiro, segundo = senhas.gerar_hash(SENHA), senhas.gerar_hash(SENHA)
    assert primeiro.startswith("scrypt$16384$8$1$") and SENHA not in primeiro
    assert primeiro != segundo  # sal diferente a cada hash
    assert senhas.conferir(SENHA, primeiro) and senhas.conferir(SENHA, segundo)
    assert not senhas.conferir(SENHA + "x", primeiro)
    assert not senhas.conferir(SENHA, "md5$abc") and not senhas.conferir(SENHA, "lixo")


@pytest.mark.parametrize("dados, mensagem", [
    (("Maria Silva", "docente", SENHA, None), "nunca o nome"),
    (("A2026-X", "aluno", SENHA, None), "aluno_id"),
    (("DOC-X", "docente", SENHA, "A2026-X"), "Só o papel aluno"),
    (("DOC-X", "diretor", SENHA, None), "Papel inválido"),
])
def test_cadastro_valida_os_dados(dados, mensagem):
    with pytest.raises(usuarios.ErroUsuario, match=mensagem):
        usuarios.criar(*dados)


def test_cadastro_recusa_senha_curta_e_id_repetido():
    with pytest.raises(senhas.SenhaFraca):
        usuarios.criar("DOC-X", "docente", "curta")
    usuarios.criar("DOC-X", "docente", SENHA)
    with pytest.raises(usuarios.ErroUsuario, match="Já existe"):
        usuarios.criar("DOC-X", "docente", SENHA)
    # criado sem dizer o contrário, a senha é temporária (troca no primeiro acesso)
    assert usuarios.listar() == [Usuario("DOC-X", "docente", None, True, trocar_senha=True)]


def test_linha_de_comando_cria_desativa_e_redefine(tmp_path):
    ambiente = {"DB_PATH": str(tmp_path / "cli.db"), "PATH": "", "PYTHONIOENCODING": "utf-8"}

    def rodar(*args, entrada=""):
        return subprocess.run([sys.executable, "-m", "tia.seguranca.usuarios", *args], input=entrada,
                              capture_output=True, text=True, env=ambiente)

    criado = rodar("criar", "--id", "DOC-CLI", "--papel", "docente", "--senha-stdin", entrada=SENHA + "\n")
    assert criado.returncode == 0 and "DOC-CLI" in criado.stdout and SENHA not in criado.stdout + criado.stderr
    assert rodar("redefinir-senha", "--id", "DOC-CLI", "--senha-stdin", entrada="outra-senha-456\n").returncode == 0
    assert "Desativado" in rodar("desativar", "--id", "DOC-CLI").stdout
    assert "'ativo': False" in rodar("listar").stdout
    assert rodar("criar", "--id", "X", "--papel", "docente", "--senha", SENHA).returncode != 0  # nunca na linha


# --- login e logout ---

def test_login_abre_sessao_com_cookie_seguro(pessoas, monkeypatch):
    monkeypatch.setattr(config, "AUTH_COOKIE_SEGURO", True)
    resposta = cliente().post("/auth/login", json={"login": "DOC-S01", "senha": SENHA}, headers=CSRF_LOGIN)
    assert resposta.status_code == 200
    cookie = resposta.headers["set-cookie"]
    assert cookie.startswith("tia_sessao=") and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" in cookie and f"Max-Age={config.AUTH_SESSAO_MAXIMA_MINUTOS * 60}" in cookie
    corpo = resposta.json()
    assert corpo["usuario"] == {"id": "DOC-S01", "papel": "docente", "aluno_id": None, "trocar_senha": False}
    assert len(corpo["csrf"]) > 20
    assert SENHA not in resposta.text and "hash" not in resposta.text  # nem a senha nem o hash


def test_eu_login_logout(pessoas):
    c = cliente()
    assert c.get("/auth/eu").json() == {"autenticacao": "ligada", "usuario": None, "csrf": None}
    c, csrf = logado("A2026-S01")
    eu = c.get("/auth/eu").json()
    assert eu["usuario"]["aluno_id"] == "A2026-S01" and eu["csrf"] == csrf["X-CSRF-Token"]
    assert c.get("/alunos/A2026-S01/dialogo").status_code == 200
    assert c.post("/auth/logout").status_code == 403          # sair também exige o anti-CSRF
    assert c.post("/auth/logout", headers=csrf).status_code == 204
    assert c.get("/alunos/A2026-S01/dialogo").status_code == 401
    assert c.get("/auth/eu").json()["usuario"] is None
    assert [r["tipo"] for r in registros() if r["tipo"] in ("login", "logout")] == ["login", "logout"]


def test_login_recusado_com_mensagem_unica(pessoas, monkeypatch):
    pausas = []
    monkeypatch.setattr(config, "AUTH_ATRASO_SEGUNDOS", 0.5)
    monkeypatch.setattr(rotas_auth.time, "sleep", pausas.append)
    c = cliente()
    errada = c.post("/auth/login", json={"login": "DOC-S01", "senha": "errada-errada"}, headers=CSRF_LOGIN)
    inexistente = c.post("/auth/login", json={"login": "NAO-EXISTE", "senha": SENHA}, headers=CSRF_LOGIN)
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json() == {"detail": "Usuário ou senha incorretos."}  # não revela quem existe
    assert pausas == [0.5, 0.5]  # atraso em cada falha
    assert "tia_sessao" not in errada.headers.get("set-cookie", "")
    falhas = registros("login_falha")
    assert [r["motivo"] for r in falhas] == ["login=DOC-S01", "login=NAO-EXISTE"]
    assert all(r["usuario_id"] is None and r["usuario_papel"] == "anonimo" for r in falhas)


def test_login_exige_cabecalho_anti_csrf(pessoas):
    assert cliente().post("/auth/login", json={"login": "DOC-S01", "senha": SENHA}).status_code == 403


def test_nome_digitado_no_login_nao_vai_para_a_auditoria(pessoas):
    cliente().post("/auth/login", json={"login": "Maria da Silva", "senha": SENHA}, headers=CSRF_LOGIN)
    assert registros("login_falha")[-1]["motivo"] == "login=(fora do formato de código)"


def test_sessao_expira(pessoas, monkeypatch):
    c, _ = logado("DOC-S01")
    assert c.get("/painel/competencias").status_code == 200
    token = c.cookies.get("tia_sessao")
    depois = datetime.now() + timedelta(minutes=config.AUTH_SESSAO_MAXIMA_MINUTOS + 1)
    assert sessoes.ler_sessao(token, agora=depois, renovar=False) is None
    monkeypatch.setattr(config, "AUTH_SESSAO_MAXIMA_MINUTOS", -1)  # sessões novas já nascem vencidas
    vencida, _ = logado("DOC-S01")
    assert vencida.get("/painel/competencias").status_code == 401


def test_desativar_e_redefinir_senha_encerram_sessoes(pessoas):
    aluno, _ = logado("A2026-S01")
    docente, _ = logado("DOC-S01")
    usuarios.redefinir_senha("A2026-S01", "nova-senha-789")
    assert aluno.get("/alunos/A2026-S01/dialogo").status_code == 401
    assert cliente().post("/auth/login", json={"login": "A2026-S01", "senha": SENHA},
                          headers=CSRF_LOGIN).status_code == 401
    logado("A2026-S01", "nova-senha-789")
    usuarios.desativar("DOC-S01")
    assert docente.get("/painel/competencias").status_code == 401
    assert cliente().post("/auth/login", json={"login": "DOC-S01", "senha": SENHA},
                          headers=CSRF_LOGIN).status_code == 401


# --- limite de tentativas ---

def tentar(c, login, senha):
    return c.post("/auth/login", json={"login": login, "senha": senha}, headers=CSRF_LOGIN)


def test_bloqueio_por_usuario(pessoas):
    c = cliente()
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO):
        assert tentar(c, "DOC-S01", "errada-errada").status_code == 401
    bloqueado = tentar(c, "DOC-S01", SENHA)  # nem a senha certa entra
    assert bloqueado.status_code == 429 and "Aguarde" in bloqueado.json()["detail"]
    assert tentar(c, "DOC-S02-INEXISTENTE", "x").status_code == 401  # outro login não é afetado
    assert tentar(c, "A2026-S01", SENHA).status_code == 200
    registro = registros("login_bloqueado")[-1]
    assert "DOC-S01" in registro["motivo"] and "usuario" in registro["motivo"]
    # passada a janela, volta a entrar
    depois = datetime.now() + timedelta(minutes=config.AUTH_JANELA_MINUTOS + 1)
    assert sessoes.bloqueio("DOC-S01", "testclient", agora=depois) is None


def test_sucesso_zera_a_contagem_do_usuario(pessoas):
    c = cliente()
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO - 1):
        tentar(c, "DOC-S01", "errada-errada")
    assert tentar(c, "DOC-S01", SENHA).status_code == 200
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO - 1):
        tentar(c, "DOC-S01", "errada-errada")
    assert tentar(c, "DOC-S01", SENHA).status_code == 200


def test_bloqueio_por_ip(pessoas, monkeypatch):
    monkeypatch.setattr(config, "AUTH_MAX_FALHAS_IP", 3)
    c = cliente()
    for login in ("X-1", "X-2", "X-3"):
        tentar(c, login, "errada-errada")
    assert tentar(c, "DOC-S01", SENHA).status_code == 429
    assert "ip" in registros("login_bloqueado")[-1]["motivo"]


# --- anti-CSRF ---

def test_escrita_exige_o_token_anti_csrf_da_sessao(pessoas):
    c, csrf = logado("DOC-S01")
    corpo = {"vetada": False}
    sem = c.patch("/tutor/dialogo/1/veto", json=corpo)
    errado = c.patch("/tutor/dialogo/1/veto", json=corpo, headers={"X-CSRF-Token": "outro"})
    assert sem.status_code == errado.status_code == 403 and "anti-CSRF" in sem.json()["detail"]
    assert c.patch("/tutor/dialogo/1/veto", json=corpo, headers=csrf).status_code == 404  # passou: diálogo não existe
    # o token de outra sessão não serve
    _, outro = logado("DOC-S01")
    assert c.patch("/tutor/dialogo/1/veto", json=corpo, headers=outro).status_code == 403
    negados = registros("acesso_negado")
    assert len(negados) == 3 and negados[0]["referencia_id"] == "PATCH /tutor/dialogo/1/veto"
    assert negados[0]["usuario_id"] == "DOC-S01"


def test_leitura_nao_precisa_do_token(pessoas):
    c, _ = logado("DOC-S01")
    assert c.get("/painel/competencias").status_code == 200


# --- papéis nas rotas principais ---

LEITURAS_DO_ALUNO = ["/aluno/{a}/estado", "/aluno/{a}/proximo", "/alunos/{a}/trilha", "/alunos/{a}/dialogo",
                     "/alunos/{a}/feedbacks", "/relatorio/aluno/{a}?narrativa=false"]
ROTAS_DO_DOCENTE = ["/painel/alunos-em-risco", "/painel/competencias", "/painel/revisao", "/painel/auditoria",
                    "/painel/exportar/indicadores.csv", "/relatorio/turma?narrativa=false", "/auditoria/A2026-S01"]


def permitido(resposta) -> bool:
    return resposta.status_code not in (401, 403)


@pytest.mark.parametrize("rota", LEITURAS_DO_ALUNO + ["/tutor/incentivo/{a}"])
def test_aluno_le_so_os_proprios_dados(pessoas, rota):
    c, _ = logado("A2026-S01")
    assert permitido(c.get(rota.format(a="A2026-S01")))
    negado = c.get(rota.format(a="A2026-S02"))
    assert negado.status_code == 403 and negado.json()["detail"] == "Você só pode acessar os seus próprios dados."


def test_aluno_escreve_so_em_nome_proprio(pessoas):
    c, csrf = logado("A2026-S01")
    matricula = {"perfil_id": "intermediario", "horas_semanais": 6, "diagnostico": {}}
    assert c.post("/aluno/A2026-S01/iniciar", json=matricula, headers=csrf).status_code == 200
    assert c.post("/aluno/A2026-S02/iniciar", json=matricula, headers=csrf).status_code == 403
    for rota, corpo in (("/tutor/perguntar", {"aluno_id": "A2026-S02", "pergunta": "O que é uma lista?"}),
                        ("/tutor/sessao", {"aluno_id": "A2026-S02", "competencia_id": "funcoes"}),
                        ("/planejador/trilha", {"aluno_id": "A2026-S02", "perfil_id": "iniciante",
                                                "horas_semanais": 6}),
                        ("/aluno/A2026-S02/sessao", {"competencia_id": "funcoes"})):
        assert c.post(rota, json=corpo, headers=csrf).status_code == 403, rota
    assert permitido(c.post("/tutor/sessao", json={"aluno_id": "A2026-S01", "competencia_id": "funcoes"},
                            headers=csrf))
    negado = registros("acesso_negado")[-1]
    assert (negado["aluno_id"], negado["usuario_id"], negado["usuario_papel"]) == ("A2026-S02", "A2026-S01", "aluno")


@pytest.mark.parametrize("rota", ROTAS_DO_DOCENTE)
def test_rotas_do_docente(pessoas, rota):
    docente, _ = logado("DOC-S01")
    assert docente.get(rota).status_code == 200
    for login in ("A2026-S01", "ADM-S01"):
        c, _ = logado(login)
        negado = c.get(rota)
        assert negado.status_code == 403 and "docente" in negado.json()["detail"]
    assert cliente().get(rota).status_code == 401


def test_docente_le_dados_do_aluno_mas_nao_age_por_ele(pessoas):
    c, csrf = logado("DOC-S01")
    for rota in LEITURAS_DO_ALUNO:
        assert permitido(c.get(rota.format(a="A2026-S01"))), rota
    assert c.get("/tutor/incentivo/A2026-S01").status_code == 403
    assert c.post("/aluno/A2026-S01/evento", json={"evento_id": "e1", "tipo": "conclusao"},
                  headers=csrf).status_code == 403
    assert c.post("/tutor/perguntar", json={"aluno_id": "A2026-S01", "pergunta": "x"}, headers=csrf).status_code == 403


def test_veto_so_docente(pessoas):
    for login, esperado in (("A2026-S01", 403), ("ADM-S01", 403), ("DOC-S01", 404)):
        c, csrf = logado(login)
        for rota in ("/tutor/dialogo/9/veto", "/tutor/feedback/9/veto"):
            assert c.patch(rota, json={"vetada": False}, headers=csrf).status_code == esperado, (login, rota)


def test_conteudo_para_qualquer_usuario_logado(pessoas):
    for login in ("A2026-S01", "DOC-S01"):
        c, _ = logado(login)
        assert c.get("/conteudo/ementa").status_code == 200
    assert cliente().get("/conteudo/ementa").status_code == 401


def test_admin_gerencia_usuarios(pessoas):
    admin, csrf = logado("ADM-S01")
    assert {u["id"] for u in admin.get("/admin/usuarios").json()} == {"A2026-S01", "A2026-S02", "DOC-S01", "ADM-S01"}
    assert "hash" not in admin.get("/admin/usuarios").text  # a lista nunca traz o hash da senha
    novo = admin.post("/admin/usuarios", json={"id": "DOC-S02", "papel": "docente", "senha": SENHA}, headers=csrf)
    assert novo.status_code == 201 and novo.json() == {"id": "DOC-S02", "papel": "docente", "aluno_id": None,
                                                        "ativo": True, "trocar_senha": True}
    assert admin.post("/admin/usuarios", json={"id": "DOC-S03", "papel": "docente", "senha": "curta"},
                      headers=csrf).status_code == 422
    assert admin.post("/admin/usuarios/DOC-S02/senha", json={"senha": "outra-senha-456"},
                      headers=csrf).status_code == 204
    assert admin.post("/admin/usuarios/DOC-S02/desativar", headers=csrf).status_code == 204
    assert admin.post("/admin/usuarios/ADM-S01/desativar", headers=csrf).status_code == 409
    assert admin.post("/admin/usuarios/NINGUEM/desativar", headers=csrf).status_code == 404
    acoes = [r["motivo"] for r in registros("gestao_usuario") if r["referencia_id"] == "DOC-S02"]
    assert acoes == ["usuário criado (papel docente); senha temporária", "senha redefinida; senha temporária",
                     "usuário desativado"]
    assert all(r["usuario_id"] == "ADM-S01" for r in registros("gestao_usuario") if r["referencia_id"] == "DOC-S02")
    for login in ("A2026-S01", "DOC-S01"):
        c, _ = logado(login)
        assert c.get("/admin/usuarios").status_code == 403


def test_sem_login_401_auditado_e_rotas_publicas():
    c = cliente()
    resposta = c.get("/aluno/A2026-S01/estado")
    assert resposta.status_code == 401 and "Faça login" in resposta.json()["detail"]
    registro = registros("acesso_negado")[-1]
    assert (registro["referencia_id"], registro["origem"], registro["usuario_papel"]) == (
        "GET /aluno/A2026-S01/estado", "401", "anonimo")
    for publica in ("/health", "/app/", "/app/painel/", "/auth/eu"):
        assert c.get(publica).status_code == 200, publica


# --- auditoria com o usuário ---

def test_auditoria_grava_o_usuario_em_toda_acao(pessoas, monkeypatch):
    from tia.agentes.tutor.repositorio import registrar_dialogo
    import tia.agentes.tutor.dialogo as dialogo
    monkeypatch.setattr(dialogo, "buscar_trechos_dialogo", lambda pergunta, materiais: [])
    aluno, csrf_aluno = logado("A2026-S01")
    assert aluno.post("/tutor/perguntar", json={"aluno_id": "A2026-S01", "pergunta": "O que é uma lista?"},
                      headers=csrf_aluno).status_code == 200
    dialogo_id = registrar_dialogo("A2026-S02", None, "p", "r", [], "LLM", 10)  # fora de requisição: sistema
    docente, csrf = logado("DOC-S01")
    docente.get("/painel/alunos-em-risco")
    docente.get("/painel/revisao")
    docente.patch(f"/tutor/dialogo/{dialogo_id}/veto", json={"vetada": True, "correcao_docente": "Correção."},
                  headers=csrf)
    quem = {r["tipo"] + ":" + (r["referencia_id"] or ""): (r["usuario_id"], r["usuario_papel"]) for r in registros()}
    assert quem["dialogo:1"] == ("A2026-S01", "aluno")
    assert quem[f"dialogo:{dialogo_id}"] == (None, "sistema")
    assert quem["consulta_painel:alunos_em_risco"] == ("DOC-S01", "docente")
    assert quem["consulta_painel:revisao"] == ("DOC-S01", "docente")
    assert quem[f"veto_docente:{dialogo_id}"] == ("DOC-S01", "docente")
    # e a tela de auditoria do painel mostra o usuário
    pagina = docente.get("/painel/auditoria?agente=tutor").json()["registros"]
    veto = next(x for x in pagina if x["tipo"] == "veto_docente")
    assert (veto["usuario_id"], veto["usuario_papel"]) == ("DOC-S01", "docente")
    assert docente.get("/painel/auditoria?agente=seguranca").json()["total"] >= 2  # os logins


# --- nenhuma senha em auditoria, banco ou log ---

def test_senha_nunca_fica_gravada(pessoas, caplog):
    caplog.set_level(logging.DEBUG)
    c = cliente()
    tentar(c, "DOC-S01", "senha-errada-secreta")
    c, csrf = logado("ADM-S01")
    c.post("/admin/usuarios", json={"id": "DOC-S09", "papel": "docente", "senha": "senha-nova-secreta"}, headers=csrf)
    c.post("/admin/usuarios/DOC-S09/senha", json={"senha": "senha-trocada-secreta"}, headers=csrf)
    conexao = database.obter_conexao()
    try:
        despejo = "\n".join(conexao.iterdump())
    finally:
        conexao.close()
    for senha in (SENHA, "senha-errada-secreta", "senha-nova-secreta", "senha-trocada-secreta"):
        assert senha not in despejo, senha
        assert senha not in caplog.text, senha


# --- provedor trocável e usuários de demonstração ---

def test_provedor_trocavel(pessoas, monkeypatch):
    class AutenticadorFalso:
        """Simula o login único do EBAULA: um "ticket" vira um usuário do TIA."""
        nome = "falso"

        def autenticar(self, credenciais):
            return Usuario("DOC-S01", "docente", None, True) if credenciais.get("senha") == "ticket-ok" else None

    monkeypatch.setitem(autenticador.PROVEDORES, "falso", AutenticadorFalso)
    monkeypatch.setattr(config, "AUTH_PROVEDOR", "falso")
    c, _ = logado("qualquer", "ticket-ok")
    assert c.get("/painel/competencias").status_code == 200
    assert registros("login")[-1]["origem"] == "falso"
    monkeypatch.setattr(config, "AUTH_PROVEDOR", "inexistente")
    with pytest.raises(RuntimeError, match="AUTH_PROVEDOR"):
        autenticador.obter_autenticador()


def test_usuarios_de_demonstracao():
    assert usuarios.criar_usuarios_demonstracao() == ["DEMO-W01", "DEMO-DOCENTE"]
    assert usuarios.criar_usuarios_demonstracao() == []
    aluno, _ = logado("DEMO-W01", usuarios.SENHA_DEMONSTRACAO)
    assert aluno.get("/auth/eu").json()["usuario"] == {"id": "DEMO-W01", "papel": "aluno", "aluno_id": "DEMO-W01",
                                                       "trocar_senha": False}  # demonstração: sem troca
    docente, _ = logado("DEMO-DOCENTE", usuarios.SENHA_DEMONSTRACAO)
    assert docente.get("/painel/competencias").status_code == 200
    assert "FICTICIA" in usuarios.SENHA_DEMONSTRACAO


# --- modo de desenvolvimento ---

def test_modo_desligado(pessoas, monkeypatch):
    monkeypatch.setattr(config, "AUTH_DESLIGADA", True)
    c = cliente()
    assert c.get("/auth/eu").json() == {"autenticacao": "desligada", "usuario": None, "csrf": None}
    assert c.get("/painel/alunos-em-risco").status_code == 200  # sem login
    assert registros("consulta_painel")[-1]["usuario_papel"] == "sem_login"
    assert c.post("/auth/login", json={"login": "DOC-S01", "senha": SENHA}, headers=CSRF_LOGIN).status_code == 409


def test_padrao_e_autenticacao_ligada():
    resultado = subprocess.run([sys.executable, "-c", "import tia.core.config as c; print(c.AUTH_DESLIGADA)"],
                               capture_output=True, text=True, env={"PATH": "", "TIA_AUTH": ""})
    assert resultado.stdout.strip() == "False"
    desligada = subprocess.run([sys.executable, "-c", "import tia.core.config as c; print(c.AUTH_DESLIGADA)"],
                               capture_output=True, text=True, env={"PATH": "", "TIA_AUTH": "desligada"})
    assert desligada.stdout.strip() == "True"


def test_registro_fora_de_requisicao_e_do_sistema():
    conexao = obter_conexao()
    with conexao:
        auditoria.registrar(conexao, None, "relatorio_turma", None, "fallback", [])
    conexao.close()
    assert (registros()[-1]["usuario_id"], registros()[-1]["usuario_papel"]) == (None, "sistema")
