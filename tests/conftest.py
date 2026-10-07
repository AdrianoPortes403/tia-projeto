"""
Fixtures compartilhadas dos testes.

- banco_temporario: cada teste usa um SQLite próprio em pasta temporária
  (nunca toca em data/tia.db).
- sem_ollama: qualquer chamada HTTP pelo llm_client falha na hora, para
  garantir que nenhum teste dependa do Ollama; quem precisa do LLM mocka
  chamar_llm explicitamente.

Como rodar:
    ./run_tests.sh
"""

import pytest

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
