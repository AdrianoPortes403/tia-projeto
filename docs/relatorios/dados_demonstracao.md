# Dados de demonstração do painel do docente (01/11/2026)

> Frente A3, branch `redesign-interface`. Amplia a turma fictícia de `python -m tia.web.dados_painel` para o
> painel mostrar vários casos e estatísticas sem grupo oculto. **Só dados fictícios**: códigos `DEMO-Pnn`, nunca
> nomes (R08), textos do tutor marcados "[demonstração]" e a senha fictícia de demonstração. Regras, rotas e telas
> não mudaram. Sem commit.

## Como recriar o banco de demonstração

A partir da raiz, com o venv ativo e a API parada:

```bash
mv data/tia.db data/tia.db.bak && python -m tia.web.dados_demo && python -m tia.web.dados_painel
uvicorn tia.api.main:app --reload    # painel: http://localhost:8000/app/painel/ ; aluno: http://localhost:8000/app/
```

- O `mv` **sobrescreve** um `data/tia.db.bak` que já exista. Se ele importa, renomeie antes.
- Tudo que só existia no banco antigo fica no `.bak` e some do novo: usuários criados à mão (A2026-R01, A2026-R02),
  vetos e aprovações feitos pela tela, respostas do DEMO-W01 e a auditoria.
- Os dois comandos levam poucos segundos e **não** chamam o Ollama. O Tutor e os agentes usam os textos fixos.
- Rodar de novo num banco que já tem os alunos não duplica nada: cada aluno existente é mantido como está.

Para entrar (senha fictícia `FICTICIA-demo-2026`, impressa pelos comandos): `DEMO-DOCENTE` no painel;
`DEMO-W01`, `DEMO-W02` e `DEMO-W03` na aplicação do aluno.

## O que o carregador cria agora

`python -m tia.web.dados_painel` roda `criar_turma_ampliada()`. São os 12 alunos de antes (DEMO-P01..P12, a
turma-base dos testes, sem mudança) mais 14 novos (DEMO-P13..P26), num total de **26 alunos**. Com os 3 do
`dados_demo` (DEMO-W01..W03, intermediários), o painel mostra **29**.

| Perfil | Alunos | Grupo mínimo (5) |
|---|---|---|
| Iniciante | 10 (P09..P18) | visível |
| Intermediário | 19 (P01..P08, P19..P26 e W01..W03) | visível |

**Sobre o "perfil com poucos alunos":** `conteudo/perfis/perfis.json` só tem esses 2 perfis, e o conteúdo não se
edita sem a Pessoa 4 ou o Tiago. Decisão de 01/11: deixar os dois perfis visíveis. A regra do grupo mínimo continua
visível em **Recursão** (3 alunos, oculta em Competências) e nas contagens "menos de 5" (por exemplo, alunos com
erro na questão `variaveis_tipos_n1a` e o alerta "concluída com ressalvas" do relatório). A turma-base sozinha
(`criar_turma()`) ainda tem o iniciante com 4 alunos, oculto.

### Situações (tabela da Visão geral; uma por aluno, a mais urgente)

| Situação | Alunos |
|---|---|
| No ritmo | P01, P07, P09, P10 (recém-matriculado, sem respostas), P12, P13, P15, P21, P22 (acerto subindo), W01, W02 |
| Queda de desempenho | P03, P08, P18, P20, P24, P25, W03 |
| Desempenho baixo | P06 |
| Concluída com ressalvas (sem acerto para avançar, recomeça a competência) | P16 (e, como motivo extra, P06 e P25) |
| Inativo (3 dias ou mais) | P26 (3), P14 (4), P11 (5), P04 (9), P23 (18), P05 e P17 (20) |
| Trilha concluída | P02, P19 |
| **Reforço em andamento** | **P20**: pelo fluxo real do orquestrador, como o DEMO-W03. Concluiu Funções, errou 2 em Listas e strings e tem a revisão de Repetição pendente. No painel aparece como "Queda" (o motivo do reforço). O reforço em si aparece na auditoria do aluno e na aplicação do aluno |

A verificação de inatividade (R3) roda no fim e grava 4 incentivos e 4 trilhas refeitas (7 dias ou mais sem
atividade).

### Estatísticas que aparecem

- **Questões com erro repetido** em 3 competências: `funcoes_n2a` (52%, 11 alunos), `listas_strings_n2a` e
  `listas_strings_n2b` (50%), `variaveis_tipos_n1a` (50%, alunos com erro: "menos de 5").
- **Competências**: acerto entre 73% e 82% em Variáveis, Condicionais, Repetição, Funções e Listas; Recursão oculta.
- **Desempenho por nível**: níveis 1, 2 e 3 com dados. **Progresso médio**: 28% na instituição, 20% no
  iniciante, 32% no intermediário.
- **Revisão**: cerca de 30 respostas do diálogo (28 a revisar, 2 já vetadas) e mais de 200 feedbacks de origem
  LLM a revisar. Dá para usar a paginação (10 por página) e os filtros de tipo, origem (LLM, guarda, fallback)
  e competência. As respostas do diálogo vêm de 22 textos de exemplo. Alguns estão **errados de propósito**
  para o docente vetar: "parâmetro e argumento são a mesma coisa", "todo if precisa de um else", "strings podem
  ser alteradas".
- **Datas**: matrículas de 4 a 35 dias atrás e sessões espalhadas pelas últimas 4 semanas (indicadores de
  tendência, engajamento e inatividade).

## Como está no código (`src/tia/web/dados_painel.py`)

| Nome | O que é |
|---|---|
| `ALUNOS` | a turma-base (12), **inalterada**: os testes de painel, correções, feedback revisável e LGPD conferem estes números |
| `ALUNOS_AMPLIACAO` | os 13 alunos sintéticos novos (P13..P19, P21..P26), no mesmo formato |
| `ALUNO_REFORCO` | DEMO-P20, criado pelo fluxo real (`criar_reforco`, que usa o `estudar` do `dados_demo`) |
| `DIALOGOS` | 9 textos antigos (mesmos índices) + 13 novos |
| `criar_turma(agora, semente, alunos, reforco)` | o padrão continua sendo só a base |
| `criar_turma_ampliada()` | base + ampliação + reforço; é o que o comando roda |

Teste novo: `tests/test_painel.py::test_turma_ampliada_para_demonstracao` confere 20 alunos ou mais, os dois perfis
visíveis, as seis situações, o reforço do P20, erro repetido em 2 competências ou mais, uma competência oculta, a
fila do diálogo com mais de 2 páginas, as três origens e matrículas espalhadas por 30 dias ou mais.
`test_dados_painel_sem_nomes` passou a conferir também os códigos da ampliação.
