# Correções da tela do aluno e teste do primeiro acesso (01/11/2026)

> Frente A3, branch `docs-fechamento`. Corrige as 3 falhas de exibição do teste funcional local
> (`docs/relatorios/teste_funcional_local_2026-11-01.md`) e testa o primeiro acesso de alunos novos. Teste
> **LOCAL**, com o modelo pequeno **`qwen3:1.7b`**: a qualidade das respostas não representa o modelo final da
> VM. Nada em `conteudo/` foi alterado. O onboarding não foi corrigido, só relatado. Sem commit.

## Resumo

| Item | Resultado |
|---|---|
| 1. "26 de 21" em "Meu relatório" | **corrigido**: agora "26 de 27" |
| 2. Código do tópico em "Meu relatório" | **corrigido**: mostra o nome da ementa |
| 3. "Fonte: texto do próprio item" no diálogo | **corrigido**: "Esta resposta não usou trecho do material do curso." |
| Testes novos em `tests/test_web.py` | 3 |
| `./run_tests.sh` | **748 passed, 9 xfailed, 1 warning in 399.32s (0:06:39)** (eram 745 passed) |
| 4. Primeiro acesso de aluno novo | o fluxo técnico funciona de ponta a ponta, mas **o onboarding gravou dados que o aluno não informou**: trilha Defesa Cibernética no lugar de Dev, nos dois alunos |

## Correções (`src/tia/web/static/app.js`)

1. **Mesma base no numerador e no denominador** (`carregarRelatorio`). O `qualidade_feedback.por_origem` soma
   as explicações das questões e as respostas do diálogo. A tela dividia pela contagem só das questões
   (`respostas_com_origem`). Agora o total é a soma de `por_origem`, e o texto diz o que conta: "26 de 27
   textos do tutor (explicações e respostas às suas perguntas) escritos pela IA local e conferidos". As linhas
   "barradas" e "texto fixo" usam a mesma base, e as três somam o total.
2. **Nome da competência** (`carregarRelatorio`). Antes de pedir o relatório, a tela carrega a ementa
   (`GET /conteudo/ementa`, função `carregarNomes`, que já existia para o primeiro acesso). Os tópicos fora da
   trilha, praticados pela rota avulsa, passam a aparecer pelo nome, por exemplo "Análise de complexidade de
   tempo e espaço (notação Big-O): 12 de 14 (86%)". O cartão "Correções do professor" também ganhou o nome
   ("Protocolos de aplicação na prática: DNS, HTTP e TLS · questão cib_02_n1_001").
3. **Texto sem fonte no diálogo** (`blocoFontes`, `itemConversa`). `blocoFontes` recebe o texto para o caso sem
   fonte. O diálogo usa "Esta resposta não usou trecho do material do curso.". O feedback de questão mantém
   "Fonte: texto do próprio item (sem trecho do material).", que lá é correto. Como antes, a resposta
   `fallback` do diálogo não mostra o bloco de fonte.

Conferido na tela (Chrome headless, DEMO-W01): os três textos novos aparecem; nenhuma exceção de
JavaScript; único 404, o `/favicon.ico`.

### Testes (`tests/test_web.py`)

O arquivo testa o front sem navegador: leitura estática do `app.js` e contrato com a API (não há `node` nem
Playwright na máquina).

- `test_relatorio_qualidade_usa_a_mesma_base_no_numerador_e_no_denominador`: o total sai de `por_origem`, não
  de `qf.respostas_com_origem`. Confere também, em `indicadores.qualidade_feedback`, que `por_origem` soma as
  questões com origem e o diálogo.
- `test_relatorio_mostra_o_nome_de_competencia_fora_da_trilha`: `carregarNomes()` roda antes do pedido do
  relatório. Pela API, um aluno matriculado responde a um item de `dev_01` pela rota avulsa: `dev_01` aparece no
  desempenho e não no progresso, e a ementa tem nome para toda chave do desempenho.
- `test_dialogo_sem_fonte_nao_fala_de_item`: o texto do diálogo não menciona "item", tem até 80 caracteres e é
  o usado em `itemConversa`; o feedback de questão continua com o texto do item.
- `CAMPOS_USADOS`: `respostas_com_origem` saiu da lista de campos que o front lê.

## 4. Primeiro acesso com alunos novos

Dois alunos criados por `python -m tia.seguranca.usuarios criar --papel aluno` (senha temporária), percorridos
pela API com login real. Os dois pediram a trilha **Dev**.

- **A2026-T01**: configuração local (`escopo: completa`, sem prazo).
- **A2026-T02**: perfil do piloto passado por variável de ambiente (`PILOTO_PRAZO_DIAS=8`,
  `PILOTO_ESCOPO=piloto`, `INATIVIDADE_DIAS=2`, `ORQ_INATIVIDADE_REFAZER_DIAS=4`), sem mudar o `.env`.

No diagnóstico, o roteiro acertou toda a base comum e errou metade das questões da trilha, pelo gabarito.

### O que funcionou

- **Cadastro e senha:** login com a senha temporária devolve `trocar_senha: true`. Antes da troca, as rotas
  recusam com 403 "Troque a senha temporária antes de continuar." Senha fraca: 422 "A senha precisa ter pelo
  menos 10 caracteres." Depois da troca, 200 e sessão nova.
- **Passos:** `primeiro-acesso` vai de `onboarding` a `diagnostico`, depois `concluir` e por fim `matriculado`.
  Antes da matrícula, `/estado` dá 404.
- **Ordem obrigatória:** concluir antes do diagnóstico dá 409 "Conclua o diagnóstico antes de montar a
  trilha."; concluir duas vezes dá 409 "O aluno já está matriculado; o primeiro acesso já foi feito."
- **Diagnóstico:** 8 tópicos (6 da base comum e os 2 do piloto da trilha), 22 questões por aluno. O `acertou`
  bateu com o gabarito nas 44 respostas. Notas: base comum 1,0; `cib_01` e `cib_02` 0,3333.
- **Planejador:** perfil `intermediario` enquadrado pelo diagnóstico (P = 2,5). A base comum dominada sai da
  trilha, e `nivel_inicial` 2 vem da nota 0,33. Decisão `matricula/planejar` com justificativas do LLM.
  - **T02 (piloto):** 2 etapas (`cib_01`, `cib_02`), prazo 8 dias, `cabe_no_prazo: true`, justificativas
    coerentes em português.
  - **T01 (completa):** 19 etapas (`cib_01` a `cib_19`), das quais 17 sem itens nem material, como já
    registrado em `docs/limitacoes_conhecidas.md`, item 1.
- **Depois da matrícula:** `/proximo` indica `iniciar_sessao` em `cib_01`, e a primeira sessão gerenciada abre
  no nível 2.
- Nenhum erro 5xx nos logs do uvicorn.

### O que falhou (não corrigido)

1. **O onboarding grava dados que o aluno não informou** (`agentes/planejador/onboarding.py`, `processar` e
   `PROMPT_EXTRACAO`). A primeira mensagem dos dois alunos foi "ainda não sei, qual a diferença entre as duas?".
   - **T01:** o LLM devolveu de uma vez trilha `defesa_cibernetica`, 10 h por semana, dias seg–sáb e objetivo
     "aprender sobre segurança e redes". O aluno não disse nada disso, e o código foi direto ao resumo de
     confirmação. Os "10 h" coincidem com o exemplo do próprio prompt ("2h por dia, de segunda a sexta" = 10).
   - **T02:** o LLM devolveu `trilha: defesa_cibernetica` em vez de `duvida_trilha: true`.
   - **Consequência:** a explicação das duas trilhas (`EXPLICACAO_TRILHAS`) **nunca apareceu**, e os dois
     alunos, que queriam Dev, foram matriculados em **Defesa Cibernética**. Bastou um "sim" na confirmação,
     resposta do roteiro.
   - **Causa no código:** `processar` aceita qualquer campo válido devolvido pelo LLM, qualquer que seja a
     pergunta da vez (só o prompt pede "Não invente valores"). Também não confere se o valor aparece no texto.
   - **Proteção que existe:** o resumo mostra os dados antes do "sim". Um aluno atento recusaria, mas o
     cadastro não deveria depender disso.
2. **O LLM troca um dado já respondido** (T02). Na resposta de horas ("2h por dia, menos no fim de semana"), os
   dias ficaram seg–sex, o que está certo. Na resposta seguinte, sobre o objetivo, o LLM devolveu dias com
   sábado, e o código sobrescreveu. O resumo mostrou seg–sáb.
3. **Justificativa que repete o prompt** (T01). As 19 justificativas foram, por exemplo, "(nota no diagnóstico:
   0.33; 1.5 h)" e "(sem diagnóstico; 3.0 h)", que são o detalhe da linha que o prompt envia
   (`justificar.montar_prompt`). Mesmo assim saíram com `origem_justificativa: "LLM"` e aparecem ao aluno na
   tela da trilha. No T02 as justificativas foram boas, então parece instabilidade do 1.7b, mas não há guarda
   contra eco.

### Estranhezas

- **Desafio prático em outra etapa:** o desafio de cada semana fica na última etapa da semana e fala dos
  tópicos anteriores. No T01, a etapa 4 (buffer overflow) traz o desafio de captura de tráfego (`cib_01` e
  `cib_02`). Parece intencional, mas na tela pode parecer trocado.
- **Contador de tópicos:** `topico_atual` indica o tópico da **próxima** questão. Ao responder a 3ª questão de
  Variáveis, já aparece "2/8".

### Não testado

- O primeiro acesso pela tela (`/app`), com cliques: o teste foi pela API. A tela da trilha do aluno novo não
  foi aberta no navegador.
- Recusar o resumo ("não") e recomeçar o cadastro; o limite de `ONBOARDING_MAX_MENSAGENS`; o onboarding sem
  LLM (só regras).

## Estado deixado na máquina

- `data/tia.db`: além dos dados do teste funcional, os usuários e as matrículas de A2026-T01 e A2026-T02
  (senha de teste (apenas local), só desta máquina). Para voltar ao banco de demonstração limpo: mover
  `data/tia.db` e rodar `python -m tia.web.dados_demo` e `python -m tia.web.dados_painel`.
- Servidor parado. `.env` e `conteudo/` sem alteração.
