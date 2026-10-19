# Orquestração (EAP 1.3.5) e diagrama de arquitetura (1.3.1): resumo (10/10/2026)

> **Atualizado:** as regras R2 e R3, a abertura de sessão e o replanejamento mudaram depois deste
> resumo. Ver `docs/relatorios/orquestracao_pendencias.md` e a seção "Decisões de orquestração" de
> `docs/arquitetura/arquitetura.md`. Este arquivo fica como histórico.

Sem commit. Detalhes de arquitetura, regras e limitações em `docs/arquitetura/arquitetura.md`.

## Arquivos

**Novos:**

| Arquivo | Conteúdo |
|---|---|
| `src/tia/orquestrador/__init__.py` | Pontos de entrada: `iniciar`, `estado`, `proxima`, `processar_evento` |
| `src/tia/orquestrador/modelos.py` | Contratos Pydantic: `Matricula`, `EventoTutor`, `DecisaoReplanejamento`, `EstadoAluno`, `ProximaAcao`, `ResultadoMatricula`, `ResultadoEvento` |
| `src/tia/orquestrador/regras.py` | TODAS as regras de replanejamento (funções puras) |
| `src/tia/orquestrador/fluxo.py` | Matrícula, estado, próxima ação e replanejamento pelo Planejador |
| `src/tia/orquestrador/eventos.py` | Eventos do Tutor com idempotência por `evento_id` |
| `src/tia/orquestrador/repositorio.py` | Matrícula, eventos e decisões, com auditoria na mesma transação |
| `src/tia/orquestrador/__main__.py` | Demonstração (`--demo [--sem-llm]`) |
| `src/tia/api/rotas_orquestrador.py` | As 4 rotas `/aluno/{id}/...` |
| `tests/test_orquestrador.py` | 28 testes |
| `docs/arquitetura/arquitetura.md` | Diagrama Mermaid, fluxo de dados, regras, real x não existe |

**Alterados:**

- `core/config.py`, `.env.example`: limiares da tendência e da orquestração.
- `core/database.py`: 3 tabelas novas e `auditoria.motivo`.
- `core/auditoria.py`: tipo `decisao_orquestrador` e o campo `motivo`.
- `tutor/modelos.py`: `RegistroAuditoria` com o tipo novo e `motivo`.
- `tutor/repositorio.py`: `sessao_aberta`.
- `tutor/__init__.py`: `pergunta_atual`, para continuar uma sessão.
- `relatorio/indicadores.py`: limiares da tendência lidos da config.
- `api/main.py`: registro das rotas.

## Regras de replanejamento e limiares (validados pela Pessoa 4)

| Regra | Gatilho | Ação | Limiares |
|---|---|---|---|
| R1 conclusão | Sessão do Tutor concluída na competência, ainda não tratada | `avancar` | Critério de conclusão do Tutor |
| R2 queda | Tendência do Relatório "caindo"; uma vez por sessão; intervalo mínimo de respostas | `reforcar` (pré-requisitos dispensados voltam) | `RELATORIO_TENDENCIA_LIMIAR=0.15`, `RELATORIO_TENDENCIA_MIN_RESPOSTAS=3`, `RELATORIO_TENDENCIA_JANELA=5`, `ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS=5`, `ORQ_NOTA_PREREQ_REFORCO=0.0` |
| R3 inatividade | Engajamento do Relatório inativo, ainda não tratado depois da última atividade | `retomar` | `INATIVIDADE_DIAS=3` |

## Testes

`./run_tests.sh`: **323 passed, 9 xfailed**. As 9 falhas esperadas são do portão do diálogo, já
documentadas. Os testes novos cobrem:

- fluxo completo, da matrícula ao relatório;
- replanejamento por conclusão, por queda (com o pré-requisito voltando) e por inatividade;
- queda uma vez por sessão;
- idempotência, e reenvio depois de falha;
- aluno inexistente e validações;
- auditoria de cada decisão;
- veto docente pelo fluxo;
- todas as regras puras.

## Tempo da demonstração

- `--sem-llm`: cerca de 0,6 s no total (18 respostas, 7 decisões, relatórios).
- Com LLM (qwen3:1.7b em CPU, notebook): **752,8 s no total**.

| Etapa | Tempo com LLM |
|---|---|
| Matrícula | 12,1 s |
| Acertos (4 respostas) | 137,0 s |
| Queda (3 respostas) | 109,3 s |
| Inatividade | 12,1 s |
| Retomada (11 respostas) | 457,1 s |
| Relatórios | 25,2 s |

- **Feedback do Tutor:** 25 a 50 s por resposta.
- **Planejamento:** a matrícula e cada replanejamento levam cerca de 12 s, que é exatamente o
  `PLANEJADOR_TIMEOUT_LLM`. É provável que as justificativas do LLM tenham estourado o tempo e usado o
  texto padrão (o log da demonstração não mostra avisos).
- **Fluxo:** os eventos, as decisões e o resultado final foram iguais aos da rodada `--sem-llm`.

**Atualização:** a causa dos ~12 s fixos foi confirmada como timeout do Planejador. O padrão passou para
120 s, e os tempos novos estão em `docs/relatorios/orquestracao_tempos.md`.

## O que ficou sem resolver

1. **O Planejador não recebe etapas concluídas:** replanejar refaz a trilha do zero, e a R1 hoje não
   muda as etapas.
2. **A abertura de sessão não passa pelo orquestrador** (`/tutor/sessao`). Nada impede abrir sessão
   fora da competência atual.
3. **Sessão abandonada:** quando a R2 traz um pré-requisito antes, a sessão em andamento fica aberta e
   é retomada depois.
4. **Sem agendador:** a inatividade só é avaliada por evento ou consulta.
5. **Sem autenticação** (1.4.6) nas rotas do orquestrador.
6. **Pacote vazio:** `src/tia/agentes/orquestracao/` ficou vazio (o pedido foi `src/tia/orquestrador/`).
   Sugiro removê-lo e atualizar a seção "Estrutura" do CLAUDE.md.

## Perguntas para a Pessoa 2 (agentes)

1. O Planejador deve aceitar as etapas concluídas, para replanejar só o restante (semanas a partir de
   hoje, sem perder o histórico)?
2. Ao detectar queda, além de trazer de volta o pré-requisito dispensado, o Tutor deve reiniciar a
   competência no nível 1 ou encerrar a sessão em andamento?
3. A abertura de sessão deve passar pelo orquestrador, que garante a competência atual?
4. Quem dispara a verificação de inatividade em produção (agendador na VM, ou o login do aluno)?

## Perguntas para a Pessoa 4 (pedagogia)

1. Concluir uma sessão do questionário (2 acertos seguidos no nível 3) basta para considerar a
   competência concluída e seguir a trilha?
2. Queda: 15 pontos entre a última sessão e as anteriores, com pelo menos 3 respostas de cada lado,
   é um bom gatilho? Reforçar trazendo o pré-requisito direto faz sentido?
3. Inatividade: após 3 dias, a trilha deve ser refeita a partir de hoje, ou só o incentivo basta?
