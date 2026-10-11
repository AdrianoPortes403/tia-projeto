"""
Fixtures compartilhadas dos testes.

- banco_temporario: cada teste usa um SQLite próprio em pasta temporária
  (nunca toca em data/tia.db).
- sem_ollama: qualquer chamada HTTP pelo llm_client falha na hora, para
  garantir que nenhum teste dependa do Ollama; quem precisa do LLM mocka
  chamar_llm explicitamente.
- auth_desligada: TIA_AUTH=desligada (modo de desenvolvimento) nos testes que
  verificam o comportamento dos agentes pelas rotas. Os testes de segurança
  (tests/test_seguranca.py) pedem a fixture auth_ligada, que liga a
  autenticação (cookie sem Secure, para o TestClient em http, e sem atraso).

Como rodar:
    ./run_tests.sh
"""

import pytest

import tia.core.config as config
import tia.core.database as database
import tia.core.llm_client as llm_client


@pytest.fixture(autouse=True)
def banco_temporario(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "teste.db"))
    database.criar_tabelas()


@pytest.fixture(autouse=True)
def sem_ollama(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("Teste tentou chamar o Ollama de verdade; mocke o llm_client.")

    monkeypatch.setattr(llm_client.requests, "post", proibido)


@pytest.fixture(autouse=True)
def auth_desligada(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DESLIGADA", True)


@pytest.fixture
def auth_ligada(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DESLIGADA", False)
    monkeypatch.setattr(config, "AUTH_COOKIE_SEGURO", False)
    monkeypatch.setattr(config, "AUTH_ATRASO_SEGUNDOS", 0)
