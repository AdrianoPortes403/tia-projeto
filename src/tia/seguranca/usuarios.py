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

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import argparse
import getpass
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

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


def criar(usuario_id: str, papel: str, senha: str, aluno_id: str | None = None, temporaria: bool = True) -> Usuario:
    """Cria o usuário. temporaria: a senha precisa ser trocada no primeiro acesso."""
    if not PADRAO_ID.match(usuario_id or ""):
        raise ErroUsuario("Id inválido: use um código (letras sem acento, números, \"-\" ou \"_\", até 32), "
                          "nunca o nome da pessoa.")
    if papel not in PAPEIS:
        raise ErroUsuario(f"Papel inválido: use {', '.join(PAPEIS)}.")
    if papel == "aluno" and not PADRAO_ID.match(aluno_id or ""):
        raise ErroUsuario("Usuário com papel aluno precisa do aluno_id (código do aluno).")
    if papel != "aluno" and aluno_id:
        raise ErroUsuario("Só o papel aluno tem aluno_id.")
    senhas.validar(senha, usuario_id)
    conexao = obter_conexao()
    try:
        with conexao:
            cursor = conexao.execute(
                """INSERT OR IGNORE INTO usuarios
                     (id, papel, aluno_id, senha_hash, ativo, trocar_senha, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (usuario_id, papel, aluno_id, senhas.gerar_hash(senha), int(temporaria), _agora(), _agora()))
            if cursor.rowcount != 1:
                raise ErroUsuario(f"Já existe o usuário '{usuario_id}'.")
            _auditar(conexao, usuario_id, f"usuário criado (papel {papel})"
                     + ("; senha temporária" if temporaria else ""))
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
    args = parser.parse_args()
    criar_tabelas()
    try:
        if args.comando == "criar":
            print(f"Criado: {asdict(criar(args.id, args.papel, _ler_senha(args), args.aluno_id))}")
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
