"""
Provedor de autenticação trocável (EAP 1.4.6; login único do EBAULA em 1.4.3).

CONTRATO (Autenticador):
    nome: str                                    identifica o provedor (config AUTH_PROVEDOR)
    autenticar(credenciais: dict) -> Usuario | None
        - recebe as credenciais do provedor (local: {"login", "senha"};
          EBAULA: por exemplo {"ticket"} ou {"token"} do login único);
        - devolve o Usuario do TIA (id de login, papel aluno/docente/admin,
          aluno_id no papel aluno) se as credenciais valem e o usuário está
          ativo; None em qualquer outro caso, sem dizer o porquê;
        - nunca grava credencial em log ou auditoria e não abre sessão.

O resto NÃO depende do provedor: limite de tentativas, sessão no servidor
(cookie HttpOnly, SameSite=Strict), anti-CSRF, autorização por papel e
auditoria ficam em tia.api.rotas_auth e seguranca.acesso. Para plugar o
EBAULA: escrever uma classe com este contrato, registrá-la em PROVEDORES e
usar AUTH_PROVEDOR=<nome>. O mapeamento usuário do EBAULA -> papel/aluno_id
do TIA é decisão pendente (ver docs/relatorios/seguranca_autenticacao.md).

Não é executável; usado por tia.api.rotas_auth.

Pré-requisitos:
    - tabelas criadas: python -m tia.core.database
"""

from typing import Protocol

import tia.core.config as config
from tia.seguranca import senhas, usuarios
from tia.seguranca.usuarios import Usuario


class Autenticador(Protocol):
    nome: str

    def autenticar(self, credenciais: dict) -> Usuario | None: ...


class AutenticadorLocal:
    """Login e senha guardados no TIA (hash scrypt com sal)."""
    nome = "local"

    def autenticar(self, credenciais: dict) -> Usuario | None:
        linha = usuarios.buscar(credenciais.get("login", ""))
        senha = credenciais.get("senha", "")
        if linha is None:
            senhas.conferir(senha, senhas.HASH_FICTICIO)  # mesmo tempo de resposta: não revela se o login existe
            return None
        if not senhas.conferir(senha, linha["senha_hash"]) or not linha["ativo"]:
            return None
        return Usuario(linha["id"], linha["papel"], linha["aluno_id"], True)


PROVEDORES: dict[str, type] = {"local": AutenticadorLocal}


def obter_autenticador() -> Autenticador:
    try:
        return PROVEDORES[config.AUTH_PROVEDOR]()
    except KeyError:
        raise RuntimeError(f"AUTH_PROVEDOR desconhecido: {config.AUTH_PROVEDOR!r} "
                           f"(disponíveis: {', '.join(PROVEDORES)}).")
