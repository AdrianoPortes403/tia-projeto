# Feedback revisável pelo docente (R12) e correção da R3

> Frente A3, 11/10/2026. Sem commit. Arquitetura: `docs/arquitetura/arquitetura.md`, seções "Feedback revisável
> (R12) e amostra para avaliação" e "Decisões de orquestração" (D7). Protocolo da avaliação:
> `docs/avaliacao/protocolo_amostra.md`.

## Resultado

- `./run_tests.sh`: **488 passados, 9 xfailed** (os 9 xfails conhecidos do portão do diálogo), 0 falhas. São
  24 testes novos: 23 em `tests/test_feedback_revisavel.py` e 1 caso de contrato em `tests/test_web.py`.
  Os testes da revisão em `tests/test_painel.py` foram adaptados ao novo formato.
- Conferido num Chrome headless (roteiro pelo DevTools Protocol, fora do repositório), com a turma fictícia:
  1. no painel, o filtro (feedback, guarda, Funções) mostrou a questão, o veredito, o texto que o aluno viu,
     o texto barrado pela guarda e o motivo;
  2. o feedback foi vetado pela tela e a taxa de vetos de feedback passou de 0 para 1 em 117;
  3. no app do aluno (DEMO-P08), "Meu relatório" mostrou a correção na seção "Correções do professor";
  4. um `<i>` na correção apareceu como texto (nenhuma tag criada);
  5. nenhuma exceção e nenhuma mensagem no console.
- Nenhum comando desta tarefa rodou contra `data/tia.db`: tudo foi feito em bancos temporários. A tabela
  nova é criada no banco real quando a API subir (`CREATE TABLE IF NOT EXISTS`).

## O que mudou, item por item

1. **Gravação do texto.** Tabela nova **`tutor_feedbacks`**, uma linha por resposta (`resposta_id` =
   `historico_respostas.id`), gravada na **mesma transação** da resposta e da auditoria. Guarda o aluno, a
   sessão, o item, a competência, o veredito, a explicação que o aluno viu, a origem, a falha do LLM, as
   fontes, o texto do LLM barrado pela guarda e o motivo, `vetada` e `correcao_docente`. Respostas
   anteriores não têm linha: não são revisáveis e aparecem contadas como "sem texto".
   `Feedback.resposta_id` (novo, opcional) devolve o id ao cliente.
2. **Veto do feedback.** `PATCH /tutor/feedback/{resposta_id}/veto`, com o mesmo corpo e as mesmas regras
   do diálogo (o veto exige a correção; `vetada: false` aprova ou retira o veto). O aluno passa a ver a
   correção em `GET /alunos/{id}/feedbacks` e em "Meu relatório" → "Correções do professor". Cada uso grava
   `veto_docente` na auditoria com a referência `feedback:<id>`. O veto do diálogo e o do feedback agora
   compartilham `repositorio._vetar`.
3. **Tela de revisão.** Uma lista única de feedbacks e respostas do diálogo, com o texto original, a questão
   (enunciado) ou a pergunta, o veredito, a origem, as fontes, o texto barrado pela guarda e a correção.
   Filtros: tipo, situação (a revisar, aprovada, vetada, todas), origem e competência. Resumo e taxa de veto
   separados por tipo. Todo texto entra por `textContent`.
4. **Amostra.** `python -m tia.painel.amostra --n 100 [--semente 2026] [--tipo] [--saida]`: só origem `LLM`,
   estratificada por competência (pelo menos 1 por competência e o resto proporcional, pelo método dos
   maiores restos), com semente fixa. Gera um CSV `;` com BOM, sem código de aluno, com as colunas vazias
   "adequado (S/N)" e "observacao". O arquivo vai para `data/avaliacao/` (fora do git) e a exportação é
   registrada na auditoria.
5. **R3.** `regra_inatividade(..., trilha_concluida=True)` devolve "nenhuma" ("Trilha concluída: sem
   incentivo nem replanejamento"). `fluxo.trilha_concluida` exige trilha, todas as etapas concluídas e
   nenhum reforço em curso. `EstadoAluno.inativo` fica `False` para quem concluiu, e `dias_inativo` continua
   sendo informado. Na turma fictícia, o DEMO-P02 (concluiu e está parado há 12 dias) não recebe mais
   incentivo; o DEMO-P04 e o DEMO-P11 continuam recebendo.
6. **Agente 3.** O indicador 5 ganhou `feedbacks_com_texto`, `feedbacks_vetados` e `taxa_veto_feedback`,
   lendo **só** a marca `vetada` de `tutor_feedbacks` (o texto nunca é lido). Aparece no painel (visão geral)
   e no CSV dos indicadores.

## Arquivos

| Arquivo | Mudança |
|---|---|
| `src/tia/core/database.py` | tabela `tutor_feedbacks` e índice por aluno |
| `src/tia/agentes/tutor/repositorio.py` | `registrar_resposta` grava o feedback e devolve o id; `_vetar` (comum), `vetar_feedback`, `listar_feedbacks`, `ler_feedback` |
| `src/tia/agentes/tutor/__init__.py` | `responder` passa o texto do feedback e devolve `resposta_id` |
| `src/tia/agentes/tutor/modelos.py` | `Feedback.resposta_id`, `ItemFeedback` |
| `src/tia/api/rotas_tutor.py` | `GET /alunos/{id}/feedbacks`, `PATCH /tutor/feedback/{id}/veto` |
| `src/tia/painel/modelos.py`, `consultas.py` | revisão unificada (`ItemRevisao`, `ResumoRevisao`); `auditar_consulta` e `celula` públicas; linha do veto de feedback no CSV |
| `src/tia/painel/amostra.py` | **novo**: comando da amostra |
| `src/tia/api/rotas_painel.py` | filtros `tipo` e `competencia_id` |
| `src/tia/agentes/relatorio/{modelos,repositorio,indicadores,narrativa}.py` | veto de feedback no indicador 5 |
| `src/tia/orquestrador/{regras,fluxo,modelos}.py` | R3 ignora quem concluiu a trilha |
| `src/tia/web/static/painel/*` | revisão com feedback, filtros novos, taxa de veto por tipo |
| `src/tia/web/static/{index.html,app.js,estilo.css}` | "Correções do professor" em "Meu relatório" |
| `src/tia/web/dados_painel.py` | grava o texto do feedback das respostas fictícias (guarda com texto descartado; fontes só na origem LLM, como no Tutor) |
| `tests/test_feedback_revisavel.py` (novo), `tests/test_painel.py`, `tests/test_web.py` | testes |
| `docs/avaliacao/protocolo_amostra.md` (novo), `docs/arquitetura/arquitetura.md` | documentação |

## Decisões

1. **Tabela nova em vez de ADD COLUMN** em `historico_respostas`. O Agente 3 e outras partes leem essa
   tabela; o texto separado (como `tutor_dialogo`) deixa claro onde está o texto livre e permite ao
   Relatório ler só `vetada` (LGPD, minimização).
2. **O texto barrado pela guarda também é gravado** (`explicacao_descartada`), porque é o que o docente
   precisa ver para julgar a guarda. Ele **nunca** vai para o aluno nem para a amostra.
3. **Referência da auditoria `feedback:<id>`.** O veto do diálogo continua com o id puro (compatível com os
   registros já gravados). Assim um diálogo e um feedback com o mesmo número não se confundem (há teste).
4. **Amostra só com origem `LLM`, com o texto original e sem mostrar se houve veto**, para medir o modelo sem
   influenciar o avaliador. Sem código de aluno. A pergunta do diálogo é mantida porque dá o contexto,
   e por isso o arquivo é de uso interno (protocolo, seção 3).
5. **R3 e "inativo":** mudou só o orquestrador, como pedido. O indicador de engajamento do Agente 3 continua
   contando quem concluiu e está parado como "inativo" (é um fato sobre a atividade). Por isso a visão geral
   do painel ("Alunos inativos") ainda conta essas pessoas, enquanto os alertas de risco e o orquestrador não
   contam. Veja a pergunta 4.
6. **Critério de sucesso.** O TAP pede "ao menos 80% de adequação nas respostas do tutor, medida por
   avaliação docente sobre amostra de 100 interações". O protocolo calcula a adequação com intervalo de
   Wilson (±8 pontos com N = 100) e a concordância entre dois avaliadores (kappa).

## Pendências

- **Login (1.4.6):** a auditoria não registra quem vetou ou aprovou.
- **Reenvio do mesmo `evento_id`** devolve o feedback original gravado, mesmo se já vetado. O reenvio só
  acontece segundos depois, por falha de rede; a correção continua no histórico. Documentado como limitação.
- **Respostas antigas** (antes de 11/10/2026) não têm texto e não entram na revisão nem na amostra.
- **`GET /tutor/incentivo/{id}`** (rota standalone do Tutor) ainda devolve `inativo: true` para quem concluiu
  e está parado, mas com a mensagem de "trilha concluída", não a de incentivo. Não mexi: é do Tutor
  (Pessoa 2).
- **Indicador "inativos" do Agente 3** (decisão 5).
- **Motivo interno do veto**, separado da correção que o aluno vê, continua pendente (precisa mudar o
  modelo `Veto`).

## Perguntas para a Pessoa 4

1. A meta de 80% de adequação vale só para o texto do LLM (como no protocolo) ou para tudo o que o tutor
   mostrou (incluindo os textos da guarda e os fixos)?
2. Os 6 critérios de adequação do protocolo estão bons? S/N ou uma escala (1 a 3)?
3. As "100 interações" devem misturar feedback e diálogo (como agora, proporcional ao uso) ou ter uma cota
   fixa de cada tipo?
4. Um aluno que concluiu a trilha e está parado deve contar como "inativo" no indicador de engajamento da
   turma? Hoje o orquestrador e os alertas dizem que não, e o indicador agregado diz que sim.
5. Quem são os dois docentes avaliadores, e a calibração com 10 textos cabe no calendário do piloto?
