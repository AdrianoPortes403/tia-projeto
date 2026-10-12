#!/usr/bin/env bash
# Gera o pacote de implantação do TIA (EAP 1.4.1). Roda na MÁQUINA DE
# DESENVOLVIMENTO, a partir da raiz do repositório, com o venv ativo.
# USA REDE (PyPI) para baixar as dependências: por isso a VM não precisa.
#
# Resultado: dist/tia-<VERSAO>/ e dist/tia-<VERSAO>.tar.gz com
#   código (src, conteudo, deploy, docs, pyproject.toml, .env.example),
#   wheels/ (dependências de deploy/requirements.lock e o próprio tia),
#   SHA256SUMS dos wheels (conferido pelo instalar.sh) e VERSAO.
# Levar o .tar.gz à VM (scp), descompactar e rodar sudo ./deploy/instalar.sh.
#
# Uso:
#   ./deploy/preparar_pacote.sh --simular
#   ./deploy/preparar_pacote.sh

source "$(dirname "$0")/lib.sh"
ler_opcoes_comuns "$@"
RAIZ_REPO="$(cd "$DEPLOY_DIR/.." && pwd)"
cd "$RAIZ_REPO"
VERSAO="$(date +%Y%m%d)-$(git rev-parse --short HEAD 2>/dev/null || echo local)"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then VERSAO="$VERSAO-modificado"; fi
DESTINO="dist/tia-$VERSAO"
[ -e "$DESTINO" ] && erro "$DESTINO já existe (apague ou espere o próximo commit)"
PYTHON="${PYTHON:-python}"

passo "Pacote $VERSAO"
fazer mkdir -p "$DESTINO/wheels"
for item in src conteudo deploy docs pyproject.toml .env.example; do
    fazer cp -a "$item" "$DESTINO/"
done
fazer find "$DESTINO" -name __pycache__ -prune -exec rm -rf {} +
passo "Dependências [USA REDE: PyPI]"
fazer "$PYTHON" -m pip wheel --wheel-dir "$DESTINO/wheels" -r deploy/requirements.lock
fazer "$PYTHON" -m pip wheel --no-deps --wheel-dir "$DESTINO/wheels" .
fazer rm -rf build   # sobra do setuptools ao montar o wheel do tia
passo "Somas e arquivo"
if [ "$SIMULAR" = 1 ]; then
    info "[simular] sha256sum dos wheels > SHA256SUMS; VERSAO; tar czf dist/tia-$VERSAO.tar.gz"
else
    (cd "$DESTINO/wheels" && sha256sum ./*.whl > ../SHA256SUMS)
    printf '%s\n' "$VERSAO" > "$DESTINO/VERSAO"
    tar czf "dist/tia-$VERSAO.tar.gz" -C dist "tia-$VERSAO"
    sha256sum "dist/tia-$VERSAO.tar.gz" | tee "dist/tia-$VERSAO.tar.gz.sha256"
fi
