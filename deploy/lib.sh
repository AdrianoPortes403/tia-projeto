# shellcheck shell=bash
# Funções comuns dos scripts de implantação (EAP 1.4.1). Não é executável:
# os scripts de deploy/ fazem "source" deste arquivo.
#
# Variáveis (todas com padrão; os testes as trocam por pastas temporárias):
#   TIA_RAIZ      raiz da instalação na VM           (padrão /srv/tia)
#   TIA_USUARIO   usuário do serviço, sem privilégio (padrão tia)
#   TIA_ENV       .env da VM                         (padrão $TIA_RAIZ/config/.env)
#   TIA_PYTHON    python do venv em uso              (padrão $TIA_RAIZ/atual/venv/bin/python)
#   SYSTEMD_DIR   onde ficam as unidades             (padrão /etc/systemd/system)
#   TIA_SEM_ROOT  1 = dispensa o root nos scripts que não mexem no sistema (backup,
#                 restaurar, modelos, verificar): só para testes e máquina de desenvolvimento

set -euo pipefail

TIA_RAIZ="${TIA_RAIZ:-/srv/tia}"
TIA_USUARIO="${TIA_USUARIO:-tia}"
TIA_ENV="${TIA_ENV:-$TIA_RAIZ/config/.env}"
TIA_PYTHON="${TIA_PYTHON:-$TIA_RAIZ/atual/venv/bin/python}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMULAR="${SIMULAR:-0}"

passo() { printf '\n== %s\n' "$*"; }
info() { printf '   %s\n' "$*"; }
aviso() { printf '   AVISO: %s\n' "$*" >&2; }
erro() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }

# executa o comando, ou só mostra com --simular (todo passo que altera algo passa por aqui)
fazer() {
    if [ "$SIMULAR" = 1 ]; then
        printf '   [simular] %s\n' "$*"
    else
        printf '   + %s\n' "$*"
        "$@"
    fi
}

eh_root() { [ "$(id -u)" = 0 ]; }

exigir_root() {
    if ! eh_root && [ "$SIMULAR" != 1 ] && [ "${TIA_SEM_ROOT:-0}" != 1 ]; then
        erro "rode como root (sudo $0 ...) ou use --simular para só ver o que seria feito"
    fi
}

# roda um módulo Python do TIA com o .env da VM carregado: como o usuário do
# serviço quando o script roda como root; como o usuário atual nos testes.
# Uso: como_tia -m tia.core.config
como_tia() {
    local diretorio="$TIA_RAIZ/atual"
    [ -d "$diretorio" ] || diretorio="$(pwd)"
    if eh_root && id "$TIA_USUARIO" >/dev/null 2>&1; then
        runuser -u "$TIA_USUARIO" -- bash -c 'umask 077; unset PYTHONPATH; cd "$1"; if [ -r "$2" ]; then set -a; . "$2"; set +a; fi; shift 2; exec "$@"' \
            _ "$diretorio" "$TIA_ENV" "$TIA_PYTHON" "$@"
    else
        (umask 077; unset PYTHONPATH; if [ -r "$TIA_ENV" ]; then set -a; . "$TIA_ENV"; set +a; fi; exec "$TIA_PYTHON" "$@")
    fi
}

# lê um valor de core/config.py (a configuração tem uma fonte só)
config_tia() {
    como_tia -c "import tia.core.config as c; v = c.$1; print(' '.join(v) if isinstance(v, list) else v)"
}

ler_opcoes_comuns() {
    for opcao in "$@"; do
        case "$opcao" in
            --simular) SIMULAR=1 ;;
        esac
    done
    if [ "$SIMULAR" = 1 ]; then
        printf 'SIMULAÇÃO: nada será alterado; cada passo mostra o comando que seria executado.\n'
    fi
}
