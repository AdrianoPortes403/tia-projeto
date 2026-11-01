# Limitações conhecidas do Sistema TIA (M6)

> Frente A3, 31/10/2026. Consolida as limitações que estavam espalhadas em `docs/arquitetura/arquitetura.md`
> ("Limitações conhecidas"), `docs/arquitetura/relatorio_indicadores.md`,
> `docs/relatorios/base_pedagogica_e_agente1.md`, `plugin-ebaula/README.md`, `docs/seguranca/implantacao.md`
> e no levantamento `docs/relatorios/retomada_2026-10-31.md` (seção 4.1).
>
> Responsáveis: **A3** (Adriano: infraestrutura, integração, segurança), **A1** (Tiago: Agente 1, conteúdo,
> VM), **Pessoa 2** (lógica dos agentes), **Pessoa 4** (validação pedagógica), **jurídico/DEP**,
> **equipe do EBAULA**.

## Resumo

| # | Limitação | Impacto | Responsável |
|---|---|---|---|
| 1 | Conteúdo incompleto (38 tópicos) e base comum só "com ressalvas" (D9) | alto fora do piloto | Pessoa 4, A1 |
| 2 | Orquestração: sem agendador, reforço standalone não vinculado, critério de etapa provisório | médio | Pessoa 2, A3 |
| 3 | Recomeço de competência sem limite de tentativas | médio | Pessoa 4 |
| 4 | Taxa de acerto considerada só da sessão | médio | Pessoa 4, Pessoa 2 |
| 5 | `INATIVIDADE_DIAS` com dois papéis | baixo/médio | A1, Pessoa 4 |
| 6 | R09 (15 s) não medido na VM | alto | A3, A1 |
| 7 | R10 (50 usuários simultâneos) sem teste de carga | médio | A3 |
| 8 | Plug-in do EBAULA: testado só em jsdom, iframe só no mesmo site, sem SSO | alto para a integração | A3, equipe do EBAULA |
| 9 | LGPD: prazos, bases legais e retenção PROVISÓRIOS | alto para produção | jurídico/DEP, A3 |
| 10 | RAG: reingestão manual, índice com pedaços antigos, distância calibrada só no piloto | médio | A3 |
| 11 | Chroma loga erro de telemetria | baixo | A3 |
| 12 | Visual provisório até o tema do EBAULA | baixo | A3, equipe do EBAULA |
| 13 | Demais itens PROVISÓRIO (senha, onboarding, modelo da VM) | médio | ver item |

## 1. Conteúdo pedagógico incompleto

- **Descrição:** 38 dos 48 tópicos das trilhas Dev e Defesa Cibernética não têm itens nem material. Os 6
  tópicos da base comum têm só 2 itens por nível: com as regras 3/2/3 ninguém chega a 3 acertos seguidos no
  nível 3, então toda conclusão neles é "concluída com ressalvas" (decisão D9).
- **Impacto:** fora do escopo do piloto (`PILOTO_ESCOPO=completa`), o aluno chega a tópicos sem questões e
  sem material, e o Tutor responde sem fonte. Na base comum, o avanço depende só do acerto da sessão
  (`ORQ_ACERTO_MIN_AVANCO=0.6`).
- **Mitigação:** o piloto usa `PILOTO_ESCOPO=piloto` (só os 4 tópicos validados e a base comum). A D9 foi
  aceita na validação de 19/10. Para a versão completa, escrever e validar os itens e materiais que faltam.
- **Responsável:** Pessoa 4 (validação) e A1 (conteúdo). Não editar `conteudo/` sem os dois.

## 2. Orquestração

- **Descrição:**
  - sem agendador fora da VM: a verificação de inatividade só roda quando alguém chama o comando ou a rota;
  - uma sessão de reforço aberta por `/tutor/sessao` (standalone) não fica vinculada ao reforço, e o
    `proximo` continua pedindo `/aluno/{id}/sessao`;
  - o critério de "etapa concluída" (`agentes/tutor/incentivo.py`) e outras partes da lógica da Pessoa 2
    seguem provisórios.
- **Impacto:** incentivos e replanejamentos por inatividade atrasam se ninguém disparar a verificação; o
  aluno que usa a tela standalone pode repetir o reforço.
- **Mitigação:** na VM, o timer do systemd (`deploy/`) roda a verificação. Na interface do aluno, o reforço é
  aberto pela rota vinculada. A lógica provisória está marcada com `# PROVISÓRIO` e isolada para troca.
- **Responsável:** Pessoa 2 (critérios), A3 (agendador e integração).

## 3. Recomeço de competência sem limite de tentativas

- **Descrição:** quem termina uma competência sem domínio e com acerto abaixo de 60% recomeça a competência
  numa sessão nova (reforço do pré-requisito ou material-base). Não há limite de tentativas nem
  encaminhamento automático ao docente.
- **Impacto:** um aluno com dificuldade persistente pode entrar num ciclo de recomeços; o docente só percebe
  pelo alerta do painel.
- **Mitigação:** o painel do docente mostra os alertas de desempenho e de inatividade. Proposta em aberto:
  após N recomeços, alertar o docente ou sugerir atendimento.
- **Responsável:** Pessoa 4 (pergunta 3 de `ajustes_integracao_agente1.md`, sem resposta registrada); A3
  implementa depois da decisão.

## 4. Taxa de acerto considerada só da sessão

- **Descrição:** a decisão de avançar sem domínio (`orquestrador/regras.py::avanca_sem_dominio`) usa o acerto
  **da sessão atual**, sem considerar sessões anteriores da mesma competência.
- **Impacto:** sessões curtas dão taxas instáveis (poucas respostas mudam muito a porcentagem); um aluno com
  histórico ruim pode avançar por uma única sessão boa, e o contrário também.
- **Mitigação:** a regra foi validada assim pela Pessoa 4 (19/10). O histórico completo fica no banco e
  aparece no painel e no Relatório (Agente 3), para o docente acompanhar.
- **Responsável:** Pessoa 4 (critério) e Pessoa 2 (lógica oficial).

## 5. `INATIVIDADE_DIAS` com dois papéis

- **Descrição:** a mesma variável define o incentivo ao aluno (R3) e o limiar do alerta "inatividade" do
  painel, do engajamento do Relatório e da narrativa. No piloto ela vale 2 (fora dele, 3).
- **Impacto:** com 2 dias no piloto, painel e Relatório também tratam como inativo quem está há 2 dias sem
  atividade, o que pode inflar o alerta.
- **Mitigação:** o efeito está documentado em `deploy/perfil_piloto.env` e no `.env.example`. Se for preciso
  separar, criar uma segunda variável em `core/config.py`.
- **Responsável:** A1 e Pessoa 4 (pergunta 5 ao Tiago, sem resposta); A3 separa a variável, se decidido.

## 6. R09 (resposta em até 15 s) não medido na VM

- **Descrição:** a VM institucional ainda não está disponível. Em CPU (máquina de desenvolvimento), nenhuma
  interação com LLM cabe em 15 s (`docs/relatorios/orquestracao_tempos.md`).
- **Impacto:** não há número que comprove o R09.
- **Mitigação:** decisão de 10/10: não otimizar no desenvolvimento. Timeouts configuráveis, instrumentação
  (`tempo_*_ms`, `falha_llm`) e `deploy/verificar.sh --medir-r09 N` (p50/p90/p95 por modelo) prontos para a
  VM. Toda demonstração imprime o tempo.
- **Responsável:** A3 (medição), A1 (VM).

## 7. R10 (50 usuários simultâneos) sem teste de carga

- **Descrição:** não houve teste de carga.
- **Impacto:** não se sabe como o Ollama e o SQLite se comportam com 50 alunos ao mesmo tempo.
- **Mitigação:** fazer um teste de carga na VM antes do uso em turma completa.
- **Responsável:** A3.

## 8. Plug-in do EBAULA

- **Descrição:**
  - testado só em jsdom (`plugin-ebaula/teste`), nunca num navegador real nem no EBAULA;
  - o iframe existe (`TIA_FRAME_ANCESTORS`), mas o cookie `tia_sessao` é `SameSite=Strict`: o login em iframe
    só funciona com o TIA no **mesmo site** do EBAULA. Em outro site, o aluno fica num ciclo de login;
  - login único (SSO) do EBAULA pendente: existe só o contrato `seguranca/autenticador.py`;
  - o aviso "O tutor não carregou" provavelmente não aparece no ciclo de login nem com `frame-ancestors`
    bloqueando;
  - `origem=ebaula` e as mensagens `tia:fechar`/`tia:abrir-em-aba` não são usadas pelo TIA;
  - no nginx, a instrução para o iframe é apagar o `X-Frame-Options: DENY`, o que o tira de todas as rotas
    (a CSP continua protegendo a API).
- **Impacto:** a integração em iframe pode não funcionar no domínio real do EBAULA; o aluno faz login local.
- **Mitigação:** **abrir o TIA em nova aba** (`modo=aba` do plug-in) funciona em qualquer domínio. Para o
  iframe, servir o TIA num subdomínio do EBAULA (alternativa A de `docs/seguranca/implantacao.md`; evitar o
  caminho na mesma origem). No nginx, preferir um `location /app/` sem o `X-Frame-Options`.
- **Responsável:** A3 (TIA) e equipe do EBAULA (domínio, SSO, CSP do lado deles).

## 9. LGPD e retenção

- **Descrição:** prazos de retenção (`RETENCAO_*`), retenção do IP (`AUTH_RETENCAO_IP_DIAS=30`) e bases
  legais estão PROVISÓRIOS (`core/config.py`, `.env.example`, `seguranca/retencao.py`, `seguranca/limpeza.py`,
  `docs/seguranca/lgpd.md`).
- **Impacto:** o sistema não deve guardar dados reais além do piloto sem a validação do jurídico/DEP.
- **Mitigação:** a retenção é aplicada por comando (`python -m tia.seguranca.retencao`) e os valores são
  configuráveis no `.env`, sem mudança de código. Logs sem dados pessoais (testado).
- **Responsável:** jurídico/DEP (parecer), A3 (aplicar os valores).

## 10. RAG

- **Descrição:**
  - a ingestão é manual (`python -m tia.rag.ingest`) e precisa ser repetida a cada mudança de material, aqui
    e na VM;
  - a ingestão faz `upsert` e **não apaga** pedaços de arquivos renomeados ou removidos. O índice local,
    reindexado em 31/10 (69 pedaços de 10 arquivos), ainda guarda 13 pedaços antigos `provisorio_*`, com o
    mesmo texto dos atuais (82 no total). Esses pedaços podem aparecer como fonte com o nome antigo;
  - `TUTOR_DISTANCIA_MAXIMA=400` foi calibrada só com o material do piloto.
- **Impacto:** fonte citada com nome antigo (R03); relevância incerta quando entrar material novo.
- **Mitigação:** na VM, ingerir num índice vazio (`CHROMA_DIR` novo). No local, apagar `data/chroma_db` e
  ingerir de novo. Recalibrar a distância com o material novo. Melhoria possível: a ingestão remover os ids
  de arquivos que não existem mais.
- **Responsável:** A3.

## 11. Erro de telemetria do Chroma no log

- **Descrição:** o Chroma imprime um erro de telemetria ao abrir o cliente, mesmo com
  `anonymized_telemetry=False` (`rag/retrieve.py`). É incompatibilidade da versão do chromadb com a do
  posthog.
- **Impacto:** só ruído no log. Não há tráfego externo: a telemetria está desligada e o teste
  `test_chroma_sem_telemetria` confere isso.
- **Mitigação:** ignorar a mensagem; ao atualizar dependências, fixar versões compatíveis.
- **Responsável:** A3.

## 12. Visual provisório

- **Descrição:** a paleta verde-oliva (`web/static/tema.css`) é provisória até o tema do EBAULA. A fonte do
  título (Bahnschrift) existe só no Windows; nos outros sistemas cai nas alternativas.
- **Impacto:** só estético.
- **Mitigação:** trocar o visual é trocar só o `tema.css` (só variáveis, testado).
- **Responsável:** A3, com o visual da equipe do EBAULA.

## 13. Demais itens PROVISÓRIO

| Onde | O quê | Impacto | Mitigação | Responsável |
|---|---|---|---|---|
| `core/config.py:192`, `.env.example:113` | política de senha (tamanho mínimo, senhas comuns) | pode divergir da política da instituição | valores configuráveis no `.env` | instituição (A1) |
| `core/config.py:73`, `.env.example:23` | `ONBOARDING_MAX_MENSAGENS=12` | limite de mensagens e chamadas ao LLM no cadastro não validado | configurável; sem LLM, o onboarding segue por regras | A3 e Pessoa 4 |
| `core/config.py:42` | raciocínio do `qwen3.5` em `RACIOCINIO_POR_MODELO` e escolha do `MODELO_PADRAO` da VM | o modelo final e o modo de raciocínio só se confirmam com a medição | `deploy/verificar.sh --medir-r09 N` por modelo | A3, A1 |
| `core/config.py:197`, `:216` | retenção do IP e prazos LGPD | ver item 9 | ver item 9 | jurídico/DEP |
| `agentes/tutor/incentivo.py:68` | "etapa concluída" | ver item 2 | ver item 2 | Pessoa 2 |
| `agentes/tutor/repositorio.py:54` | `palavras_chave` da ementa | tópicos sem conteúdo | ver item 1 | Pessoa 4, A1 |
| `web/dados_painel.py:58` | diagnóstico fictício | só demonstração | não usar no banco real | A3 |
