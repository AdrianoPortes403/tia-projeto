"""
Hash de senha com scrypt (biblioteca padrão: hashlib.scrypt), com sal
aleatório por senha. Formato guardado (uma string, sem a senha):

    scrypt$<n>$<r>$<p>$<sal em hex>$<hash em hex>

A conferência usa comparação em tempo constante (hmac.compare_digest). A
senha nunca vai para log, auditoria ou documentação.

Política de senha (validar), configurável em core/config.py: pelo menos
AUTH_SENHA_MINIMA caracteres, não pode ser uma das senhas mais comuns
(senhas_comuns.txt e AUTH_SENHAS_COMUNS_EXTRA; ignora maiúsculas e os números
e símbolos das pontas), nem conter o id do usuário, nem repetir quase só um
caractere. PROVISÓRIA até a política da instituição.

Não é executável; usado por seguranca.usuarios e seguranca.autenticador.

Pré-requisitos:
    - Python 3.12 (hashlib com OpenSSL)
"""

import hashlib
import hmac
import os
from functools import cache
from pathlib import Path

import tia.core.config as config

# custo do scrypt: 2**14 * 8 * 128 bytes = 16 MiB de memória por conferência (~50 ms)
N, R, P = 2 ** 14, 8, 1
TAMANHO_HASH = 32
TAMANHO_SAL = 16
LISTA_COMUNS = Path(__file__).with_name("senhas_comuns.txt")
MINIMO_CARACTERES_DIFERENTES = 4


class SenhaFraca(ValueError):
    pass


@cache
def _ler_lista(caminho: str) -> frozenset[str]:
    linhas = Path(caminho).read_text(encoding="utf-8").splitlines()
    return frozenset(l.strip().lower() for l in linhas if l.strip() and not l.lstrip().startswith("#"))


def senhas_comuns() -> frozenset[str]:
    """Senhas bloqueadas: a lista do TIA mais o arquivo extra da instituição, se houver."""
    comuns = _ler_lista(str(LISTA_COMUNS))
    if config.AUTH_SENHAS_COMUNS_EXTRA:
        comuns = comuns | _ler_lista(config.AUTH_SENHAS_COMUNS_EXTRA)
    return comuns


def _base(senha: str) -> str:
    """A senha em minúsculas sem os números e símbolos das pontas ("Senha@2026!" -> "senha")."""
    texto = senha.strip().lower()
    inicio, fim = 0, len(texto)
    while inicio < fim and not texto[inicio].isalpha():
        inicio += 1
    while fim > inicio and not texto[fim - 1].isalpha():
        fim -= 1
    return texto[inicio:fim]


def validar(senha: str, usuario_id: str | None = None):
    """Aplica a política de senha; levanta SenhaFraca com a mensagem para o usuário."""
    minima = config.AUTH_SENHA_MINIMA
    if len(senha) < minima or not senha.strip():
        raise SenhaFraca(f"A senha precisa ter pelo menos {minima} caracteres.")
    if len(set(senha.lower())) < MINIMO_CARACTERES_DIFERENTES:
        raise SenhaFraca("A senha repete quase só os mesmos caracteres. Escolha outra.")
    if usuario_id and usuario_id.lower() in senha.lower():
        raise SenhaFraca("A senha não pode conter o nome de usuário.")
    if config.AUTH_SENHA_BLOQUEAR_COMUNS:
        comuns = senhas_comuns()
        if senha.strip().lower() in comuns or _base(senha) in comuns:
            raise SenhaFraca("Essa senha é muito comum e fácil de adivinhar. Escolha outra.")


def _derivar(senha: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=TAMANHO_HASH,
                          maxmem=256 * 1024 * 1024)


def gerar_hash(senha: str) -> str:
    sal = os.urandom(TAMANHO_SAL)
    return f"scrypt${N}${R}${P}${sal.hex()}${_derivar(senha, sal, N, R, P).hex()}"


def conferir(senha: str, guardado: str) -> bool:
    """True se a senha corresponde ao hash guardado. Hash malformado: False."""
    try:
        algoritmo, n, r, p, sal, esperado = guardado.split("$")
        if algoritmo != "scrypt":
            return False
        calculado = _derivar(senha, bytes.fromhex(sal), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), esperado)


# hash de uma senha qualquer, para gastar o mesmo tempo quando o usuário não
# existe (não revela pelo tempo de resposta se o login existe)
HASH_FICTICIO = gerar_hash("usuario-inexistente-tempo-constante")
