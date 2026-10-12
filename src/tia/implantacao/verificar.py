"""
Teste de fumaça da VM e medição do R09 (EAP 1.4.1; deploy/verificar.sh).

Fumaça (padrão): confere, sem alterar nada,
    configuracao  nenhum problema de produção (config.problemas_de_configuracao) e avisos
    banco         arquivo existe, só o dono lê, integridade (PRAGMA integrity_check), há admin
    api           /health responde com os cabeçalhos de segurança; /docs fechado em produção
    login         autenticação ligada (/auth/eu) e login sem anti-CSRF recusado; com
                  --usuario, login de verdade (senha pela entrada padrão), /auth/eu e saída
    ollama        os modelos de MODELOS_LLM e o de embeddings instalados; o padrão responde
    chroma        a coleção do material tem trechos indexados
    rede          nenhuma conexão de SAÍDA da máquina para fora de 127.0.0.1 e do host do
                  Ollama (lê /proc/net/tcp e tcp6; sem root, sem tráfego novo)

--medir-r09 N: para CADA modelo (MODELOS_LLM ou --modelos), uma chamada de
aquecimento e N interações reais de cada tipo, pelas mesmas funções dos agentes:
    feedback      Tutor: feedback de uma questão (RAG + LLM + guarda)
    dialogo       Tutor: resposta a uma pergunta livre fixa (portão, RAG, LLM, guarda)
    planejamento  Planejador: justificativas de uma trilha
Grava uma linha por interação em CSV (";", vírgula decimal) com o tempo de
ponta a ponta, o tempo só do LLM, a origem (LLM, guarda, fallback, parcial),
o tipo do motivo de descarte, a falha, e se veio raciocínio no texto, bloco
aberto, raciocínio pela API, resposta cortada pelo limite de tokens ou vazia.
No fim, resume por modelo e tipo: média, p50, p90, p95, máximo e a fração
dentro do limite (R09_LIMITE_SEGUNDOS, 15 s). Nada é gravado no banco e nenhum
dado de aluno é usado (perguntas e itens fixos do material).

Como rodar (a partir da raiz, com o venv ativo; na VM: /srv/tia/bin/tia verificar):
    python -m tia.implantacao.verificar
    python -m tia.implantacao.verificar --usuario ADM-01 < senha.txt
    python -m tia.implantacao.verificar --medir-r09 10 --saida medicoes/r09.csv [--modelos qwen3:4b]

Pré-requisitos:
    - API no ar (API_URL_LOCAL), Ollama com os modelos (deploy/modelos.sh), RAG indexado
"""

import argparse
import csv
import ipaddress
import os
import sqlite3
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

import tia.core.config as config
import tia.core.database as database
from tia.core import llm_client

TIPOS = ("feedback", "dialogo", "planejamento")
# perguntas fixas do diálogo (sobre o material do curso; nenhuma é de aluno)
PERGUNTAS = ("O que é uma lista em Python?", "Como funciona o laço for?", "Para que serve uma função?",
             "Qual a diferença entre if e elif?", "O que é uma variável?")


@dataclass
class Verificacao:
    nome: str
    ok: bool
    detalhe: str


# --- fumaça ---

def verificar_configuracao() -> Verificacao:
    problemas = config.problemas_de_configuracao() if config.EM_PRODUCAO else []
    avisos = config.avisos_de_configuracao()
    detalhe = "; ".join(problemas + [f"aviso: {a}" for a in avisos]) or f"ambiente {config.TIA_AMBIENTE}, sem problemas"
    return Verificacao("configuracao", not problemas, detalhe)


def verificar_banco() -> Verificacao:
    caminho = Path(database.DB_PATH)
    if not caminho.exists():
        return Verificacao("banco", False, f"{caminho} não existe (a API cria ao subir)")
    problemas = []
    if caminho.stat().st_mode & 0o077:
        problemas.append(f"permissão {oct(caminho.stat().st_mode & 0o777)} (esperado 600)")
    conexao = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        integridade = conexao.execute("PRAGMA integrity_check").fetchone()[0]
        admins = conexao.execute("SELECT COUNT(*) FROM usuarios WHERE papel = 'admin' AND ativo").fetchone()[0]
    except sqlite3.Error as erro:
        return Verificacao("banco", False, f"erro ao ler ({type(erro).__name__})")
    finally:
        conexao.close()
    if integridade != "ok":
        problemas.append(f"integridade: {integridade}")
    detalhe = "; ".join(problemas) or "íntegro, só o dono lê"
    if not admins:
        detalhe += "; aviso: nenhum admin ativo (python -m tia.seguranca.usuarios criar --papel admin)"
    return Verificacao("banco", not problemas, detalhe)


def verificar_api(base: str | None = None) -> Verificacao:
    base = (base or config.API_URL_LOCAL).rstrip("/")
    try:
        saude = requests.get(f"{base}/health", timeout=10)
        docs = requests.get(f"{base}/docs", timeout=10)
    except requests.RequestException as erro:
        return Verificacao("api", False, f"{base} sem resposta ({type(erro).__name__})")
    problemas = []
    if saude.status_code != 200:
        problemas.append(f"/health respondeu {saude.status_code}")
    for cabecalho in ("content-security-policy", "x-content-type-options", "referrer-policy"):
        if cabecalho not in saude.headers:
            problemas.append(f"falta o cabeçalho {cabecalho}")
    if config.EM_PRODUCAO and docs.status_code != 404:
        problemas.append(f"/docs aberto em produção ({docs.status_code})")
    return Verificacao("api", not problemas, "; ".join(problemas) or f"{base} no ar, cabeçalhos ok, /docs fechado")


def verificar_login(base: str | None = None, usuario: str | None = None, senha: str | None = None) -> Verificacao:
    base = (base or config.API_URL_LOCAL).rstrip("/")
    sessao = requests.Session()
    try:
        situacao = sessao.get(f"{base}/auth/eu", timeout=10).json()
        if situacao.get("autenticacao") != "ligada":
            return Verificacao("login", False, "autenticação DESLIGADA")
        # sem o cabeçalho anti-CSRF o login é recusado antes de conferir a senha (nada vai para a auditoria)
        sem_csrf = sessao.post(f"{base}/auth/login", json={"login": "x", "senha": "x"}, timeout=10)
        if sem_csrf.status_code != 403:
            return Verificacao("login", False, f"login sem anti-CSRF respondeu {sem_csrf.status_code}")
        if not usuario:
            return Verificacao("login", True, "autenticação ligada; anti-CSRF ativo (login real: --usuario)")
        # o cookie é Secure: por http://127.0.0.1 o requests não o devolve; o teste usa o cabeçalho
        entrada = sessao.post(f"{base}/auth/login", json={"login": usuario, "senha": senha or ""},
                              headers={"X-CSRF-Token": "login"}, timeout=30)
        if entrada.status_code != 200:
            return Verificacao("login", False, f"login de {usuario} respondeu {entrada.status_code}")
        token = entrada.cookies.get("tia_sessao") or sessao.cookies.get("tia_sessao")
        cabecalhos = {"X-CSRF-Token": entrada.json()["csrf"], "Cookie": f"tia_sessao={token}"}
        eu = requests.get(f"{base}/auth/eu", headers=cabecalhos, timeout=10).json()
        saida = requests.post(f"{base}/auth/logout", headers=cabecalhos, timeout=10)
    except (requests.RequestException, ValueError, KeyError) as erro:
        return Verificacao("login", False, f"falhou ({type(erro).__name__})")
    ok = (eu.get("usuario") or {}).get("id") == usuario and saida.status_code == 204
    return Verificacao("login", ok, f"login, /auth/eu e saída de {usuario}" + ("" if ok else ": FALHOU"))


def verificar_ollama(modelos: list[str] | None = None) -> Verificacao:
    from tia.implantacao.modelos import _com_etiqueta
    modelos = config.MODELOS_LLM if modelos is None else modelos
    try:
        instalados = {_com_etiqueta(m) for m in llm_client.listar_modelos_instalados()}
    except Exception as erro:
        return Verificacao("ollama", False, f"{config.OLLAMA_URL} indisponível ({llm_client.descrever_falha(erro)})")
    faltam = [m for m in [*modelos, config.EMBED_MODEL] if _com_etiqueta(m) not in instalados]
    if faltam:
        return Verificacao("ollama", False, "faltam modelos: " + ", ".join(faltam) + " (deploy/modelos.sh)")
    with llm_client.coletar_chamadas() as chamadas:
        try:
            texto = llm_client.chamar_llm("Responda apenas com a palavra: ok", max_tokens=50, timeout=300)
        except Exception as erro:
            return Verificacao("ollama", False, f"{config.MODELO_PADRAO} não respondeu "
                                                f"({llm_client.descrever_falha(erro)})")
    tempo = chamadas[-1].tempo_ms / 1000 if chamadas else 0
    return Verificacao("ollama", bool(texto.strip()),
                       f"{len(modelos) + 1} modelo(s) instalado(s); {config.MODELO_PADRAO} respondeu em {tempo:.1f} s"
                       if texto.strip() else f"{config.MODELO_PADRAO} devolveu resposta vazia")


def verificar_chroma() -> Verificacao:
    from tia.rag.retrieve import abrir_cliente
    try:
        quantidade = abrir_cliente().get_collection(config.COLLECTION_NAME).count()
    except Exception as erro:
        return Verificacao("chroma", False, f"coleção {config.COLLECTION_NAME} ausente ({type(erro).__name__}); "
                                            "rode deploy/modelos.sh (reindexa)")
    return Verificacao("chroma", quantidade > 0, f"{quantidade} trecho(s) indexado(s) em {config.CHROMA_DIR}")


# --- conexões de saída (/proc/net/tcp) ---

def _endereco(hexa: str) -> tuple[ipaddress._BaseAddress, int]:
    ip_hex, porta_hex = hexa.split(":")
    dados = bytes.fromhex(ip_hex)
    if len(dados) == 4:
        ip = ipaddress.IPv4Address(dados[::-1])
    else:  # IPv6: quatro palavras de 32 bits em little-endian
        ip = ipaddress.IPv6Address(b"".join(dados[i:i + 4][::-1] for i in range(0, 16, 4)))
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    return ip, int(porta_hex, 16)


def conexoes_de_saida(arquivos: list[Path] | None = None) -> list[str]:
    """Conexões ESTABELECIDAS da máquina cujo lado local não é uma porta em
    escuta (ou seja, de saída), para fora de 127.0.0.1 e do host do Ollama."""
    arquivos = arquivos if arquivos is not None else [Path("/proc/net/tcp"), Path("/proc/net/tcp6")]
    linhas = []
    for arquivo in arquivos:
        if arquivo.exists():
            linhas += [l.split() for l in arquivo.read_text().splitlines()[1:] if l.strip()]
    escutando = {_endereco(l[1])[1] for l in linhas if l[3] == "0A"}
    host_ollama = urlparse(config.OLLAMA_URL).hostname or ""
    permitidos = {host_ollama, "localhost"}
    inesperadas = []
    for l in linhas:
        if l[3] != "01":  # ESTABLISHED
            continue
        (_, porta_local), (remoto, porta_remota) = _endereco(l[1]), _endereco(l[2])
        if porta_local in escutando or remoto.is_loopback or str(remoto) in permitidos:
            continue
        inesperadas.append(f"{remoto}:{porta_remota}")
    return sorted(set(inesperadas))


def verificar_rede(arquivos: list[Path] | None = None) -> Verificacao:
    inesperadas = conexoes_de_saida(arquivos)
    if inesperadas:
        return Verificacao("rede", False, "conexões de saída inesperadas: " + ", ".join(inesperadas))
    return Verificacao("rede", True, "nenhuma conexão de saída além do Ollama e de 127.0.0.1")


def fumaca(usuario: str | None = None, senha: str | None = None) -> list[Verificacao]:
    return [verificar_configuracao(), verificar_banco(), verificar_api(), verificar_login(usuario=usuario, senha=senha),
            verificar_ollama(), verificar_chroma(), verificar_rede()]


# --- medição do R09 ---

@dataclass
class Medida:
    modelo: str
    tipo: str
    rodada: int
    aquecimento: bool
    tempo_s: float
    tempo_llm_s: float = 0.0
    chamadas_llm: int = 0
    origem: str = ""
    motivo_descarte: str = ""
    falha: str = ""
    raciocinio_no_texto: bool = False
    raciocinio_aberto: bool = False
    raciocinio_api: bool = False
    cortada: bool = False
    vazia: bool = False
    tokens: int | None = None


def _executar(tipo: str, rodada: int):
    """Uma interação pelo mesmo caminho dos agentes; devolve (origem, motivo do descarte, falha)."""
    if tipo == "feedback":
        from tia.agentes.tutor.feedback import gerar_feedback
        from tia.agentes.tutor.repositorio import carregar_itens, materiais_da_competencia
        itens = carregar_itens()
        item = itens[rodada % len(itens)]
        indice = (item["indice_correto"] + rodada % 2) % len(item["alternativas"])  # alterna acerto e erro
        r = gerar_feedback(item, indice, materiais_da_competencia(item["competencia_id"]) or [])
        return r.origem, r.motivo_descarte, r.falha_llm or ""
    if tipo == "dialogo":
        from tia.agentes.tutor.dialogo import gerar_resposta
        r = gerar_resposta(PERGUNTAS[rodada % len(PERGUNTAS)], None)
        return r.origem, r.motivo_descarte or "", r.falha_llm or ""
    from tia.agentes.planejador.justificar import justificar_trilha
    from tia.agentes.planejador.modelos import EntradaPlanejador
    from tia.agentes.planejador.planejar import carregar_perfis, gerar_trilha
    perfis = carregar_perfis()
    entrada = EntradaPlanejador(aluno_id="R09-MEDIDA", perfil_id=perfis[rodada % len(perfis)]["id"],
                                horas_semanais=6, diagnostico={})
    trilha = justificar_trilha(gerar_trilha(entrada), entrada.diagnostico)
    origens = {e.origem_justificativa for e in trilha.etapas if e.origem_justificativa}
    origem = origens.pop() if len(origens) == 1 else ("parcial" if origens else "")
    return origem, "", trilha.falha_llm or ""


def medir_interacao(modelo: str, tipo: str, rodada: int, aquecimento: bool = False) -> Medida:
    with llm_client.usar_modelo(modelo), llm_client.coletar_chamadas() as chamadas:
        inicio = time.perf_counter()
        if aquecimento:  # carrega o modelo na memória; não entra no resumo
            try:
                llm_client.chamar_llm("Responda apenas com a palavra: ok", max_tokens=20, timeout=600)
            except Exception:
                pass
            origem, motivo, falha = "aquecimento", "", ""
        else:
            origem, motivo, falha = _executar(tipo, rodada)
        tempo = time.perf_counter() - inicio
    medida = Medida(modelo, tipo, rodada, aquecimento, round(tempo, 3), origem=origem,
                    motivo_descarte=(motivo or "").split(":")[0], falha=falha or "")
    medida.chamadas_llm = len(chamadas)
    medida.tempo_llm_s = round(sum(c.tempo_ms for c in chamadas) / 1000, 3)
    for c in chamadas:
        medida.raciocinio_no_texto |= c.raciocinio_no_texto
        medida.raciocinio_aberto |= c.raciocinio_aberto
        medida.raciocinio_api |= c.raciocinio_api
        medida.cortada |= c.cortada
        medida.vazia |= c.vazia
        medida.falha = medida.falha or (c.falha or "")
        medida.tokens = (medida.tokens or 0) + (c.tokens or 0) if c.tokens is not None else medida.tokens
    return medida


def medir_r09(n: int, modelos: list[str] | None = None, tipos: tuple[str, ...] = TIPOS,
              ao_medir=None) -> list[Medida]:
    medidas = []
    for modelo in (config.MODELOS_LLM if modelos is None else modelos):
        medidas.append(medir_interacao(modelo, "aquecimento", 0, aquecimento=True))
        for rodada in range(n):
            for tipo in tipos:
                medidas.append(medir_interacao(modelo, tipo, rodada))
                if ao_medir:
                    ao_medir(medidas[-1])
    return medidas


def percentil(valores: list[float], p: float) -> float:
    """Percentil pelo posto mais próximo (sem interpolação): um valor medido de verdade."""
    ordenados = sorted(valores)
    posto = max(1, -(-len(ordenados) * p // 100))  # teto
    return ordenados[int(posto) - 1]


@dataclass
class Resumo:
    modelo: str
    tipo: str
    n: int
    media_s: float
    p50_s: float
    p90_s: float
    p95_s: float
    max_s: float
    dentro_do_limite: float
    llm: int = 0
    guarda: int = 0
    fallback: int = 0
    parcial: int = 0
    sem_llm: int = 0
    falhas: int = 0
    vazias: int = 0
    cortadas: int = 0
    raciocinio_vazou: int = 0
    raciocinio_api: int = 0
    motivos: dict = field(default_factory=dict)


def resumir(medidas: list[Medida], limite: float | None = None) -> list[Resumo]:
    limite = config.R09_LIMITE_SEGUNDOS if limite is None else limite
    grupos: dict[tuple[str, str], list[Medida]] = {}
    for m in medidas:
        if not m.aquecimento:
            grupos.setdefault((m.modelo, m.tipo), []).append(m)
    resumos = []
    for (modelo, tipo), lista in grupos.items():
        tempos = [m.tempo_s for m in lista]
        resumo = Resumo(modelo, tipo, len(lista), round(statistics.fmean(tempos), 3), percentil(tempos, 50),
                        percentil(tempos, 90), percentil(tempos, 95), max(tempos),
                        round(sum(t <= limite for t in tempos) / len(tempos), 3))
        for m in lista:
            if m.origem in ("LLM", "guarda", "fallback", "parcial"):
                setattr(resumo, m.origem.lower(), getattr(resumo, m.origem.lower()) + 1)
            resumo.sem_llm += m.chamadas_llm == 0
            resumo.falhas += bool(m.falha)
            resumo.vazias += m.vazia
            resumo.cortadas += m.cortada
            resumo.raciocinio_vazou += m.raciocinio_no_texto or m.raciocinio_aberto
            resumo.raciocinio_api += m.raciocinio_api
            if m.motivo_descarte:
                resumo.motivos[m.motivo_descarte] = resumo.motivos.get(m.motivo_descarte, 0) + 1
        resumos.append(resumo)
    return resumos


def _celula(valor) -> str:
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, float):
        return f"{valor:.3f}".replace(".", ",")
    if isinstance(valor, dict):
        return ", ".join(f"{k}={v}" for k, v in valor.items())
    return "" if valor is None else str(valor)


def gravar_csv(linhas: list, caminho: Path):
    """CSV com ";" e vírgula decimal (abre direto no Excel/LibreOffice em pt-BR)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";", lineterminator="\n")
        campos = list(asdict(linhas[0]).keys()) if linhas else []
        escritor.writerow(campos)
        for linha in linhas:
            escritor.writerow([_celula(v) for v in asdict(linha).values()])


def tabela_resumo(resumos: list[Resumo], limite: float | None = None) -> str:
    limite = config.R09_LIMITE_SEGUNDOS if limite is None else limite
    linhas = [f"Limite do R09: {limite:g} s (tempo de ponta a ponta de cada interação; aquecimento fora)",
              f"{'modelo':<14} {'tipo':<13} {'n':>3} {'média':>7} {'p50':>7} {'p90':>7} {'p95':>7} {'máx':>7} "
              f"{'≤limite':>8}  LLM/guarda/fallback/parcial/sem LLM; falhas; vazias; cortadas; raciocínio"]
    for r in resumos:
        linhas.append(
            f"{r.modelo:<14} {r.tipo:<13} {r.n:>3} {r.media_s:>6.1f}s {r.p50_s:>6.1f}s {r.p90_s:>6.1f}s "
            f"{r.p95_s:>6.1f}s {r.max_s:>6.1f}s {r.dentro_do_limite:>7.0%}  "
            f"{r.llm}/{r.guarda}/{r.fallback}/{r.parcial}/{r.sem_llm}; {r.falhas}; {r.vazias}; {r.cortadas}; "
            f"{r.raciocinio_vazou} no texto, {r.raciocinio_api} pela API"
            + (f"; descartes: {_celula(r.motivos)}" if r.motivos else ""))
    return "\n".join(linhas)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Teste de fumaça da VM e medição do R09.")
    parser.add_argument("--usuario", help="login para testar de verdade (senha pela entrada padrão)")
    parser.add_argument("--medir-r09", type=int, metavar="N", help="N interações de cada tipo por modelo")
    parser.add_argument("--modelos", help="lista separada por vírgula (padrão: MODELOS_LLM)")
    parser.add_argument("--tipos", default=",".join(TIPOS), help=f"subconjunto de {','.join(TIPOS)}")
    parser.add_argument("--saida", type=Path, help="CSV das medidas (padrão: medicoes/r09-<data>.csv)")
    args = parser.parse_args()
    if args.medir_r09:
        modelos = [m.strip() for m in args.modelos.split(",")] if args.modelos else None
        tipos = tuple(t.strip() for t in args.tipos.split(",") if t.strip() in TIPOS)
        saida = args.saida or Path("medicoes") / f"r09-{datetime.now():%Y%m%d-%H%M%S}.csv"
        print(f"Medindo R09: {args.medir_r09} interação(ões) de {', '.join(tipos)} por modelo "
              f"({', '.join(modelos or config.MODELOS_LLM)}). Isto pode levar muitos minutos em CPU.")
        medidas = medir_r09(args.medir_r09, modelos, tipos,
                            ao_medir=lambda m: print(f"  {m.modelo} {m.tipo} #{m.rodada + 1}: {m.tempo_s:.1f} s "
                                                     f"({m.origem or '-'})", flush=True))
        resumos = resumir(medidas)
        gravar_csv(medidas, saida)
        gravar_csv(resumos, saida.with_name(saida.stem + "-resumo.csv"))
        print("\n" + tabela_resumo(resumos))
        print(f"\nMedidas em {saida}; resumo em {saida.with_name(saida.stem + '-resumo.csv')}")
        sys.exit(0)
    senha = sys.stdin.readline().rstrip("\n") if args.usuario else None
    resultado = fumaca(args.usuario, senha)
    for v in resultado:
        print(f"[{'ok' if v.ok else 'FALHOU'}] {v.nome}: {v.detalhe}")
    print("Tudo certo." if all(v.ok for v in resultado) else "Há falhas: veja docs/implantacao_vm.md, seção 6.")
    sys.exit(0 if all(v.ok for v in resultado) else 1)
