#!/usr/bin/env bash
# Restaura um backup do TIA (EAP 1.4.1). Confere SHA256 e integridade antes; NADA
# é apagado: o banco e o índice atuais ficam como "<nome>.antes-restauracao-<data>".
# A API precisa estar PARADA (systemctl stop tia-api), senão o script recusa.
# O .env só é restaurado com --com-env. Sem rede.
#
# Uso (como root):
#   sudo ./deploy/restaurar.sh /srv/tia/backup/20261015-023000 --simular
#   sudo systemctl stop tia-api && sudo ./deploy/restaurar.sh /srv/tia/backup/20261015-023000
#   sudo ./deploy/restaurar.sh <pasta> --com-env          # também o .env (de BACKUP_DIR/config)
#   sudo systemctl start tia-api && sudo ./deploy/verificar.sh

source "$(dirname "$0")/lib.sh"
ler_opcoes_comuns "$@"
PASTA=""
COM_ENV=0
for opcao in "$@"; do
    case "$opcao" in
        --simular) ;;
        --com-env) COM_ENV=1 ;;
        -*) erro "opção desconhecida: $opcao" ;;
        *) PASTA="$opcao" ;;
    esac
done
[ -n "$PASTA" ] || erro "informe a pasta do backup (sudo ./deploy/backup.sh --listar)"
exigir_root
if [ "$SIMULAR" != 1 ] && command -v systemctl >/dev/null && systemctl is-active --quiet tia-api 2>/dev/null; then
    erro "a API está no ar: pare antes (sudo systemctl stop tia-api)"
fi
passo "Restaurar $PASTA"
argumentos=(restaurar "$PASTA")
if [ "$COM_ENV" = 1 ]; then argumentos+=(--com-env "$TIA_ENV"); fi
if [ "$SIMULAR" = 1 ]; then argumentos+=(--simular); fi
como_tia -m tia.implantacao.backup "${argumentos[@]}"
if [ "$SIMULAR" != 1 ]; then
    info "Pronto. Suba a API (sudo systemctl start tia-api) e rode sudo ./deploy/verificar.sh"
fi
