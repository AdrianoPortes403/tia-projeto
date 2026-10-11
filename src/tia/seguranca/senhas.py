"""
Hash de senha com scrypt (biblioteca padrão: hashlib.scrypt), com sal
aleatório por senha. Formato guardado (uma string, sem a senha):

    scrypt$<n>$<r>$<p>$<sal em hex>$<hash em hex>

A conferência usa comparação em tempo constante (hmac.compare_digest). A
senha nunca vai para log, auditoria ou documentação.

Não é executável; usado por seguranca.usuarios e seguranca.autenticador.

Pré-requisitos:
    - Python 3.12 (hashlib com OpenSSL)
"""

import hashlib
import hmac
import os

# custo do scrypt: 2**14 * 8 * 128 bytes = 16 MiB de memória por conferência (~50 ms)
N, R, P = 2 ** 14, 8, 1
TAMANHO_HASH = 32
TAMANHO_SAL = 16
SENHA_MINIMA = 10  # caracteres; PROVISÓRIO até a política da instituição (Tiago)


class SenhaFraca(ValueError):
    pass


def validar(senha: str):
    """Política mínima: pelo menos SENHA_MINIMA caracteres e não só espaços."""
    if len(senha) < SENHA_MINIMA or not senha.strip():
        raise SenhaFraca(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")


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
