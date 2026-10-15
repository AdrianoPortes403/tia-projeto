# Ajustes de integração do Agente 1 (branch `integracao-agente1`)

> Frente A3, 15/10/2026. Ajustes pedidos pela revisão `docs/relatorios/revisao_agente1_tiago.md` sobre o
> trabalho do Tiago (`origin/agente1-tiago`, já mesclado em `32d1efe`). **Sem commit**: tudo está na árvore de
> trabalho. As regras 3/2/3 e os 7 dias de refazer trilha foram mantidos (decisões do Tiago, a confirmar).
> O conteúdo pedagógico (`conteudo/`: itens, materiais, ementa, perfis) **não foi alterado**.

**Testes:** `./run_tests.sh` deu **717 passed, 9 xfailed** (os 9 xfail já eram conhecidos). Antes dos ajustes:
697 passed. A demonstração `python -m tia.orquestrador --demo` também roda (banco temporário, sem LLM).

## 1. O que foi feito, por item

| # | Pedido | Feito |
|---|---|---|
| 1 | Conclusão sem domínio | O Tutor marca `com_ressalvas` quando os itens acabam sem `TUTOR_ACERTOS_CONCLUIR` acertos seguidos no nível 3. Grava `tutor_sessoes.com_ressalvas` e `taxa_acerto` (ADD COLUMN) e devolve `Feedback.com_ressalvas`. A R1 só avança com acerto da sessão ≥ `ORQ_ACERTO_MIN_AVANCO` (0,6, PROVISÓRIO). Abaixo disso, `regra_sem_dominio` faz `reforcar` o pré-requisito (sem pausa) ou `revisar_material`, cada um no máximo uma vez por sessão, ou `nenhuma` gravada com o motivo; o aluno recomeça numa sessão nova. O Relatório mostra a ressalva por competência (`com_ressalvas`, `taxa_sem_dominio`, contagem no progresso, narrativa). O painel tem o motivo de risco `conclusao_sem_dominio` e o alerta da turma de mesmo nome. A asserção forte do banco de itens voltou. Há teste "errou tudo e os itens acabaram não avança" |
| 2 | Autenticação das rotas novas | `test_seguranca.py`: cada uma das 5 escritas com 401 sem login, 403 sem CSRF ou com CSRF errado, 403 para outro aluno, 403 para docente e para admin, e a recusa na auditoria. A leitura (`GET .../primeiro-acesso`) entrou na matriz `LEITURAS_DO_ALUNO`, com teste próprio (admin recebe 403). Percurso completo com login ligado. Tabela "Quem pode chamar o quê" atualizada em `arquitetura.md` |
| 3a | Retenção | `retencao.py` apaga o `planejador_onboarding` **não concluído** após `RETENCAO_DIALOGO_DIAS` (a conversa só existe nele) e tira o `objetivo` do cadastro concluído no mesmo prazo (`json_remove`). Há teste de simulação, aplicação e idempotência |
| 3b | Objetivo só para o aluno | `GET /aluno/{id}/primeiro-acesso` não devolve `objetivo` ao docente (lista `SO_DO_ALUNO`). O aluno e o modo de desenvolvimento recebem |
| 3c | Inventário LGPD | `lgpd.md`: linhas para o cadastro inicial (com a conversa), o objetivo e o diagnóstico inicial. Matrícula com trilha, prazo e escopo. O que a auditoria do primeiro acesso guarda. Eliminação a pedido. Pergunta 7 ao jurídico |
| 3d | Limite do onboarding | `ONBOARDING_MAX_MENSAGENS` (12) limita as mensagens por conversa (depois, 409 "recomece") **e** as chamadas ao LLM por aluno, somando as conversas recomeçadas (depois, só regras). Sem isso, recomeçar zeraria o limite |
| 4 | Testes enfraquecidos | Restaurados `test_nao_repete_item_ate_esgotar` (com "nunca pega item de outra competência" e "esgota exatamente os 6") e `test_nivel_sem_itens_usa_o_mais_proximo`. Novos: `test_nivel_esgotado_depois_de_erro_vai_para_o_mais_facil`, `test_nunca_pega_item_de_outra_competencia...` e `test_conclusao_por_dominio_nao_tem_ressalva...`. Asserção forte no banco: os 4 tópicos do piloto concluem **por domínio** (sem ressalva, sem reusar itens do diagnóstico); a base comum, só com ressalvas |
| 5 | PROVISÓRIO | `test_itens_gerados_por_llm_continuam_provisorios`: os 84 itens `rascunho_llm` não podem estar `validado` sem constar em `VALIDADOS_PELA_PESSOA_4` (vazio). Nenhum item do banco pode estar validado fora da lista. CLAUDE.md, "Quem faz o quê": parágrafo acrescentado; o texto do Tiago ficou |
| 6 | `revisar_material` uma vez por sessão | Na lacuna e na R1 sem domínio (`_ja_na_sessao`). Lacuna repetida passa a `nenhuma` e a R2 continua valendo. Há teste com `cib_01` (7 itens por nível, duas lacunas, um aviso) |
| 7 | Demonstração, `.env` e `deploy/` | Detalhes logo abaixo |
| 8 | Conteúdo | Não alterado (`git diff --stat -- conteudo` vazio) |

**Item 7 em detalhe:**

- `dados_painel.py`:
  - o nível das respostas segue 3/2;
  - as sessões concluídas gravam `com_ressalvas` e `taxa_acerto` como o Tutor grava;
  - a 1ª sessão de funções do DEMO-P06 passou de `"0100100"` (aberta) para `"010010"` (concluída, 33%). É o caso de demonstração de "não avançou".
- `dados_demo.py`: só o docstring mudou, porque o script já usa o orquestrador de verdade.
- Os bancos foram refeitos num `data/tia.db` novo. **O antigo foi guardado** como `data/tia.db.antes_integracao_agente1`.
- No banco novo, o painel mostra o DEMO-P06 com `conclusao_sem_dominio`.
- `.env.example`:
  - `ONBOARDING_MAX_MENSAGENS` e `ORQ_ACERTO_MIN_AVANCO`;
  - bloco comentado "PERFIL DE PILOTO" (8 dias, escopo piloto, inatividade 2 e 4), com o aviso de que `INATIVIDADE_DIAS=2` muda também o painel, o Relatório e a narrativa.
- `deploy/perfil_piloto.env`: o mesmo bloco, comentado (não é lido pela aplicação).
- `docs/implantacao_vm.md`: seção "Perfil de piloto".

## 2. Arquivos alterados

- **Tutor:**
  - `agentes/tutor/adaptativo.py`: `com_ressalvas`;
  - `tutor/modelos.py`: `Feedback.com_ressalvas`;
  - `tutor/__init__.py`;
  - `tutor/repositorio.py`: grava a ressalva e a taxa, e tem `resultado_sessao`, `CONCLUSAO_QUE_VALE` e `competencias_concluidas` filtrada.
- **Orquestrador:**
  - `orquestrador/regras.py`: `regra_sem_dominio`, `avanca_sem_dominio`, avisos, `regra_lacuna` com `sessao_ja_com_material`;
  - `orquestrador/eventos.py`: `_avaliar_conclusao`, `_ja_na_sessao`;
  - `orquestrador/fluxo.py`: reforço sem pausa, retomada quando a original já terminou, aviso do material.
- **Relatório:** `agentes/relatorio/{repositorio,indicadores,modelos,narrativa}.py`.
- **Painel:**
  - `painel/{consultas,modelos}.py`;
  - `web/static/painel/{painel.js,index.html}`: rótulos e filtro;
  - `web/static/app.js`: mensagem "concluída com ressalvas" ao aluno.
- **Primeiro acesso:** `agentes/planejador/onboarding.py` (limite) e `api/rotas_primeiro_acesso.py` (objetivo e limite).
- **Infraestrutura:**
  - `seguranca/retencao.py`;
  - `core/config.py`: `ORQ_ACERTO_MIN_AVANCO`, `ONBOARDING_MAX_MENSAGENS`;
  - `core/database.py`: ADD COLUMN.
- **Demonstração e implantação:**
  - `web/dados_painel.py`, `web/dados_demo.py`;
  - `.env.example`, `deploy/perfil_piloto.env` (novo), `docs/implantacao_vm.md`.
- **Documentos:**
  - `docs/arquitetura/arquitetura.md`: D9, R1 sem domínio, lacuna, fim do reforço, colunas novas, matriz de acesso, alerta do painel, limitações;
  - `docs/seguranca/lgpd.md`;
  - `CLAUDE.md`.
- **Testes:**
  - `test_tutor.py`, `test_regras_eap.py`, `test_primeiro_acesso.py`, `test_seguranca.py`;
  - `test_painel.py` e `test_web.py`.

**Mudança de expectativa em teste existente (transparência):** em `test_painel.py::test_alunos_em_risco_e_motivos`, o
DEMO-P06 ganhou o motivo `conclusao_sem_dominio`, por causa do dado de demonstração novo. Com isso ele empata com
o DEMO-P08 em 2 motivos e passa à frente pelo código. A asserção "P08 é o primeiro" virou "P06 e P08 são os dois
primeiros", mais a checagem de que a lista está ordenada por número de motivos. Em `test_web.py`, só entraram os
campos novos que a tela lê.

## 3. Decisões tomadas aqui (a confirmar)

1. **Taxa da sessão, não da competência inteira.** Quem recomeça é julgado pela nova tentativa, sem carregar os
   erros da anterior. "Taxa de acerto da competência" podia ser lida como todas as respostas na competência.
2. **O painel só alerta a ressalva que impediu o avanço.** Na base comum (2 itens por nível), toda conclusão é com
   ressalvas, e alertar todas tornaria o alerta inútil. O Relatório do aluno mostra todas.
3. **Reforço sem pausa** na R1 sem domínio: a sessão já terminou. No fim do reforço, o aviso pede para recomeçar
   a competência (`AVISO_RECOMECO`) em vez de "voltando ao nível N". A regra da decisão é `conclusao`.
4. **"No máximo uma vez por sessão" vale por ação.** Uma sessão pode ter um reforço e um material, somando lacuna e
   R1. Esgotados os dois, a R1 sem domínio grava `nenhuma` com o motivo, e o aluno vê a ressalva no feedback.
5. **Sessões antigas** (sem a coluna) contam como conclusão plena. Nenhum dado existente muda de sentido.
6. **Limite do onboarding:** por conversa (mensagens) e por aluno (chamadas ao LLM, mesmo número).

## 4. Pendências

- **Base comum sem itens para o domínio:** só se resolve com mais itens (pelo menos 3 de tutoria por nível), o
  que é trabalho da Pessoa 4. Até lá, o avanço nela depende só do mínimo de 60%.
- **Recomeço sem limite:** quem não atinge o mínimo pode recomeçar indefinidamente, com um reforço por sessão. Não
  há encaminhamento automático ao docente além do alerta do painel.
- **Diagnóstico abandonado** (`planejador_diagnosticos` sem conclusão) não tem prazo de retenção. Não tem texto
  livre, então ficou como o cadastro.
- **`INATIVIDADE_DIAS` com dois papéis:** incentivo da R3 e alerta do painel e do Relatório. O piloto com 2 dias
  muda os dois. Separar exige outra variável.
- **Observação fora do escopo (já existia na `main`):** o chromadb 0.5.23 registra no log "Failed to send
  telemetry event ... capture()". Com `anonymized_telemetry=False`, ele põe `posthog.disabled = True`, e o erro
  vem da incompatibilidade com o posthog 7.x antes do envio: **nada sai da máquina**, mas o log assusta. Vale
  silenciar o logger `chromadb.telemetry` ou fixar a versão do posthog (frente A3, depois).
- Commit, push e merge na `main`: não feitos, aguardando a sua revisão.

## 5. Perguntas

**Ao Tiago:**

1. As regras 3/2/3 e os 7 dias vêm do documento 1.2.5 aprovado? Substituem a nossa D7 (14 dias)?
2. Os 84 itens `rascunho_llm` foram gerados por qual LLM: local (Qwen/Ollama) ou serviço externo (R07)?
3. O mínimo de 60% para avançar sem domínio e a leitura "taxa da sessão" combinam com a base pedagógica?
4. O piloto só com `dev_01`/`dev_02` (ou `cib_01`/`cib_02`), com a base comum fora do escopo mas dentro do
   diagnóstico, é intencional? O reforço por lacuna em `dev_01` cai em `repeticao`, que está fora da trilha.
5. No piloto, `INATIVIDADE_DIAS=2` deve valer também para o alerta do painel, ou só para o incentivo?

**À Pessoa 4:**

1. Revisão dos 84 itens gerados por LLM e dos 36 da base comum. Quando chegar, os ids aprovados entram em
   `VALIDADOS_PELA_PESSOA_4` e só então o `status` muda.
2. Mais itens na base comum (pelo menos 3 de tutoria por nível), para que o domínio seja possível.
3. `ORQ_ACERTO_MIN_AVANCO` (0,6): o valor e o que fazer depois de N tentativas sem atingir o mínimo (limite?
   encaminhar ao docente?).
4. Textos ao aluno: aviso de conclusão com ressalvas, reforço sem domínio e recomeço (`regras.py`, PROVISÓRIOS).
