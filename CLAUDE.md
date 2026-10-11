# Sistema TIA — contexto para o Claude Code

Projeto acadêmico do IME (empresa fictícia Areté): plataforma de tutoria
inteligente com 3 agentes de IA. Prazo final: 12/11/2026. Feature freeze do
MVP: 22/10/2026. Estou construindo aqui, sozinho, um protótipo integrado
(fatia vertical) que depois alimenta o repositório oficial do time.

Dono deste repositório: Adriano (A3, infraestrutura e integração).
Idioma de código, comentários, docstrings e commits: português.

## Requisitos não negociáveis (TAP)

- R07: toda inferência roda localmente (Qwen via Ollama). NUNCA chamar API
  externa de LLM, nem em desenvolvimento.
- R03: respostas do Tutor citam a fonte do material usado (RAG).
- R09: resposta de uma interação em até 15 segundos. Usar `/nothink` e
  modelos pequenos (qwen3:1.7b em máquina sem GPU).
- R08: LGPD. `aluno_id` é código, nunca nome. Nenhum dado pessoal em log.

## Stack

Python 3.12, FastAPI, SQLite (`sqlite3` puro, sem ORM), Chroma (RAG),
Ollama (`qwen3:*` para chat, `nomic-embed-text` para embeddings).

## Estrutura

- `src/tia/core/`: llm_client (única porta para o LLM), database, config, schemas
- `src/tia/rag/`: ingest, retrieve, demo
- `src/tia/agentes/`: planejador (Agente 1), tutor (Agente 2), relatorio (Agente 3)
- `src/tia/orquestrador/`: orquestração dos agentes (EAP 1.3.5): fluxo, eventos, regras
- `src/tia/api/`: FastAPI e rotas
- `conteudo/`: dados pedagógicos em JSON (ementa, perfis, trilha, banco_itens, materiais)
- `src/tia/web/`: aplicação web standalone do aluno (`/app`) e painel do docente/instituição
  (`/app/painel`), em HTML/CSS/JS puros servidos pelo FastAPI. As pastas `web/` e `dashboard/` da raiz
  ficaram vazias. `src/tia/painel/`: consultas somente de leitura do painel. `plugin-ebaula/`: por último.
- `docs/`: referência, arquitetura, seguranca-lgpd, evidencias. `infra/`: scripts de ambiente.

## Quem faz o quê no projeto real

- Agentes (Pessoa 2) e conteúdo pedagógico (Pessoa 4) ainda não foram entregues.
  Aqui, qualquer dado ou lógica deles é PROVISÓRIO: marcar com `# PROVISÓRIO`
  e manter fácil de substituir.
- Minha frente: LLM local, RAG, API, web standalone, dashboard, plug-in, segurança/LGPD.

## Padrão de código (seguir sempre)

- Nomes em português (`buscar_contexto`, `trechos`), type hints simples.
- Todo módulo começa com docstring: o que faz, como rodar (`python -m tia...`), pré-requisitos.
- Configuração só em `core/config.py` via `os.getenv` com valor padrão.
- Chamadas ao Ollama só em `core/llm_client.py` (chat e embedding). Com timeout e `raise_for_status()`.
- `/nothink` é acrescentado automaticamente no llm_client quando `think=False`.
- Módulos executáveis têm bloco `if __name__ == "__main__":`.

## Migração inicial (primeira tarefa)

O código já validado está em `~/ipe_project/pacote_1.4.2_rag` (app/llm_client.py,
app/database.py, app/main.py, app/models/schemas.py, app/rag/*, tests/, data/materiais/).
Copie para a nova estrutura adaptando imports (`app.` vira `tia.`):
`llm_client`, `database`, `schemas` para `core/`; `rag/*` para `rag/`; `main.py` para `api/`;
material de exemplo para `conteudo/materiais/`. Leia os arquivos de origem antes e
preserve as correções já feitas (gerar_embedding unificado no llm_client, /nothink
automático, load_dotenv). Não reescreva do zero.

## Ambiente da minha máquina

Ubuntu 24.04 com ROS 2 Jazzy, que quebra o autoload de plugins do pytest.
Rodar testes com `./run_tests.sh` (usa `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest`).
Sempre ativar o venv da raiz: `source venv/bin/activate`.

## Pendências conhecidas

- Pacote 1.4.6 (segurança/LGPD) não iniciado: documentos vão em `docs/seguranca-lgpd/`.
- Material real do curso depende da Pessoa 4.
- VM institucional ainda não disponível; testes feitos em notebook e em máquina com RTX 3050.

## Desempenho (decisão de 10/10)

- Não otimizar para o limite de 15 s (R09) durante o desenvolvimento: o LLM de produção roda
  em máquina mais potente que a de desenvolvimento. Priorizar qualidade da resposta.
- Todo timeout de chamada ao LLM fica em core/config.py (lido do .env), nunca fixo no código.
  Em desenvolvimento usar valores altos (ex.: 120 s). O R09 será medido na VM.
- Mesmo assim, toda demonstração imprime o tempo gasto, para termos o número quando a VM chegar.
