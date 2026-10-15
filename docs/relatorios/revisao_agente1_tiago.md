# Revisão da branch `origin/agente1-tiago` em relação à `main`

> Frente A3, 15/10/2026. Revisão só de leitura (nenhum arquivo do código foi alterado).
> Base: `git diff main...origin/agente1-tiago` (6 commits, de `9599439` a `6e21b7c`, 52 arquivos, +6653/−372).
> O merge-base é o próprio `4262f99` (ponta da `main` local). O `git fetch` falhou por falta de acesso ao
> remoto, então as referências `origin/*` são as da última busca.
> Testes: `./run_tests.sh` com o conteúdo da branch (árvore de `simulacao-merge`): **697 passaram, 9 xfailed**
> (os xfail já existiam na `main`; a branch não acrescenta nenhum).

## 1. O que a branch muda, por área

| Área | Mudança |
|---|---|
| Planejador | Trilha = base comum (etapa 0) + `dev` ou `defesa_cibernetica`. O perfil, quando não é informado, é enquadrado pelo diagnóstico (P = média de nota×3, limiar 1,5). Tópico com nota 1 sai da trilha em qualquer perfil. Novos campos por etapa: `nivel_inicial`, `revisar_antes`, `desafio_pratico`. Prazo e escopo do piloto (`cabe_no_prazo`, `opcoes_prazo`). Primeiro acesso: `onboarding.py` (conversa com LLM local ou regras) e `diagnostico.py` (níveis 1→2→3 por tópico, para no primeiro erro). |
| Tutor | Regras 3/2/3 configuráveis (`TUTOR_ACERTOS_SUBIR`, `TUTOR_ERROS_DESCER`, `TUTOR_ACERTOS_CONCLUIR`). Dois erros seguidos no nível 1 sinalizam `lacuna`. A sessão começa no `nivel_inicial` e evita os itens já vistos no diagnóstico. Quando um nível se esgota, o desempate vai na direção da resposta. |
| Orquestrador | Nova regra `lacuna`, com prioridade sobre a R2: reforça o pré-requisito direto ou, sem ele, `revisar_material` (ação nova). A matrícula ganha `trilha`, `prazo_dias` e `escopo`, e grava o perfil enquadrado. O prazo restante é recalculado a cada replanejamento. `abrir_sessao` passa o nível inicial (o reforço continua no nível 1). |
| Web | O formulário de matrícula (perfil e horas) foi trocado pelo primeiro acesso em 3 passos (conversa, diagnóstico, "montar trilha") em `index.html`/`app.js`. O painel ganha os rótulos dos dois tipos novos de auditoria. Os dados de demonstração usam a convenção nova de notas. |
| Conteúdo | Ementa passa de 6 para 48 tópicos (6 base + 23 dev + 19 cyber). Itens passam de 36 para 120 (84 novos para dev_01, dev_02, cib_01, cib_02, 7 por nível). 4 materiais novos. Perfis reescritos (ritmo 1,0, sem `competencias_dispensaveis`, com `regras_enquadramento`). |
| Config | `ONBOARDING_USA_LLM`, `ONBOARDING_TIMEOUT_LLM`, `PILOTO_PRAZO_DIAS`, `PILOTO_ESCOPO` e os três limiares do Tutor. **`ORQ_INATIVIDADE_REFAZER_DIAS` muda de 14 para 7.** Tudo em `core/config.py` com `os.getenv`, como manda o padrão. |
| Banco | Duas tabelas novas: `planejador_onboarding` e `planejador_diagnosticos`. ADD COLUMN em `trilha_estudo` (11 colunas), `tutor_sessoes` (`acertos_seguidos`, `erros_seguidos`) e `orquestrador_matriculas` (`trilha`, `prazo_dias`, `escopo`). |
| Segurança | Seis rotas novas com `acesso_ao_aluno`. Tipos de auditoria `onboarding` e `diagnostico` (agente planejador). As tabelas novas entram em `anonimizacao.TABELAS_DO_ALUNO` e em `titular.APAGAR`/`exportar`. `retencao.py` não muda. |

## 2. Conflitos com decisões nossas

- **Regras do Tutor (3/2/3 contra 1/1/2).** Na `main`, um acerto sobe, um erro desce e 2 acertos seguidos no nível 3
  concluem. Na branch, 3 acertos sobem, 2 erros descem e 3 acertos no nível 3 concluem. É uma decisão da Pessoa 2
  e entra como valor padrão. **Efeito colateral importante:** os 6 tópicos da base comum têm só 2 itens por nível,
  então o critério de domínio (3 acertos seguidos no nível 3) **nunca pode ser atingido**. Esses tópicos só
  terminam quando os itens acabam, e quando os itens acabam a sessão é dada como `concluida` **mesmo que o aluno
  tenha errado tudo**. A R1 avança do mesmo jeito. A regra de "terminar quando os itens acabam" já existia na
  `main`, mas lá o domínio era alcançável. O próprio teste do banco foi relaxado para "conclui por domínio ou por
  fim dos itens" (seção 5).
- **Prazos de inatividade.**

  | Valor | Onde vale | `main` | branch |
  |---|---|---|---|
  | 3 dias | `INATIVIDADE_DIAS`: incentivo da R3, alerta "inativo" do painel, engajamento do Relatório e narrativa | 3 | 3 (sem mudança) |
  | 7 dias | `ORQ_INATIVIDADE_REFAZER_DIAS`: R3 refaz a trilha | **14** (D7) | **7** (padrão no código e no `.env.example`) |
  | 2 e 4 dias | Piloto de 8 dias: `INATIVIDADE_DIAS=2` e `ORQ_INATIVIDADE_REFAZER_DIAS=4` | — | só num comentário do `.env.example`; precisa ser posto à mão no `.env` da VM |

  Os 2 dias do piloto também mudam o limiar de "inativo" do painel e do Relatório, porque é a mesma variável.
  A D7 da arquitetura foi atualizada pela própria branch ("padrão 7 desde 12/10; era 14"). Isso contraria a nossa
  D7, que está marcada como PROVISÓRIO da Pessoa 4: falta confirmar quem decidiu.
- **Orquestração (R1 a R3 e reforço).** A R1 continua igual, mas o critério de conclusão mudou (acima). A R2
  continua e passa a vir depois da `lacuna`. As duas usam o mesmo limite de "um reforço por sessão", e
  `sessao_ja_reforcada` conta também os reforços por queda. Lacuna dentro de um reforço não reforça (coerente com
  a D6). A R3 só muda o prazo. Ponto novo: a `revisar_material` não tem limite e repete o aviso a cada 2 erros no
  nível 1. Outro ponto: no piloto, o reforço de `dev_01` por lacuna cai em `repeticao`, que está fora do escopo da
  trilha (funciona, mas o aluno vê um tópico que não está na trilha dele).
- **Progresso do reforço.** Preservado. `competencias_originais` agora usa a mesma `_entrada` (trilha e escopo da
  matrícula), e o prazo não corta etapas, só avisa. `test_reforco_concluido_nao_conta_no_progresso_da_trilha`
  continua e passa (só trocou `"1111"` por `CONCLUI`).

## 3. Segurança e LGPD

- **Autenticação e papel:** sim. As cinco rotas POST são `SoOAluno` (`acesso_ao_aluno()`): só o próprio aluno,
  com CSRF pela sessão. `GET /aluno/{id}/primeiro-acesso` é aluno ou docente. Com a autenticação ligada, um aluno
  não acessa outro (403 por `conferir_aluno`). **Porém não há nenhum teste de autenticação das rotas novas:**
  `test_primeiro_acesso.py` roda com `TIA_AUTH=desligada`, e a matriz de `test_seguranca.py` não as inclui. A tabela
  "Quem pode chamar o quê" da arquitetura também não foi atualizada.
- **Dados de outro aluno:** não. Tudo é lido por `aluno_id` da rota. `itens_do_diagnostico` só lê o próprio aluno.
- **Texto livre do aluno e por quanto tempo:**
  - A conversa do onboarding (até 500 caracteres por mensagem, sem limite de mensagens) fica em
    `planejador_onboarding.estado.historico` **enquanto o cadastro não termina**. Ao concluir, é apagada.
    **Um cadastro abandonado guarda a conversa para sempre:** não há operação em `retencao.py` para as tabelas
    novas.
  - O campo `objetivo` (até 200 caracteres, texto livre) **fica para sempre** em `dados` depois de concluído.
    O docente o lê pelo `GET .../primeiro-acesso` **sem registro de consulta na auditoria**, ao contrário das
    outras telas do docente que mostram texto livre ou código.
  - A eliminação a pedido (`titular eliminar`) apaga as duas tabelas, e a exportação as inclui. Há teste
    (`test_lgpd_exporta_e_elimina_cadastro_e_diagnostico`).
- **Rede externa (R07):** nenhuma chamada nova. O onboarding usa `chamar_llm` (Ollama local), e
  `test_pontos_de_rede_do_codigo` passa. **Pergunta à parte:** os 84 itens novos têm `"origem": "llm"`,
  `"status": "rascunho_llm"`. Falta saber qual LLM os gerou. Se foi um serviço externo, isso é autoria de
  conteúdo, não inferência do sistema, mas o CLAUDE.md diz "nunca, nem em desenvolvimento".
- **Dados pessoais em log ou auditoria:** não encontrei. O `log.warning` do onboarding grava só o tipo do erro. A
  auditoria `onboarding` grava o passo e **os nomes** dos campos coletados. A auditoria `diagnostico` grava o
  item, acerto ou erro e o nível. Nenhuma das duas grava texto do aluno. O `aluno_id` vai na auditoria como em
  todo o resto, e a anonimização já o cobre.
- **Documentação LGPD:** o inventário de `docs/seguranca/lgpd.md` (seção 2) não lista `planejador_onboarding` nem
  `planejador_diagnosticos`, nem o `objetivo` como texto livre.

## 4. Banco

- **Só CREATE TABLE IF NOT EXISTS e ADD COLUMN** (por `_acrescentar_colunas`). Nada é apagado ou renomeado, e as
  colunas novas aceitam NULL. As leituras tratam NULL (`or 0`, `or "[]"`, `or "completa"`).
- **Dados existentes não quebram na leitura, mas mudam de sentido no próximo replanejamento:**
  - Os perfis novos não têm `competencias_dispensaveis`. Matrículas antigas com notas como 0,9/0,8 (o padrão
    dos nossos dados de demonstração e de testes) **voltam a ter `variaveis_tipos`, `condicionais` e `repeticao`
    como etapas pendentes** na próxima R1 ou R3. A competência atual e o progresso mudam.
  - "Ausente = 0" passou a ser "ausente = não diagnosticada": muda a justificativa e o nível inicial
    (intermediário começa no 2).
  - Sessões do Tutor em andamento começam com sequências zeradas (inofensivo).
  - Na prática, todo banco de desenvolvimento ou de demonstração deve ser refeito (`dados_demo`, `dados_painel`).
    Não há VM com dados reais, então o risco é baixo.
- **Retenção e eliminação:**
  - `titular.py`: **sim**. As duas tabelas estão em `APAGAR` e na exportação, e `anonimizacao.TABELAS_DO_ALUNO`
    também as inclui.
  - `retencao.py`: **não**. Nenhuma operação para `planejador_onboarding` (conversa abandonada, `objetivo`) nem
    para `planejador_diagnosticos`. A `lgpd.md` já diz que cadastro e matrícula não têm prazo por data, mas a
    conversa abandonada é texto livre e deveria seguir `RETENCAO_DIALOGO_DIAS` (180).

## 5. Testes

Nenhum teste foi marcado como skip ou xfail. Dez funções foram removidas ou renomeadas. A maioria é ajuste
legítimo à regra nova, mas há três enfraquecimentos reais:

| Teste (main) | O que aconteceu | Avaliação |
|---|---|---|
| `test_nao_repete_item_ate_esgotar` | removido | **Enfraquece.** Perdeu-se a checagem "nunca pega item de outra competência" e a de esgotar exatamente os 6 itens. A não repetição só aparece de forma indireta em `test_fim_da_competencia...` (API). |
| `test_nivel_sem_itens_usa_o_mais_proximo` | removido; `test_nivel_esgotado_depois_de_acerto_nao_desce` cobre só o caso do acerto | **Enfraquece em parte** (o caso depois de um erro ficou sem teste) |
| `test_banco_de_itens_provisorio_e_consistente` | virou `test_banco_de_itens_e_consistente`. Não exige mais `_provisorio`, e "conclui pelo caminho 1-2-3-3" virou "conclui por domínio **ou fim dos itens**" | **Enfraquece.** Esconde o problema da seção 2: na base comum só se conclui pelo fim dos itens |
| `test_conteudo_provisorio_e_consistente` | não exige mais `_provisorio` nos JSON; passa a conferir 48 tópicos e as 3 trilhas | ajuste, mas tira a marca de PROVISÓRIO de um conteúdo ainda não validado (seção 6) |
| `test_acerto_sobe_erro_desce...`, `test_conclui_com_2_acertos...`, `test_resposta_correta_sobe_nivel...` | reescritos para 3/2/3 | ajuste legítimo |
| `test_inatividade_de_3_a_13...`, `test_inatividade_de_14_dias...` | viraram 3 a 6 e 7 dias | segue a mudança de 14 para 7 (seção 2) |
| `test_nao_pula_abaixo_do_limiar_nem_fora_do_perfil` | inverteu a asserção: "b" com nota 1 agora **sai** | segue a regra nova (dominado sai) |
| `test_feedback_revisavel`, `test_painel` | DEMO-P04 passa de `incentivar` para `refazer_trilha`; total do planejador de 13 para 14 | consequência dos 7 dias |
| `test_orquestrador`, `test_correcoes`, `test_api_planejador`, `test_web` | notas 0,9/0,8 viram 1,0; `"1111"` vira `"111111"`; `"000"` vira `"00"`; nível inicial esperado de 1 para 2 | consequência das regras; as asserções de comportamento (queda, reforço, retomada, progresso) continuam. `test_web` tira `Matricula` dos campos usados pela tela (a tela não chama mais `/iniciar` diretamente) |

Acrescentados: `test_planejador_eap.py` (8), `test_primeiro_acesso.py` (9), `test_regras_eap.py` (5) e novos casos
em `test_tutor.py`. Total de funções de teste: de 382 para 407.

## 6. Conteúdo

- **Conteúdo antigo preservado:** sim. Os 6 tópicos e os 36 itens da `main` continuam com os mesmos ids,
  enunciados, alternativas, gabaritos e explicações. Só ganharam metadados (`trilha`, `etapa`, `uso`, `status`,
  `fonte`, `tempo_esperado_s`). Os materiais antigos continuam. Os perfis antigos foram **substituídos** (ritmo
  1,25/0,8 e `competencias_dispensaveis` sumiram), o que é a causa da quebra de sentido da seção 4.
- **Itens novos (84):** todos com 4 alternativas distintas, `indice_correto` válido (equilibrado: 21 em cada
  posição) e explicação não vazia. Conferi o gabarito dos 84 um a um e **não achei nenhum errado**. Ressalvas:
  - o status é `rascunho_llm` (gerados por LLM) e **nenhum foi validado pela Pessoa 4**;
  - `dev_01_n3_004` tem um distrator confuso ("O(n) no pior caso de todas as inserções");
  - `cib_01_n3_005` trata de varredura furtiva. Já traz o aviso "só com autorização", mas vale a revisão
    pedagógica.
- A marca `_provisorio` saiu da ementa, dos perfis e do banco de itens, e o CLAUDE.md da branch chama o conjunto de
  "base pedagógica alinhada à EAP". Itens `rascunho_llm`, materiais "PROVISÓRIO para a A4 revisar" e 38 tópicos
  sem itens nem material **continuam provisórios**. Isso contraria a regra do CLAUDE.md de marcar o que é
  provisório.

## 7. Conflitos esperados no merge com a `main`

- **Textuais: nenhum.** A `main` local (`4262f99`) é o merge-base, então o merge é fast-forward. A árvore de
  `simulacao-merge` já contém exatamente a branch (as mudanças estão no índice, sem commit). Se a `main` remota
  tiver avançado, refazer com `git fetch` (falhou nesta revisão por acesso).
- **Semânticos (o que o merge "aceita" sem avisar):**
  1. D7: `ORQ_INATIVIDADE_REFAZER_DIAS` de 14 para 7, inclusive nos `.env` existentes que não definem a variável.
  2. Critério de conclusão do Tutor e da R1: 2 para 3 no nível 3. Na base comum, a conclusão passa a ser só pelo
     fim dos itens.
  3. Perfis sem `competencias_dispensaveis`: matrículas e bancos antigos mudam de trilha no próximo
     replanejamento.
  4. A tela de matrícula por perfil e horas deixa de existir. O primeiro acesso exige onboarding e diagnóstico.
  5. Documentos desatualizados: matriz "Quem pode chamar o quê" (`arquitetura.md`), inventário e retenção
     (`lgpd.md`), e `.env` da VM e `deploy/` para o piloto (2/4/8 dias, `PILOTO_ESCOPO=piloto`).
  6. O CLAUDE.md da branch reescreve a seção "Quem faz o quê". Conferir o texto antes de aceitar, porque é a
     instrução que o Claude Code segue neste repositório.

## 8. Recomendação

**Aceitar como está:**

- Planejador com trilha, enquadramento, prazo e escopo; diagnóstico; onboarding com LLM local e queda para
  regras, que validam os campos.
- Regra `lacuna` e `revisar_material`; nível inicial e itens evitados no Tutor.
- Migrações (só aditivas); integração com `titular.py` e `anonimizacao.py`; auditoria sem texto livre.
- Conteúdo antigo intacto; 84 itens novos com gabarito correto na minha conferência; materiais do piloto.

**Ajustar antes do merge (pequeno, posso fazer na A3):**

1. Testes de autenticação das 6 rotas novas: 401 sem login, 403 para outro aluno e para docente nos POST, CSRF.
   Atualizar a matriz da arquitetura.
2. Retenção: operação para `planejador_onboarding`, apagando o `historico` de cadastro não concluído após
   `RETENCAO_DIALOGO_DIAS`. Decidir o destino do `objetivo` (apagar após a matrícula ou seguir o diálogo).
   Atualizar o inventário da `lgpd.md`.
3. `objetivo` na rota do docente: tirar do `GET .../primeiro-acesso` para o papel docente, ou auditar a consulta.
4. Base comum com 2 itens por nível: ou acrescentar itens (mínimo de 3 no nível 3) ou parar de tratar "itens
   acabaram" como conclusão da R1 sem domínio (por exemplo, exigir acerto mínimo ou sinalizar ao docente).
   Restaurar a asserção forte no teste do banco para os tópicos que tiverem itens suficientes.
5. Restaurar os testes de não repetição (incluindo "nunca outra competência") e de nível esgotado depois de um
   erro.
6. Voltar a marcar como PROVISÓRIO o que não foi validado (flag nos JSON ou por item via `status`, com um teste
   que exija `status` diferente de "validado" enquanto a A4 não revisar). Ajustar o texto do CLAUDE.md.
7. Limitar a repetição de `revisar_material` (uma vez por sessão, como o reforço) e o número de mensagens do
   onboarding (cada uma chama o LLM).
8. Refazer os bancos de demonstração depois do merge.

**Perguntar ao Tiago:**

1. Quem decidiu 3/2/3 e os 7 dias de refazer trilha: está no documento 1.2.5 aprovado pela Pessoa 2/Pessoa 4?
   Vale substituir a nossa D7 (14 dias)?
2. No piloto, `INATIVIDADE_DIAS=2` deve valer também para o alerta do painel e do Relatório, ou só para o
   incentivo? Se for só para o incentivo, precisamos de duas variáveis.
3. Qual LLM gerou os 84 itens e os materiais (`origem: llm`)? Foi local (Qwen/Ollama) ou serviço externo (R07)?
4. A A4 já viu os itens? Existe planilha de revisão? Quando entra o `status` validado?
5. O piloto só com `dev_01`/`dev_02` (ou `cib_01`/`cib_02`), com a base comum fora do escopo mas dentro do
   diagnóstico, é intencional? O reforço por lacuna cai em tópico fora da trilha (`repeticao`).
6. Os tópicos da base comum terminam só pelo fim dos itens: é aceitável no piloto, ou vale escrever mais itens
   de nível 3?
7. O docente precisa ver o `objetivo` do aluno?
