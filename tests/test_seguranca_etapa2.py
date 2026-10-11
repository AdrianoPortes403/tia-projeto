"""
Testes da etapa 2 da segurança (EAP 1.4.6, parte E), com o TestClient e banco
temporário (conftest), autenticação ligada:

- E1: limpeza das sessões vencidas e das tentativas de login fora da retenção
  (o IP fica no máximo AUTH_RETENCAO_IP_DIAS e nunca vai para a auditoria);
  limpeza pela API ao subir e pelo comando;
- E2: pedidos sem login (401) e logins bloqueados (429) agregados por origem e
  janela, com resumo na auditoria, sem perder a contagem;
- E3: política de senha configurável e troca obrigatória da senha temporária
  criada pelo admin (POST /auth/senha);
- E4: expiração da sessão por inatividade e pelo limite absoluto.

Como rodar:
    ./run_tests.sh tests/test_seguranca_etapa2.py
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tia.core.config as config
from tia.api.main import app
from tia.core.database import obter_conexao
from tia.seguranca import anonimos, autenticador, limpeza, senhas, sessoes, usuarios
from tia.seguranca.acesso import MENSAGEM_TROCAR_SENHA
from tia.seguranca.usuarios import Usuario

SENHA = "senha-de-teste-123"
CSRF_LOGIN = {"X-CSRF-Token": "login"}
IP_DO_TESTCLIENT = "testclient"


@pytest.fixture(autouse=True)
def ligada(auth_ligada):
    """Autenticação ligada em todos os testes deste arquivo."""


@pytest.fixture
def pessoas():
    """Docente DOC-S01 e admin ADM-S01, com senha definitiva."""
    usuarios.criar("DOC-S01", "docente", SENHA, temporaria=False)
    usuarios.criar("ADM-S01", "admin", SENHA, temporaria=False)


def entrar(login: str, senha: str = SENHA) -> tuple[TestClient, dict, dict]:
    """(cliente com a sessão, cabeçalho anti-CSRF, corpo do login)."""
    c = TestClient(app)
    resposta = c.post("/auth/login", json={"login": login, "senha": senha}, headers=CSRF_LOGIN)
    assert resposta.status_code == 200, resposta.text
    return c, {"X-CSRF-Token": resposta.json()["csrf"]}, resposta.json()


def consultar(sql: str, parametros=()) -> list[dict]:
    conexao = obter_conexao()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def registros(tipo: str) -> list[dict]:
    return consultar("SELECT * FROM auditoria WHERE tipo = ? ORDER BY id", (tipo,))


def auditoria_inteira() -> str:
    return str(consultar("SELECT * FROM auditoria"))


def inserir_tentativa(ts: datetime, login: str = "DOC-S01", ip: str = "10.0.0.9"):
    conexao = obter_conexao()
    with conexao:
        conexao.execute("INSERT INTO auth_tentativas (ts, login, ip, sucesso) VALUES (?, ?, ?, 0)",
                        (ts.isoformat(timespec="seconds"), login, ip))
    conexao.close()


# --- E1: retenção e limpeza ---

def test_limpeza_apaga_sessoes_vencidas_e_tentativas_fora_da_retencao(pessoas):
    agora = datetime.now()
    entrar("DOC-S01")
    inserir_tentativa(agora - timedelta(days=config.AUTH_RETENCAO_IP_DIAS + 1), ip="10.0.0.1")
    inserir_tentativa(agora - timedelta(days=config.AUTH_RETENCAO_IP_DIAS - 1), ip="10.0.0.2")
    # nada vencido: só a tentativa antiga sai
    assert limpeza.limpar(agora) == {"sessoes": 0, "tentativas": 1, "pedidos_sem_login": 0}
    assert {t["ip"] for t in consultar("SELECT ip FROM auth_tentativas")} == {"10.0.0.2", IP_DO_TESTCLIENT}
    # depois do limite absoluto, a sessão também sai
    depois = agora + timedelta(minutes=config.AUTH_SESSAO_MAXIMA_MINUTOS + 1)
    assert limpeza.limpar(depois)["sessoes"] == 1
    assert consultar("SELECT * FROM auth_sessoes") == []
    # cada limpeza que apagou algo fica na auditoria (quantidades, sem IP); sem nada a apagar, nenhuma linha
    linhas = registros("limpeza_retencao")
    assert [l["motivo"] for l in linhas] == ["sessoes=0; tentativas=1; pedidos_sem_login=0",
                                             "sessoes=1; tentativas=0; pedidos_sem_login=0"]
    assert all(l["usuario_papel"] == "sistema" for l in linhas)
    assert limpeza.limpar(depois) == {"sessoes": 0, "tentativas": 0, "pedidos_sem_login": 0}
    assert len(registros("limpeza_retencao")) == 2


def test_limpeza_apaga_sessao_parada_por_inatividade(pessoas):
    entrar("DOC-S01")
    depois = datetime.now() + timedelta(minutes=config.AUTH_SESSAO_INATIVIDADE_MINUTOS + 1)
    assert limpeza.limpar(depois)["sessoes"] == 1


def test_limpeza_apaga_contagens_de_pedidos_sem_login_fora_da_retencao():
    antigo = datetime.now() - timedelta(days=config.AUTH_RETENCAO_IP_DIAS + 1)
    for _ in range(3):
        anonimos.registrar("acesso_negado", "10.0.0.7", "GET /x", "401", "sem login", antigo)
    assert limpeza.limpar()["pedidos_sem_login"] == 1
    assert consultar("SELECT * FROM auth_anonimos") == []
    # antes de apagar, a janela foi resumida: a contagem continua na auditoria
    assert "3 pedidos" in registros("resumo_anonimos")[-1]["motivo"]


def test_api_limpa_ao_subir(monkeypatch):
    monkeypatch.setattr(config, "AUTH_LIMPEZA_MINUTOS", 60)
    monkeypatch.setattr(config, "EM_PRODUCAO", False)  # o cookie sem Secure dos testes barraria a subida
    inserir_tentativa(datetime.now() - timedelta(days=config.AUTH_RETENCAO_IP_DIAS + 5))
    with TestClient(app):  # o ciclo de vida da API roda a primeira limpeza ao subir
        for _ in range(50):
            if not consultar("SELECT * FROM auth_tentativas"):
                break
            time.sleep(0.05)
    assert consultar("SELECT * FROM auth_tentativas") == []


def test_comando_de_limpeza(tmp_path):
    ambiente = {"DB_PATH": str(tmp_path / "limpeza.db"), "PATH": "", "PYTHONIOENCODING": "utf-8"}
    resultado = subprocess.run([sys.executable, "-m", "tia.seguranca.limpeza"], capture_output=True, text=True,
                               env=ambiente)
    assert resultado.returncode == 0, resultado.stderr
    assert "Linhas apagadas: sessoes 0, tentativas 0, pedidos_sem_login 0" in resultado.stdout


def test_ip_nunca_vai_para_a_auditoria(pessoas):
    c = TestClient(app)
    c.get("/painel/competencias")                                                 # 401 sem login
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO + 2):                           # falhas e bloqueio
        c.post("/auth/login", json={"login": "DOC-S01", "senha": "errada-errada"}, headers=CSRF_LOGIN)
    entrar("ADM-S01")
    assert registros("login_falha") and registros("login_bloqueado") and registros("acesso_negado")
    assert IP_DO_TESTCLIENT not in auditoria_inteira()


# --- E2: pedidos sem login agregados ---

def test_pedidos_sem_login_um_registro_por_origem_e_janela():
    c = TestClient(app)
    for _ in range(30):
        assert c.get("/painel/competencias").status_code == 401
    negados = registros("acesso_negado")
    assert len(negados) == 1  # e não 30
    assert negados[0]["referencia_id"] == "GET /painel/competencias" and negados[0]["usuario_papel"] == "anonimo"
    assert "só são contados" in negados[0]["motivo"]
    contagem = consultar("SELECT * FROM auth_anonimos")
    assert [(l["ip"], l["tipo"], l["pedidos"], l["registrado"]) for l in contagem] == [
        (IP_DO_TESTCLIENT, "acesso_negado", 30, 1)]
    # fechada a janela, o resumo grava o total na auditoria (sem IP)
    depois = datetime.now() + timedelta(minutes=config.AUTH_ANONIMOS_JANELA_MINUTOS)
    assert anonimos.resumir(depois) == 1
    resumo = registros("resumo_anonimos")[-1]
    assert resumo["origem"] == "acesso_negado" and resumo["referencia_id"].startswith("janela:")
    assert resumo["motivo"].startswith("30 pedidos de 1 origem(ns)") and "1 registrado(s) um a um" in resumo["motivo"]
    assert anonimos.resumir(depois) == 0  # resumida uma vez só
    assert IP_DO_TESTCLIENT not in auditoria_inteira()


def test_janela_sem_excesso_nao_gera_resumo():
    TestClient(app).get("/painel/competencias")
    assert anonimos.resumir(datetime.now() + timedelta(minutes=config.AUTH_ANONIMOS_JANELA_MINUTOS)) == 0
    assert registros("resumo_anonimos") == []


def test_nova_janela_registra_de_novo_e_resume_a_anterior():
    agora = datetime(2026, 10, 11, 14, 3)
    for minuto in (0, 1, 2):
        anonimos.registrar("acesso_negado", "10.0.0.5", "GET /a", "401", "sem login", agora + timedelta(minutes=minuto))
    assert len(registros("acesso_negado")) == 1
    # a próxima janela começa registrando de novo, e o primeiro pedido dela resume a anterior
    proxima = agora + timedelta(minutes=config.AUTH_ANONIMOS_JANELA_MINUTOS)
    assert anonimos.registrar("acesso_negado", "10.0.0.5", "GET /a", "401", "sem login", proxima) is True
    assert len(registros("acesso_negado")) == 2
    assert registros("resumo_anonimos")[-1]["motivo"].startswith("3 pedidos de 1 origem(ns) entre 14:03 e 14:05")


def test_limite_de_origens_registradas_por_janela(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ANONIMOS_MAX_ORIGENS", 2)
    agora = datetime(2026, 10, 11, 9, 0)
    gravados = [anonimos.registrar("acesso_negado", f"10.0.1.{n}", "GET /a", "401", "sem login", agora)
                for n in range(5)]
    assert gravados == [True, True, False, False, False]
    assert len(registros("acesso_negado")) == 2
    anonimos.resumir(agora + timedelta(minutes=config.AUTH_ANONIMOS_JANELA_MINUTOS))
    assert registros("resumo_anonimos")[-1]["motivo"].startswith("5 pedidos de 5 origem(ns)")


def test_login_bloqueado_agregado(pessoas):
    c = TestClient(app)
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO):
        c.post("/auth/login", json={"login": "DOC-S01", "senha": "errada-errada"}, headers=CSRF_LOGIN)
    for _ in range(10):
        assert c.post("/auth/login", json={"login": "DOC-S01", "senha": SENHA},
                      headers=CSRF_LOGIN).status_code == 429
    bloqueios = registros("login_bloqueado")
    assert len(bloqueios) == 1 and "login=DOC-S01" in bloqueios[0]["motivo"]
    assert consultar("SELECT pedidos FROM auth_anonimos WHERE tipo = 'login_bloqueado'") == [{"pedidos": 10}]
    # as falhas antes do bloqueio: a primeira registrada, as outras contadas (D4, tests/test_seguranca_lgpd.py)
    assert len(registros("login_falha")) == 1
    assert consultar("SELECT pedidos FROM auth_anonimos WHERE tipo = 'login_falha'") == [
        {"pedidos": config.AUTH_MAX_FALHAS_USUARIO}]


def test_recusas_de_quem_esta_logado_continuam_uma_a_uma(pessoas):
    c, _, _ = entrar("ADM-S01")
    for _ in range(3):
        assert c.get("/painel/competencias").status_code == 403
    assert len(registros("acesso_negado")) == 3
    assert consultar("SELECT * FROM auth_anonimos") == []


# --- E3: política de senha ---

@pytest.mark.parametrize("senha, trecho", [
    ("curta-9ch", "pelo menos 10"),
    ("aaaaaaaaaaaa", "mesmos caracteres"),
    ("abababababab", "mesmos caracteres"),
    ("1234567890", "muito comum"),
    ("Senha@2026!", "muito comum"),
    ("PASSWORD1234", "muito comum"),
    ("!!brasil2026", "muito comum"),
    ("qwertyuiop", "muito comum"),
    ("doc-s01-meu-segredo", "nome de usuário"),
])
def test_politica_recusa_senhas_fracas(senha, trecho):
    with pytest.raises(senhas.SenhaFraca, match=trecho):
        senhas.validar(senha, "DOC-S01")


@pytest.mark.parametrize("senha", ["cavalo-bateria-grampo", "Mesa verde 42 lua", "senha-de-teste-123"])
def test_politica_aceita_senhas_razoaveis(senha):
    senhas.validar(senha, "DOC-S01")


def test_politica_configuravel(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUTH_SENHA_MINIMA", 16)
    with pytest.raises(senhas.SenhaFraca, match="pelo menos 16"):
        senhas.validar("cavalo-bateria")
    monkeypatch.setattr(config, "AUTH_SENHA_MINIMA", 10)
    monkeypatch.setattr(config, "AUTH_SENHA_BLOQUEAR_COMUNS", False)
    senhas.validar("Senha@2026!")  # bloqueio das comuns desligado
    monkeypatch.setattr(config, "AUTH_SENHA_BLOQUEAR_COMUNS", True)
    extra = tmp_path / "proibidas.txt"
    extra.write_text("# lista da instituição\ngirassol\n", encoding="utf-8")
    monkeypatch.setattr(config, "AUTH_SENHAS_COMUNS_EXTRA", str(extra))
    with pytest.raises(senhas.SenhaFraca, match="muito comum"):
        senhas.validar("Girassol2026!")


def test_lista_de_senhas_comuns_sem_caracteres_estranhos():
    comuns = senhas.senhas_comuns()
    assert len(comuns) > 100 and "senha" in comuns and "123456789" in comuns
    assert all(s.isascii() and s == s.lower() for s in comuns)


def test_usuarios_de_demonstracao_passam_na_politica():
    senhas.validar(usuarios.SENHA_DEMONSTRACAO)


# --- E3: troca obrigatória da senha temporária ---

def criar_temporario(admin: TestClient, csrf: dict, usuario_id: str = "DOC-T01") -> str:
    temporaria = "temporaria-do-admin-1"
    assert admin.post("/admin/usuarios", json={"id": usuario_id, "papel": "docente", "senha": temporaria},
                      headers=csrf).status_code == 201
    return temporaria


def test_senha_temporaria_exige_troca_no_primeiro_acesso(pessoas):
    admin, csrf_admin, _ = entrar("ADM-S01")
    temporaria = criar_temporario(admin, csrf_admin)
    c, csrf, corpo = entrar("DOC-T01", temporaria)
    assert corpo["usuario"]["trocar_senha"] is True
    assert c.get("/auth/eu").json()["usuario"]["trocar_senha"] is True
    # enquanto não troca, as outras rotas recusam com mensagem clara (e auditada)
    recusa = c.get("/painel/competencias")
    assert recusa.status_code == 403 and recusa.json()["detail"] == MENSAGEM_TROCAR_SENHA
    assert registros("acesso_negado")[-1]["usuario_id"] == "DOC-T01"
    outra_sessao, _, _ = entrar("DOC-T01", temporaria)
    # erros de troca
    troca = {"senha_atual": temporaria, "nova_senha": "cavalo-bateria-grampo"}
    assert c.post("/auth/senha", json=troca).status_code == 403  # sem o anti-CSRF
    errada = c.post("/auth/senha", json={**troca, "senha_atual": "nao-e-esta-1"}, headers=csrf)
    assert errada.status_code == 403 and errada.json()["detail"] == "A senha atual não confere."
    assert "senha atual incorreta" in registros("login_falha")[-1]["motivo"]
    fraca = c.post("/auth/senha", json={**troca, "nova_senha": "Senha@2026!"}, headers=csrf)
    assert fraca.status_code == 422 and "muito comum" in fraca.json()["detail"]
    igual = c.post("/auth/senha", json={**troca, "nova_senha": temporaria}, headers=csrf)
    assert igual.status_code == 422 and "diferente da atual" in igual.json()["detail"]
    # troca certa: sessão nova (cookie e anti-CSRF novos), as outras sessões caem
    token_antigo = c.cookies.get("tia_sessao")
    trocou = c.post("/auth/senha", json=troca, headers=csrf)
    assert trocou.status_code == 200
    assert trocou.json()["usuario"]["trocar_senha"] is False and trocou.json()["csrf"] != csrf["X-CSRF-Token"]
    assert c.cookies.get("tia_sessao") != token_antigo and sessoes.ler_sessao(token_antigo) is None
    assert c.get("/painel/competencias").status_code == 200
    assert outra_sessao.get("/auth/eu").json()["usuario"] is None
    # a nova senha vale e a temporária não
    entrar("DOC-T01", "cavalo-bateria-grampo")
    assert TestClient(app).post("/auth/login", json={"login": "DOC-T01", "senha": temporaria},
                                headers=CSRF_LOGIN).status_code == 401
    acoes = [(r["motivo"], r["usuario_id"]) for r in registros("gestao_usuario") if r["referencia_id"] == "DOC-T01"]
    assert acoes == [("usuário criado (papel docente); senha temporária", "ADM-S01"),
                     ("senha trocada pelo próprio usuário", "DOC-T01")]


def test_saida_funciona_com_senha_temporaria(pessoas):
    admin, csrf_admin, _ = entrar("ADM-S01")
    c, csrf, _ = entrar("DOC-T01", criar_temporario(admin, csrf_admin))
    assert c.post("/auth/logout", headers=csrf).status_code == 204


def test_redefinicao_pelo_admin_volta_a_exigir_troca(pessoas):
    admin, csrf_admin, _ = entrar("ADM-S01")
    assert admin.post("/admin/usuarios/DOC-S01/senha", json={"senha": "provisoria-nova-2"},
                      headers=csrf_admin).status_code == 204
    _, _, corpo = entrar("DOC-S01", "provisoria-nova-2")
    assert corpo["usuario"]["trocar_senha"] is True


def test_troca_voluntaria_de_senha(pessoas):
    c, csrf, _ = entrar("DOC-S01")
    assert c.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": "outra-frase-longa"},
                  headers=csrf).status_code == 200
    entrar("DOC-S01", "outra-frase-longa")


def test_senha_atual_errada_conta_para_o_bloqueio(pessoas):
    c, csrf, _ = entrar("DOC-S01")
    for _ in range(config.AUTH_MAX_FALHAS_USUARIO):
        assert c.post("/auth/senha", json={"senha_atual": "chute-errado-1", "nova_senha": "outra-frase-longa"},
                      headers=csrf).status_code == 403
    assert c.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": "outra-frase-longa"},
                  headers=csrf).status_code == 429
    assert TestClient(app).post("/auth/login", json={"login": "DOC-S01", "senha": SENHA},
                                headers=CSRF_LOGIN).status_code == 429


def test_troca_de_senha_com_provedor_externo(pessoas, monkeypatch):
    class AutenticadorFalso:
        nome = "falso"

        def autenticar(self, credenciais):
            return Usuario("DOC-S01", "docente", None, True)

    monkeypatch.setitem(autenticador.PROVEDORES, "falso", AutenticadorFalso)
    monkeypatch.setattr(config, "AUTH_PROVEDOR", "falso")
    c, csrf, _ = entrar("DOC-S01", "ticket")
    resposta = c.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": "outra-frase-longa"}, headers=csrf)
    assert resposta.status_code == 409 and "instituição" in resposta.json()["detail"]


def test_linha_de_comando_cria_senha_temporaria(tmp_path):
    ambiente = {"DB_PATH": str(tmp_path / "cli.db"), "PATH": "", "PYTHONIOENCODING": "utf-8"}
    comando = [sys.executable, "-m", "tia.seguranca.usuarios"]
    criado = subprocess.run(comando + ["criar", "--id", "DOC-CLI", "--papel", "docente", "--senha-stdin"],
                            input="temporaria-do-admin-1\n", capture_output=True, text=True, env=ambiente)
    assert criado.returncode == 0 and "'trocar_senha': True" in criado.stdout
    fraca = subprocess.run(comando + ["criar", "--id", "DOC-CLJ", "--papel", "docente", "--senha-stdin"],
                           input="Senha@2026!\n", capture_output=True, text=True, env=ambiente)
    assert fraca.returncode != 0 and "muito comum" in fraca.stderr


# --- E4: expiração da sessão ---

def test_sessao_expira_por_inatividade(pessoas):
    c, _, _ = entrar("DOC-S01")
    token = c.cookies.get("tia_sessao")
    inicio = datetime.now()
    inatividade = timedelta(minutes=config.AUTH_SESSAO_INATIVIDADE_MINUTOS)
    # usada a cada 20 minutos, a sessão segue viva além dos 30 minutos
    for minutos in (20, 40, 60):
        assert sessoes.ler_sessao(token, agora=inicio + timedelta(minutes=minutos)) is not None, minutos
    # parada por mais que a inatividade, vence
    assert sessoes.ler_sessao(token, agora=inicio + timedelta(minutes=60) + inatividade + timedelta(seconds=1)) is None


def test_sessao_tem_limite_absoluto_mesmo_com_uso(pessoas):
    c, _, _ = entrar("DOC-S01")
    token = c.cookies.get("tia_sessao")
    inicio = datetime.now()
    passo = config.AUTH_SESSAO_INATIVIDADE_MINUTOS - 5
    minutos = passo
    while minutos < config.AUTH_SESSAO_MAXIMA_MINUTOS:
        assert sessoes.ler_sessao(token, agora=inicio + timedelta(minutes=minutos)) is not None, minutos
        minutos += passo
    assert sessoes.ler_sessao(token, agora=inicio + timedelta(minutes=config.AUTH_SESSAO_MAXIMA_MINUTOS + 1)) is None


def test_api_recusa_sessao_parada(pessoas):
    c, _, _ = entrar("DOC-S01")
    assert c.get("/painel/competencias").status_code == 200
    parada = (datetime.now() - timedelta(minutes=config.AUTH_SESSAO_INATIVIDADE_MINUTOS + 1)).isoformat(
        timespec="seconds")
    conexao = obter_conexao()
    with conexao:
        conexao.execute("UPDATE auth_sessoes SET ultimo_uso = ?", (parada,))
    conexao.close()
    recusa = c.get("/painel/competencias")
    assert recusa.status_code == 401 and "inatividade" in recusa.json()["detail"]


def test_ultimo_uso_nao_e_regravado_a_cada_pedido(pessoas):
    c, _, _ = entrar("DOC-S01")
    token = c.cookies.get("tia_sessao")
    inicio = datetime.now()
    usos = []
    for segundos in (10, 30, 90):
        sessoes.ler_sessao(token, agora=inicio + timedelta(seconds=segundos))
        usos.append(consultar("SELECT ultimo_uso FROM auth_sessoes")[0]["ultimo_uso"])
    assert usos[0] == usos[1]  # 10 s e 30 s depois do login: nada regravado
    assert usos[2] == (inicio + timedelta(seconds=90)).isoformat(timespec="seconds")


def test_tempos_da_sessao_configuraveis(pessoas, monkeypatch):
    monkeypatch.setattr(config, "AUTH_SESSAO_INATIVIDADE_MINUTOS", 5)
    c, _, _ = entrar("DOC-S01")
    token = c.cookies.get("tia_sessao")
    assert sessoes.ler_sessao(token, agora=datetime.now() + timedelta(minutes=6)) is None


# --- telas: formulário da troca de senha ---

@pytest.mark.parametrize("pagina", ["index.html", "painel/index.html"])
def test_telas_tem_a_troca_de_senha(pagina):
    html = (Path(__file__).parents[1] / "src/tia/web/static" / pagina).read_text(encoding="utf-8")
    assert 'id="form-senha"' in html and html.count('autocomplete="new-password"') == 2
    for campo in ("campo-senha-atual", "campo-senha-nova", "campo-senha-repetir"):
        assert f'for="{campo}"' in html, campo
