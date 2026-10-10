"""
Testes do llm_client sem Ollama: confere o corpo enviado nas requisições
(keep_alive em chat e embedding, /nothink automático, limite de tokens).

Como rodar:
    ./run_tests.sh tests/test_llm_client.py
"""

import tia.core.llm_client as llm_client
from tia.core.config import OLLAMA_KEEP_ALIVE


class RespostaFalsa:
    def __init__(self, dados: dict):
        self.dados = dados

    def raise_for_status(self):
        pass

    def json(self) -> dict:
        return self.dados


def test_corpo_das_requisicoes(monkeypatch):
    enviados = []

    def post_falso(url, json, timeout):
        enviados.append(json)
        if url.endswith("/api/chat"):
            return RespostaFalsa({"message": {"content": "oi"}})
        return RespostaFalsa({"embedding": [0.1, 0.2]})

    monkeypatch.setattr(llm_client.requests, "post", post_falso)
    assert llm_client.chamar_llm("Diga oi") == "oi"
    assert llm_client.gerar_embedding("texto") == [0.1, 0.2]

    llm_client.chamar_llm("Diga oi", max_tokens=50)

    chat, embedding, chat_limitado = enviados
    assert chat["keep_alive"] == OLLAMA_KEEP_ALIVE
    assert embedding["keep_alive"] == OLLAMA_KEEP_ALIVE
    assert chat["messages"][-1]["content"].endswith("/nothink")
    assert "options" not in chat  # sem limite, o Ollama usa o padrão dele
    assert chat_limitado["options"] == {"num_predict": 50}
