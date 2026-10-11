"""
Sessões no servidor e tentativas de login (EAP 1.4.6).

Sessão: o cookie leva um token aleatório (secrets.token_urlsafe); a tabela
auth_sessoes guarda só o SHA-256 dele, o usuário, o token anti-CSRF e a
expiração (AUTH_SESSAO_MINUTOS a partir do login). Usuário desativado ou
sessão expirada = sem sessão.

Tentativas: cada login (com sucesso ou não) grava o login e o IP em
auth_tentativas, sem senha. O login fica bloqueado quando há
AUTH_MAX_FALHAS_USUARIO falhas do mesmo login (desde o último sucesso dele)
ou AUTH_MAX_FALHAS_IP falhas do mesmo IP dentro de AUTH_JANELA_MINUTOS.

Não é executável; usado por tia.api.rotas_auth e seguranca.acesso.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import hashlib
import secrets
from datetime import datetime, timedelta

import tia.core.config as config
from tia.core.database import obter_conexao


def _texto(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- sessões ---

def criar_sessao(usuario_id: str, agora: datetime | None = None) -> tuple[str, str]:
    """Abre uma sessão e devolve (token do cookie, token anti-CSRF)."""
    agora = agora or datetime.now()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conexao = obter_conexao()
    try:
        with conexao:
            # aproveita para limpar as sessões vencidas
            conexao.execute("DELETE FROM auth_sessoes WHERE expira_em < ?", (_texto(agora),))
            conexao.execute(
                "INSERT INTO auth_sessoes (token_hash, usuario_id, csrf, criada_em, expira_em) VALUES (?, ?, ?, ?, ?)",
                (_hash(token), usuario_id, csrf, _texto(agora),
                 _texto(agora + timedelta(minutes=config.AUTH_SESSAO_MINUTOS))))
    finally:
        conexao.close()
    return token, csrf


def ler_sessao(token: str, agora: datetime | None = None) -> dict | None:
    """Usuário da sessão (id, papel, aluno_id, csrf); None se não existe,
    venceu ou o usuário foi desativado."""
    agora = agora or datetime.now()
    conexao = obter_conexao()
    try:
        linha = conexao.execute(
            """SELECT u.id, u.papel, u.aluno_id, s.csrf FROM auth_sessoes s JOIN usuarios u ON u.id = s.usuario_id
               WHERE s.token_hash = ? AND s.expira_em > ? AND u.ativo""",
            (_hash(token), _texto(agora))).fetchone()
    finally:
        conexao.close()
    return dict(linha) if linha else None


def encerrar_sessao(token: str):
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("DELETE FROM auth_sessoes WHERE token_hash = ?", (_hash(token),))
    finally:
        conexao.close()


def encerrar_sessoes_do_usuario(usuario_id: str, conexao=None):
    """Encerra todas as sessões do usuário (desativação, troca de senha)."""
    propria = conexao is None
    conexao = conexao or obter_conexao()
    try:
        conexao.execute("DELETE FROM auth_sessoes WHERE usuario_id = ?", (usuario_id,))
        if propria:
            conexao.commit()
    finally:
        if propria:
            conexao.close()


# --- tentativas de login ---

def registrar_tentativa(login: str, ip: str, sucesso: bool, agora: datetime | None = None):
    conexao = obter_conexao()
    try:
        with conexao:
            conexao.execute("INSERT INTO auth_tentativas (ts, login, ip, sucesso) VALUES (?, ?, ?, ?)",
                            (_texto(agora or datetime.now()), login, ip, int(sucesso)))
    finally:
        conexao.close()


def bloqueio(login: str, ip: str, agora: datetime | None = None) -> str | None:
    """Motivo do bloqueio ("usuario" ou "ip") se o limite de falhas foi atingido na janela; senão None."""
    agora = agora or datetime.now()
    inicio = _texto(agora - timedelta(minutes=config.AUTH_JANELA_MINUTOS))
    conexao = obter_conexao()
    try:
        do_login = conexao.execute(
            """SELECT COUNT(*) FROM auth_tentativas WHERE login = ? AND NOT sucesso AND ts >= ?
                 AND ts > COALESCE((SELECT MAX(ts) FROM auth_tentativas WHERE login = ? AND sucesso), '')""",
            (login, inicio, login)).fetchone()[0]
        do_ip = conexao.execute("SELECT COUNT(*) FROM auth_tentativas WHERE ip = ? AND NOT sucesso AND ts >= ?",
                                (ip, inicio)).fetchone()[0]
    finally:
        conexao.close()
    if do_login >= config.AUTH_MAX_FALHAS_USUARIO:
        return "usuario"
    if do_ip >= config.AUTH_MAX_FALHAS_IP:
        return "ip"
    return None
