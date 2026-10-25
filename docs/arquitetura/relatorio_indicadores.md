# Agente 3 (Relatório): indicadores — EAP 1.3.4

> **Status: validado pela Pessoa 4 (conteúdo pedagógico) em 19/10/2026.** Definições, fórmulas e limiares
> foram propostos pela frente A3 (infraestrutura e integração) em 10/10/2026, para a fatia vertical.

Código: `src/tia/agentes/relatorio/` (cálculo em `indicadores.py`). API: `GET /relatorio/aluno/{aluno_id}`
e `GET /relatorio/turma[?perfil_id=]`. Demonstração: `python -m tia.agentes.relatorio --demo`.

## Princípios

- **Os indicadores são calculados por código**, de forma determinística (mesmos dados e mesmo "agora",
  mesmo resultado). O LLM não calcula nada.
- **O LLM local (R07) só redige** um parágrafo de interpretação a partir de um resumo com os números já
  calculados. A guarda de saída descarta texto com número que não está no resumo, com referência ao
  prompt ou com contradição interna. Nesses casos, e com o LLM fora do ar, vai um texto fixo. O
  relatório fica completo sem LLM (`?narrativa=false` pula o LLM).
- **Auditoria (R11):** toda geração grava uma linha em `auditoria` (`relatorio_aluno`, com o código do
  aluno; `relatorio_turma`, sem aluno, com o perfil filtrado em `referencia_id`).
- **LGPD (R08):** o relatório da turma só traz agregados. Grupos com menos de `RELATORIO_MIN_GRUPO` alunos
  (padrão 5) são suprimidos, e contagens de alunos abaixo disso saem como "menos de 5". Nenhum nome nem
  código de aluno aparece, nem é enviado ao LLM. O relatório não lê o texto livre do diálogo.

## Os 5 indicadores

| # | Indicador | Definição | Fórmula | Fonte de dados | Status |
|---|---|---|---|---|---|
| 1 | Progresso na trilha | Quanto da trilha do Planejador o aluno concluiu e em que nível está em cada competência | `% = etapas concluídas / etapas da trilha`. Etapa concluída = há sessão do questionário concluída na competência. Nível atual = `nivel` da sessão mais recente da competência | `trilha_estudo` (Agente 1), `tutor_sessoes` | Validado |
| 2 | Desempenho | Taxa de acerto por competência e por nível, com tendência | `taxa = acertos / respostas`. Tendência (`base: "sessao"`): taxa na **última sessão** (a da resposta mais recente) − taxa nas outras sessões, só entre respostas com `sessao_id`; exige 2 sessões ou mais e 3 respostas de cada lado. Senão (respostas antigas sem `sessao_id`, sessão recém-aberta), fallback (`base: "janela"`): últimas 5 respostas − anteriores. ≥ +15 pontos = subindo, ≤ −15 = caindo, senão estável; menos de 3 respostas em um dos lados = insuficiente | `historico_respostas` (`topico`, `nivel`, `acertou`, `timestamp`, `sessao_id`) | Validado |
| 3 | Engajamento | Sessões, dias ativos e dias de inatividade | sessões = linhas em `tutor_sessoes`; dias ativos = datas distintas com resposta, sessão ou pergunta no diálogo; dias de inatividade = dias inteiros desde a última ação (sem ação: desde a criação da trilha); inativo se ≥ `INATIVIDADE_DIAS` (3) | `tutor_sessoes`, `historico_respostas`, `tutor_dialogo`, `trilha_estudo` | Validado |
| 4 | Pontos fracos recorrentes | Competências e itens com erro repetido, e quanto o aluno pediu explicação nelas | **Competência** (todas as respostas, com ou sem `item_id`): ≥ 2 erros **e** taxa de erro ≥ 50%; também a maior sequência de erros seguidos e o nº de perguntas no diálogo na competência (aproximação de "uso de explicação"). **Item** (`itens_fracos`, só respostas com `item_id`): mesmos limiares por item | `historico_respostas` (`item_id`), `tutor_dialogo` (`competencia_id`) | Validado |
| 5 | Qualidade do feedback | Quanto do feedback veio do LLM, foi barrado pela guarda ou caiu no fallback, e quanto o docente vetou | `taxa(origem) = respostas com a origem / respostas com origem registrada` (item + diálogo); `taxa de veto = diálogos vetados / diálogos` | `auditoria` (origem de cada resposta de item, por `referencia_id`), `tutor_dialogo` (`origem`, `vetada`) | Validado |

### Turma / instituição (agregado)

- **Grupo:** a instituição inteira, ou um perfil (`?perfil_id=`, o perfil da trilha), porque **não existe
  turma no banco**.
- **Supressão:** grupo inteiro com menos de N alunos aparece só com a contagem ("menos de 5").
  Uma taxa por competência ou por nível só aparece se pelo menos N alunos responderam.
- **Indicadores agregados:** progresso médio, acerto agregado por competência e por nível, médias de
  engajamento, número de alunos com cada ponto fraco e qualidade do feedback do grupo.
- **Itens com erro repetido:** só entram itens respondidos por pelo menos N alunos. Mostram quantos alunos
  erraram (abaixo de N, "menos de 5") e o erro agregado.
- **Alertas de risco** (contagens, nunca alunos):
  - inatividade (≥ `INATIVIDADE_DIAS`);
  - desempenho em queda (tendência "caindo");
  - competência com acerto agregado abaixo de 50%.

## Dados que faltam (nada foi inventado)

| Indicador afetado | Falta | Hoje | Proposta (só ADD COLUMN, sem apagar dados) |
|---|---|---|---|
| 4 (uso de dica) | Não existe recurso de dica, e a leitura da explicação não é registrada (o feedback sempre vem com ela) | Aproximação: perguntas no diálogo na competência | Quando houver dica: `ALTER TABLE historico_respostas ADD COLUMN pediu_dica INTEGER` |
| Turma | Turma do aluno | Instituição inteira ou perfil | `ALTER TABLE alunos ADD COLUMN turma_id TEXT` |
| 5 (respostas antigas) | Origem das respostas gravadas antes da auditoria | Contadas em "sem registro" | Opcional: `ALTER TABLE historico_respostas ADD COLUMN origem TEXT`, para não depender do JOIN com a auditoria |

**Resolvido em 10/10:** `historico_respostas.item_id` e `historico_respostas.sessao_id` (ADD COLUMN,
nuláveis). O Tutor grava os dois em toda resposta. As respostas anteriores ficam com NULL e seguem
pelos caminhos antigos: só por competência no indicador 4, janela de respostas no indicador 2.
Detalhes em `docs/relatorios/colunas_item_sessao.md`.

## Limitações conhecidas

- **A guarda da narrativa confere se cada número existe nos indicadores, não se está no lugar certo.**
  "Você concluiu 2 de 6 etapas" passa se "2" aparece em outro ponto do resumo (ex.: "2 dias desde a
  última atividade"). Há teste documentando isso.
- **"Etapa concluída" usa a sessão concluída do questionário** (mesmo critério do incentivo do Tutor),
  até haver critério oficial.

## Perguntas para a Pessoa 4

1. Uma etapa da trilha deve contar como concluída quando o aluno conclui uma sessão do questionário na
   competência (2 acertos seguidos no nível 3), ou há outro critério (nota mínima, todas as atividades)?
2. A tendência compara a última sessão com as anteriores. Isso basta, ou deve comparar mais de uma
   sessão recente? Qual variação conta como queda (hoje: 15 pontos percentuais)?
3. "Ponto fraco recorrente": ≥ 2 erros e ≥ 50% de erro serve, por competência e por item? Como o
   questionário não repete item na mesma sessão, o erro repetido por item só aparece entre sessões.
   Isso faz sentido pedagogicamente?
4. Haverá recurso de dica? Se sim, como registrar o uso (para o indicador 4)?
5. Qual nível de inatividade justifica alerta para o docente (hoje: 3 dias, o mesmo do incentivo)?
6. O grupo mínimo de 5 alunos para o relatório agregado está adequado para as turmas do piloto (30 alunos)?
7. O relatório da instituição deve ser por turma? Se sim, de onde vem a turma do aluno?
8. Que indicadores o aluno deve ver no próprio relatório (hoje: os 5, com o 5 em linguagem simples)?
