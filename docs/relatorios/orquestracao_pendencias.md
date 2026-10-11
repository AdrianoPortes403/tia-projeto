# Pendências da Orquestração fechadas (EAP 1.3.5), 10/10/2026

Sem commit. Decisões registradas em `docs/arquitetura/arquitetura.md`, seção "Decisões de orquestração".
Ponto de partida: árvore limpa (último commit `ceca042`), **327 passed, 9 xfailed**.

## Itens

| # | Item | Situação |
|---|---|---|
| 0 | Tempo do Planejador (~12 s fixos) | **Já feito** no commit `ceca042` (timeout 120 s, origem e falha visíveis, tempos por agente). Pulado |
| 1 | Replanejamento incremental | Feito: `EntradaPlanejador.concluidas`. As concluídas ficam na trilha marcadas `concluida` e nunca voltam a ficar pendentes. Só o que falta é agendado. A R1 e o refazer da R3 usam isso |
| 2 | Abertura de sessão pelo orquestrador | Feito: `POST /aluno/{id}/sessao`. Só abre a competência atual ou o reforço; o resto é recusado (409) e auditado. `/tutor/sessao` documentada como standalone |
| 3 | Sessão pausada | Feito: `tutor_sessoes.pausada` (ADD COLUMN) e a tabela `orquestrador_reforcos`. A sessão pausada recusa resposta. Ao concluir o reforço, ela é retomada no mesmo nível e item |
| 4 | Verificação de inatividade | Feito: `python -m tia.orquestrador --verificar-inatividade` e `POST /orquestrador/verificar-inatividade`. Sem agendador |
| 5 | R3: incentivo x refazer | Feito: `incentivar` a partir de 3 dias; `refazer_trilha` a partir de `ORQ_INATIVIDADE_REFAZER_DIAS` (14) |
| 6 | Limpeza | Feito: `src/tia/agentes/orquestracao/` removido; "Estrutura" do CLAUDE.md atualizada |
| 7 | Autenticação | Adiada (1.4.6). TODO mantido e lista de rotas na documentação |

## Arquivos alterados

- **Config e banco:**
  - `core/config.py`, `.env.example`: entra `ORQ_INATIVIDADE_REFAZER_DIAS=14`; sai
    `ORQ_NOTA_PREREQ_REFORCO`, porque o reforço não mexe mais no diagnóstico.
  - `core/database.py`: `tutor_sessoes.pausada`, `trilha_estudo.concluida`, `orquestrador_decisoes.aviso`
    e a tabela `orquestrador_reforcos`.
- **Planejador:**
  - `modelos.py`: `EntradaPlanejador.concluidas` e `EtapaTrilha.concluida`.
  - `planejar.py`: planeja só o que falta.
  - `justificar.py`: o LLM só justifica o que falta.
  - `repositorio.py`: grava e lê `concluida`.
- **Tutor:**
  - `repositorio.py`: `pausar_sessao`, `retomar_sessao`, `sessao_pausada`. `sessao_aberta` ignora as
    pausadas, e uma sessão pausada não grava resposta.
  - `__init__.py`: `responder` e `pergunta_atual` recusam sessão pausada.
  - `incentivo.py`: etapa marcada `concluida` não conta como pendente.
- **Relatório:** `indicadores.py`: etapa marcada `concluida` conta no progresso.
- **Orquestrador:**
  - `modelos.py`: novas ações e regras, `Reforco`, `PedidoSessao`, `SessaoOrquestrada`,
    `ResultadoVerificacao`, `aviso` e `avisos`.
  - `regras.py`: reescrito.
  - `fluxo.py`: reescrito (`aplicar`, `abrir_sessao`, `concluir_reforco`, `verificar_inatividade`).
  - `eventos.py`: conclusão do reforço e nova R2.
  - `repositorio.py`: reforços, lista de matrículas e aviso.
  - `__main__.py`: demonstração nova e `--verificar-inatividade`.
  - `__init__.py`.
- **API:**
  - `rotas_orquestrador.py`: `/aluno/{id}/sessao` e `/orquestrador/verificar-inatividade`.
  - `main.py`.
  - `rotas_tutor.py`: documentação de `/tutor/sessao` como standalone.
- **Documentação:** `CLAUDE.md` (Estrutura) e `docs/arquitetura/arquitetura.md`.
- **Removido:** `src/tia/agentes/orquestracao/__init__.py`, um pacote vazio que nada importava.
- **Testes:**
  - `tests/test_planejador.py`: 7 novos (incremental).
  - `tests/test_orquestrador.py`: reescrito, com 43 testes.

## Regras e limiares

| Regra | Ação | Limiares (`core/config.py`) | Status |
|---|---|---|---|
| R1 conclusão | `avancar` (Planejador incremental + aviso) | critério de conclusão do Tutor | **PROVISÓRIO** (D5, Pessoa 4) |
| R2 queda | `reforcar` (pausa + reforço do pré-requisito direto no nível 1) | `RELATORIO_TENDENCIA_LIMIAR=0.15`, `RELATORIO_TENDENCIA_MIN_RESPOSTAS=3`, `RELATORIO_TENDENCIA_JANELA=5`, `ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS=5` | **PROVISÓRIO** (D6, Pessoa 4) |
| Fim do reforço | `retomar_original` (mesmo nível) | - | Decidido (D2, Pessoa 2) |
| R3 inatividade | `incentivar` / `refazer_trilha` | `INATIVIDADE_DIAS=3`, `ORQ_INATIVIDADE_REFAZER_DIAS=14` | **PROVISÓRIO** (D7, Pessoa 4) |

## Testes

`./run_tests.sh`: **350 passed, 9 xfailed**. As 9 falhas esperadas são do portão do diálogo, já
conhecidas.

**Novos:**
- **Planejador:** trilha reduzida; concluída nunca volta, com 4 combinações; concluída conta como
  pré-requisito; concluída dispensável; concluída fora da ementa; LLM só para o que falta.
- **Orquestrador (R1):** replaneja só o que falta e avisa; um replanejamento não traz de volta uma
  concluída.
- **Abertura de sessão:**
  - só a competência atual; a recusa é auditada;
  - sessão duplicada recusada;
  - trilha concluída recusa sessão;
  - `/tutor/sessao` continua standalone.
- **Ciclo completo da queda:**
  - pausa: a sessão guarda nível e item e recusa resposta;
  - reforço: só o pré-requisito pode ser aberto, no nível 1;
  - retomada: mesmo nível, mesmo item e itens usados;
  - sem novo reforço pela mesma queda.
- **R3:** 2 dias e 23 h não faz nada; de 3 a 13 dias só incentivo, sem acionar o Planejador; 13 dias
  e 23 h incentiva, 14 dias refaz, uma vez; aluno que volta e some de novo recebe novo incentivo; a
  rota percorre todos os alunos.
- **Regras puras:** queda (8 casos), inatividade (9 casos, nos dois lados dos limiares),
  pré-requisito direto e prioridade da próxima ação com reforço.

## Tempos da demonstração

### `--sem-llm`

| Etapa | Total | Tutor | Planejador | Relatório | Resto |
|---|---|---|---|---|---|
| Matrícula | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| Acertos | 0,3 | 0,2 | 0,0 | 0,0 | 0,1 |
| Queda | 0,1 | 0,0 | 0,0 | 0,0 | 0,1 |
| Reforço e retomada | 0,2 | 0,0 | 0,0 | 0,0 | 0,1 |
| Inatividade (3 verificações) | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| Fim | 0,1 | 0,0 | 0,0 | 0,0 | 0,1 |
| Relatórios | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| **Total** | **0,7** | 0,2 | 0,0 | 0,0 | 0,4 |

### Com LLM (qwen3:1.7b em CPU, notebook)

| Etapa | Total | Tutor | Planejador | Relatório | Resto |
|---|---|---|---|---|---|
| Matrícula | 22,6 | 0,0 | 22,5 | 0,0 | 0,0 |
| Acertos (4 respostas + R1) | 150,8 | 137,8 | 12,8 | 0,0 | 0,3 |
| Queda (3 respostas + R2, sem Planejador) | 105,8 | 105,6 | 0,0 | 0,0 | 0,2 |
| Reforço e retomada (4 + 4 respostas + R1) | 316,2 | 302,4 | 13,4 | 0,0 | 0,4 |
| Inatividade (incentivo, nada, refazer) | 10,8 | 0,0 | 10,7 | 0,0 | 0,1 |
| Fim (4 respostas + R1) | 126,4 | 126,1 | 0,0 | 0,0 | 0,3 |
| Relatórios | 24,8 | 0,0 | 0,0 | 24,8 | 0,0 |
| **Total** | **757,5** | **671,9** (89%) | **59,4** (8%) | **24,8** (3%) | **1,4** |

- **Origem:** 18 de 18 feedbacks vieram do LLM; as justificativas das 4 chamadas do Planejador que tinham
  etapas a justificar vieram do LLM; a interpretação do relatório também.
- **Fallbacks:** nenhum por timeout.
- **Última conclusão:** não chamou o LLM (0,0 s), porque não sobrou etapa a justificar.
- **Planejador:** caiu de 150,1 s (demonstração anterior) para 59,4 s. A R2 não aciona mais o Planejador,
  a inatividade de 5 dias só incentiva, e o replanejamento incremental justifica menos etapas.
- **Total:** caiu de 840,5 s para 757,5 s, com mais respostas que antes (18, incluindo o reforço).
- **R09:** nenhuma interação com LLM cabe em 15 s nesta máquina. A medição vale na VM.

## O que ficou sem resolver

1. **Competência de reforço concluída entra na trilha** como etapa concluída: o progresso conta uma etapa
   a mais que a trilha original ("4 de 4" na demonstração). Falta decidir se o reforço deve contar.
2. **Reforço aberto por `/tutor/sessao`** (standalone) não é vinculado: o fluxo segue pedindo o reforço
   pela rota do orquestrador.
3. **Agendador:** fica para a VM, depois de 15/10. Até lá, a verificação de inatividade só roda manualmente.
4. **Autenticação:** pacote 1.4.6.
5. **Sessões abertas fora do fluxo:** a verificação de inatividade e o "proximo" não fecham nem pausam
   sessões antigas abertas por `/tutor/sessao`.

## Perguntas que ainda dependem da Pessoa 4

1. **D5:** concluir uma sessão do questionário (2 acertos seguidos no nível 3) basta para avançar? O
   texto do aviso de conclusão serve?
2. **D6:** reforçar só o pré-requisito direto é suficiente? O que fazer quando a competência não tem
   pré-requisito (hoje: não reforça)? O reforço concluído deve contar no progresso da trilha?
3. **R2 (limiares):** 15 pontos de queda entre a última sessão e as anteriores, com 3 respostas de cada
   lado e 5 respostas entre reforços, estão bons?
4. **D7:** 3 dias para o incentivo e 14 dias para refazer a trilha estão bons? O texto do incentivo serve?
