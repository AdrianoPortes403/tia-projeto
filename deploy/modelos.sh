#!/usr/bin/env bash
# Baixa e confere os modelos do Ollama e reindexa o RAG (EAP 1.4.1).
#
# ESTE É O ÚNICO PASSO DA IMPLANTAÇÃO QUE USA REDE: o "ollama pull" baixa do
# registro do Ollama (registry.ollama.ai e o CDN dele, porta 443). Peça ao
# Tiago a liberação temporária da saída (ou um proxy, ver
# systemd/ollama.service.d/tia.conf) só durante este passo.
#
# Passos:
#   1. lista: MODELOS_LLM e EMBED_MODEL do .env (core/config.py)
#   2. [REDE] ollama pull de cada um (já baixado: o pull só confere, é rápido)
#   3. reindexa o material do curso no Chroma (python -m tia.rag.ingest; upsert, idempotente)
#   4. cada modelo responde a um prompt curto (python -m tia.implantacao.modelos)
#
# Uso (como root):
#   sudo ./deploy/modelos.sh --simular
#   sudo ./deploy/modelos.sh
#   sudo ./deploy/modelos.sh --sem-download    # passos 3 e 4, sem rede (ex.: modelos já copiados)

source "$(dirname "$0")/lib.sh"
ler_opcoes_comuns "$@"
BAIXAR=1
for opcao in "$@"; do
    case "$opcao" in
        --sem-download) BAIXAR=0 ;;
        --simular) ;;
        *) erro "opção desconhecida: $opcao (use --simular ou --sem-download)" ;;
    esac
done
exigir_root

passo "1. Modelos configurados"
MODELOS="$(config_tia MODELOS_LLM)"
EMBEDDINGS="$(config_tia EMBED_MODEL)"
info "chat: $MODELOS"
info "embeddings: $EMBEDDINGS"

passo "2. Download [USA REDE: registry.ollama.ai:443]"
if [ "$BAIXAR" = 0 ]; then
    info "pulado (--sem-download)"
else
    command -v ollama >/dev/null || [ "$SIMULAR" = 1 ] || erro "Ollama não instalado (docs/implantacao_vm.md, passo 2)"
    for modelo in $MODELOS $EMBEDDINGS; do
        fazer ollama pull "$modelo"
    done
fi

passo "3. Índice do RAG (material do curso)"
if [ "$SIMULAR" = 1 ]; then
    info "[simular] python -m tia.rag.ingest como $TIA_USUARIO"
else
    como_tia -m tia.rag.ingest
fi

passo "4. Cada modelo responde"
if [ "$SIMULAR" = 1 ]; then
    info "[simular] python -m tia.implantacao.modelos (um prompt curto por modelo)"
else
    como_tia -m tia.implantacao.modelos
fi
