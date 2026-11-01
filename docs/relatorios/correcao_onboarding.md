# Correção do onboarding do primeiro acesso (01/11/2026)

> Frente A3, branch `docs-fechamento`. Corrige as falhas relatadas em `docs/relatorios/correcoes_tela_aluno.md`
> (seção 4): o onboarding gravava dados que o aluno não informou, e as justificativas do Planejador aceitavam
> cópia do prompt. Teste de ponta a ponta **LOCAL**, com o modelo pequeno **`qwen3:1.7b`**. Nada em `conteudo/`
> foi alterado; sem commit.

## Resumo

| Item | Resultado |
|---|---|
| Dois alunos novos pedem Dev (teste real com o 1.7b) | **os dois matriculados em Dev** (antes: os dois em Defesa Cibernética) |
| `./run_tests.sh` | **758 passed, 9 xfailed, 1 warning in 327.46s (0:05:27)** (eram 748 passed; +10 testes novos) |
| Testes novos | 10 em `tests/test_primeiro_acesso.py` (LLM simulado: (a) a (d), confirmação, rotas, sem LLM, limite, justificativas) |
| Os testes novos pegam o defeito? | sim: rodados contra o `onboarding.py` antigo, 4 falham (o do limite passa nos dois, porque o limite já existia) |

## O que mudou

### `src/tia/agentes/planejador/onboarding.py`

O desenho passou a ser: **o código entende e decide; o LLM só sugere, e só onde as regras não entendem.**

1. **Só o campo da pergunta da vez** (`CAMPOS_DA_PERGUNTA`). Trilha só na pergunta da trilha; horas (e os dias
   ditos junto) só na de horas; objetivo só na de objetivo. Qualquer outro campo devolvido pelo LLM é
   descartado. O LLM é consultado só nas perguntas de trilha e de horas (`PERGUNTAS_COM_LLM`), com um prompt por
   pergunta que pede só aquele campo (`PROMPT_TRILHA`, `PROMPT_HORAS`). O prompt de horas não tem mais o
   exemplo com número que o 1.7b copiava.
2. **Valor ancorado no texto do turno** (`aceitar_do_llm`):
   - **trilha:** aceita só se a mensagem cita palavras dessa trilha (`trilhas_citadas`, que ignora negação:
     "não quero segurança" não conta). Mensagem que cita só uma trilha é decidida pelas regras; se cita as duas,
     a escolha do LLM desempata, desde que esteja entre as citadas;
   - **horas:** a sugestão do LLM só vale se sair dos números que o aluno escreveu: o próprio número, ou por dia
     vezes os dias citados, 5 ou 7 (`horas_ancoradas`). Números por extenso e "e meia" contam ("duas horinhas nos
     dias de semana" vira 2 × 5 = 10);
   - **mensagem vaga:** "ainda não sei, qual a diferença" não grava nada e mostra a explicação das trilhas.
     Sem número na resposta de horas, a pergunta volta com exemplos (`HORAS_DE_NOVO`). Sem trilha clara:
     `TRILHA_DE_NOVO`, com as duas opções.
3. **Dias, objetivo e confirmação só pelo código.** Os dias vêm das regras, na resposta de horas, e nunca são
   sobrescritos pelo LLM (o caso seg–sex que virou seg–sáb). O objetivo é o texto do aluno ("pular" deixa vazio).
4. **Confirmação obrigatória** (`_confirmacao`):
   - conclui só com "sim" explícito (sim, confirmo, correto, certo, isso, exato, ok, pode seguir) e sem correção
     na mesma mensagem;
   - "não" com correção ("não, são 6 horas por semana") aplica a correção e mostra o resumo de novo;
   - **"não" sem correção volta ao começo das perguntas**, sem os valores anteriores (`REFAZER`);
   - resposta ambígua ("hmm", ou "sim" e "não" juntos) repete o resumo pedindo sim ou não
     (`CONFIRMACAO_DE_NOVO`).
5. **Limite** `ONBOARDING_MAX_MENSAGENS`: inalterado (mensagens por conversa e chamadas ao LLM por aluno). A volta
   pelo "não" continua contando mensagens.

Textos novos ao aluno (`TRILHA_DE_NOVO`, `HORAS_DE_NOVO`, `CONFIRMACAO_DE_NOVO`, `REFAZER`) marcados como
`# PROVISÓRIO`, a validar com a Pessoa 4.

### `src/tia/api/rotas_primeiro_acesso.py`

O diagnóstico e a matrícula (`/primeiro-acesso/concluir`) exigem `_cadastro_confirmado`: cadastro concluído (o
que só acontece com "sim") **e** trilha e horas válidas (`onboarding.dados_completos`). Sem isso, 409 "Conclua o
cadastro (onboarding) e confirme os dados com "sim" antes de montar a trilha."

### `src/tia/agentes/planejador/justificar.py`

`copia_do_prompt` compara cada frase com o prompt enviado e rejeita:

- o detalhe da linha da etapa ("(nota no diagnóstico: 0.33; 1.5 h)", "sem diagnóstico") — o caso visto no T01;
- o nome da etapa sozinho;
- frase com menos de 3 palavras, todas tiradas do prompt ("frase", do exemplo do formato `'1. frase'`);
- cópia das instruções ou da lista: metade ou mais das trincas de palavras da frase já estão no prompt.

A etapa rejeitada fica com a justificativa determinística do Planejador e origem `fallback`. Origem `LLM` só
para texto genuíno. A trilha recebe `falha_llm: "copia_do_prompt"`, e a tela do aluno traduz como "a IA repetiu
o pedido em vez de justificar" (`app.js`, mapa `FALHA`).

### Testes alterados (e por quê)

- `test_primeiro_acesso.py::test_onboarding_com_llm_e_queda_para_regras`: o LLM devolvia trilha e horas na
  pergunta da trilha, e o teste esperava as duas gravadas. Pelo item 1, agora só a trilha é gravada, e as horas
  são perguntadas depois.
- `test_planejador.py` (2 testes): o mock respondia "Frase B.", "Frase 1." numa ementa de teste com etapas
  chamadas "A", "B"... Isso é literalmente a palavra do exemplo do formato mais o nome da etapa, ou seja, cópia
  do prompt pela regra nova. O texto do mock virou "Motivo B."; as verificações não mudaram.

### Testes novos (`tests/test_primeiro_acesso.py`)

| Teste | O que verifica |
|---|---|
| `..._todos_os_campos_de_uma_vez_...` (a) | "não sei" não grava nada; Dev vence o cyber do LLM; dias seg–sex e objetivo do texto, apesar do LLM; o `confirmou: true` do LLM não confirma; o LLM é chamado 3 vezes, nunca no objetivo nem na confirmação |
| `..._trilha_errada_...` (b) | o LLM diz cyber, o aluno disse dev: grava dev; "não quero segurança, prefiro programar" é dev; citando as duas, o LLM desempata; pelas rotas, matrícula em Dev |
| `..._copia_o_exemplo_do_prompt_...` (c) | 10 h para "depende da semana" é descartado e a pergunta volta; 10 h para "duas horinhas nos dias de semana" é aceito (ancorado), com dias pelo código |
| `..._texto_vazio_...` (d) | resposta vazia do LLM: tudo por regras até concluir |
| `test_confirmacao_exige_sim_explicito_...` | "hmm" e "sim, não precisa mudar" não concluem; "não" volta à trilha sem dados; o objetivo é perguntado de novo |
| `test_rotas_nao_matriculam_sem_o_sim` | sem "sim", diagnóstico e matrícula dão 409 |
| `test_onboarding_sem_llm_do_comeco_ao_fim` | `ONBOARDING_USA_LLM=0`: o LLM nunca é chamado (ele lança erro se for) e o percurso vai até a matrícula em Dev |
| `test_limite_de_mensagens_vale_tambem_depois_do_nao` | o "não" não zera a conta de mensagens |
| `test_justificativa_que_copia_o_prompt_...` | eco do detalhe de cada linha (o caso do T01): todas `fallback`, `falha_llm` `copia_do_prompt`, decisão `fallback` |
| `test_justificativa_genuina_continua_como_llm_...` | frases genuínas ficam LLM; "frase" e cópia das instruções caem; decisão `parcial` |

## Teste de ponta a ponta (local, `qwen3:1.7b`)

Dois alunos novos criados por `python -m tia.seguranca.usuarios criar` (senha temporária, troca no primeiro
login), percorridos pela API com login real. A mesma conversa que antes levava a Defesa Cibernética: primeiro
"ainda não sei, qual a diferença entre as duas?", depois "vou de desenvolvimento de software".

| | A2026-T03 | A2026-T04 |
|---|---|---|
| Configuração | local (`escopo: completa`) | perfil do piloto (prazo 8, escopo piloto) |
| "ainda não sei, qual a diferença…" | explicação das trilhas, **nada gravado** | igual |
| "vou de desenvolvimento de software" | `trilha: dev` (origem LLM, ancorada) | igual |
| "umas 2h por dia, menos no fim de semana" | 10 h, seg–sex (regras) | igual |
| Objetivo | o texto do aluno; dias não mudam | igual |
| Confirmação | "sim, está certo" → concluído | **"não, quero refazer" → volta à trilha, dados vazios**; refaz (Dev, "10 horas por semana", objetivo) e "sim" → concluído |
| Diagnóstico | 8 tópicos (base comum + `dev_01`, `dev_02`); veredito igual ao gabarito | igual |
| **Matrícula** | **Dev**, intermediário, 23 etapas | **Dev**, intermediário, 2 etapas (`dev_01`, `dev_02`), prazo 8, cabe no prazo |
| Justificativas | 23 de 23 genuínas (origem LLM) | 2 de 2 genuínas |
| Primeira sessão | 200, `dev_01`, nível 2 | igual |

Nenhum erro 5xx nos logs do uvicorn. Nesta rodada o 1.7b não copiou o prompt nas justificativas, então o filtro
de cópia não precisou agir no teste real; ele está coberto pelos testes com LLM simulado.

## Limitações e o que fica em aberto

- **O LLM agora ajuda pouco no onboarding.** Como todo valor precisa estar ancorado no texto, nas falas comuns as
  regras já decidem sozinhas. O LLM só acrescenta quando a trilha é citada junto com a outra (desempate) e
  quando as horas vêm numa forma que as regras não leem, mas com os números no texto. É a troca pedida:
  previsibilidade antes de flexibilidade.
- **Palavras de trilha fixas** (`PALAVRAS_TRILHA`). Um aluno que escolhe por descrição sem as palavras-chave
  ("quero proteger redes de empresas", sem "segurança") recebe a pergunta de novo com as opções. Ampliar a lista
  é decisão a combinar com a Pessoa 4.
- **"Não" refaz o cadastro inteiro.** Para corrigir um campo só, o aluno pode responder "não, são 6 horas por
  semana" ou "não, quero dev": a correção é aplicada direto.
- Cadastros concluídos **antes** desta correção (como os de A2026-T01 e A2026-T02, matriculados em Defesa
  Cibernética por engano) não são revistos automaticamente.
- Os textos novos ao aluno são `# PROVISÓRIO` até a Pessoa 4.

## Estado deixado na máquina

`data/tia.db` ganhou os usuários e as matrículas de A2026-T03 e A2026-T04 (senha "Nova-senha-teste-T-2026",
só desta máquina). Servidor parado. `.env` e `conteudo/` sem alteração.
