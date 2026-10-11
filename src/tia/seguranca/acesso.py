"""
Autorização das rotas (EAP 1.4.6): dependências do FastAPI.

    usuario_atual           exige sessão válida (401) e, em escrita, o cabeçalho
                            anti-CSRF igual ao da sessão (403); define o usuário
                            da auditoria (core.auditoria.definir_usuario)
    exigir_papel(*papeis)   só os papéis listados (403)
    acesso_ao_aluno(*papeis) rota com {aluno_id}: o próprio aluno, ou um dos papéis
    conferir_aluno(...)     o mesmo, para aluno_id que vem no corpo do pedido

Toda recusa (401/403) responde com mensagem clara e grava "acesso_negado" na
auditoria, com a rota. Os 401 de quem não tem sessão são agregados por origem
e janela (seguranca.anonimos), para ninguém encher a auditoria. Com
TIA_AUTH=desligada (modo de desenvolvimento) tudo passa e a auditoria grava o
papel "sem_login".

Senha temporária (criada ou redefinida pelo admin): até o usuário trocá-la, só
POST /auth/senha e POST /auth/logout aceitam a sessão; as outras rotas
respondem 403 pedindo a troca.

Matriz de acesso: docs/arquitetura/arquitetura.md, seção "Segurança".

Não é executável; usado pelas rotas em tia.api.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

import hmac
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, Request

import tia.core.config as config
from tia.core import auditoria
from tia.core.database import obter_conexao
from tia.seguranca import anonimos
from tia.seguranca.sessoes import ler_sessao

NOME_COOKIE = "tia_sessao"
CABECALHO_CSRF = "X-CSRF-Token"
METODOS_SEGUROS = ("GET", "HEAD", "OPTIONS")
SEM_LOGIN = "sem_login"
ANONIMO = "anonimo"
# rotas que aceitam a sessão com senha temporária ainda não trocada
ROTAS_DA_TROCA_DE_SENHA = ("/auth/senha", "/auth/logout")
MENSAGEM_TROCAR_SENHA = "Troque a senha temporária antes de continuar."

_ROTA: ContextVar[str] = ContextVar("rota", default="")
_IP: ContextVar[str] = ContextVar("ip", default="desconhecido")


@dataclass
class UsuarioSessao:
    id: str | None
    papel: str
    aluno_id: str | None = None
    csrf: str | None = None
    trocar_senha: bool = False


def ip_de(request: Request) -> str:
    """Origem do pedido (só para os limites; nunca vai para a auditoria)."""
    return request.client.host if request.client else "desconhecido"


def negar(status: int, detalhe: str, aluno_id: str | None = None):
    """Grava a recusa na auditoria e levanta o erro HTTP. Sem sessão (401 de
    anônimo), só o primeiro pedido da origem na janela é gravado (anonimos)."""
    agora = datetime.now()
    usuario = auditoria.USUARIO_ATUAL.get()
    if status == 401 and usuario and usuario[1] == ANONIMO:
        anonimos.registrar("acesso_negado", _IP.get(), _ROTA.get() or None, str(status), detalhe, agora)
    else:
        conexao = obter_conexao()
        try:
            with conexao:
                auditoria.registrar(conexao, aluno_id, "acesso_negado", _ROTA.get() or None, str(status), [],
                                    ts=agora.isoformat(timespec="seconds"), motivo=detalhe)
        finally:
            conexao.close()
    raise HTTPException(status_code=status, detail=detalhe)


async def usuario_atual(request: Request) -> UsuarioSessao:
    _ROTA.set(f"{request.method} {request.url.path}")
    _IP.set(ip_de(request))
    if config.AUTH_DESLIGADA:
        auditoria.definir_usuario(None, SEM_LOGIN)
        return UsuarioSessao(None, SEM_LOGIN)
    token = request.cookies.get(NOME_COOKIE)
    sessao = ler_sessao(token) if token else None
    if sessao is None:
        auditoria.definir_usuario(None, ANONIMO)
        negar(401, "Faça login para continuar (sessão ausente, expirada ou encerrada por inatividade).")
    auditoria.definir_usuario(sessao["id"], sessao["papel"])
    usuario = UsuarioSessao(sessao["id"], sessao["papel"], sessao["aluno_id"], sessao["csrf"], sessao["trocar_senha"])
    if request.method not in METODOS_SEGUROS and not hmac.compare_digest(
            request.headers.get(CABECALHO_CSRF, ""), usuario.csrf):
        negar(403, "Pedido recusado: falta o cabeçalho anti-CSRF válido. Recarregue a página e tente de novo.")
    if usuario.trocar_senha and request.url.path not in ROTAS_DA_TROCA_DE_SENHA:
        negar(403, MENSAGEM_TROCAR_SENHA)
    return usuario


def exigir_papel(*papeis: str):
    async def dependencia(usuario: UsuarioSessao = Depends(usuario_atual)) -> UsuarioSessao:
        if usuario.papel != SEM_LOGIN and usuario.papel not in papeis:
            negar(403, f"Acesso permitido só ao papel {' ou '.join(papeis)}.")
        return usuario
    return dependencia


def conferir_aluno(usuario: UsuarioSessao, aluno_id: str, *papeis: str):
    """O próprio aluno (aluno_id da sessão) ou um dos papéis; senão 403."""
    if usuario.papel == SEM_LOGIN or usuario.papel in papeis:
        return
    if usuario.papel == "aluno" and usuario.aluno_id == aluno_id:
        return
    if usuario.papel == "aluno":
        negar(403, "Você só pode acessar os seus próprios dados.", aluno_id)
    negar(403, "Estes dados são do aluno" + (f"; acesso permitido também ao papel {' ou '.join(papeis)}."
                                              if papeis else ": só o próprio aluno tem acesso."), aluno_id)


def acesso_ao_aluno(*papeis: str):
    """Para rotas com {aluno_id} no caminho."""
    async def dependencia(aluno_id: str, usuario: UsuarioSessao = Depends(usuario_atual)) -> UsuarioSessao:
        conferir_aluno(usuario, aluno_id, *papeis)
        return usuario
    return dependencia
