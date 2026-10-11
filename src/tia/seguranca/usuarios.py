"""
Usuários do TIA (EAP 1.4.6): cadastro, desativação e troca de senha, pela
linha de comando ou pelas rotas /admin/usuarios.

Cada usuário tem um id de login (código, nunca nome; R08), um papel (aluno,
docente ou admin), o aluno_id quando o papel é aluno, a senha só como hash
scrypt com sal (seguranca.senhas) e a marca de ativo. Desativar ou trocar a
senha encerra as sessões abertas. Cada mudança vai para a auditoria
(gestao_usuario), sem a senha.

Senha temporária: a senha criada ou redefinida pelo admin (comando ou rotas
/admin) vale só para entrar; no primeiro acesso o usuário precisa trocá-la
(POST /auth/senha, tela de troca no /app e no painel). Só os usuários
fictícios de demonstração nascem sem essa exigência.

Como rodar (a partir da raiz, com o venv ativo). A senha é pedida no
terminal, sem eco (getpass), ou lida da entrada padrão com --senha-stdin;
nunca pela linha de comando:
    python -m tia.seguranca.usuarios criar --id DOC-01 --papel docente
    python -m tia.seguranca.usuarios criar --id A2026-001 --papel aluno --aluno-id A2026-001
    python -m tia.seguranca.usuarios desativar --id DOC-01
    python -m tia.seguranca.usuarios redefinir-senha --id DOC-01
    (a senha criada ou redefinida pelo comando é temporária: troca no primeiro acesso)
    python -m tia.seguranca.usuarios listar
    python -m tia.seguranca.usuarios importar --arquivo usuarios.csv [--saida senhas.csv]

Importação em lote (E6): CSV com cabeçalho login,papel,aluno_id (aluno_id só
no papel aluno; separador "," ou ";"). Tudo é conferido antes: se alguma
linha for inválida ou repetida (no arquivo ou no banco), nada é criado. Cada
usuário recebe uma senha temporária aleatória (troca obrigatória no primeiro
acesso). As senhas vão SÓ para o arquivo de saída (login;senha_temporaria),
criado com permissão só do dono e que nunca sobrescreve outro: entregue cada
senha ao dono e apague o arquivo. Nunca vão para log, auditoria ou terminal.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import argparse
import csv
import getpass
import os
import re
import secrets
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from tia.core import auditoria
from tia.core.database import criar_tabelas, obter_conexao
from tia.seguranca import senhas
from tia.seguranca.sessoes import encerrar_sessoes_do_usuario

PAPEIS = ("aluno", "docente", "admin")
PADRAO_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")  # mesmo padrão do código de aluno

# Usuários FICTÍCIOS dos comandos de demonstração (dados_demo, dados_painel).
# A senha abaixo é FICTÍCIA, pública e serve só para demonstração em máquina de
# desenvolvimento: nunca usar em banco com dados reais.
SENHA_DEMONSTRACAO = "FICTICIA-demo-2026"
USUARIOS_DEMONSTRACAO = (("DEMO-W01", "aluno", "DEMO-W01"), ("DEMO-DOCENTE", "docente", None))


class ErroUsuario(ValueError):
    """Dado inválido ou conflito no cadastro (mensagem pensada para o usuário)."""


@dataclass
class Usuario:
    id: str
    papel: str
    aluno_id: str | None
    ativo: bool
    trocar_senha: bool = False


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _auditar(conexao, usuario_id: str, acao: str):
    auditoria.registrar(conexao, None, "gestao_usuario", usuario_id, acao, [], ts=_agora(), motivo=acao)


def _validar_cadastro(usuario_id: str, papel: str, aluno_id: str | None):
    """Confere id, papel e aluno_id (sem consultar o banco); levanta ErroUsuario."""
    if not PADRAO_ID.match(usuario_id or ""):
        raise ErroUsuario("Id inválido: use um código (letras sem acento, números, \"-\" ou \"_\", até 32), "
                          "nunca o nome da pessoa.")
    if papel not in PAPEIS:
        raise ErroUsuario(f"Papel inválido: use {', '.join(PAPEIS)}.")
    if papel == "aluno" and not PADRAO_ID.match(aluno_id or ""):
        raise ErroUsuario("Usuário com papel aluno precisa do aluno_id (código do aluno).")
    if papel != "aluno" and aluno_id:
        raise ErroUsuario("Só o papel aluno tem aluno_id.")


def _inserir(conexao, usuario_id: str, papel: str, aluno_id: str | None, senha: str, temporaria: bool,
             origem: str = ""):
    """Grava o usuário na transação de quem chama (conflitos levantam ErroUsuario)."""
    if aluno_id and conexao.execute("SELECT 1 FROM usuarios WHERE aluno_id = ?", (aluno_id,)).fetchone():
        raise ErroUsuario(f"O aluno '{aluno_id}' já está ligado a outro usuário.")
    cursor = conexao.execute(
        """INSERT OR IGNORE INTO usuarios
             (id, papel, aluno_id, senha_hash, ativo, trocar_senha, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
        (usuario_id, papel, aluno_id, senhas.gerar_hash(senha), int(temporaria), _agora(), _agora()))
    if cursor.rowcount != 1:
        raise ErroUsuario(f"Já existe o usuário '{usuario_id}'.")
    _auditar(conexao, usuario_id, f"usuário criado (papel {papel})" + ("; senha temporária" if temporaria else "")
             + origem)


def criar(usuario_id: str, papel: str, senha: str, aluno_id: str | None = None, temporaria: bool = True) -> Usuario:
    """Cria o usuário. temporaria: a senha precisa ser trocada no primeiro acesso."""
    _validar_cadastro(usuario_id, papel, aluno_id)
    senhas.validar(senha, usuario_id)
    conexao = obter_conexao()
    try:
        with conexao:
            _inserir(conexao, usuario_id, papel, aluno_id, senha, temporaria)
    finally:
        conexao.close()
    return Usuario(usuario_id, papel, aluno_id, True, temporaria)


def buscar(usuario_id: str) -> dict | None:
    """Linha do usuário COM o hash da senha (só para o autenticador)."""
    conexao = obter_conexao()
    try:
        linha = conexao.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def listar() -> list[Usuario]:
    conexao = obter_conexao()
    try:
        linhas = conexao.execute(
            "SELECT id, papel, aluno_id, ativo, trocar_senha FROM usuarios ORDER BY papel, id").fetchall()
    finally:
        conexao.close()
    return [Usuario(l["id"], l["papel"], l["aluno_id"], bool(l["ativo"]), bool(l["trocar_senha"])) for l in linhas]


def desativar(usuario_id: str) -> bool:
    """Desativa e encerra as sessões; False se o usuário não existe."""
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute("UPDATE usuarios SET ativo = 0, atualizado_em = ? WHERE id = ?",
                                     (_agora(), usuario_id))
            if cursor.rowcount != 1:
                return False
            encerrar_sessoes_do_usuario(usuario_id, conexao)
            _auditar(conexao, usuario_id, "usuário desativado")
    finally:
        conexao.close()
    return True


def redefinir_senha(usuario_id: str, senha: str, temporaria: bool = True) -> bool:
    """Troca a senha e encerra as sessões; False se o usuário não existe.
    temporaria (padrão, redefinição pelo admin): troca obrigatória no próximo acesso.
    Com temporaria=False é a troca feita pelo próprio usuário (trocar_propria_senha)."""
    senhas.validar(senha, usuario_id)
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                "UPDATE usuarios SET senha_hash = ?, trocar_senha = ?, atualizado_em = ? WHERE id = ?",
                (senhas.gerar_hash(senha), int(temporaria), _agora(), usuario_id))
            if cursor.rowcount != 1:
                return False
            encerrar_sessoes_do_usuario(usuario_id, conexao)
            _auditar(conexao, usuario_id, "senha redefinida; senha temporária" if temporaria
                     else "senha trocada pelo próprio usuário")
    finally:
        conexao.close()
    return True


def trocar_propria_senha(usuario_id: str, atual: str, nova: str) -> bool:
    """O próprio usuário troca a senha: confere a atual e grava a nova como
    definitiva (sai a exigência de troca). Encerra todas as sessões dele; quem
    chama abre uma nova. False se a senha atual não confere."""
    linha = buscar(usuario_id)
    if linha is None or not senhas.conferir(atual, linha["senha_hash"]):
        return False
    if atual == nova:
        raise senhas.SenhaFraca("A nova senha precisa ser diferente da atual.")
    return redefinir_senha(usuario_id, nova, temporaria=False)


def criar_usuarios_demonstracao() -> list[str]:
    """Usuários FICTÍCIOS das demonstrações (aluno DEMO-W01 e um docente), com
    a SENHA_DEMONSTRACAO. Quem já existe é mantido. Devolve os criados."""
    criados = []
    for usuario_id, papel, aluno_id in USUARIOS_DEMONSTRACAO:
        if buscar(usuario_id) is None:
            criar(usuario_id, papel, SENHA_DEMONSTRACAO, aluno_id, temporaria=False)
            criados.append(usuario_id)
    return criados


# --- importação em lote (E6) ---

ALFABETO_SENHA = "abcdefghjkmnpqrstuvwxyz23456789"  # sem 0/o, 1/l/i: fácil de ditar e digitar


def gerar_senha_temporaria(usuario_id: str = "") -> str:
    """Senha aleatória (secrets) no formato xxxx-xxxx-xxxx (~59 bits), já conferida pela política."""
    while True:
        senha = "-".join("".join(secrets.choice(ALFABETO_SENHA) for _ in range(4)) for _ in range(3))
        try:
            senhas.validar(senha, usuario_id)
            return senha
        except senhas.SenhaFraca:
            continue


def ler_importacao(caminho: Path) -> list[tuple[str, str, str | None]]:
    """Lê e confere o CSV inteiro; levanta ErroUsuario com TODOS os problemas
    (por número de linha, sem repetir o conteúdo, que pode ser um nome)."""
    texto = caminho.read_text(encoding="utf-8-sig")
    linhas_texto = texto.splitlines()
    if not linhas_texto:
        raise ErroUsuario("Arquivo vazio.")
    separador = ";" if ";" in linhas_texto[0] else ","
    leitor = csv.DictReader(linhas_texto, delimiter=separador)
    campos = [c.strip().lower() for c in (leitor.fieldnames or [])]
    if not {"login", "papel"} <= set(campos) or not set(campos) <= {"login", "papel", "aluno_id"}:
        raise ErroUsuario("Cabeçalho deve ser login,papel,aluno_id (aluno_id opcional).")
    leitor.fieldnames = campos
    registros, problemas = [], []
    for numero, linha in enumerate(leitor, start=2):
        if None in linha:
            problemas.append(f"linha {numero}: colunas a mais")
            continue
        login, papel = (linha.get("login") or "").strip(), (linha.get("papel") or "").strip().lower()
        aluno_id = (linha.get("aluno_id") or "").strip() or None
        try:
            _validar_cadastro(login, papel, aluno_id)
        except ErroUsuario as erro:
            problemas.append(f"linha {numero}: {erro}")
            continue
        registros.append((numero, login, papel, aluno_id))
    if not registros and not problemas:
        raise ErroUsuario("Nenhum usuário no arquivo.")
    vistos_login, vistos_aluno = {}, {}
    for numero, login, _, aluno_id in registros:
        if login.lower() in vistos_login:
            problemas.append(f"linha {numero}: login repetido (já na linha {vistos_login[login.lower()]})")
        vistos_login.setdefault(login.lower(), numero)
        if aluno_id:
            if aluno_id in vistos_aluno:
                problemas.append(f"linha {numero}: aluno_id repetido (já na linha {vistos_aluno[aluno_id]})")
            vistos_aluno.setdefault(aluno_id, numero)
    conexao = obter_conexao()
    try:
        for numero, login, _, aluno_id in registros:
            if conexao.execute("SELECT 1 FROM usuarios WHERE lower(id) = lower(?)", (login,)).fetchone():
                problemas.append(f"linha {numero}: já existe usuário com esse login")
            if aluno_id and conexao.execute("SELECT 1 FROM usuarios WHERE aluno_id = ?", (aluno_id,)).fetchone():
                problemas.append(f"linha {numero}: esse aluno_id já está ligado a outro usuário")
    finally:
        conexao.close()
    if problemas:
        raise ErroUsuario("nada foi criado. Corrija o arquivo:\n  " + "\n  ".join(sorted(
            problemas, key=lambda p: int(p.split()[1].rstrip(":")))))
    return [(login, papel, aluno_id) for _, login, papel, aluno_id in registros]


def importar(caminho: Path, saida: Path) -> list[str]:
    """Cria todos os usuários do CSV com senha temporária aleatória, numa
    transação só, e grava login;senha_temporaria em `saida` (permissão 600,
    nunca sobrescreve). Qualquer problema: nada é criado e `saida` não fica.
    Devolve os logins criados."""
    novos = ler_importacao(caminho)
    descritor = os.open(saida, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)  # falha antes de mexer no banco
    criado = False
    try:
        with os.fdopen(descritor, "w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";", lineterminator="\n")
            escritor.writerow(["login", "senha_temporaria"])
            conexao = obter_conexao()
            try:
                with conexao:
                    for login, papel, aluno_id in novos:
                        senha = gerar_senha_temporaria(login)
                        _inserir(conexao, login, papel, aluno_id, senha, temporaria=True,
                                 origem="; importação em lote")
                        escritor.writerow([login, senha])
                    arquivo.flush()
                    os.fsync(arquivo.fileno())  # o arquivo existe inteiro antes de confirmar o banco
                    auditoria.registrar(conexao, None, "gestao_usuario", "importacao", "importação em lote", [],
                                        ts=_agora(), motivo=f"importação em lote: {len(novos)} usuário(s) criado(s) "
                                                            "com senha temporária")
            finally:
                conexao.close()
        criado = True
    finally:
        if not criado:
            saida.unlink(missing_ok=True)
    return [login for login, _, _ in novos]


def _ler_senha(args) -> str:
    if args.senha_stdin:
        return sys.stdin.readline().rstrip("\n")
    senha = getpass.getpass("Nova senha: ")
    if senha != getpass.getpass("Repita a senha: "):
        raise ErroUsuario("As senhas não conferem.")
    return senha


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Usuários do TIA (a senha nunca vai na linha de comando).")
    comandos = parser.add_subparsers(dest="comando", required=True)
    criar_cmd = comandos.add_parser("criar", help="cria um usuário")
    criar_cmd.add_argument("--id", required=True, help="código de login (nunca o nome)")
    criar_cmd.add_argument("--papel", required=True, choices=PAPEIS)
    criar_cmd.add_argument("--aluno-id", help="código do aluno (obrigatório no papel aluno)")
    for nome in ("desativar", "redefinir-senha"):
        sub = comandos.add_parser(nome)
        sub.add_argument("--id", required=True)
    for sub in (criar_cmd, comandos.choices["redefinir-senha"]):
        sub.add_argument("--senha-stdin", action="store_true", help="lê a senha da entrada padrão")
    comandos.add_parser("listar", help="lista usuários (sem senha)")
    importar_cmd = comandos.add_parser("importar", help="cria usuários em lote a partir de um CSV")
    importar_cmd.add_argument("--arquivo", required=True, type=Path, help="CSV com login,papel,aluno_id")
    importar_cmd.add_argument("--saida", type=Path,
                              help="arquivo com as senhas temporárias (padrão: senhas_temporarias-<data>.csv)")
    args = parser.parse_args()
    criar_tabelas()
    try:
        if args.comando == "criar":
            print(f"Criado: {asdict(criar(args.id, args.papel, _ler_senha(args), args.aluno_id))}")
        elif args.comando == "importar":
            saida = args.saida or Path(f"senhas_temporarias-{datetime.now():%Y%m%d-%H%M%S}.csv")
            if saida.exists():
                raise ErroUsuario(f"{saida} já existe; escolha outro --saida.")
            criados = importar(args.arquivo, saida)
            print(f"{len(criados)} usuário(s) criado(s), todos com troca de senha no primeiro acesso.")
            print(f"Senhas temporárias em {saida} (permissão só do dono). ATENÇÃO: entregue cada senha ao dono "
                  "por canal seguro e APAGUE o arquivo em seguida.")
        elif args.comando == "desativar":
            print("Desativado." if desativar(args.id) else "Usuário não encontrado.")
        elif args.comando == "redefinir-senha":
            print("Senha redefinida; sessões encerradas." if redefinir_senha(args.id, _ler_senha(args))
                  else "Usuário não encontrado.")
        else:
            for usuario in listar():
                print(asdict(usuario))
    except (ErroUsuario, senhas.SenhaFraca) as erro:
        sys.exit(f"Erro: {erro}")
    except (OSError, UnicodeDecodeError) as erro:
        sys.exit(f"Erro ao ler ou gravar arquivo: {type(erro).__name__}; nada foi criado.")
