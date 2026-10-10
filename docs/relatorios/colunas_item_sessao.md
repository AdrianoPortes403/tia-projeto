# Colunas `item_id` e `sessao_id` em `historico_respostas` (10/10/2026)

Pedido: gravar o item e a sessão de cada resposta do questionário do Tutor, para o Agente 3
(Relatório) calcular pontos fracos por item e tendência por sessão. Não houve commit.

## O que mudou

| Onde | Mudança |
|---|---|
| `src/tia/core/database.py` | `COLUNAS_NOVAS_HISTORICO` ganhou `item_id TEXT` e `sessao_id TEXT`, migradas por `ADD COLUMN` (nuláveis) em `criar_tabelas()`. A migração é idempotente e não apaga dados |
| `src/tia/agentes/tutor/repositorio.py` | `registrar_resposta` grava `item_id` (id do item respondido) e `sessao_id` em toda resposta, na mesma transação de antes |
| `src/tia/agentes/relatorio/repositorio.py` | Lê as duas colunas |
| `src/tia/agentes/relatorio/indicadores.py` | Indicador 2: `tendencia` compara a **última sessão** com as anteriores (`base: "sessao"`). Sem `sessao_id`, ou sem dado suficiente, cai na janela de 5 respostas (`base: "janela"`). Indicador 4: novo `itens_fracos` (por item, só respostas com `item_id`); por competência continua igual, com todas as respostas. Na turma, `itens_fracos` agregado, só com itens respondidos por pelo menos N alunos |
| `src/tia/agentes/relatorio/modelos.py` | `Tendencia.base`, `ItemFraco`, `RelatorioAluno.itens_fracos`, `RelatorioTurma.itens_fracos` |
| `src/tia/agentes/relatorio/narrativa.py` | Texto: "na última sessão" ou "nas últimas N respostas", e a lista de itens |
| `src/tia/agentes/relatorio/__main__.py` | A demonstração grava as duas colunas, menos para o DEMO-R06, que simula respostas antigas (NULL) |
| `docs/arquitetura/relatorio_indicadores.md` | Indicadores 2 e 4, tabela de dados faltantes e perguntas para a Pessoa 4 |

## Respostas antigas

Ficam com `item_id` e `sessao_id` NULL:
- **Indicador 4:** continuam contando por competência e não aparecem em `itens_fracos`.
- **Indicador 2:** se o aluno não tem pelo menos 2 sessões identificadas com 3 respostas de cada lado,
  a tendência usa a janela de respostas.

Conferido numa **cópia** de `data/tia.db`: 36 linhas antes, 36 depois, colunas novas em NULL.

## Decisões

- **Competência usa todas as respostas** (com e sem `item_id`). O detalhe por item é um campo à
  parte (`itens_fracos`), para não perder o histórico antigo no agrupamento por competência.
- **Última sessão** = a sessão da resposta mais recente. "Anteriores" = respostas de todas as outras
  sessões identificadas. Respostas sem `sessao_id` ficam fora da comparação por sessão.
- **Sessão recém-aberta** (menos de 3 respostas) volta para a janela, para o aluno não ficar sem
  tendência logo no começo de uma sessão.
- **Por item, na turma,** só entram itens respondidos por pelo menos `RELATORIO_MIN_GRUPO` alunos (R08).
- **Erro repetido por item só aparece entre sessões:** o questionário não repete item na mesma sessão.
  A pergunta está registrada para a Pessoa 4.

## Testes

`./run_tests.sh`: **295 passed, 9 xfailed** (as 9 falhas esperadas são do portão do diálogo, já
documentadas). Testes novos:

- **Migração em banco existente** (`tests/test_tutor.py`): a linha antiga é preservada, com as
  colunas novas em NULL.
- **Gravação pelo Tutor** (`tests/test_api_tutor.py`): duas respostas pela API gravam o item de cada
  pergunta e o id da sessão.
- **Indicadores** (`tests/test_relatorio.py`):
  - tendência por sessão, ignorando as respostas antigas sem sessão;
  - fallback para a janela (sessão recém-aberta ou sessão única);
  - itens fracos só com `item_id`, e a competência contando tudo;
  - item da turma respeitando o grupo mínimo;
  - relatório de aluno com dados antigos (DEMO-R06) e com item errado em duas sessões.
