"""
Implantação na VM (EAP 1.4.1): a parte em Python dos scripts de deploy/.

    modelos.py    confere se cada modelo de MODELOS_LLM e o de embeddings estão no
                  Ollama e respondem a um prompt curto (deploy/modelos.sh)
    verificar.py  teste de fumaça da VM e medição do R09 por modelo (deploy/verificar.sh)
    backup.py     cópia consistente do banco, do Chroma e do .env, rotação e
                  restauração (deploy/backup.sh e deploy/restaurar.sh)

Os scripts em shell só preparam o ambiente (usuário, venv, .env) e chamam
estes módulos; assim a lógica é testada aqui, sem root e com LLM simulado.
Passo a passo: docs/implantacao_vm.md.

Pré-requisitos:
    - pip install -e . (desenvolvimento) ou deploy/instalar.sh (VM)
"""
