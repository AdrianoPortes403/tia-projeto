"""
Testes da etapa 2 de 2 do 1.4.6 (LGPD, segurança geral e importação em lote),
com banco temporário (conftest) e sem LLM:

- C1: retenção simulada (nada muda) e aplicada (só o que passou do prazo;
  auditoria anonimizada, nunca apagada; cópia do banco antes; cópias vencidas);
- C2: exportação e eliminação dos dados de um aluno, sem afetar outros;
- C3: rotas agregadas sem códigos de aluno; 422 sem o valor enviado; logs sem
  texto do aluno; telemetria do Chroma desligada; pontos de rede do código;
- D1: cabeçalhos de segurança em todas as respostas; /docs desligável; a API
  não sobe com configuração insegura em produção;
- D4: login recusado vindo de muitos IPs agregado, sem perder bloqueio e resumo;
- E6: importação de usuários em lote (válido, inválido, repetido).

Como rodar:
    ./run_tests.sh tests/test_seguranca_lgpd.py
"""

import json
import logging
import os
import re
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tia.core.config as config
import tia.core.database as database
from tia.agentes.relatorio import gerar_relatorio_turma, narrativa
from tia.api.main import app, criar_app
from tia.core import auditoria
from tia.core.database import obter_conexao
from tia.seguranca import anonimizacao, anonimos, retencao, titular, usuarios
from tia.web import dados_painel

RAIZ = Path(__file__).parents[1]
SENHA = "senha-de-teste-123"
CSRF_LOGIN = {"X-CSRF-Token": "login"}
AGORA = datetime(2026, 10, 11, 12, 0)


def consultar(sql: str, parametros=()) -> list[dict]:
    conexao = obter_conexao()
    try:
        return [dict(l) for l in conexao.execute(sql, parametros).fetchall()]
    finally:
        conexao.close()


def despejo() -> str:
    conexao = obter_conexao()
    try:
        return "\n".join(conexao.iterdump())
    finally:
        conexao.close()


def registros(tipo: str) -> list[dict]:
    return consultar("SELECT * FROM auditoria WHERE tipo = ? ORDER BY id", (tipo,))


# --- dados semeados direto no banco, com data escolhida ---

def semear(aluno: str, quando: datetime, marca: str, sessao: str | None = None):
    """Uma linha por tabela de estudo do aluno, com data `quando`; textos com a `marca`."""
    ts = quando.isoformat(timespec="seconds")
    sessao = sessao or f"s-{aluno}-{marca}"
    conexao = obter_conexao()
    with conexao:
        conexao.execute("INSERT OR IGNORE INTO alunos (id, conhecimento_previo, horas_semana_disponiveis) "
                        "VALUES (?, '{}', 6)", (aluno,))
        conexao.execute("INSERT INTO trilha_estudo (aluno_id, semana, topico, ordem, competencia_id, criado_em) "
                        "VALUES (?, 1, 'funcoes', 1, 'funcoes', ?)", (aluno, ts))
        conexao.execute("INSERT OR IGNORE INTO orquestrador_matriculas (aluno_id, perfil_id, horas_semanais, "
                        "diagnostico, criado_em) VALUES (?, 'iniciante', 6, '{}', ?)", (aluno, ts))
        conexao.execute("INSERT INTO tutor_sessoes (id, aluno_id, competencia_id, nivel, criado_em, atualizado_em) "
                        "VALUES (?, ?, 'funcoes', 1, ?, ?)", (sessao, aluno, ts, ts))
        resposta = conexao.execute(
            "INSERT INTO historico_respostas (aluno_id, acertou, timestamp, nivel, item_id, sessao_id) "
            "VALUES (?, 1, ?, 1, 'item-1', ?)", (aluno, ts, sessao)).lastrowid
        conexao.execute(
            """INSERT INTO tutor_feedbacks (resposta_id, aluno_id, sessao_id, item_id, competencia_id, ts, veredito,
                 explicacao, origem, fontes, correcao_docente) VALUES (?, ?, ?, 'item-1', 'funcoes', ?, 'Correto.',
                 ?, 'LLM', '[]', ?)""", (resposta, aluno, sessao, ts, f"explicação {marca}", f"correção {marca}"))
        conexao.execute("INSERT INTO tutor_dialogo (aluno_id, ts, competencia_id, pergunta, resposta, fontes, origem) "
                        "VALUES (?, ?, 'funcoes', ?, ?, '[]', 'LLM')", (aluno, ts, f"pergunta {marca}",
                                                                        f"resposta {marca}"))
        conexao.execute("INSERT INTO orquestrador_eventos (evento_id, aluno_id, tipo, recebido_em, resultado) "
                        "VALUES (?, ?, 'resposta', ?, ?)",
                        (f"e-{aluno}-{marca}", aluno, ts, json.dumps({"feedback": {"explicacao": f"explicação {marca}"}})))
        conexao.execute("INSERT INTO orquestrador_decisoes (aluno_id, ts, regra, acao, motivo, evento_id, sessao_id) "
                        "VALUES (?, ?, 'R1', 'nada', 'motivo', ?, ?)", (aluno, ts, f"e-{aluno}-{marca}", sessao))
        conexao.execute("INSERT INTO orquestrador_reforcos (aluno_id, competencia_original, sessao_original_id, "
                        "estado, criado_em, concluido_em) VALUES (?, 'funcoes', ?, 'concluido', ?, ?)",
                        (aluno, sessao, ts, ts))
        auditoria.definir_usuario(aluno, "aluno")
        auditoria.registrar(conexao, aluno, "dialogo", "1", "LLM", [], ts=ts, motivo=f"login={aluno}")
        auditoria.registrar(conexao, aluno, "acesso_negado", f"GET /aluno/{aluno}/estado", "403", [], ts=ts,
                            motivo="Você só pode acessar os seus próprios dados.")
        auditoria.USUARIO_ATUAL.set(None)
    conexao.close()


def linha(tabela: str, condicao: str, parametros=()) -> dict:
    resultado = consultar(f"SELECT * FROM {tabela} WHERE {condicao}", parametros)
    assert len(resultado) == 1, (tabela, condicao, resultado)
    return resultado[0]


@pytest.fixture
def dados_com_idades():
    """Aluno A2026-R01 com dados velhos (400 e 800 dias), médios (200) e novos (10)."""
    for dias, marca in ((800, "antiga"), (400, "velha"), (200, "media"), (10, "nova")):
        semear("A2026-R01", AGORA - timedelta(days=dias), marca)
    usuarios.criar("A2026-R01", "aluno", SENHA, "A2026-R01", temporaria=False)


# --- C1: retenção ---

def test_retencao_simulada_nao_altera_nada(dados_com_idades):
    antes = despejo()
    resultado = retencao.executar(simular=True, agora=AGORA)
    assert despejo() == antes
    por_tabela = {(o.tabela, o.descricao): o.linhas for o in resultado.operacoes}
    assert por_tabela[("historico_respostas", "respostas do questionário")] == 2          # 800 e 400 dias
    assert por_tabela[("tutor_dialogo", "diálogo livre (pergunta, resposta e correção)")] == 3  # 800, 400 e 200
    assert por_tabela[("tutor_feedbacks", "textos do feedback das questões")] == 3
    assert resultado.auditoria_anonimizada == 2 and resultado.total > 0
    assert not anonimizacao.pasta_das_copias().exists()  # simular não copia o banco
    texto = retencao.relatorio(resultado)
    assert "SIMULAÇÃO (nada foi alterado)" in texto and "A2026-R01" not in texto  # só quantidades


def test_retencao_aplicada_so_no_que_passou_do_prazo(dados_com_idades):
    novas_antes = {t: consultar(f"SELECT * FROM {t} WHERE {c} >= ?", ((AGORA - timedelta(days=30)).isoformat(),))
                   for t, c in (("historico_respostas", "timestamp"), ("tutor_dialogo", "ts"), ("tutor_feedbacks", "ts"),
                                ("orquestrador_eventos", "recebido_em"), ("orquestrador_decisoes", "ts"),
                                ("auditoria", "ts"))}
    total_auditoria = len(consultar("SELECT id FROM auditoria"))
    resultado = retencao.executar(simular=False, agora=AGORA)
    # o que está dentro do prazo não mudou
    for tabela, linhas_antes in novas_antes.items():
        coluna = {"historico_respostas": "timestamp", "orquestrador_eventos": "recebido_em"}.get(tabela, "ts")
        depois = consultar(f"SELECT * FROM {tabela} WHERE {coluna} >= ?", ((AGORA - timedelta(days=30)).isoformat(),))
        if tabela == "auditoria":
            depois = [r for r in depois if r["tipo"] != "retencao"]
        assert depois == linhas_antes, tabela
    # 200 dias: textos do feedback e diálogo saem; a resposta continua ligada ao aluno (prazo de 365)
    media = (AGORA - timedelta(days=200)).isoformat(timespec="seconds")
    feedback = linha("tutor_feedbacks", "ts = ?", (media,))
    assert (feedback["explicacao"], feedback["correcao_docente"], feedback["aluno_id"]) == (None, None, "A2026-R01")
    dialogo = linha("tutor_dialogo", "ts = ?", (media,))
    assert (dialogo["aluno_id"], dialogo["pergunta"], dialogo["resposta"]) == (None, None, None)
    assert dialogo["origem"] == "LLM" and dialogo["competencia_id"] == "funcoes"  # o que não é pessoal fica
    assert linha("historico_respostas", "timestamp = ?", (media,))["aluno_id"] == "A2026-R01"
    assert consultar("SELECT * FROM orquestrador_eventos WHERE recebido_em = ?", (media,)) == []
    # 400 dias: tudo desvinculado do aluno; acerto, item e nível ficam para estatística
    velha = (AGORA - timedelta(days=400)).isoformat(timespec="seconds")
    resposta = linha("historico_respostas", "timestamp = ?", (velha,))
    assert (resposta["aluno_id"], resposta["sessao_id"], resposta["acertou"], resposta["item_id"]) == (
        None, None, 1, "item-1")
    for tabela, coluna in (("tutor_sessoes", "criado_em"), ("orquestrador_decisoes", "ts"),
                           ("orquestrador_reforcos", "criado_em"), ("tutor_feedbacks", "ts")):
        assert linha(tabela, f"{coluna} = ?", (velha,))["aluno_id"] is None, tabela
    # auditoria: nenhuma linha apagada; as de 800 dias sem códigos
    assert len(consultar("SELECT id FROM auditoria")) == total_auditoria + 1  # + a linha "retencao"
    antigas = consultar("SELECT * FROM auditoria WHERE ts = ?",
                        ((AGORA - timedelta(days=800)).isoformat(timespec="seconds"),))
    assert len(antigas) == 2 and all(r["anonimizada"] == 1 for r in antigas)
    assert "A2026-R01" not in json.dumps(antigas)
    assert {r["motivo"] for r in antigas} >= {"login=[anonimizado]"}
    assert {r["referencia_id"] for r in antigas} >= {"GET /aluno/[anonimizado]/estado"}
    assert all(r["usuario_papel"] == "aluno" for r in antigas)  # o papel fica
    # cadastro e trilha não têm prazo por data
    assert len(consultar("SELECT * FROM trilha_estudo")) == 4
    # cópia do banco antes de aplicar, só do dono; a auditoria registra as quantidades
    assert resultado.copia_feita.exists() and stat.S_IMODE(resultado.copia_feita.stat().st_mode) == 0o600
    assert stat.S_IMODE(resultado.copia_feita.parent.stat().st_mode) == 0o700
    registro = registros("retencao")[-1]
    assert "historico_respostas.anonimizar=2" in registro["motivo"] and registro["aluno_id"] is None
    # a cópia tem os dados de antes
    copia = sqlite3.connect(resultado.copia_feita)
    assert copia.execute("SELECT COUNT(*) FROM tutor_dialogo WHERE pergunta IS NOT NULL").fetchone()[0] == 4
    copia.close()


def test_retencao_aplicada_de_novo_nao_faz_nada(dados_com_idades):
    retencao.executar(simular=False, agora=AGORA)
    antes = despejo()
    resultado = retencao.executar(simular=False, agora=AGORA)
    assert resultado.total == 0 and resultado.copia_feita is None and despejo() == antes


def test_retencao_apaga_copias_vencidas(dados_com_idades):
    pasta = anonimizacao.pasta_das_copias()
    pasta.mkdir(parents=True)
    velha, recente = pasta / "tia-20250101-000000-000000-retencao.db", pasta / "tia-20261010-000000-000000-retencao.db"
    for copia, dias in ((velha, config.RETENCAO_COPIAS_DIAS + 5), (recente, 1)):
        copia.write_bytes(b"x")
        instante = (AGORA - timedelta(days=dias)).timestamp()
        os.utime(copia, (instante, instante))
    assert retencao.executar(simular=True, agora=AGORA).copias_vencidas == [velha] and velha.exists()
    retencao.executar(simular=False, agora=AGORA)
    assert not velha.exists() and recente.exists()


def test_comando_de_retencao(tmp_path):
    ambiente = {"DB_PATH": str(tmp_path / "ret.db"), "PATH": "", "PYTHONIOENCODING": "utf-8"}
    comando = [sys.executable, "-m", "tia.seguranca.retencao"]
    simulado = subprocess.run(comando + ["--simular"], capture_output=True, text=True, env=ambiente)
    assert simulado.returncode == 0 and "SIMULAÇÃO (nada foi alterado)" in simulado.stdout
    assert subprocess.run(comando, capture_output=True, text=True, env=ambiente).returncode != 0  # modo obrigatório


# --- C2: direitos do titular ---

@pytest.fixture
def dois_alunos():
    """A2026-T01 (usuário USR-T01) e A2026-T02 (USR-T02), com dados; o T01 tentou ler o T02 e um docente vetou."""
    for aluno in ("A2026-T01", "A2026-T02"):
        semear(aluno, AGORA - timedelta(days=5), f"de {aluno}")
    usuarios.criar("USR-T01", "aluno", SENHA, "A2026-T01", temporaria=False)
    usuarios.criar("USR-T02", "aluno", SENHA, "A2026-T02", temporaria=False)
    usuarios.criar("DOC-T09", "docente", SENHA, temporaria=False)
    conexao = obter_conexao()
    with conexao:
        auditoria.definir_usuario("USR-T01", "aluno")
        auditoria.registrar(conexao, "A2026-T02", "acesso_negado", "GET /aluno/A2026-T02/estado", "403", [])
        auditoria.definir_usuario("DOC-T09", "docente")
        auditoria.registrar(conexao, "A2026-T01", "veto_docente", "1", "docente", [])
        auditoria.registrar(conexao, None, "consulta_painel", "alunos_em_risco", "painel", [],
                            motivo="2 aluno(s) exibido(s): A2026-T01, A2026-T02")
        auditoria.USUARIO_ATUAL.set(None)
    conexao.close()


def test_exportar_traz_tudo_do_aluno_e_nada_de_outros(dois_alunos):
    dados = titular.exportar("A2026-T01")
    texto = json.dumps(dados, ensure_ascii=False)
    assert "pergunta de A2026-T01" in texto and "explicação de A2026-T01" in texto
    for outro in ("A2026-T02", "USR-T02", "DOC-T09", "de A2026-T02"):
        assert outro not in texto, outro
    assert "senha_hash" not in texto and SENHA not in texto
    assert dados["usuarios"][0]["id"] == "USR-T01" and len(dados["respostas"]) == 1
    assert dados["eventos"][0]["resultado"]["feedback"]["explicacao"] == "explicação de A2026-T01"
    # o acesso negado que ele fez aparece, com o código do outro aluno anonimizado
    negado = next(r for r in dados["auditoria"] if r["tipo"] == "acesso_negado" and r["usuario_id"] == "USR-T01")
    assert negado["aluno_id"] == "[anonimizado]" and negado["referencia_id"] == "GET /aluno/[anonimizado]/estado"
    # o veto do docente aparece só pelo papel
    veto = next(r for r in dados["auditoria"] if r["tipo"] == "veto_docente")
    assert (veto["usuario_id"], veto["usuario_papel"]) == ("[anonimizado]", "docente")
    assert dados["consultas_do_painel_que_mostraram_o_aluno"][0]["referencia_id"] == "alunos_em_risco"
    registro = registros("direito_titular")[-1]
    assert (registro["aluno_id"], registro["referencia_id"]) == ("A2026-T01", "exportacao")


def test_exportar_aluno_inexistente():
    with pytest.raises(titular.ErroTitular, match="Nenhum dado"):
        titular.exportar("A2026-NADA")


def test_eliminar_exige_confirmacao(dois_alunos):
    antes = despejo()
    with pytest.raises(titular.ErroTitular, match="Confirmação"):
        titular.eliminar("A2026-T01", "A2026-T0")
    assert despejo() == antes and not anonimizacao.pasta_das_copias().exists()


def test_eliminar_um_aluno_sem_afetar_outros(dois_alunos, auth_ligada):
    def do_outro():
        return {t: consultar(f"SELECT * FROM {t} WHERE aluno_id = 'A2026-T02' ORDER BY rowid")
                for t in anonimizacao.TABELAS_DO_ALUNO if t != "auditoria"}
    outro_antes = do_outro()
    usuario_outro = consultar("SELECT * FROM usuarios WHERE id = 'USR-T02'")
    c = TestClient(app)
    resumo = titular.eliminar("A2026-T01", "A2026-T01")
    banco = despejo()
    # nenhum dado do aluno sobra, nem o texto dele, nem os códigos dele (fora o login desativado)
    assert "A2026-T01" not in banco and "de A2026-T01" not in banco
    usuario = consultar("SELECT * FROM usuarios WHERE id = 'USR-T01'")[0]
    assert (usuario["ativo"], usuario["aluno_id"], usuario["senha_hash"]) == (0, None, "eliminado")
    assert c.post("/auth/login", json={"login": "USR-T01", "senha": SENHA}, headers=CSRF_LOGIN).status_code == 401
    assert c.post("/auth/login", json={"login": "USR-T02", "senha": SENHA}, headers=CSRF_LOGIN).status_code == 200
    # agregados: as respostas continuam, sem dono
    assert consultar("SELECT COUNT(*) AS n FROM historico_respostas WHERE aluno_id IS NULL")[0]["n"] == 1
    # o outro aluno não mudou
    assert do_outro() == outro_antes
    assert consultar("SELECT * FROM usuarios WHERE id = 'USR-T02'") == usuario_outro
    # a auditoria não perde linha; o veto continua com o docente; a consulta do painel mantém o outro código
    veto = registros("veto_docente")[0]
    assert (veto["aluno_id"], veto["usuario_id"]) == (None, "DOC-T09")
    assert registros("consulta_painel")[0]["motivo"] == "2 aluno(s) exibido(s): [anonimizado], A2026-T02"
    negado = registros("acesso_negado")[-1]
    assert (negado["aluno_id"], negado["usuario_id"]) == ("A2026-T02", None)  # o alvo era o outro aluno
    # registro da eliminação, sem o código, com protocolo; cópia feita antes
    registro = registros("direito_titular")[-1]
    assert registro["aluno_id"] is None and registro["referencia_id"] == resumo["protocolo"]
    assert "eliminação a pedido do titular" in registro["motivo"]
    copia = Path(resumo["copia"])
    assert copia.exists() and stat.S_IMODE(copia.stat().st_mode) == 0o600
    with pytest.raises(titular.ErroTitular, match="Nenhum dado"):  # de novo: nada a eliminar
        titular.eliminar("A2026-T01", "A2026-T01")


def test_comando_do_titular(tmp_path, monkeypatch):
    banco = tmp_path / "titular.db"
    monkeypatch.setattr(database, "DB_PATH", str(banco))
    database.criar_tabelas()
    semear("A2026-T05", AGORA, "cli")
    ambiente = {"DB_PATH": str(banco), "PATH": "", "PYTHONIOENCODING": "utf-8"}
    comando = [sys.executable, "-m", "tia.seguranca.titular"]
    saida = tmp_path / "export.json"
    exportado = subprocess.run(comando + ["exportar", "--aluno", "A2026-T05", "--saida", str(saida)],
                               capture_output=True, text=True, env=ambiente, cwd=tmp_path)
    assert exportado.returncode == 0 and stat.S_IMODE(saida.stat().st_mode) == 0o600
    assert json.loads(saida.read_text(encoding="utf-8"))["titular"]["aluno_id"] == "A2026-T05"
    de_novo = subprocess.run(comando + ["exportar", "--aluno", "A2026-T05", "--saida", str(saida)],
                             capture_output=True, text=True, env=ambiente)
    assert de_novo.returncode != 0 and "já existe" in de_novo.stderr  # nunca sobrescreve
    errado = subprocess.run(comando + ["eliminar", "--aluno", "A2026-T05"], input="outro\n",
                            capture_output=True, text=True, env=ambiente)
    assert errado.returncode != 0 and "nada foi alterado" in errado.stderr
    certo = subprocess.run(comando + ["eliminar", "--aluno", "A2026-T05"], input="A2026-T05\n",
                           capture_output=True, text=True, env=ambiente)
    assert certo.returncode == 0 and "Protocolo: titular-" in certo.stdout
    assert consultar("SELECT * FROM alunos") == []


# --- C3: minimização ---

def test_rotas_agregadas_sem_codigos_de_aluno(monkeypatch):
    monkeypatch.setattr("tia.core.llm_client.requests.post", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    dados_painel.criar_turma(datetime.now())
    c = TestClient(app)
    codigo = re.compile(r"DEMO-P\d\d")
    for rota in ("/relatorio/turma?narrativa=false", "/painel/competencias", "/painel/exportar/indicadores.csv",
                 "/relatorio/turma?narrativa=false&perfil_id=iniciante", "/conteudo/ementa", "/conteudo/perfis"):
        resposta = c.get(rota)
        assert resposta.status_code == 200 and not codigo.search(resposta.text), rota
    # a rota de risco mostra códigos (por desenho, só docente e auditada): o teste de fato vê códigos
    assert codigo.search(c.get("/painel/alunos-em-risco").text)


def test_narrativa_da_turma_nao_manda_codigos_ao_llm(monkeypatch):
    dados_painel.criar_turma(datetime.now())
    prompts = []
    monkeypatch.setattr(narrativa, "chamar_llm", lambda prompt, **k: prompts.append(prompt) or "Texto da turma.")
    gerar_relatorio_turma(com_narrativa=True)
    assert prompts and not re.search(r"DEMO-P\d\d", prompts[0])


def test_erro_de_validacao_nao_devolve_o_valor_enviado():
    c = TestClient(app)
    segredo = "S" * 300 + "-segredo-do-aluno"
    for rota, corpo in (("/auth/login", {"login": "DOC-1", "senha": segredo}),
                        ("/tutor/perguntar", {"aluno_id": "A2026-X", "pergunta": segredo * 20}),
                        ("/admin/usuarios", {"id": "Maria da Silva", "papel": "aluno", "senha": segredo})):
        resposta = c.post(rota, json=corpo, headers=CSRF_LOGIN)
        assert resposta.status_code == 422, rota
        assert "segredo" not in resposta.text and "Maria" not in resposta.text, rota
        assert all(set(d) == {"loc", "msg", "type"} for d in resposta.json()["detail"])


def test_logs_sem_texto_do_aluno(monkeypatch, caplog):
    import tia.agentes.tutor.dialogo as dialogo
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(dialogo, "buscar_trechos_dialogo", lambda pergunta, materiais: [])
    c = TestClient(app)
    pergunta = "pergunta-pessoal-xyz sobre minha vida"
    assert c.post("/tutor/perguntar", json={"aluno_id": "A2026-L01", "pergunta": pergunta}).status_code == 200
    assert "pergunta-pessoal-xyz" not in caplog.text and "A2026-L01" not in caplog.text


def test_chroma_sem_telemetria(tmp_path, monkeypatch):
    import tia.rag.retrieve as retrieve
    monkeypatch.setattr(retrieve, "CHROMA_DIR", str(tmp_path / "chroma"))
    assert retrieve.abrir_cliente().get_settings().anonymized_telemetry is False
    # nenhum outro lugar abre o Chroma por conta própria
    codigo = "\n".join(p.read_text(encoding="utf-8") for p in (RAIZ / "src/tia").rglob("*.py"))
    assert codigo.count("PersistentClient(") == 1


# endereços que podem aparecer no código (docs/seguranca/lgpd.md, "Pontos de rede")
ENDERECOS_PERMITIDOS = {
    "http://localhost:11434",          # Ollama (OLLAMA_URL padrão)
    "http://localhost:8000",           # mensagens "abra ..." dos comandos de demonstração
    "http://127.0.0.1:8000",           # API_URL_LOCAL: teste de fumaça da VM (implantacao.verificar)
    "http://127.0.0.1",                # comentário sobre o cookie Secure no teste de fumaça
    "http://localhost",                # comentário sobre o cookie Secure em http://localhost
    "http://www.w3.org",               # namespace do SVG (não é acesso de rede)
    "https://cdn.jsdelivr.net",        # CSP do /docs (desligado em produção)
    "https://fastapi.tiangolo.com",    # CSP do /docs (ícone)
    "http://testserver",               # nunca usado fora de teste, mas pode aparecer em docstring
    # exemplos em comentários/documentação do plug-in EBAULA (sem chamada de rede)
    "https://ebaula.exemplo.eb.mil.br.",  # o ponto final vem da pontuação do comentário (regex o inclui)
    "https://tia.exemplo.eb.mil.br",   # exemplo de uso no cabeçalho de tia-ebaula.js
    "https://host",                    # sintaxe de origem em config.py (https://host[:porta])
}


def test_pontos_de_rede_do_codigo():
    achados = set()
    for arquivo in list((RAIZ / "src/tia").rglob("*.py")) + list((RAIZ / "src/tia/web/static").rglob("*.*")):
        for url in re.findall(r"https?://[A-Za-z0-9.\-]+(?::\d+)?", arquivo.read_text(encoding="utf-8")):
            achados.add(url)
    assert achados <= ENDERECOS_PERMITIDOS, achados - ENDERECOS_PERMITIDOS
    # a única biblioteca HTTP do código é usada só no llm_client (Ollama)
    for arquivo in (RAIZ / "src/tia").rglob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")
        if re.search(r"(requests|sessao)\.(post|get|put|request)\(", texto):
            # llm_client: Ollama; implantacao/verificar: a própria API em API_URL_LOCAL (127.0.0.1)
            assert arquivo.name in ("llm_client.py", "verificar.py"), arquivo
        assert not re.search(r"^\s*import (httpx|urllib3|aiohttp|socket)\b", texto, re.M), arquivo


# --- D1: cabeçalhos e /docs ---

def test_cabecalhos_em_todas_as_respostas():
    c = TestClient(app)
    respostas = {"health": c.get("/health"), "eu": c.get("/auth/eu"), "404": c.get("/nao-existe"),
                 "422": c.post("/auth/login", json={}, headers=CSRF_LOGIN), "app": c.get("/app/"),
                 "js": c.get("/app/comum.js"), "painel": c.get("/painel/competencias"),
                 "csv": c.get("/painel/exportar/indicadores.csv")}
    for nome, resposta in respostas.items():
        assert "content-security-policy" in resposta.headers, nome
        assert resposta.headers["x-content-type-options"] == "nosniff", nome
        assert resposta.headers["referrer-policy"] == "no-referrer", nome
        assert "frame-ancestors 'none'" in resposta.headers["content-security-policy"], nome
    assert respostas["health"].headers["cache-control"] == "no-store"


def test_cabecalhos_tambem_em_401_e_403(auth_ligada):
    c = TestClient(app)
    assert "content-security-policy" in c.get("/painel/competencias").headers  # 401
    usuarios.criar("A2026-H01", "aluno", SENHA, "A2026-H01", temporaria=False)
    c.post("/auth/login", json={"login": "A2026-H01", "senha": SENHA}, headers=CSRF_LOGIN)
    negado = c.get("/painel/competencias")
    assert negado.status_code == 403 and negado.headers["x-content-type-options"] == "nosniff"


def test_docs_desligado_por_configuracao(monkeypatch):
    monkeypatch.setattr(config, "API_DOCS", False)
    c = TestClient(criar_app())
    for rota in ("/docs", "/openapi.json", "/redoc"):
        assert c.get(rota).status_code == 404, rota
    monkeypatch.setattr(config, "API_DOCS", True)
    c = TestClient(criar_app())
    docs = c.get("/docs")
    assert docs.status_code == 200 and "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert c.get("/openapi.json").status_code == 200 and c.get("/redoc").status_code == 404


def test_docs_padrao_por_ambiente():
    def valor(ambiente: dict) -> str:
        return subprocess.run([sys.executable, "-c", "import tia.core.config as c; print(c.API_DOCS)"],
                              capture_output=True, text=True, env={"PATH": "", **ambiente}).stdout.strip()
    assert valor({}) == "False"                                         # padrão: produção, sem /docs
    assert valor({"TIA_AMBIENTE": "desenvolvimento"}) == "True"
    assert valor({"TIA_AMBIENTE": "producao", "API_DOCS": "1"}) == "True"


def test_api_nao_sobe_com_configuracao_insegura_em_producao(monkeypatch):
    monkeypatch.setattr(config, "EM_PRODUCAO", True)
    monkeypatch.setattr(config, "AUTH_DESLIGADA", True)
    with pytest.raises(RuntimeError, match="TIA_AUTH=desligada"):
        with TestClient(criar_app()):
            pass
    monkeypatch.setattr(config, "AUTH_DESLIGADA", False)
    monkeypatch.setattr(config, "AUTH_COOKIE_SEGURO", True)
    monkeypatch.setattr(config, "AUTH_LIMPEZA_MINUTOS", 0)
    with TestClient(criar_app()) as c:  # configuração boa: sobe
        assert c.get("/health").status_code == 200


@pytest.mark.parametrize("url, problema", [
    ("http://localhost:11434", False), ("http://127.0.0.1:11434", False), ("http://10.0.0.5:11434", False),
    ("http://192.168.1.20:11434", False), ("https://api.openai.com", True), ("http://8.8.8.8:11434", True),
])
def test_ollama_so_local_ou_rede_interna(monkeypatch, url, problema):
    monkeypatch.setattr(config, "OLLAMA_URL", url)
    monkeypatch.setattr(config, "AUTH_DESLIGADA", False)
    monkeypatch.setattr(config, "AUTH_COOKIE_SEGURO", True)
    assert bool(config.problemas_de_configuracao()) is problema


# --- D4: login recusado de muitos IPs ---

def cliente_com_ip(ip: str) -> TestClient:
    async def com_ip(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": (ip, 50000)}
        await app(scope, receive, send)
    return TestClient(com_ip)


def test_login_recusado_de_muitos_ips_agregado(auth_ligada):
    for n in range(60):
        resposta = cliente_com_ip(f"10.1.0.{n}").post(
            "/auth/login", json={"login": f"X-{n:03d}", "senha": "errada-errada"}, headers=CSRF_LOGIN)
        assert resposta.status_code == 401
    falhas = registros("login_falha")
    assert len(falhas) == config.AUTH_ANONIMOS_MAX_ORIGENS  # 50 uma a uma, e não 60
    assert len(consultar("SELECT * FROM auth_tentativas")) == 60  # o bloqueio continua vendo todas
    anonimos.resumir(datetime.now() + timedelta(minutes=config.AUTH_ANONIMOS_JANELA_MINUTOS))
    resumo = registros("resumo_anonimos")[-1]
    assert resumo["origem"] == "login_falha" and resumo["motivo"].startswith("60 pedidos de 60 origem(ns)")
    assert "50 registrado(s) um a um" in resumo["motivo"] and "60 login(s) diferente(s)" in resumo["motivo"]
    assert "10.1.0." not in json.dumps(consultar("SELECT * FROM auditoria"))  # IP nunca na auditoria


def test_bloqueio_por_usuario_vindo_de_muitos_ips(auth_ligada):
    usuarios.criar("DOC-B01", "docente", SENHA, temporaria=False)
    for n in range(config.AUTH_MAX_FALHAS_USUARIO):
        cliente_com_ip(f"10.2.0.{n}").post("/auth/login", json={"login": "DOC-B01", "senha": "errada-errada"},
                                          headers=CSRF_LOGIN)
    bloqueado = cliente_com_ip("10.2.0.99").post("/auth/login", json={"login": "DOC-B01", "senha": SENHA},
                                                 headers=CSRF_LOGIN)
    assert bloqueado.status_code == 429


# --- E6: importação em lote ---

def escrever(tmp_path: Path, nome: str, texto: str) -> Path:
    caminho = tmp_path / nome
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_importar_arquivo_valido(tmp_path, caplog, auth_ligada):
    caplog.set_level(logging.DEBUG)
    entrada = escrever(tmp_path, "usuarios.csv", "login;papel;aluno_id\nA2026-I01;aluno;A2026-I01\n"
                                                  "A2026-I02;Aluno;A2026-I02\nDOC-I01;docente;\n")
    saida = tmp_path / "senhas.csv"
    assert usuarios.importar(entrada, saida) == ["A2026-I01", "A2026-I02", "DOC-I01"]
    assert stat.S_IMODE(saida.stat().st_mode) == 0o600
    linhas = saida.read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "login;senha_temporaria" and len(linhas) == 4
    senhas_geradas = dict(l.split(";") for l in linhas[1:])
    assert len(set(senhas_geradas.values())) == 3
    assert all(re.fullmatch(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", s) for s in senhas_geradas.values())
    assert all(u.trocar_senha for u in usuarios.listar())
    assert usuarios.listar()[0].papel in ("aluno", "docente")
    # a senha entra, mas só para trocar
    c = TestClient(app)
    corpo = c.post("/auth/login", json={"login": "DOC-I01", "senha": senhas_geradas["DOC-I01"]},
                   headers=CSRF_LOGIN).json()
    assert corpo["usuario"]["trocar_senha"] is True
    # nenhuma senha em auditoria, banco ou log
    banco = despejo()
    for senha in senhas_geradas.values():
        assert senha not in banco and senha not in caplog.text
    assert registros("gestao_usuario")[-1]["motivo"].startswith("importação em lote: 3 usuário(s)")


@pytest.mark.parametrize("conteudo, trecho", [
    ("login,papel,aluno_id\nA2026-I01,aluno,A2026-I01\nMaria da Silva,aluno,A2026-I02\n", "linha 3: Id inválido"),
    ("login,papel,aluno_id\nA2026-I01,aluno,\n", "linha 2: Usuário com papel aluno precisa do aluno_id"),
    ("login,papel,aluno_id\nDOC-I01,professor,\n", "linha 2: Papel inválido"),
    ("login,papel,aluno_id\nDOC-I01,docente,A2026-I09\n", "linha 2: Só o papel aluno"),
    ("login,papel\nDOC-I01,docente,extra\n", "linha 2: colunas a mais"),
    ("nome,papel\nX,aluno\n", "Cabeçalho"),
    ("", "Arquivo vazio"),
])
def test_importar_arquivo_invalido_nao_cria_nada(tmp_path, conteudo, trecho):
    entrada, saida = escrever(tmp_path, "usuarios.csv", conteudo), tmp_path / "senhas.csv"
    with pytest.raises(usuarios.ErroUsuario, match=re.escape(trecho)):
        usuarios.importar(entrada, saida)
    assert usuarios.listar() == [] and not saida.exists()


@pytest.mark.parametrize("conteudo, trecho", [
    ("login,papel,aluno_id\nA2026-I01,aluno,A2026-I01\nDOC-I01,docente,\na2026-i01,aluno,A2026-I03\n",
     "linha 4: login repetido (já na linha 2)"),
    ("login,papel,aluno_id\nA2026-I01,aluno,A2026-I01\nA2026-I02,aluno,A2026-I01\n",
     "linha 3: aluno_id repetido (já na linha 2)"),
    ("login,papel,aluno_id\nDOC-I01,docente,\nDOC-EXISTE,docente,\n", "linha 3: já existe usuário com esse login"),
    ("login,papel,aluno_id\nA2026-I05,aluno,A2026-LIGADO\n", "linha 2: esse aluno_id já está ligado"),
])
def test_importar_repetido_nao_cria_nada(tmp_path, conteudo, trecho):
    usuarios.criar("DOC-EXISTE", "docente", SENHA)
    usuarios.criar("A2026-LIG", "aluno", SENHA, "A2026-LIGADO")
    entrada, saida = escrever(tmp_path, "usuarios.csv", conteudo), tmp_path / "senhas.csv"
    with pytest.raises(usuarios.ErroUsuario, match=re.escape(trecho)):
        usuarios.importar(entrada, saida)
    assert {u.id for u in usuarios.listar()} == {"DOC-EXISTE", "A2026-LIG"} and not saida.exists()


def test_mensagem_de_erro_nao_repete_o_conteudo(tmp_path):
    entrada = escrever(tmp_path, "usuarios.csv", "login,papel,aluno_id\nMaria da Silva,aluno,A2026-I02\n")
    with pytest.raises(usuarios.ErroUsuario) as erro:
        usuarios.importar(entrada, tmp_path / "senhas.csv")
    assert "Maria" not in str(erro.value)


def test_importar_nao_sobrescreve_a_saida(tmp_path):
    entrada = escrever(tmp_path, "usuarios.csv", "login,papel,aluno_id\nDOC-I01,docente,\n")
    saida = escrever(tmp_path, "senhas.csv", "não apagar")
    with pytest.raises(FileExistsError):
        usuarios.importar(entrada, saida)
    assert saida.read_text(encoding="utf-8") == "não apagar" and usuarios.listar() == []


def test_comando_importar(tmp_path):
    ambiente = {"DB_PATH": str(tmp_path / "imp.db"), "PATH": "", "PYTHONIOENCODING": "utf-8"}
    entrada = escrever(tmp_path, "usuarios.csv", "login,papel,aluno_id\nDOC-I01,docente,\n")
    comando = [sys.executable, "-m", "tia.seguranca.usuarios", "importar", "--arquivo", str(entrada)]
    feito = subprocess.run(comando + ["--saida", str(tmp_path / "s.csv")], capture_output=True, text=True,
                           env=ambiente)
    assert feito.returncode == 0 and "APAGUE o arquivo" in feito.stdout
    senha = (tmp_path / "s.csv").read_text(encoding="utf-8").splitlines()[1].split(";")[1]
    assert senha not in feito.stdout + feito.stderr  # a senha nunca vai para o terminal
    repetido = subprocess.run(comando + ["--saida", str(tmp_path / "t.csv")], capture_output=True, text=True,
                              env=ambiente)
    assert repetido.returncode != 0 and "nada foi criado" in repetido.stderr
