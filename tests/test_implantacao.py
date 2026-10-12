"""
Testes do pacote de implantação na VM (EAP 1.4.1), sem root e sem Ollama de
verdade (LLM simulado), em pastas temporárias:

- 1.1 lista de modelos e modelo padrão configuráveis;
- 1.2 modo de raciocínio por modelo (corpo enviado ao Ollama) e remoção dos
  blocos de raciocínio antes das guardas, com respostas simuladas com e sem
  esses blocos (completo, vazio, só o fechamento, aberto e cortado);
- scripts: instalar.sh, modelos.sh e preparar_pacote.sh em --simular (nada
  muda); backup.sh e restaurar.sh de verdade numa pasta temporária;
  verificar.sh de ponta a ponta contra a API real (subprocesso) e um Ollama
  falso, inclusive --medir-r09;
- arquivos: unidades do systemd, requirements travado e exemplo do proxy.

Como rodar:
    ./run_tests.sh tests/test_implantacao.py
"""

import csv
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

import tia.core.config as config
import tia.core.database as database
import tia.core.llm_client as llm_client
from tia.agentes.planejador import justificar
from tia.agentes.relatorio import narrativa
from tia.agentes.tutor import feedback as feedback_mod
from tia.agentes.tutor.repositorio import carregar_itens
from tia.implantacao import backup, modelos, verificar

RAIZ = Path(__file__).parents[1]
DEPLOY = RAIZ / "deploy"
POST_REAL, GET_REAL = requests.post, requests.get  # antes do conftest trocar o post


class RespostaFalsa:
    def __init__(self, dados: dict):
        self.dados = dados

    def raise_for_status(self):
        pass

    def json(self) -> dict:
        return self.dados


def ollama_falso(monkeypatch, conteudo: str, **extra):
    """Troca o POST do llm_client por um que devolve `conteudo`; devolve os corpos enviados."""
    enviados = []

    def post(url, json, timeout):
        enviados.append(json)
        return RespostaFalsa({"message": {"content": conteudo, **extra.pop("mensagem", {})}, **extra})

    monkeypatch.setattr(llm_client.requests, "post", post)
    return enviados


# --- 1.1 modelos configuráveis ---

def _config(ambiente: dict, expressao: str) -> str:
    return subprocess.run([sys.executable, "-c", f"import tia.core.config as c; print({expressao})"],
                          capture_output=True, text=True, env={"PATH": "", **ambiente}, cwd="/").stdout.strip()


def test_lista_de_modelos_e_padrao():
    assert _config({}, "c.MODELOS_LLM") == "['qwen3:1.7b', 'qwen3:4b', 'qwen3:8b', 'qwen3.5:9b']"
    assert _config({"MODELOS_LLM": " a:1b , b:2b ,"}, "c.MODELOS_LLM") == "['a:1b', 'b:2b']"
    assert _config({}, "c.MODELO_PADRAO") == "qwen3:1.7b"
    assert _config({"CHAT_MODEL": "qwen3:4b"}, "c.MODELO_PADRAO") == "qwen3:4b"  # nome antigo ainda vale
    assert _config({"CHAT_MODEL": "x", "MODELO_PADRAO": "qwen3:8b"}, "c.MODELO_PADRAO, c.CHAT_MODEL") == \
        "qwen3:8b qwen3:8b"


def test_modelo_padrao_fora_da_lista_e_aviso_nao_bloqueio(monkeypatch):
    monkeypatch.setattr(config, "MODELO_PADRAO", "outro:1b")
    assert any("MODELO_PADRAO" in a for a in config.avisos_de_configuracao())
    assert not any("MODELO_PADRAO" in p for p in config.problemas_de_configuracao())


def test_usar_modelo_troca_o_padrao_so_no_bloco(monkeypatch):
    enviados = ollama_falso(monkeypatch, "oi")
    with llm_client.usar_modelo("qwen3:8b"):
        llm_client.chamar_llm("x")
        llm_client.chamar_llm("x", model="qwen3:4b")  # model= explícito vence
    llm_client.chamar_llm("x")
    assert [e["model"] for e in enviados] == ["qwen3:8b", "qwen3:4b", config.MODELO_PADRAO]


# --- 1.2 modo de raciocínio por modelo ---

@pytest.mark.parametrize("modelo, modo", [("qwen3:1.7b", "prompt+api"), ("qwen3:8b", "prompt+api"),
                                          ("qwen3.5:9b", "api"), ("llama3.2:3b", "nada")])
def test_mapa_padrao(modelo, modo):
    assert llm_client.modo_raciocinio(modelo) == modo


@pytest.mark.parametrize("modo, sufixo, campo_think", [("prompt", True, None), ("api", False, False),
                                                       ("prompt+api", True, False), ("nada", False, None)])
def test_corpo_enviado_por_modo(monkeypatch, modo, sufixo, campo_think):
    monkeypatch.setattr(config, "RACIOCINIO_POR_MODELO", f"m:*={modo}")
    enviados = ollama_falso(monkeypatch, "oi")
    llm_client.chamar_llm("Pergunta", model="m:1b")
    corpo = enviados[0]
    assert corpo["messages"][-1]["content"].endswith("/nothink") is sufixo
    assert corpo.get("think") is campo_think


def test_mapa_primeira_regra_vale_e_regra_invalida(monkeypatch):
    monkeypatch.setattr(config, "RACIOCINIO_POR_MODELO", "qwen3:8b=nada; qwen3:*=api")
    assert llm_client.modo_raciocinio("qwen3:8b") == "nada" and llm_client.modo_raciocinio("qwen3:4b") == "api"
    monkeypatch.setattr(config, "RACIOCINIO_POR_MODELO", "qwen3:*=desligar")
    with pytest.raises(ValueError, match="RACIOCINIO_POR_MODELO"):
        llm_client.modo_raciocinio("qwen3:4b")


@pytest.mark.parametrize("bruto, limpo, havia, aberto", [
    ("Resposta direta.", "Resposta direta.", False, False),
    ("<think>\n\n</think>\n\nResposta.", "Resposta.", False, False),               # qwen3 com /nothink
    ("<think>Vou calcular 2+2=4.</think>Resposta.", "Resposta.", True, False),
    ("<Thinking>passo 1</Thinking> Resposta.", "Resposta.", True, False),
    ("raciocínio sem abertura</think>\nResposta.", "Resposta.", True, False),      # abertura veio no template
    ("Começo. <think>raciocínio cortado pelo limite", "Começo.", True, True),
    ("<think>só raciocínio, cortado", "", True, True),
    ("<reasoning>a</reasoning><think>b</think>Fim.", "Fim.", True, False),
])
def test_remover_raciocinio(bruto, limpo, havia, aberto):
    assert llm_client.remover_raciocinio(bruto) == (limpo, havia, aberto)


def test_chamada_devolve_texto_sem_raciocinio_e_registra(monkeypatch):
    ollama_falso(monkeypatch, "<think>pensei</think>Texto final.", done_reason="length", eval_count=200,
                 mensagem={"thinking": "pensou pela API"})
    with llm_client.coletar_chamadas() as chamadas:
        assert llm_client.chamar_llm("x", model="qwen3:4b") == "Texto final."
    c = chamadas[0]
    assert (c.modelo, c.modo_raciocinio, c.raciocinio_no_texto, c.raciocinio_api, c.cortada, c.tokens, c.vazia) == (
        "qwen3:4b", "prompt+api", True, True, True, 200, False)


def test_falha_tambem_e_registrada(monkeypatch):
    def falha(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(llm_client.requests, "post", falha)
    with llm_client.coletar_chamadas() as chamadas:
        with pytest.raises(requests.Timeout):
            llm_client.chamar_llm("x")
    assert chamadas[0].falha == "timeout" and not chamadas[0].vazia


ITEM = next(i for i in carregar_itens())
TRECHOS = [{"texto": ITEM["explicacao"] + " " + ITEM["enunciado"], "fonte": "provisorio.txt", "indice": 0,
            "distancia": 100.0}]


def test_guarda_do_feedback_nao_ve_o_raciocinio(monkeypatch):
    """Um número inventado DENTRO do raciocínio seria barrado pela guarda; fora dele, não chega lá."""
    monkeypatch.setattr(feedback_mod, "buscar_trechos", lambda item, materiais: TRECHOS)
    ollama_falso(monkeypatch, "<think>Talvez o resultado seja 987654.</think>" + ITEM["explicacao"])
    resultado = feedback_mod.gerar_feedback(ITEM, ITEM["indice_correto"], ["provisorio.txt"])
    assert resultado.origem == "LLM" and "987654" not in resultado.explicacao


def test_raciocinio_cortado_vira_fallback_sem_vazar(monkeypatch):
    monkeypatch.setattr(feedback_mod, "buscar_trechos", lambda item, materiais: TRECHOS)
    ollama_falso(monkeypatch, "<think>Pensando no item e no aluno, o valor 987654 parece", done_reason="length")
    resultado = feedback_mod.gerar_feedback(ITEM, ITEM["indice_correto"], ["provisorio.txt"])
    # bloco aberto: sobra texto vazio, então vai a explicação do item, sem passar pela guarda
    assert (resultado.origem, resultado.explicacao, resultado.explicacao_descartada) == (
        "fallback", ITEM["explicacao"], "")


def test_narrativa_e_planejador_recebem_texto_limpo(monkeypatch):
    ollama_falso(monkeypatch, "<think>rascunho com 123</think>A turma avançou bem.")
    assert narrativa.redigir("progresso: 50%", "turma").texto == "A turma avançou bem."
    ollama_falso(monkeypatch, "raciocínio 1. que vazou</think>\n1. Frase da primeira etapa.")
    assert justificar.extrair_frases(llm_client.chamar_llm("x"), 1) == {1: "Frase da primeira etapa."}


# --- verificar: partes testáveis em processo ---

def test_percentis_pelo_posto_mais_proximo():
    valores = [float(v) for v in range(1, 21)]
    assert (verificar.percentil(valores, 50), verificar.percentil(valores, 90), verificar.percentil(valores, 95)) == (
        10.0, 18.0, 19.0)
    assert verificar.percentil([7.0], 95) == 7.0


def test_medir_r09_com_llm_simulado(monkeypatch, tmp_path):
    def post(url, json, timeout):
        com_raciocinio = json["model"] == "pensa:1b"
        texto = ("1. Primeira etapa da trilha.\n2. Segunda etapa.\n3. Terceira.\n4. Quarta.\n5. Quinta.\n6. Sexta."
                 if "lista numerada" in json["messages"][-1]["content"] else ITEM["explicacao"])
        return RespostaFalsa({"message": {"content": ("<think>pensando</think>" if com_raciocinio else "") + texto},
                              "done_reason": "stop", "eval_count": 30})
    monkeypatch.setattr(llm_client.requests, "post", post)
    monkeypatch.setattr(feedback_mod, "buscar_trechos", lambda item, materiais: TRECHOS)
    import tia.agentes.tutor.dialogo as dialogo
    monkeypatch.setattr(dialogo, "buscar_trechos_dialogo", lambda pergunta, materiais: [])  # sem material: fallback
    medidas = verificar.medir_r09(2, ["pensa:1b", "direto:1b"])
    assert len(medidas) == 2 * (1 + 2 * 3)
    assert sum(m.aquecimento for m in medidas) == 2
    resumos = {(r.modelo, r.tipo): r for r in verificar.resumir(medidas)}
    assert set(resumos) == {(m, t) for m in ("pensa:1b", "direto:1b") for t in verificar.TIPOS}
    assert resumos[("pensa:1b", "planejamento")].raciocinio_vazou == 2
    assert resumos[("direto:1b", "planejamento")].raciocinio_vazou == 0
    assert resumos[("direto:1b", "dialogo")].sem_llm == 2 and resumos[("direto:1b", "dialogo")].fallback == 2
    assert resumos[("direto:1b", "planejamento")].dentro_do_limite == 1.0
    saida = tmp_path / "r09.csv"
    verificar.gravar_csv(medidas, saida)
    linhas = list(csv.DictReader(saida.open(encoding="utf-8"), delimiter=";"))
    assert len(linhas) == len(medidas) and {"modelo", "tipo", "tempo_s", "raciocinio_no_texto", "cortada",
                                             "vazia", "origem"} <= set(linhas[0])
    assert "," in linhas[1]["tempo_s"] or linhas[1]["tempo_s"].isdigit()  # vírgula decimal
    tabela = verificar.tabela_resumo(verificar.resumir(medidas))
    assert "p95" in tabela and "pensa:1b" in tabela


def test_conexoes_de_saida(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://10.0.0.7:11434")
    tcp = tmp_path / "tcp"
    tcp.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:1F40 00000000:0000 0A\n"   # 127.0.0.1:8000 em escuta (API)
        "   1: 00000000:0016 00000000:0000 0A\n"   # 0.0.0.0:22 em escuta (ssh)
        "   2: 0500000A:0016 0900000A:D431 01\n"   # entrada de ssh (10.0.0.9): ignorada
        "   3: 0100007F:C738 0100007F:2CAA 01\n"   # 127.0.0.1 -> Ollama local
        "   4: 0500000A:C739 0700000A:2CAA 01\n"   # -> Ollama na rede interna (permitido)
        "   5: 0500000A:C73A 08080808:01BB 01\n"   # -> 8.8.8.8:443  INESPERADA
        "   6: 0500000A:C73B 08080808:01BB 06\n")  # TIME_WAIT: ignorada
    tcp6 = tmp_path / "tcp6"
    tcp6.write_text("  sl  local_address remote_address st\n"
                    "   0: 00000000000000000000000001000000:C73C 0000000000000000FFFF00000A0B0C0D:0050 01\n")
    assert verificar.conexoes_de_saida([tcp, tcp6]) == ["13.12.11.10:80", "8.8.8.8:443"]
    assert verificar.verificar_rede([tcp]).ok is False
    tcp.write_text("  sl  local_address rem_address   st\n   0: 0100007F:1F40 00000000:0000 0A\n")
    assert verificar.verificar_rede([tcp]).ok is True


def test_conferir_modelos(monkeypatch):
    monkeypatch.setattr(llm_client, "listar_modelos_instalados", lambda timeout=10: ["a:1b", "nomic-embed-text:latest"])
    ollama_falso(monkeypatch, "<think>hm</think>ok")
    monkeypatch.setattr(llm_client, "gerar_embedding", lambda texto, model=None, timeout=60: [0.1] * 8)
    situacoes = {s.modelo: s for s in modelos.conferir(["a:1b", "b:1b"], "nomic-embed-text")}
    assert situacoes["a:1b"].respondeu and situacoes["a:1b"].raciocinio_vazou
    assert not situacoes["b:1b"].instalado and "modelos.sh" in situacoes["b:1b"].detalhe
    assert situacoes["nomic-embed-text"].respondeu and "8 dimensões" in situacoes["nomic-embed-text"].detalhe
    assert "NÃO" in modelos.relatorio(list(situacoes.values()))


# --- backup e restauração ---

def preparar_dados(tmp_path: Path, monkeypatch) -> dict:
    banco, chroma = tmp_path / "data" / "tia.db", tmp_path / "data" / "chroma_db"
    monkeypatch.setattr(database, "DB_PATH", str(banco))
    monkeypatch.setattr(config, "CHROMA_DIR", str(chroma))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backup"))
    database.criar_tabelas()
    conexao = database.obter_conexao()
    with conexao:
        conexao.execute("INSERT INTO alunos (id) VALUES ('A2026-B01')")
    conexao.close()
    chroma.mkdir(parents=True)
    (chroma / "chroma.sqlite3").write_text("indice", encoding="utf-8")
    env = tmp_path / "config" / ".env"
    env.parent.mkdir()
    env.write_text("TIA_AMBIENTE=producao\n", encoding="utf-8")
    return {"banco": banco, "chroma": chroma, "env": env}


def alunos(banco: Path) -> list[str]:
    import sqlite3
    conexao = sqlite3.connect(banco)
    try:
        return [l[0] for l in conexao.execute("SELECT id FROM alunos ORDER BY id")]
    finally:
        conexao.close()


def test_backup_e_restauracao_em_pasta_temporaria(tmp_path, monkeypatch):
    d = preparar_dados(tmp_path, monkeypatch)
    from datetime import datetime
    agora = datetime(2026, 10, 15, 2, 30)
    assert backup.fazer(d["env"], agora=agora, simular=True)[0].startswith("copiar o banco")
    assert not (tmp_path / "backup").exists()  # simular não cria nada
    backup.fazer(d["env"], agora=agora)
    pasta = tmp_path / "backup" / "20261015-023000"
    assert stat.S_IMODE(pasta.stat().st_mode) == 0o700
    assert {p.name for p in pasta.iterdir()} == {"tia.db", "chroma.tar.gz", "SHA256SUMS"}
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in pasta.iterdir())
    env_guardado = tmp_path / "backup" / "config" / "env-20261015-023000"
    assert env_guardado.read_text(encoding="utf-8") == "TIA_AMBIENTE=producao\n"
    # estrago depois do backup
    conexao = database.obter_conexao()
    with conexao:
        conexao.execute("DELETE FROM alunos")
        conexao.execute("INSERT INTO alunos (id) VALUES ('A2026-DEPOIS')")
    conexao.close()
    (d["chroma"] / "chroma.sqlite3").write_text("estragado", encoding="utf-8")
    d["env"].write_text("TIA_AMBIENTE=errado\n", encoding="utf-8")
    simulado = backup.restaurar(pasta, simular=True)
    assert alunos(d["banco"]) == ["A2026-DEPOIS"] and any("guardar o atual" in a for a in simulado)
    backup.restaurar(pasta, com_env=d["env"], agora=datetime(2026, 10, 15, 9, 0))
    assert alunos(d["banco"]) == ["A2026-B01"]
    assert (d["chroma"] / "chroma.sqlite3").read_text(encoding="utf-8") == "indice"
    assert d["env"].read_text(encoding="utf-8") == "TIA_AMBIENTE=producao\n"
    # nada foi apagado: os atuais ficaram ao lado
    assert alunos(d["banco"].with_name("tia.db.antes-restauracao-20261015-090000")) == ["A2026-DEPOIS"]
    assert (d["chroma"].with_name("chroma_db.antes-restauracao-20261015-090000") / "chroma.sqlite3").exists()
    assert stat.S_IMODE(d["banco"].stat().st_mode) == 0o600


def test_restauracao_recusa_backup_alterado(tmp_path, monkeypatch):
    d = preparar_dados(tmp_path, monkeypatch)
    backup.fazer(d["env"])
    pasta = next(p for p in (tmp_path / "backup").iterdir() if p.name != "config")
    with open(pasta / "tia.db", "ab") as arquivo:
        arquivo.write(b"x")
    with pytest.raises(backup.ErroBackup, match="SHA256"):
        backup.restaurar(pasta)
    assert alunos(d["banco"]) == ["A2026-B01"]  # nada mudou
    with pytest.raises(backup.ErroBackup, match="não é uma pasta de backup"):
        backup.restaurar(tmp_path)


def test_rotacao_mantem_o_mais_recente_e_so_o_que_criou(tmp_path, monkeypatch):
    from datetime import datetime
    d = preparar_dados(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "BACKUP_DIAS", 7)
    estranho = tmp_path / "backup" / "nao-apagar"
    estranho.mkdir(parents=True)
    for dia in (1, 5):
        backup.fazer(d["env"], agora=datetime(2026, 10, dia, 3, 0))
    assert backup.listar() == ["20261001-030000", "20261005-030000"]
    acoes = backup.fazer(d["env"], agora=datetime(2026, 10, 20, 3, 0))  # cada backup já faz a rotação
    assert backup.listar() == ["20261020-030000"]
    assert len([a for a in acoes if "vencido" in a]) == 4  # 2 pastas + 2 .env
    assert estranho.exists()  # só apaga o que tem o formato de nome do backup
    # mesmo vencido, o único backup fica
    assert backup.rotacionar(datetime(2027, 1, 1)) == [] and backup.listar() == ["20261020-030000"]


# --- scripts em shell ---

def rodar(script: str, *args, ambiente: dict | None = None, entrada: str = "", cwd: Path = RAIZ):
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    return subprocess.run(["bash", str(DEPLOY / script), *args], capture_output=True, text=True,
                          env={**base, **(ambiente or {})}, input=entrada, cwd=cwd, timeout=600)


@pytest.mark.skipif(os.geteuid() == 0, reason="o teste confere o comportamento sem root")
def test_instalar_simular_nao_altera_nada(tmp_path):
    raiz, systemd = tmp_path / "srv", tmp_path / "systemd"
    resultado = rodar("instalar.sh", "--simular", ambiente={"TIA_RAIZ": str(raiz), "SYSTEMD_DIR": str(systemd)})
    assert resultado.returncode == 0, resultado.stderr
    saida = resultado.stdout
    for trecho in ("SIMULAÇÃO", "1. Conferências", "Python 3.12 com venv: ok", "[simular] useradd --system",
                   "install -d -m 700 -o tia -g tia", f"{raiz}/versoes/simulacao", "--no-index --find-links",
                   f"install -m 640 -o root -g tia", "tia-api.service", "systemctl enable tia-api.service",
                   "ÚNICO PASSO COM REDE"):
        assert trecho in saida, trecho
    assert "useradd" not in resultado.stderr
    assert not raiz.exists() and not systemd.exists()  # nada foi criado


@pytest.mark.skipif(os.geteuid() == 0, reason="o teste confere o comportamento sem root")
def test_instalar_exige_root_e_recusa_opcao_desconhecida(tmp_path):
    ambiente = {"TIA_RAIZ": str(tmp_path / "srv"), "TIA_SEM_ROOT": "1"}  # a instalação ignora o TIA_SEM_ROOT
    sem_root = rodar("instalar.sh", ambiente=ambiente)
    assert sem_root.returncode != 0 and "rode como root" in sem_root.stderr
    assert "opção desconhecida" in rodar("instalar.sh", "--forcar", ambiente=ambiente).stderr
    assert not (tmp_path / "srv").exists()


def test_modelos_simular_marca_o_passo_com_rede(tmp_path):
    env = tmp_path / ".env"
    env.write_text('MODELOS_LLM=qwen3:1.7b,qwen3:4b\nEMBED_MODEL=nomic-embed-text\n', encoding="utf-8")
    resultado = rodar("modelos.sh", "--simular", ambiente={"TIA_ENV": str(env), "TIA_PYTHON": sys.executable,
                                                           "TIA_RAIZ": str(tmp_path)})
    assert resultado.returncode == 0, resultado.stderr
    assert "USA REDE" in resultado.stdout
    for modelo in ("qwen3:1.7b", "qwen3:4b", "nomic-embed-text"):
        assert f"[simular] ollama pull {modelo}" in resultado.stdout
    sem_download = rodar("modelos.sh", "--simular", "--sem-download",
                         ambiente={"TIA_ENV": str(env), "TIA_PYTHON": sys.executable, "TIA_RAIZ": str(tmp_path)})
    assert "ollama pull" not in sem_download.stdout and "pulado" in sem_download.stdout


def test_preparar_pacote_simular():
    antes = sorted((RAIZ / "dist").glob("*")) if (RAIZ / "dist").exists() else None
    resultado = rodar("preparar_pacote.sh", "--simular", ambiente={"PYTHON": sys.executable})
    assert resultado.returncode == 0, resultado.stderr
    assert "USA REDE: PyPI" in resultado.stdout and "pip wheel --wheel-dir" in resultado.stdout
    depois = sorted((RAIZ / "dist").glob("*")) if (RAIZ / "dist").exists() else None
    assert depois == antes  # simular não cria o pacote


def test_backup_sh_e_restaurar_sh_de_verdade(tmp_path):
    dados, copias = tmp_path / "data", tmp_path / "backup"
    env = tmp_path / ".env"
    env.write_text(f"DB_PATH={dados / 'tia.db'}\nCHROMA_DIR={dados / 'chroma_db'}\nBACKUP_DIR={copias}\n",
                   encoding="utf-8")
    ambiente = {"TIA_ENV": str(env), "TIA_PYTHON": sys.executable, "TIA_RAIZ": str(tmp_path), "TIA_SEM_ROOT": "1"}
    subprocess.run([sys.executable, "-c", "from tia.core.database import criar_tabelas; criar_tabelas()"],
                   env={**os.environ, "DB_PATH": str(dados / "tia.db")}, check=True, capture_output=True)
    assert "faria: copiar o banco" in rodar("backup.sh", "--simular", ambiente=ambiente).stdout
    assert not copias.exists()
    feito = rodar("backup.sh", ambiente=ambiente)
    assert feito.returncode == 0, feito.stderr
    pasta = next(p for p in copias.iterdir() if p.name != "config")
    assert (copias / "config").is_dir() and stat.S_IMODE(copias.stat().st_mode) == 0o700
    assert pasta.name in rodar("backup.sh", "--listar", ambiente=ambiente).stdout
    restaurado = rodar("restaurar.sh", str(pasta), ambiente=ambiente)
    assert restaurado.returncode == 0, restaurado.stderr
    assert "restaurar" in restaurado.stdout and list(dados.glob("tia.db.antes-restauracao-*"))
    assert "informe a pasta" in rodar("restaurar.sh", ambiente=ambiente).stderr


# --- verificar.sh de ponta a ponta: API real (subprocesso) e Ollama falso ---

def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OllamaFalso(BaseHTTPRequestHandler):
    modelos = ("pensa:1b", "direto:1b", "nomic-embed-text:latest")

    def log_message(self, *args):
        pass

    def _responder(self, dados: dict):
        corpo = json.dumps(dados).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        self._responder({"models": [{"name": m} for m in self.modelos]})

    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embeddings":
            semente = sum(map(ord, pedido["prompt"]))
            self._responder({"embedding": [((semente * (i + 3)) % 97) / 97 for i in range(16)]})
            return
        texto = pedido["messages"][-1]["content"]
        resposta = ("1. Primeira etapa.\n2. Segunda etapa.\n3. Terceira.\n4. Quarta.\n5. Quinta.\n6. Sexta."
                    if "lista numerada" in texto else "ok.")
        if pedido["model"] == "pensa:1b":
            resposta = "<think>raciocínio vazando</think>" + resposta
        self._responder({"message": {"content": resposta}, "done_reason": "stop", "eval_count": 12})


@pytest.fixture
def vm_simulada(tmp_path):
    """API do TIA num subprocesso (produção) + Ollama falso, com índice do RAG feito pelo reindexador."""
    servidor = ThreadingHTTPServer(("127.0.0.1", porta_livre()), OllamaFalso)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta_api = porta_livre()
    valores = {
        "OLLAMA_URL": f"http://127.0.0.1:{servidor.server_address[1]}", "API_URL_LOCAL": f"http://127.0.0.1:{porta_api}",
        "DB_PATH": str(tmp_path / "data" / "tia.db"), "CHROMA_DIR": str(tmp_path / "data" / "chroma_db"),
        "MATERIAIS_DIR": str(RAIZ / "conteudo" / "materiais"), "MODELOS_LLM": "pensa:1b,direto:1b",
        "MODELO_PADRAO": "direto:1b", "RACIOCINIO_POR_MODELO": '"*=api"', "TIA_AMBIENTE": "producao",
        "TIA_AUTH": "ligada", "AUTH_COOKIE_SEGURO": "1", "AUTH_LIMPEZA_MINUTOS": "0",
    }
    env = tmp_path / ".env"
    env.write_text("".join(f"{k}={v}\n" for k, v in valores.items()), encoding="utf-8")
    ambiente_python = {**os.environ, **{k: v.strip('"') for k, v in valores.items()}}
    subprocess.run([sys.executable, "-m", "tia.rag.ingest"], env=ambiente_python, cwd=RAIZ, check=True,
                   capture_output=True, timeout=300)
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "tia.api.main:app", "--host", "127.0.0.1",
                            "--port", str(porta_api), "--no-access-log"], env=ambiente_python, cwd=RAIZ,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if GET_REAL(f"http://127.0.0.1:{porta_api}/health", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.2)
        os.chmod(tmp_path / "data" / "tia.db", 0o600)
        yield {"TIA_ENV": str(env), "TIA_PYTHON": sys.executable, "TIA_RAIZ": str(tmp_path), "TIA_SEM_ROOT": "1"}
    finally:
        api.terminate()
        api.wait(timeout=10)
        servidor.shutdown()


def test_verificar_sh_fumaca(vm_simulada):
    resultado = rodar("verificar.sh", ambiente=vm_simulada)
    linhas = {l.split("]")[1].split(":")[0].strip(): l for l in resultado.stdout.splitlines() if l.startswith("[")}
    for nome in ("configuracao", "banco", "api", "login", "ollama", "chroma"):
        assert linhas[nome].startswith("[ok]"), linhas[nome]
    assert "rede" in linhas  # depende das conexões desta máquina; o algoritmo tem teste próprio
    assert "nenhum admin ativo" in linhas["banco"]


def test_verificar_sh_login_de_verdade(vm_simulada, tmp_path):
    criar = ("from tia.seguranca import usuarios; "
             "usuarios.criar('ADM-V01', 'admin', 'senha-de-verificacao-1', temporaria=False)")
    subprocess.run([sys.executable, "-c", criar], env={**os.environ, "DB_PATH": str(tmp_path / "data" / "tia.db")},
                   check=True, capture_output=True)
    certo = rodar("verificar.sh", "--usuario", "ADM-V01", entrada="senha-de-verificacao-1\n", ambiente=vm_simulada)
    assert "[ok] login: login, /auth/eu e saída de ADM-V01" in certo.stdout
    assert "senha-de-verificacao-1" not in certo.stdout + certo.stderr
    errado = rodar("verificar.sh", "--usuario", "ADM-V01", entrada="outra\n", ambiente=vm_simulada)
    assert "[FALHOU] login: login de ADM-V01 respondeu 401" in errado.stdout


def test_verificar_sh_medir_r09(vm_simulada, tmp_path):
    saida = tmp_path / "medicoes" / "r09.csv"
    resultado = rodar("verificar.sh", "--medir-r09", "1", "--tipos", "planejamento,dialogo", "--saida", str(saida),
                      ambiente=vm_simulada)
    assert resultado.returncode == 0, resultado.stderr
    medidas = list(csv.DictReader(saida.open(encoding="utf-8"), delimiter=";"))
    assert len(medidas) == 2 * (1 + 2)  # aquecimento + 1 de cada tipo, por modelo
    planejamento = {m["modelo"]: m for m in medidas if m["tipo"] == "planejamento"}
    assert planejamento["pensa:1b"]["raciocinio_no_texto"] == "1"
    assert planejamento["direto:1b"]["raciocinio_no_texto"] == "0"
    assert planejamento["direto:1b"]["origem"] == "LLM"
    resumo = saida.with_name("r09-resumo.csv")
    assert resumo.exists() and "p95" in resultado.stdout and "Limite do R09: 15 s" in resultado.stdout


# --- arquivos de deploy/ ---

def test_unidades_do_systemd():
    pasta = DEPLOY / "systemd"
    servicos = sorted(pasta.glob("*.service"))
    assert {s.stem for s in servicos} == {"tia-api", "tia-limpeza", "tia-inatividade", "tia-retencao", "tia-backup"}
    for servico in servicos:
        texto = servico.read_text(encoding="utf-8")
        for exigido in ("User=@TIA_USUARIO@", "NoNewPrivileges=true", "ProtectSystem=strict", "UMask=0077",
                        "EnvironmentFile=@TIA_RAIZ@/config/.env"):
            assert exigido in texto, (servico.name, exigido)
        if servico.stem != "tia-api":
            assert (pasta / f"{servico.stem}.timer").exists(), servico.name
    api = (pasta / "tia-api.service").read_text(encoding="utf-8")
    for exigido in ("--host 127.0.0.1", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1", "--no-access-log",
                    "Restart=on-failure"):
        assert exigido in api, exigido
    assert "--simular" in (pasta / "tia-retencao.service").read_text(encoding="utf-8")
    assert "OLLAMA_HOST=127.0.0.1:11434" in (pasta / "ollama.service.d" / "tia.conf").read_text(encoding="utf-8")


def test_requirements_travado_cobre_o_pyproject():
    travado = {l.split("==")[0].lower(): l.split("==")[1].strip()
               for l in (DEPLOY / "requirements.lock").read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.startswith("#")}
    assert all(v for v in travado.values())  # tudo com versão exata
    import tomllib
    projeto = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    for dependencia in projeto["project"]["dependencies"]:
        nome, versao = dependencia.split("==")
        assert travado[nome.split("[")[0].lower()] == versao, dependencia
    assert "pytest" not in travado  # só o que roda em produção


def test_exemplo_do_proxy():
    texto = (DEPLOY / "proxy" / "nginx-tia.conf").read_text(encoding="utf-8")
    for exigido in ("listen 443 ssl", "ssl_protocols TLSv1.2 TLSv1.3", "Strict-Transport-Security",
                    "client_max_body_size", "X-Forwarded-Proto", "proxy_pass http://127.0.0.1:8000", "limit_req",
                    "return 301 https://"):
        assert exigido in texto, exigido


def test_scripts_sao_executaveis_e_validos():
    for script in ("instalar.sh", "modelos.sh", "backup.sh", "restaurar.sh", "verificar.sh", "preparar_pacote.sh",
                   "tia"):
        caminho = DEPLOY / script
        assert os.access(caminho, os.X_OK), script
        assert subprocess.run(["bash", "-n", str(caminho)], capture_output=True).returncode == 0, script
