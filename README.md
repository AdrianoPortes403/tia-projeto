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

## Aplicação web do aluno (demonstração)

```bash
source venv/bin/activate
python -m tia.web.dados_demo           # alunos fictícios DEMO-W01, DEMO-W02 e DEMO-W03 (rápido, sem LLM)
uvicorn tia.api.main:app --reload      # com o Ollama rodando
```

Abra http://localhost:8000/app/ e entre com um dos códigos:

- `DEMO-W01`: recém-matriculado (começa Funções);
- `DEMO-W02`: concluiu Funções e tem uma sessão aberta em Listas e strings;
- `DEMO-W03`: caiu em Listas e strings e tem uma revisão (reforço) de Repetição pendente.

Um código novo (ex.: `DEMO-W09`) abre a matrícula. Protótipo sem login (TODO 1.4.6): use só códigos
fictícios. Cada resposta do tutor leva de 20 a 70 s em CPU; a tela mostra o contador de segundos.
Detalhes: `docs/arquitetura/arquitetura.md` (seção "Web standalone").

## Testes

```bash
./run_tests.sh
```

## Estrutura

```
docs/          referência, arquitetura, segurança/LGPD, evidências
conteudo/      dados pedagógicos (ementa, perfis, trilha, banco de itens, materiais)
src/tia/       core, rag, agentes (planejador, tutor, relatório), orquestrador, api,
               web (aplicação web standalone, servida em /app)
dashboard/     painel institucional
plugin-ebaula/ plug-in para o EBAULA (por último)
infra/         scripts de ambiente
tests/         testes automatizados
```

Contexto completo e regras do projeto: `CLAUDE.md`.
