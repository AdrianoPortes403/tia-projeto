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

Abra http://localhost:8000/app/ e entre com um dos usuários abaixo (senha fictícia de demonstração
`FICTICIA-demo-2026`, impressa pelo comando; o docente é `DEMO-DOCENTE`):

- `DEMO-W01`: recém-matriculado (começa Funções);
- `DEMO-W02`: concluiu Funções e tem uma sessão aberta em Listas e strings;
- `DEMO-W03`: caiu em Listas e strings e tem uma revisão (reforço) de Repetição pendente.

Um código novo (ex.: `DEMO-W09`) abre o **primeiro acesso**: conversa de cadastro (trilha Dev ou
Defesa Cibernética, horas por semana, dias, objetivo), diagnóstico inicial (base comum de Python + etapa 1
da trilha, níveis 1→2→3) e a trilha montada pelo Planejador, com o perfil (iniciante ou intermediário)
enquadrado pelo diagnóstico. Protótipo sem login (TODO 1.4.6): use só códigos
fictícios. Cada resposta do tutor leva de 20 a 70 s em CPU; a tela mostra o contador de segundos.
Detalhes: `docs/arquitetura/arquitetura.md` (seção "Web standalone").

## Piloto (27/10 a 04/11/2026, 1.5.1)

No `.env`:

```bash
PILOTO_PRAZO_DIAS=8                 # prazo da trilha
PILOTO_ESCOPO=piloto                # só os tópicos marcados no_piloto (dev_01, dev_02, cib_01, cib_02)
INATIVIDADE_DIAS=2
ORQ_INATIVIDADE_REFAZER_DIAS=4
```

Base pedagógica e regras do Agente 1: `docs/relatorios/base_pedagogica_e_agente1.md`.

## Testes

```bash
./run_tests.sh
```

## Estrutura

```
docs/          referência, arquitetura, segurança/LGPD, evidências
conteudo/      dados pedagógicos (ementa, perfis, trilha, banco de itens, materiais)
src/tia/       core, rag, agentes (planejador, tutor, relatório), orquestrador, api,
               web (aplicação do aluno em /app e painel do docente em /app/painel),
               painel (consultas somente de leitura do painel)
dashboard/     vazia: o painel institucional fica em src/tia/web/static/painel
plugin-ebaula/ documentação, demo e teste do plug-in do EBAULA (o código está em src/tia/web/static/plugin/)
infra/         scripts de ambiente
tests/         testes automatizados
```

Contexto completo e regras do projeto: `CLAUDE.md`.
