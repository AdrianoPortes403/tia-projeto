"""
Rotas de autenticação (EAP 1.4.6) e de gestão de usuários (papel admin).

    POST /auth/login     {login, senha}: abre a sessão (cookie HttpOnly, SameSite=Strict,
                         Secure configurável) e devolve o usuário e o token anti-CSRF.
                         Exige o cabeçalho X-CSRF-Token (qualquer valor: um site de
                         terceiros não consegue enviá-lo). Limite de falhas por usuário
                         e por IP (429), atraso em cada falha; falha e bloqueio vão para
                         a auditoria agregados por origem e janela (seguranca.anonimos).
                         Com sucesso, a sessão anterior do cookie (se ainda válida)
                         é encerrada e auditada antes de abrir a nova
    POST /auth/logout    encerra a sessão (exige o token anti-CSRF da sessão)
    POST /auth/senha     {senha_atual, nova_senha}: o próprio usuário troca a senha
                         (obrigatório no primeiro acesso com senha temporária); abre
                         uma sessão nova e encerra as outras
    GET  /auth/eu        situação: autenticação ligada ou desligada, usuário (com
                         trocar_senha) e token anti-CSRF (o front guarda só em memória)

    GET  /admin/usuarios                 lista (sem hash de senha)
    POST /admin/usuarios                 cria {id, papel, aluno_id?, senha} (senha temporária)
    POST /admin/usuarios/{id}/desativar  desativa e encerra as sessões
    POST /admin/usuarios/{id}/senha      {senha}: redefine (temporária) e encerra as sessões

A senha nunca vai para log, auditoria ou resposta.

Incluídas em tia.api.main; para subir a API:
    uvicorn tia.api.main:app --reload

Pré-requisitos:
    - usuários criados: python -m tia.seguranca.usuarios criar ... (ou os comandos de demonstração)
"""

import time
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import tia.core.config as config
from tia.core import auditoria
from tia.core.database import obter_conexao
from tia.seguranca import anonimos, senhas, sessoes, usuarios
from tia.seguranca.acesso import (CABECALHO_CSRF, NOME_COOKIE, SEM_LOGIN, UsuarioSessao, exigir_papel, ip_de,
                                  negar, usuario_atual)
from tia.seguranca.autenticador import obter_autenticador

router = APIRouter(prefix="/auth", tags=["seguranca"])
router_admin = APIRouter(prefix="/admin", tags=["seguranca"])


class Login(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    senha: str = Field(min_length=1, max_length=256)


class UsuarioPublico(BaseModel):
    id: str | None
    papel: str
    aluno_id: str | None = None
    trocar_senha: bool = False  # senha temporária: só a troca de senha e a saída funcionam


class Situacao(BaseModel):
    autenticacao: Literal["ligada", "desligada"]
    usuario: UsuarioPublico | None = None
    csrf: str | None = None


class NovoUsuario(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    papel: Literal["aluno", "docente", "admin"]
    aluno_id: str | None = Field(default=None, max_length=32)
    senha: str = Field(min_length=1, max_length=256)


class NovaSenha(BaseModel):
    senha: str = Field(min_length=1, max_length=256)


class TrocaDeSenha(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=256)
    nova_senha: str = Field(min_length=1, max_length=256)


class UsuarioCadastro(BaseModel):
    id: str
    papel: str
    aluno_id: str | None
    ativo: bool
    trocar_senha: bool


def _auditar(tipo: str, origem: str, motivo: str):
    conexao = obter_conexao()
    try:
        with conexao:
            auditoria.registrar(conexao, None, tipo, None, origem, [], motivo=motivo)
    finally:
        conexao.close()


def _login_seguro(login: str) -> str:
    """O login como vai para a auditoria: só se tiver o formato de código (nunca um nome digitado)."""
    return login if usuarios.PADRAO_ID.match(login) else "(fora do formato de código)"


def _recusar_bloqueado(motivo_bloqueio: str, login: str, ip: str):
    """429 com atraso; na auditoria, só o primeiro bloqueio da origem na janela (anonimos)."""
    time.sleep(config.AUTH_ATRASO_SEGUNDOS)
    anonimos.registrar("login_bloqueado", ip, None, "429",
                       f"login={login}; limite de falhas por {motivo_bloqueio} na janela de "
                       f"{config.AUTH_JANELA_MINUTOS} min")
    raise HTTPException(status_code=429, detail=(
        f"Muitas tentativas de login. Aguarde {config.AUTH_JANELA_MINUTOS} minutos e tente de novo."))


def _abrir_sessao(response: Response, usuario_id: str) -> str:
    """Abre a sessão, põe o cookie e devolve o token anti-CSRF."""
    token, csrf = sessoes.criar_sessao(usuario_id)
    response.set_cookie(NOME_COOKIE, token, max_age=config.AUTH_SESSAO_MAXIMA_MINUTOS * 60, httponly=True,
                        samesite="strict", secure=config.AUTH_COOKIE_SEGURO, path="/")
    return csrf


def _encerrar_sessao_anterior(request: Request):
    """Login bem-sucedido com o cookie de uma sessão ainda válida (outro perfil ou o mesmo
    usuário, neste navegador): encerra essa sessão no servidor e audita em nome de quem
    era o dono dela. Cookie ausente, inválido ou vencido: nada a fazer, o login segue."""
    token = request.cookies.get(NOME_COOKIE)
    anterior = sessoes.ler_sessao(token, renovar=False) if token else None
    if anterior is None:
        return
    sessoes.encerrar_sessao(token)
    auditoria.definir_usuario(anterior["id"], anterior["papel"])
    _auditar("logout", "sessao", "sessão anterior encerrada por um novo login neste navegador")


def _publico(sessao: dict) -> UsuarioPublico:
    return UsuarioPublico(id=sessao["id"], papel=sessao["papel"], aluno_id=sessao["aluno_id"],
                          trocar_senha=sessao["trocar_senha"])


@router.post("/login", response_model=Situacao)
def entrar(dados: Login, request: Request, response: Response) -> Situacao:
    """Confere as credenciais pelo provedor configurado e abre a sessão."""
    if config.AUTH_DESLIGADA:
        raise HTTPException(status_code=409, detail="A autenticação está desligada (modo de desenvolvimento).")
    if not request.headers.get(CABECALHO_CSRF):
        raise HTTPException(status_code=403, detail="Pedido recusado: falta o cabeçalho anti-CSRF.")
    ip = ip_de(request)
    login = _login_seguro(dados.login)
    auditoria.definir_usuario(None, "anonimo")  # o login tentado vai no motivo
    motivo_bloqueio = sessoes.bloqueio(dados.login, ip)
    if motivo_bloqueio:
        _recusar_bloqueado(motivo_bloqueio, login, ip)
    usuario = obter_autenticador().autenticar({"login": dados.login, "senha": dados.senha})
    sessoes.registrar_tentativa(dados.login, ip, usuario is not None)
    if usuario is None:
        time.sleep(config.AUTH_ATRASO_SEGUNDOS)
        # agregado como os pedidos sem login (D4): muitas origens não enchem a auditoria;
        # o bloqueio continua contando cada falha em auth_tentativas
        anonimos.registrar("login_falha", ip, None, "401", f"login={login}")
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
    _encerrar_sessao_anterior(request)
    csrf = _abrir_sessao(response, usuario.id)
    auditoria.definir_usuario(usuario.id, usuario.papel)
    _auditar("login", obter_autenticador().nome,
             f"sessão de até {config.AUTH_SESSAO_MAXIMA_MINUTOS} min, encerrada após "
             f"{config.AUTH_SESSAO_INATIVIDADE_MINUTOS} min sem uso"
             + ("; senha temporária: troca obrigatória" if usuario.trocar_senha else ""))
    return Situacao(autenticacao="ligada", csrf=csrf,
                    usuario=UsuarioPublico(id=usuario.id, papel=usuario.papel, aluno_id=usuario.aluno_id,
                                           trocar_senha=usuario.trocar_senha))


@router.post("/logout", status_code=204)
def sair(request: Request, response: Response, usuario: UsuarioSessao = Depends(usuario_atual)) -> None:
    """Encerra a sessão atual."""
    token = request.cookies.get(NOME_COOKIE)
    if token:
        sessoes.encerrar_sessao(token)
    _auditar("logout", "sessao", "sessão encerrada pelo usuário")
    response.delete_cookie(NOME_COOKIE, path="/", httponly=True, samesite="strict", secure=config.AUTH_COOKIE_SEGURO)


@router.post("/senha", response_model=Situacao)
def trocar_senha(dados: TrocaDeSenha, request: Request, response: Response,
                 usuario: UsuarioSessao = Depends(usuario_atual)) -> Situacao:
    """O próprio usuário troca a senha (confere a atual). Encerra todas as
    sessões dele e abre uma nova; a nova senha deixa de ser temporária."""
    if usuario.papel == SEM_LOGIN:
        raise HTTPException(status_code=409, detail="A autenticação está desligada (modo de desenvolvimento).")
    if obter_autenticador().nome != "local":
        raise HTTPException(status_code=409, detail="A senha é gerenciada pelo login da instituição.")
    ip = ip_de(request)
    motivo_bloqueio = sessoes.bloqueio(usuario.id, ip)
    if motivo_bloqueio:
        _recusar_bloqueado(motivo_bloqueio, usuario.id, ip)
    try:
        trocou = usuarios.trocar_propria_senha(usuario.id, dados.senha_atual, dados.nova_senha)
    except senhas.SenhaFraca as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    if not trocou:
        # senha atual errada conta como falha de login (a sessão não vira um jeito de adivinhar a senha)
        sessoes.registrar_tentativa(usuario.id, ip, False)
        time.sleep(config.AUTH_ATRASO_SEGUNDOS)
        _auditar("login_falha", "403", f"login={usuario.id}; senha atual incorreta na troca de senha")
        raise HTTPException(status_code=403, detail="A senha atual não confere.")
    csrf = _abrir_sessao(response, usuario.id)
    return Situacao(autenticacao="ligada", csrf=csrf,
                    usuario=UsuarioPublico(id=usuario.id, papel=usuario.papel, aluno_id=usuario.aluno_id))


@router.get("/eu", response_model=Situacao)
def eu(request: Request) -> Situacao:
    """Quem está logado (ou que a autenticação está desligada). Nunca 401."""
    if config.AUTH_DESLIGADA:
        return Situacao(autenticacao="desligada")
    token = request.cookies.get(NOME_COOKIE)
    sessao = sessoes.ler_sessao(token) if token else None
    if sessao is None:
        return Situacao(autenticacao="ligada")
    return Situacao(autenticacao="ligada", csrf=sessao["csrf"], usuario=_publico(sessao))


# --- gestão de usuários (admin) ---

SoAdmin = Annotated[UsuarioSessao, Depends(exigir_papel("admin"))]


@router_admin.get("/usuarios", response_model=list[UsuarioCadastro])
def listar_usuarios(usuario: SoAdmin) -> list[dict]:
    return [asdict(u) for u in usuarios.listar()]


@router_admin.post("/usuarios", response_model=UsuarioCadastro, status_code=201)
def criar_usuario(novo: NovoUsuario, usuario: SoAdmin) -> dict:
    try:
        return asdict(usuarios.criar(novo.id, novo.papel, novo.senha, novo.aluno_id))
    except (usuarios.ErroUsuario, senhas.SenhaFraca) as erro:
        raise HTTPException(status_code=422, detail=str(erro))


@router_admin.post("/usuarios/{usuario_id}/desativar", status_code=204)
def desativar_usuario(usuario_id: str, usuario: SoAdmin) -> None:
    if usuario_id == usuario.id:
        negar(409, "Um admin não pode desativar a si mesmo.")
    if not usuarios.desativar(usuario_id):
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")


@router_admin.post("/usuarios/{usuario_id}/senha", status_code=204)
def redefinir_senha(usuario_id: str, dados: NovaSenha, usuario: SoAdmin) -> None:
    try:
        encontrado = usuarios.redefinir_senha(usuario_id, dados.senha)
    except senhas.SenhaFraca as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    if not encontrado:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
