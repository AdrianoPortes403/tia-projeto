#!/usr/bin/env bash
# Backup do TIA (EAP 1.4.1): cópia consistente do SQLite (funciona com a API no
# ar), o índice do Chroma e, à parte, o .env; permissões 700/600; rotação por
# BACKUP_DIAS (core/config.py). O timer tia-backup.timer roda o mesmo todo dia.
# Lógica e testes: tia.implantacao.backup. Sem rede.
#
# Uso (como root):
#   sudo ./deploy/backup.sh --simular
#   sudo ./deploy/backup.sh
#   sudo ./deploy/backup.sh --listar

source "$(dirname "$0")/lib.sh"
ler_opcoes_comuns "$@"
for opcao in "$@"; do
    case "$opcao" in
        --listar) como_tia -m tia.implantacao.backup listar; exit 0 ;;
        --simular) ;;
        *) erro "opção desconhecida: $opcao (use --simular ou --listar)" ;;
    esac
done
exigir_root
passo "Backup em $(config_tia BACKUP_DIR || true) (vazio = pasta backup ao lado do banco)"
argumentos=(fazer --env "$TIA_ENV")
if [ "$SIMULAR" = 1 ]; then argumentos+=(--simular); fi
como_tia -m tia.implantacao.backup "${argumentos[@]}"
