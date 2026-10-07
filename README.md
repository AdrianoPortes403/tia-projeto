# tia-sistema

Protótipo integrado do Sistema TIA (Tutoria Inteligente baseada em Agentes
de IA), projeto Areté / IME. Inferência 100% local (Qwen via Ollama).

## Preparar o ambiente

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
cp .env.example .env
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

## Testes

```bash
./run_tests.sh
```

## Estrutura

```
docs/          referência, arquitetura, segurança/LGPD, evidências
conteudo/      dados pedagógicos (ementa, perfis, trilha, banco de itens, materiais)
src/tia/       core, rag, agentes (planejador, tutor, relatório), api
web/           aplicação web standalone
dashboard/     painel institucional
plugin-ebaula/ plug-in para o EBAULA (por último)
infra/         scripts de ambiente
tests/         testes automatizados
```

Contexto completo e regras do projeto: `CLAUDE.md`.
