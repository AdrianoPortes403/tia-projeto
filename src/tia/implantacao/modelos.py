"""
Confere os modelos do Ollama (EAP 1.4.1): cada modelo de chat de MODELOS_LLM
e o de embeddings (EMBED_MODEL) estão instalados e respondem a um prompt
curto. Não baixa nada: o download é do deploy/modelos.sh (único passo com rede).

Para cada modelo de chat mostra o tempo da resposta (a primeira chamada inclui
carregar o modelo na memória), o modo de desligar o raciocínio (mapa
RACIOCINIO_POR_MODELO) e se veio raciocínio no texto apesar disso.

Como rodar (a partir da raiz, com o venv ativo; na VM: /srv/tia/bin/tia modelos):
    python -m tia.implantacao.modelos
    python -m tia.implantacao.modelos --modelos qwen3:1.7b,qwen3:4b

Pré-requisitos:
    - Ollama no ar (OLLAMA_URL) com os modelos baixados (deploy/modelos.sh)
"""

import argparse
import sys
from dataclasses import dataclass

import tia.core.config as config
from tia.core import llm_client

PROMPT_CURTO = "Responda apenas com a palavra: ok"


@dataclass
class SituacaoModelo:
    modelo: str
    tipo: str                 # "chat" ou "embeddings"
    instalado: bool
    respondeu: bool = False
    tempo_s: float | None = None
    modo_raciocinio: str = ""
    raciocinio_vazou: bool = False
    detalhe: str = ""


def _com_etiqueta(nome: str) -> str:
    """O Ollama lista "nomic-embed-text" como "nomic-embed-text:latest"."""
    return nome if ":" in nome else nome + ":latest"


def conferir(modelos: list[str] | None = None, embeddings: str | None = None,
             timeout: int = 300) -> list[SituacaoModelo]:
    modelos = config.MODELOS_LLM if modelos is None else modelos
    embeddings = embeddings or config.EMBED_MODEL
    try:
        instalados = {_com_etiqueta(m) for m in llm_client.listar_modelos_instalados()}
    except Exception as erro:
        falha = llm_client.descrever_falha(erro)
        return [SituacaoModelo(m, t, False, detalhe=f"Ollama indisponível ({falha})")
                for m, t in [*((m, "chat") for m in modelos), (embeddings, "embeddings")]]
    situacoes = []
    for modelo in modelos:
        situacao = SituacaoModelo(modelo, "chat", _com_etiqueta(modelo) in instalados,
                                  modo_raciocinio=llm_client.modo_raciocinio(modelo))
        if not situacao.instalado:
            situacao.detalhe = "não instalado (deploy/modelos.sh)"
        else:
            with llm_client.coletar_chamadas() as chamadas:
                try:
                    texto = llm_client.chamar_llm(PROMPT_CURTO, model=modelo, timeout=timeout, max_tokens=50)
                    situacao.respondeu = bool(texto.strip())
                    situacao.detalhe = "ok" if situacao.respondeu else "resposta vazia"
                except Exception as erro:
                    situacao.detalhe = f"falhou ({llm_client.descrever_falha(erro)})"
            if chamadas:
                situacao.tempo_s = chamadas[-1].tempo_ms / 1000
                situacao.raciocinio_vazou = chamadas[-1].raciocinio_no_texto or chamadas[-1].raciocinio_api
        situacoes.append(situacao)
    situacao = SituacaoModelo(embeddings, "embeddings", _com_etiqueta(embeddings) in instalados)
    if situacao.instalado:
        try:
            vetor = llm_client.gerar_embedding("teste de verificação", model=embeddings, timeout=timeout)
            situacao.respondeu, situacao.detalhe = bool(vetor), f"vetor de {len(vetor)} dimensões"
        except Exception as erro:
            situacao.detalhe = f"falhou ({llm_client.descrever_falha(erro)})"
    else:
        situacao.detalhe = "não instalado (deploy/modelos.sh)"
    situacoes.append(situacao)
    return situacoes


def relatorio(situacoes: list[SituacaoModelo]) -> str:
    linhas = [f"{'modelo':<22} {'tipo':<11} {'instalado':<9} {'respondeu':<9} {'tempo':>8}  raciocínio"]
    for s in situacoes:
        tempo = f"{s.tempo_s:.1f} s" if s.tempo_s is not None else "-"
        raciocinio = (f"{s.modo_raciocinio}{'; VAZOU' if s.raciocinio_vazou else ''}" if s.tipo == "chat" else "-")
        linhas.append(f"{s.modelo:<22} {s.tipo:<11} {'sim' if s.instalado else 'NÃO':<9} "
                      f"{'sim' if s.respondeu else 'NÃO':<9} {tempo:>8}  {raciocinio}  {s.detalhe}")
    return "\n".join(linhas)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Confere se os modelos do Ollama estão instalados e respondem.")
    parser.add_argument("--modelos", help="lista separada por vírgula (padrão: MODELOS_LLM)")
    args = parser.parse_args()
    resultado = conferir([m.strip() for m in args.modelos.split(",") if m.strip()] if args.modelos else None)
    print(relatorio(resultado))
    sys.exit(0 if all(s.instalado and s.respondeu for s in resultado) else 1)
