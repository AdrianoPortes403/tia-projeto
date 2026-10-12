#!/usr/bin/env bash
# Teste de fumaça da VM e medição do R09 (EAP 1.4.1). Não altera nada no banco
# e não usa rede de fora (só a API e o Ollama locais). Lógica e testes:
# tia.implantacao.verificar.
#
# Fumaça: configuração, banco, API no ar com cabeçalhos, autenticação, Ollama
# com todos os modelos, Chroma indexado e nenhuma conexão de saída inesperada.
#
# Uso (como root ou como o usuário do serviço):
#   sudo ./deploy/verificar.sh
#   sudo ./deploy/verificar.sh --usuario ADM-01 < arquivo_com_a_senha   # login de verdade
#   sudo ./deploy/verificar.sh --medir-r09 10 [--modelos qwen3:4b,qwen3:8b] [--tipos feedback,dialogo]
#     -> CSV em $TIA_RAIZ/medicoes/r09-<data>.csv e o resumo (média, p50, p90, p95) na tela

source "$(dirname "$0")/lib.sh"
argumentos=("$@")
if [[ " $* " == *" --medir-r09 "* && " $* " != *" --saida "* ]]; then
    argumentos+=(--saida "$TIA_RAIZ/medicoes/r09-$(date +%Y%m%d-%H%M%S).csv")
fi
como_tia -m tia.implantacao.verificar "${argumentos[@]}"
