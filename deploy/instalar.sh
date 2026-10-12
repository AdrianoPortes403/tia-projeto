#!/usr/bin/env bash
# Instala ou atualiza o TIA na VM (Ubuntu 24.04), SEM rede (EAP 1.4.1).
#
# Roda a partir do pacote gerado por deploy/preparar_pacote.sh (código, wheels
# das dependências travadas em deploy/requirements.lock, SHA256SUMS e VERSAO).
# Idempotente: rodar de novo só faz o que falta. Nada destrutivo: cada versão
# fica em $TIA_RAIZ/versoes/<VERSAO>, com venv próprio; $TIA_RAIZ/atual aponta
# para a versão em uso e $TIA_RAIZ/anterior para a de antes (reverter =
# apontar "atual" de volta e reiniciar; docs/implantacao_vm.md).
#
# Passos:
#   1. confere sistema, Python 3.12, pacote e somas SHA256 (só leitura)
#   2. usuário de serviço $TIA_USUARIO, sem login e sem privilégio
#   3. diretórios e permissões (dados 700 do serviço; config 750 root:tia)
#   4. versão: cópia do código e venv com as dependências do pacote (pip --no-index)
#   5. $TIA_RAIZ/atual -> versão nova (guarda a anterior)
#   6. .env a partir do .env.example com os valores de produção (nunca sobrescreve)
#   7. comando $TIA_RAIZ/bin/tia (roda os módulos como o usuário do serviço)
#   8. unidades do systemd (API e timers) e ajuste do Ollama (só 127.0.0.1)
#   9. tabelas do banco, permissão 600
#
# Uso (como root, de dentro do pacote descompactado):
#   sudo ./deploy/instalar.sh --simular     # mostra tudo o que faria
#   sudo ./deploy/instalar.sh
#   sudo ./deploy/instalar.sh --com-rede    # SÓ se não houver wheels: pip baixa do PyPI (usa rede)
#
# Pré-requisitos: Ubuntu 24.04, python3.12 e python3.12-venv (apt), systemd;
# Ollama instalado à parte (docs/implantacao_vm.md).

source "$(dirname "$0")/lib.sh"
ler_opcoes_comuns "$@"
COM_REDE=0
for opcao in "$@"; do
    case "$opcao" in
        --com-rede) COM_REDE=1 ;;
        --simular) ;;
        *) erro "opção desconhecida: $opcao (use --simular ou --com-rede)" ;;
    esac
done
PACOTE="${PACOTE:-$(cd "$DEPLOY_DIR/.." && pwd)}"
TIA_SEM_ROOT=0  # a instalação de verdade sempre exige root
exigir_root

passo "1. Conferências (só leitura)"
if grep -q '^VERSION_ID="24.04"' /etc/os-release 2>/dev/null && grep -q '^ID=ubuntu' /etc/os-release; then
    info "Ubuntu 24.04: ok"
else
    aviso "sistema não é Ubuntu 24.04; os passos foram escritos para ele"
fi
PYTHON_SISTEMA="${PYTHON_SISTEMA:-python3}"
"$PYTHON_SISTEMA" -c 'import sys; assert sys.version_info[:2] == (3, 12)' 2>/dev/null \
    || erro "$PYTHON_SISTEMA não é o Python 3.12 (apt install python3.12)"
"$PYTHON_SISTEMA" -c 'import ensurepip, venv' 2>/dev/null || erro "falta o venv (apt install python3.12-venv)"
info "Python 3.12 com venv: ok"
[ -f "$PACOTE/deploy/requirements.lock" ] || erro "$PACOTE não parece o pacote do TIA (falta deploy/requirements.lock)"
VERSAO="$(cat "$PACOTE/VERSAO" 2>/dev/null || true)"
if [ -z "$VERSAO" ]; then
    [ "$SIMULAR" = 1 ] || erro "falta $PACOTE/VERSAO: gere o pacote com deploy/preparar_pacote.sh"
    VERSAO="simulacao"
    aviso "sem VERSAO (rodando do repositório?): versão fictícia '$VERSAO' na simulação"
fi
info "versão do pacote: $VERSAO"
if [ "$COM_REDE" = 1 ]; then
    aviso "--com-rede: as dependências virão do PyPI (USA REDE); o normal é o pacote com wheels"
elif [ -f "$PACOTE/SHA256SUMS" ] && [ -d "$PACOTE/wheels" ]; then
    (cd "$PACOTE/wheels" && sha256sum --quiet -c ../SHA256SUMS) || erro "wheels alterados: SHA256SUMS não confere"
    info "wheels conferidos ($(find "$PACOTE/wheels" -name '*.whl' | wc -l) arquivos)"
else
    [ "$SIMULAR" = 1 ] || erro "faltam $PACOTE/wheels e SHA256SUMS (deploy/preparar_pacote.sh)"
    aviso "sem wheels: na instalação de verdade, isto pararia aqui"
fi
command -v systemctl >/dev/null || aviso "systemctl não encontrado: as unidades serão copiadas, mas não ativadas"
command -v ollama >/dev/null || aviso "Ollama não instalado: instale antes de deploy/modelos.sh (docs/implantacao_vm.md)"

passo "2. Usuário do serviço ($TIA_USUARIO)"
if id "$TIA_USUARIO" >/dev/null 2>&1; then
    info "já existe"
else
    fazer useradd --system --home-dir "$TIA_RAIZ" --no-create-home --shell /usr/sbin/nologin "$TIA_USUARIO"
fi

passo "3. Diretórios e permissões"
GRUPO="$TIA_USUARIO"
fazer install -d -m 755 -o root -g root "$TIA_RAIZ" "$TIA_RAIZ/versoes" "$TIA_RAIZ/bin"
fazer install -d -m 750 -o root -g "$GRUPO" "$TIA_RAIZ/config"
fazer install -d -m 700 -o "$TIA_USUARIO" -g "$GRUPO" "$TIA_RAIZ/data" "$TIA_RAIZ/backup" "$TIA_RAIZ/medicoes"

passo "4. Versão $VERSAO"
DESTINO="$TIA_RAIZ/versoes/$VERSAO"
if [ -f "$DESTINO/.instalada" ]; then
    info "já instalada em $DESTINO"
else
    fazer install -d -m 755 -o root -g root "$DESTINO"
    for item in src conteudo deploy docs pyproject.toml .env.example; do
        if [ -e "$PACOTE/$item" ]; then fazer cp -a "$PACOTE/$item" "$DESTINO/"; fi
    done
    fazer chown -R root:root "$DESTINO"
    fazer chmod -R go-w,a+rX "$DESTINO"
    fazer "$PYTHON_SISTEMA" -m venv "$DESTINO/venv"
    if [ "$COM_REDE" = 1 ]; then
        fazer "$DESTINO/venv/bin/pip" install --require-virtualenv -r "$DESTINO/deploy/requirements.lock"   # USA REDE
        fazer "$DESTINO/venv/bin/pip" install --require-virtualenv --no-deps "$DESTINO"                    # USA REDE
    else
        fazer "$DESTINO/venv/bin/pip" install --require-virtualenv --no-index --find-links "$PACOTE/wheels" \
            -r "$DESTINO/deploy/requirements.lock"
        fazer "$DESTINO/venv/bin/pip" install --require-virtualenv --no-index --no-deps \
            --find-links "$PACOTE/wheels" tia
    fi
    fazer touch "$DESTINO/.instalada"
fi

passo "5. Versão em uso"
ATUAL="$(readlink "$TIA_RAIZ/atual" 2>/dev/null || true)"
if [ "$ATUAL" = "versoes/$VERSAO" ]; then
    info "$TIA_RAIZ/atual já aponta para $VERSAO"
else
    if [ -n "$ATUAL" ]; then fazer ln -sfn "$ATUAL" "$TIA_RAIZ/anterior"; fi
    fazer ln -sfn "versoes/$VERSAO" "$TIA_RAIZ/atual.novo"
    fazer mv -T "$TIA_RAIZ/atual.novo" "$TIA_RAIZ/atual"
    if [ -n "$ATUAL" ]; then info "versão anterior guardada em $TIA_RAIZ/anterior ($ATUAL)"; fi
fi

passo "6. Configuração ($TIA_ENV)"
# valores de produção que o .env da VM precisa ter (o resto vem do .env.example)
PRODUCAO=(
    "TIA_AMBIENTE=producao" "TIA_AUTH=ligada" "AUTH_COOKIE_SEGURO=1" "API_DOCS=0"
    "OLLAMA_URL=http://127.0.0.1:11434" "API_URL_LOCAL=http://127.0.0.1:8000"
    "DB_PATH=$TIA_RAIZ/data/tia.db" "CHROMA_DIR=$TIA_RAIZ/data/chroma_db" "COPIAS_DIR=$TIA_RAIZ/data/copias"
    "BACKUP_DIR=$TIA_RAIZ/backup"
)
if [ -f "$TIA_ENV" ]; then
    info "já existe: não é alterado"
    faltando="$(grep -oE '^[A-Z_]+=' "$PACOTE/.env.example" | sort -u | while read -r chave; do
        grep -q "^$chave" "$TIA_ENV" || printf '%s ' "${chave%=}"; done)"
    if [ -n "$faltando" ]; then
        info "chaves novas do .env.example (valem os padrões; acrescente se quiser): $faltando"
    fi
else
    novo="$(mktemp)"
    cp "$PACOTE/.env.example" "$novo"
    for par in "${PRODUCAO[@]}"; do
        chave="${par%%=*}"
        if grep -qE "^#? ?$chave=" "$novo"; then
            sed -i -E "s|^#? ?$chave=.*|$par|" "$novo"
        else
            printf '%s\n' "$par" >> "$novo"
        fi
    done
    fazer install -m 640 -o root -g "$GRUPO" "$novo" "$TIA_ENV"
    rm -f "$novo"
    info "criado com: ${PRODUCAO[*]}"
fi

passo "7. Comando $TIA_RAIZ/bin/tia"
modelo_tia="$(mktemp)"
sed -e "s|@TIA_RAIZ@|$TIA_RAIZ|g" -e "s|@TIA_USUARIO@|$TIA_USUARIO|g" "$PACOTE/deploy/tia" > "$modelo_tia"
if cmp -s "$modelo_tia" "$TIA_RAIZ/bin/tia" 2>/dev/null; then
    info "já atualizado"
else
    fazer install -m 755 -o root -g root "$modelo_tia" "$TIA_RAIZ/bin/tia"
fi
rm -f "$modelo_tia"

passo "8. systemd ($SYSTEMD_DIR)"
mudou=0
for unidade in "$PACOTE"/deploy/systemd/*.service "$PACOTE"/deploy/systemd/*.timer \
               "$PACOTE"/deploy/systemd/ollama.service.d/*.conf; do
    relativo="${unidade#"$PACOTE"/deploy/systemd/}"
    gerado="$(mktemp)"
    sed -e "s|@TIA_RAIZ@|$TIA_RAIZ|g" -e "s|@TIA_USUARIO@|$TIA_USUARIO|g" "$unidade" > "$gerado"
    if cmp -s "$gerado" "$SYSTEMD_DIR/$relativo" 2>/dev/null; then
        info "$relativo: sem mudança"
    else
        fazer install -D -m 644 -o root -g root "$gerado" "$SYSTEMD_DIR/$relativo"
        mudou=1
    fi
    rm -f "$gerado"
done
if command -v systemctl >/dev/null; then
    if [ "$mudou" = 1 ]; then fazer systemctl daemon-reload; fi
    fazer systemctl enable tia-api.service tia-limpeza.timer tia-inatividade.timer tia-retencao.timer tia-backup.timer
    if [ "$mudou" = 1 ] && systemctl is-active --quiet ollama 2>/dev/null; then fazer systemctl restart ollama; fi
fi

passo "9. Banco de dados"
if [ "$SIMULAR" = 1 ]; then
    info "[simular] $TIA_RAIZ/bin/tia config  e  python -m tia.core.database como $TIA_USUARIO"
else
    como_tia -m tia.core.database
    chmod 600 "$TIA_RAIZ/data/tia.db"
    if command -v systemctl >/dev/null; then
        fazer systemctl restart tia-api.service tia-limpeza.timer tia-inatividade.timer tia-retencao.timer \
            tia-backup.timer
    fi
fi

passo "Pronto. Próximos passos (docs/implantacao_vm.md)"
info "1. sudo $TIA_RAIZ/atual/deploy/modelos.sh       (baixa os modelos: ÚNICO PASSO COM REDE)"
info "2. sudo $TIA_RAIZ/bin/tia usuarios criar --id <código> --papel admin"
info "3. proxy HTTPS: $TIA_RAIZ/atual/deploy/proxy/nginx-tia.conf"
info "4. sudo $TIA_RAIZ/atual/deploy/verificar.sh"
