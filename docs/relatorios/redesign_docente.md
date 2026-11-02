# Redesenho visual do painel do docente, parte 2 (01/11/2026)

> Frente A3, branch `redesign-interface`. Aplica a prévia de `docs/design/prototipo_redesign/` (PainelDocente,
> Revisar, RelatorioTurma) em `src/tia/web/static/painel/`, reaproveitando o menu lateral, os tokens e as formas
> do redesenho do aluno (`docs/relatorios/redesign_aluno.md`). Sem commit.

## Resumo

| Item | Resultado |
|---|---|
| `./run_tests.sh` | **767 passed, 9 xfailed** (eram 758 + 9; 9 testes novos). Depois das últimas edições de limpeza e do Sair no login, painel, web e segurança rodaram de novo: 269 passed |
| Aplicação do aluno | **idêntica pixel a pixel** depois da mudança nos seletores compartilhados: mesmo hash, CSS do último commit contra o atual, em Início, Trilha, Estudar e Login (DEMO-W02; 1280 e 390 px) |
| Rolagem horizontal da página | nenhuma em 1280 e 390 px (as tabelas largas rolam dentro da própria região, acessível pelo teclado) |
| Capturas | `docs/relatorios/redesign/docente_*` (1280 e 390 px, turma fictícia de `python -m tia.web.dados_painel`) |
| Rotas novas | `GET /painel/alunos` (auditada) e `GET /painel/revisao/contagem` (só número, não auditada) |

## Decisões aprovadas antes de editar

- **(A)** `GET /painel/alunos`: somente leitura, só docente (401 sem login, 403 para aluno e admin), grava
  `consulta_painel` com os códigos exibidos e devolve **apenas** código, perfil, competência atual, taxa de
  acerto e situação. Nunca nome, objetivo ou texto do diálogo (há teste).
- **(B)** "Concluíram esta semana" virou **"Progresso médio na trilha"**, o indicador 1 do Agente 3. Nenhuma
  métrica nova.
- **(C)** A abertura da Visão geral grava `consulta_painel` porque mostra códigos. O contador "a revisar" do menu
  mostra só o número e **não** grava auditoria.
- **(D)** Os testes de `tests/test_painel.py` mudaram só para os ids e as telas novas. Só tema claro.

## Mapeamento das telas

| Antes (5 abas no topo) | Agora (menu lateral) |
|---|---|
| Visão geral (5 indicadores) | **Relatório da turma**: resumo escrito pela IA (sob pedido), 4 números, desempenho por grupo, alertas da turma (contagens) e os 5 indicadores completos recolhidos. CSV e Imprimir ficam aqui |
| Alertas de risco | **Visão geral** (tela inicial): 4 números, alertas por aluno (com código) e a tabela de alunos com filtro de nível |
| Revisão docente | **Revisar textos**: fila à esquerda e o texto à direita; filtros e taxa de vetos recolhidos |
| Competências, Auditoria | itens secundários do menu, abaixo de uma linha divisória, com o mesmo conteúdo e a forma nova |

O endereço antigo `/app/painel/#risco` abre a Visão geral.

### Escolhas de detalhe

1. **Situação na tabela**: uma por aluno, a mais urgente, pelas mesmas regras dos alertas: queda, desempenho
   baixo, com ressalvas, inativo; sem alerta, "No ritmo" ou "Trilha concluída"; "Sem trilha" para quem não tem
   trilha. A competência atual é a primeira etapa ainda não concluída da trilha (`consultas.situacao_do_aluno`).
2. **Alunos ativos** = total menos os que têm alerta de inatividade (critério `INATIVIDADE_DIAS`, que aparece no
   próprio cartão). Quem concluiu a trilha conta como ativo, como no Agente 3.
3. **Alertas**: um cartão por aluno com todos os motivos, na cor do mais grave: terracota para queda e
   desempenho baixo, dourado para ressalvas, creme para inatividade. O nome do motivo vai sempre em texto.
4. **Desempenho por grupo**: progresso médio na trilha de cada perfil (o mesmo `/relatorio/turma`, um por
   perfil). Não existe "acerto geral" agregado no Agente 3, e criar um seria métrica nova. O perfil abaixo do
   mínimo aparece com cadeado: "Iniciante (menos de 5 alunos): oculto por ter menos de 5 alunos."
5. **Números do relatório**: progresso médio, alunos com trilha, sessões por aluno (com perguntas ao tutor por
   aluno) e inativos. São todos campos que já existiam. Contagem abaixo do mínimo sai como "menos de 5".
6. **Revisar**: a correção é obrigatória para vetar (a tela recusa o veto vazio e põe o foco no campo). Num texto
   vetado, os botões viram "Salvar correção" e "Retirar veto (aprovar a original)". O texto barrado pela guarda
   continua visível, recolhido. O contador do menu conta os textos "a revisar" de origem LLM, o mesmo filtro
   padrão da fila, e é atualizado depois de cada aprovação ou veto.
7. **Login**: o mesmo cartão central do aluno. Quem entra com outro papel vê o aviso, "Sair" e "Ir para a
   aplicação do aluno". Sem isso, ficava preso: o menu com o Sair não aparece no login.
8. **Reaproveitamento**: em `tema.css`, o bloco de tokens vale para `body.app-aluno, body.app-docente`. Em
   `estilo.css`, a estrutura (menu, área, formas dos componentes, peças comuns e login) passou de `.app-aluno` para
   `:is(.app-aluno, .app-docente)`, com a mesma especificidade (por isso o aluno não mudou). O que é só do
   painel fica em `painel/painel.css`, só com variáveis.

## Auditoria por abertura de tela

| Tela | Linhas gravadas |
|---|---|
| Visão geral | 2 `consulta_painel` (alertas e lista de alunos) + 1 `relatorio_turma` (progresso médio) |
| Revisar textos | 1 `consulta_painel` por carga da fila; o contador não grava |
| Relatório da turma | 1 `relatorio_turma` para o grupo escolhido + 1 por perfil (desempenho por grupo) |

O relatório da turma agora grava uma linha a mais por perfil a cada abertura. É ruído na auditoria, sem dado
pessoal. Se incomodar, dá para buscar os perfis só quando o docente abrir a seção.

## Testes

- Novos em `tests/test_painel.py`: só os campos permitidos na lista de alunos (inclusive a ausência de nome,
  objetivo e textos do diálogo), a situação de cada aluno conferida contra os alertas, a auditoria da lista de
  alunos e o contador (só o número, nenhum código, **nenhuma linha nova de auditoria**, mesmo total da fila).
  O contrato (`CAMPOS_USADOS`) ganhou `ListaAlunos`, `AlunoTurma` e `ContagemRevisao`, e o teste de valores
  traduzidos passou a cobrir as situações do aluno.
- `tests/test_seguranca.py`: as duas rotas entraram em `ROTAS_DO_DOCENTE` (200 para docente, 403 para aluno e
  admin, 401 sem login).
- Ajustado: `test_tela_de_risco_avisa_que_a_consulta_e_auditada` virou
  `test_visao_geral_avisa_que_a_consulta_e_auditada` (mesmas frases, agora na `tela-geral`).

## Capturas (`docs/relatorios/redesign/docente_*`)

| Arquivos | Tela |
|---|---|
| `docente_0_login_*`, `docente_0_login_aluno_recusado_*`, `docente_0_login_aluno_saiu_*` | login; aluno recusado com Sair; depois de sair |
| `docente_1_visao_geral_*`, `docente_1_visao_geral_iniciante_*` | Visão geral; filtro de nível "Iniciante" |
| `docente_2_revisar_*`, `_fonte_*`, `_sem_correcao_*`, `_vetadas_*` | fila e texto; "Ver fonte" aberto; veto sem correção recusado; fila dos vetados (correção com `<b>` aparece como texto) |
| `docente_3_relatorio_*`, `_detalhes_*`, `_iniciante_*`, `docente_3_relatorio_resumo_llm_1280.png` | relatório; indicadores completos; perfil abaixo do mínimo; resumo escrito pelo `qwen3:1.7b` (origem LLM, conferido pela guarda) |
| `docente_4_competencias_*`, `docente_5_auditoria_*` | telas secundárias |

As capturas usaram um banco temporário (fora de `data/tia.db`) com a turma fictícia e os alunos DEMO-W01 a W03.
Durante o roteiro, um texto foi aprovado e outro vetado nesse banco.

## Não mudou

`comum.js`, `app.js`, `index.html` do aluno, rotas de escrita, modelos do Tutor e do Agente 3, `conteudo/`.
