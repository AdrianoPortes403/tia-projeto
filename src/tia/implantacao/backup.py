"""
Backup e restauração (EAP 1.4.1; deploy/backup.sh e deploy/restaurar.sh).

fazer: cria BACKUP_DIR/AAAAMMDD-HHMMSS/ (pasta 700, arquivos 600) com
    tia.db          cópia CONSISTENTE do SQLite pela API de backup (funciona com a API
                    no ar) e conferida com PRAGMA integrity_check
    chroma.tar.gz   o índice do RAG (CHROMA_DIR); dá para refazer com o reindexador
    SHA256SUMS      conferido antes de restaurar
e, À PARTE, BACKUP_DIR/config/env-AAAAMMDD-HHMMSS (o .env, 600), para o
backup dos dados poder ir a um lugar e o da configuração a outro. Depois
apaga as pastas e os .env com mais de BACKUP_DIAS, mantendo sempre o mais
recente. Só apaga o que tem o formato de nome criado aqui.

restaurar: confere o SHA256SUMS e a integridade, e só então troca o banco e
o índice. NADA é apagado: o banco e o índice atuais são renomeados para
"<nome>.antes-restauracao-AAAAMMDD-HHMMSS". O .env só volta com --com-env.

Os dois aceitam --simular (mostra o que faria, sem alterar nada).
Atenção LGPD: os backups têm dados pessoais, inclusive os já apagados pela
retenção (docs/seguranca/lgpd.md); por isso a rotação e as permissões.

Como rodar (a partir da raiz, com o venv ativo; na VM pelos scripts de deploy/):
    python -m tia.implantacao.backup fazer [--env /srv/tia/config/.env] [--simular]
    python -m tia.implantacao.backup restaurar BACKUP_DIR/20261015-030000 [--com-env ARQ] [--simular]
    python -m tia.implantacao.backup listar

Pré-requisitos:
    - nenhum além do Python (sqlite3, tarfile e hashlib da biblioteca padrão)
"""

import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

import tia.core.config as config
import tia.core.database as database

NOME_PASTA = re.compile(r"^\d{8}-\d{6}$")
NOME_ENV = re.compile(r"^env-(\d{8}-\d{6})$")
FORMATO = "%Y%m%d-%H%M%S"


class ErroBackup(RuntimeError):
    pass


def pasta_base() -> Path:
    return Path(config.BACKUP_DIR) if config.BACKUP_DIR else Path(database.DB_PATH).parent / "backup"


def _diretorio_privado(caminho: Path):
    caminho.mkdir(parents=True, exist_ok=True)
    os.chmod(caminho, 0o700)


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _copiar_sqlite(origem: Path, destino: Path):
    os.close(os.open(destino, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    fonte, copia = sqlite3.connect(f"file:{origem}?mode=ro", uri=True), sqlite3.connect(destino)
    try:
        fonte.backup(copia)
        resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copia.close()
        fonte.close()
    if resultado != "ok":
        raise ErroBackup(f"cópia do banco não passou na integridade: {resultado}")


def fazer(env: Path | None = None, agora: datetime | None = None, simular: bool = False) -> list[str]:
    """Faz o backup e a rotação; devolve as ações (feitas ou, com simular, que seriam feitas)."""
    agora = agora or datetime.now()
    base, banco, chroma = pasta_base(), Path(database.DB_PATH), Path(config.CHROMA_DIR)
    pasta = base / agora.strftime(FORMATO)
    acoes = [f"copiar o banco {banco} (consistente) para {pasta / 'tia.db'}"]
    if chroma.is_dir():
        acoes.append(f"compactar o índice {chroma} em {pasta / 'chroma.tar.gz'}")
    if env and env.exists():
        acoes.append(f"copiar {env} para {base / 'config' / ('env-' + agora.strftime(FORMATO))} (à parte)")
    if not banco.exists():
        raise ErroBackup(f"banco {banco} não existe")
    if pasta.exists():
        raise ErroBackup(f"{pasta} já existe")
    if not simular:
        mascara = os.umask(0o077)
        try:
            _diretorio_privado(base)
            pasta.mkdir(mode=0o700)
            _copiar_sqlite(banco, pasta / "tia.db")
            if chroma.is_dir():
                with tarfile.open(pasta / "chroma.tar.gz", "w:gz") as tar:
                    tar.add(chroma, arcname=chroma.name)
            somas = [f"{_sha256(a)}  {a.name}" for a in sorted(pasta.iterdir())]
            (pasta / "SHA256SUMS").write_text("\n".join(somas) + "\n", encoding="utf-8")
            for arquivo in pasta.iterdir():
                os.chmod(arquivo, 0o600)
            if env and env.exists():
                _diretorio_privado(base / "config")
                destino = base / "config" / ("env-" + agora.strftime(FORMATO))
                shutil.copyfile(env, destino)
                os.chmod(destino, 0o600)
        finally:
            os.umask(mascara)
    return acoes + rotacionar(agora, simular)


def _vencidos(base: Path, agora: datetime) -> list[Path]:
    limite = agora - timedelta(days=config.BACKUP_DIAS)
    vencidos = []
    for grupo, padrao in ((base, NOME_PASTA), (base / "config", NOME_ENV)):
        if not grupo.is_dir():
            continue
        datados = []
        for item in grupo.iterdir():
            achado = padrao.match(item.name)
            if achado:
                datados.append((datetime.strptime(achado.group(1) if achado.groups() else item.name, FORMATO), item))
        datados.sort()
        vencidos += [item for data, item in datados[:-1] if data < limite]  # o mais recente fica sempre
    return vencidos


def rotacionar(agora: datetime | None = None, simular: bool = False) -> list[str]:
    acoes = []
    for item in _vencidos(pasta_base(), agora or datetime.now()):
        acoes.append(f"apagar o backup vencido {item} (BACKUP_DIAS={config.BACKUP_DIAS})")
        if not simular:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    return acoes


def conferir(pasta: Path) -> None:
    """Levanta ErroBackup se faltar arquivo, a soma não conferir ou o banco não estiver íntegro."""
    somas = pasta / "SHA256SUMS"
    if not somas.exists():
        raise ErroBackup(f"{somas} não existe: não é uma pasta de backup")
    for linha in somas.read_text(encoding="utf-8").splitlines():
        soma, nome = linha.split(maxsplit=1)
        arquivo = pasta / nome.strip()
        if not arquivo.exists() or _sha256(arquivo) != soma:
            raise ErroBackup(f"{arquivo.name} ausente ou alterado (SHA256 não confere)")
    conexao = sqlite3.connect(f"file:{pasta / 'tia.db'}?mode=ro", uri=True)
    try:
        resultado = conexao.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conexao.close()
    if resultado != "ok":
        raise ErroBackup(f"banco do backup não está íntegro: {resultado}")


def _guardar_atual(caminho: Path, marca: str, acoes: list[str], simular: bool):
    if caminho.exists():
        antigo = caminho.with_name(f"{caminho.name}.antes-restauracao-{marca}")
        acoes.append(f"guardar o atual {caminho} como {antigo}")
        if not simular:
            caminho.rename(antigo)


def restaurar(pasta: Path, com_env: Path | None = None, agora: datetime | None = None,
              simular: bool = False) -> list[str]:
    """Restaura o banco e o índice do backup (ver o topo do módulo); devolve as ações."""
    conferir(pasta)
    marca = (agora or datetime.now()).strftime(FORMATO)
    banco, chroma = Path(database.DB_PATH), Path(config.CHROMA_DIR)
    acoes = [f"conferido: {pasta} (SHA256 e integridade)"]
    _guardar_atual(banco, marca, acoes, simular)
    acoes.append(f"restaurar {pasta / 'tia.db'} em {banco}")
    if not simular:
        banco.parent.mkdir(parents=True, exist_ok=True)
        provisorio = banco.with_name(banco.name + ".restaurando")
        shutil.copyfile(pasta / "tia.db", provisorio)
        os.chmod(provisorio, 0o600)
        provisorio.rename(banco)
    if (pasta / "chroma.tar.gz").exists():
        _guardar_atual(chroma, marca, acoes, simular)
        acoes.append(f"restaurar o índice em {chroma}")
        if not simular:
            temporaria = chroma.with_name(chroma.name + ".restaurando")
            temporaria.mkdir(parents=True, mode=0o700)
            with tarfile.open(pasta / "chroma.tar.gz") as tar:
                tar.extractall(temporaria, filter="data")
            (temporaria / next(temporaria.iterdir()).name).rename(chroma)
            temporaria.rmdir()
    if com_env:
        origem = _env_do_backup(pasta)
        _guardar_atual(com_env, marca, acoes, simular)
        acoes.append(f"restaurar {origem} em {com_env}")
        if not simular:
            shutil.copyfile(origem, com_env)
            os.chmod(com_env, 0o640)
    return acoes


def _env_do_backup(pasta: Path) -> Path:
    """O .env guardado junto (mesmo instante) ou o mais recente anterior ao backup."""
    candidatos = sorted(p for p in (pasta.parent / "config").glob("env-*")
                        if NOME_ENV.match(p.name) and p.name[4:] <= pasta.name)
    if not candidatos:
        raise ErroBackup("nenhum .env guardado até a data desse backup")
    return candidatos[-1]


def listar() -> list[str]:
    base = pasta_base()
    return sorted(p.name for p in base.iterdir() if NOME_PASTA.match(p.name)) if base.is_dir() else []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup e restauração do banco, do índice do RAG e do .env.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    fazer_cmd = comandos.add_parser("fazer")
    fazer_cmd.add_argument("--env", type=Path, help="arquivo .env a guardar à parte")
    restaurar_cmd = comandos.add_parser("restaurar")
    restaurar_cmd.add_argument("pasta", type=Path)
    restaurar_cmd.add_argument("--com-env", type=Path, metavar="DESTINO", help="restaura também o .env neste caminho")
    comandos.add_parser("listar")
    for sub in (fazer_cmd, restaurar_cmd):
        sub.add_argument("--simular", action="store_true", help="mostra o que faria, sem alterar nada")
    args = parser.parse_args()
    try:
        if args.comando == "listar":
            print("\n".join(listar()) or "nenhum backup")
            sys.exit(0)
        acoes = (fazer(args.env, simular=args.simular) if args.comando == "fazer"
                 else restaurar(args.pasta, args.com_env, simular=args.simular))
    except (ErroBackup, OSError) as erro:
        sys.exit(f"Erro: {erro}. Nada foi alterado." if not isinstance(erro, OSError) else f"Erro: {erro}")
    prefixo = "SIMULAÇÃO, faria: " if args.simular else ""
    for acao in acoes:
        print(prefixo + acao)
