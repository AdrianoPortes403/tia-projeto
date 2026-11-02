# Redesenho visual da aplicação do aluno, parte 1 (01/11/2026)

> Frente A3, branch `redesign-interface`. Aplica a prévia de `docs/design/prototipo_redesign/` (Main, Trilha,
> Estudar, Relatorio, Entrar, PrimeiroAcesso, Confirmar) em `src/tia/web/static/`, reescrita no padrão do projeto
> (HTML/CSS/JS estáticos, sem as marcações do editor). O painel do docente (`painel/`) não foi tocado e continua
> **idêntico pixel a pixel** (mesmo hash da captura antes e depois, em 1280 e 390 px). Sem commit.

## Resumo

| Item | Resultado |
|---|---|
| `./run_tests.sh` depois de cada uma das 6 etapas | **758 passed, 9 xfailed** em todas (nenhum teste alterado) |
| Capturas (Chrome headless, 1280 e 390 px, página inteira) | 60 arquivos em `docs/relatorios/redesign/` |
| Rolagem horizontal em 360, 390, 1280 e 1440 px | nenhuma (Início, Trilha, Estudar, Relatório, Login) |
| Primeiro acesso de um aluno novo pela tela nova | A2026-R01: cartão Dev, Tempo, Objetivo, "Sim", diagnóstico, **matriculado em Dev** (29 etapas). A2026-R02: "Não, quero refazer" voltou à trilha sem os dados |
| Contrato da API, rotas, `chamar()` | sem mudança. Os ids existentes continuam no HTML, e os testes de ids, rótulos, URLs externas e segredos passam |

## Decisões aprovadas antes de editar

1. A aba "Perguntar ao tutor" saiu. O formulário e o histórico foram para dentro de **Estudar**, com os mesmos ids:
   `form-dialogo`, `campo-pergunta`, `campo-competencia`, `contador-pergunta` e `conversa`. Nenhum teste dependia de
   `data-tela="dialogo"`. O teste de ids exige que exista `tela-X` para cada `"X"` citado no JS, então
   `"dialogo"` saiu da lista `TELAS`, e o comentário que a citava entre aspas foi reescrito.
2. Novos: `data-tela="inicio"`, `tela-inicio` e ids das etapas do primeiro acesso. A aba "Estudo" virou "Estudar".
3. Depois do login e depois de montar a trilha, o aluno cai no **Início**.
4. O menu mostra o **código** do usuário (R08), não um nome, com um ícone no lugar das iniciais.
5. Itens da prévia sem função no sistema ficaram de fora: "Esqueci a senha", "Criar minha senha", "Questão 3 de 8"
   e "60% da competência". No login entrou a dica "Primeiro acesso? Entre com a senha temporária que você recebeu."
6. 5ª etapa na barra do primeiro acesso: **Diagnóstico**.
7. "Acertos seguidos": "Nível N de 3" e os acertos **Nesta visita**, contados só na página. A API não mudou.
8. Paleta só em `body.app-aluno`. Os tokens de `:root` (usados pelo painel) mantêm os valores. O tema escuro ficou
   para depois (sem prioridade): a página do aluno declara `color-scheme: light`.

## Paleta e contraste (WCAG AA)

Os tokens novos ficam em `tema.css`, no bloco `body.app-aluno`. O mesmo bloco redefine os tokens antigos para os
componentes de `estilo.css`. Os pares conferidos no cálculo de contraste passam no AA (texto 4,5:1; bordas e
indicadores 3:1). Seis pares da prévia falhavam e foram ajustados:

| Par da prévia | Contraste | Ajuste |
|---|---|---|
| foco dourado `#C9A227` sobre o creme | 2,1:1 (mín. 3) | anel duplo: contorno interno `#1F2A17` (13,2:1) + dourado; sobre o menu, o dourado sozinho dá 3,95:1 |
| foco dourado sobre o branco | 2,4:1 | o mesmo anel duplo |
| barra dourada (< 80%) sobre branco | 2,4:1 | dourado escuro `#8C6D00` (4,9:1 no branco; 4,0:1 no trilho `#ECE9DC`) |
| texto de etapa bloqueada `#6B7260` sobre `#ECE9DC` | 4,1:1 (mín. 4,5) | `#5E6454` (5,0:1) |
| borda de campo `#D8D6C6` | 1,5:1 | `#858A76` (3,6:1 no branco; 3,2:1 no creme) |
| verde claro `#A8B88A` sobre branco | 2,1:1 | usado só como decoração (fundo do avatar e da marca, com texto `#2A3720` a 5,9:1) |

Outros pares usados passam sem ajuste:

| Par | Contraste |
|---|---|
| branco sobre o oliva | 9,6 |
| creme sobre o oliva | 8,5 |
| texto sobre o creme | 13,3 |
| secundário sobre o creme | 5,9 |
| secundário sobre o branco | 6,7 |
| branco sobre o verde | 5,5 |
| `#2A3720` sobre o dourado | 5,2 |
| alerta | 8,1 |
| aviso | 6,7 |
| `#D9DEC8` sobre o menu | 6,9 |
| oliva sobre `#E6E9D2` | 7,7 |

A etapa atual dourada ganhou contorno `#8C6D00` e o rótulo em texto ("Em andamento"/"Etapa atual"): o estado não
depende só da cor.

## O que mudou por tela

### 1. Estrutura geral (`index.html`, `tema.css`, `estilo.css`)
- O topo virou **menu lateral** verde-oliva de 240 px: marca, Início, Trilha, Estudar, Meu relatório e, no rodapé,
  código, papel e "Sair".
  - São os mesmos botões `.aba` com `data-tela` e `aria-current="page"`, agora com ícone SVG `aria-hidden`.
  - Abaixo de 56rem (896 px), o menu **empilha no topo** em grade de 2 colunas.
  - Some sozinho quando `#abas` está escondido (login e primeiro acesso), por CSS `:has`, sem JS novo.
  - A coluna verde vai até o fim da página, por um gradiente no fundo do layout.
- Cartões brancos com raio de 18 a 24 px, sem borda. Botões com 52 px de altura mínima; o principal ("botão
  grande") tem 56 px.
- Fonte do sistema (`system-ui`); nada externo. O arquivo não tem nenhum `http(s)://` novo (o SVG inline dispensa
  `xmlns`).
- A faixa de espera e a faixa de erro (`comum.js`) ficaram iguais, só com a forma nova.

### 2. Início (nova)
- Saudação "Olá, CÓDIGO" e a situação real: trilha (quando a matrícula tem trilha) e "etapa N de M".
- Cartão **"Continue de onde parou"**, que muda conforme `/proximo`:
  - questão em aberto: "Continue de onde parou";
  - revisão: "Revisão antes de seguir";
  - próxima etapa: "Próxima etapa";
  - trilha concluída: o cartão vira "Parabéns!" e o botão some.
- O cartão traz a barra de etapas concluídas (`role=progressbar`) e o botão **Continuar**, que leva a Estudar.
- **Sua trilha** resumida: até 5 etapas em volta da atual, com marcador concluída (✓), atual (número, dourado) ou
  bloqueada (cadeado). O link "Ver trilha completa" leva à Trilha.
- **Próximos passos**, só com dados reais:
  - reforço em curso;
  - aviso da última decisão do orquestrador;
  - trilha que não cabe no prazo;
  - a etapa seguinte;
  - o cartão do relatório.
- Rotas: `GET /aluno/{id}/estado`, `GET /alunos/{id}/trilha` e `GET /aluno/{id}/proximo`, todas existentes.

### 3. Trilha
- Cabeçalho com perfil, trilha e prazo, mais "Siga na ordem. Cada etapa libera a próxima." e a barra "N de M".
- Lista vertical numerada, ligada por uma linha (verde depois das concluídas), com grupos "Base comum" e
  "Trilha …" pelo prefixo do tópico (`dev_` ou `cib_`).
- A etapa atual tem borda dourada e o botão **Continuar**. É o mesmo `#ir-estudar`, movido pelo JS para dentro dela
  e devolvido ao rodapé antes de cada redesenho.
- As bloqueadas aparecem com fundo creme e cadeado.
- Justificativa do Planejador, origem, "Antes, revise" e desafio prático ficam em **"Por que esta etapa?"**
  (`<details>`), recolhidos.
- Os avisos de reforço, decisão e prazo continuam no topo.

### 4. Estudar
- Cabeçalho: grupo, etapa e nome da competência.
- Questão em **cartão**, com alternativas de aparência de botão e letra A–D. Por dentro continuam rádios num
  `fieldset`, apenas escondidos visualmente: teclado, leitor de tela e o mesmo `name="alternativa"`.
- Botão grande **Enviar resposta**.
- A correção vem num **balão do tutor** (avatar "T") com:
  - veredito com ✓ ou ✗;
  - explicação;
  - origem e motivo;
  - **"Ver fonte"** recolhido, que mostra o nome do arquivo do material (R03, mesmo `blocoFontes`);
  - nível.
- A alternativa certa e a marcada recebem os selos "correta" e "sua resposta".
- **Pergunte ao tutor**: campo com botão-ícone (`aria-label="Enviar pergunta"`), contador e filtro de assunto.
  - O histórico aparece em balões: pergunta à direita, resposta do tutor à esquerda.
  - Uma resposta **corrigida pelo professor** leva o rótulo "Corrigida pelo professor" e "Origem: professor"
    (R12, mesma lógica `vetada || origem === "docente"`).
- Painel lateral:
  - **Seu nível agora**: "Nível N de 3", com barra;
  - **Nesta visita**: "Acertos: X de Y.";
  - a dica e o link "Voltar à trilha".
- O reenvio com o mesmo `evento_id`, "Buscar a atividade atual" e os avisos do orquestrador ficaram iguais.

### 5. Meu relatório
- **3 números grandes**: questões respondidas, taxa de acerto e etapas concluídas "N de M".
- **Por competência**: barras com o **nome** da competência, vindo da ementa, inclusive para tópicos fora da
  trilha.
  - O texto é "acertos de respostas (taxa)". A barra fica verde a partir de 80% e dourado-escuro abaixo.
  - Antes das barras vem a frase de desempenho com a tendência; depois, "Etapas da trilha" com o estado de cada uma.
- Coluna de avisos:
  - **Correções do professor** (fundo de aviso);
  - aviso de inatividade;
  - Pontos a reforçar;
  - Participação;
  - **Sobre os textos do tutor**, com a mesma conta de antes: o total é a soma de `por_origem` (por exemplo
    "27 de 28 textos do tutor").
- Ação principal: **Voltar a estudar**. "Gerar resumo" ficou como ação secundária, no cartão "Resumo do tutor".

### 6. Login e primeiro acesso
- **Login**: cartão central sobre fundo creme quadriculado, com marca "T", "Entrar no TIA", Usuário, Senha e o botão
  **mostrar/esconder senha**.
  - O botão tem `aria-pressed` e `aria-label`.
  - Depois do envio, a senha volta a ficar oculta.
  - Embaixo vem a dica do primeiro acesso.
- A **troca da senha temporária** (mesmo `form-senha`, do `comum.js`) mostra a barra de etapas no passo **Senha**.
- **Primeiro acesso** em etapas: **Senha, Trilha, Tempo, Confirmar, Diagnóstico**, com barra no topo e
  `aria-current="step"` na etapa atual. Cada escolha envia um **texto** para a mesma conversa
  (`POST /onboarding/mensagem`). Quem entende e decide continua sendo o servidor.
  - **Trilha**: dois cartões de escolha (rádios). Ao continuar, o texto enviado é o nome da trilha. As descrições
    são as do próprio tutor (`EXPLICACAO_TRILHAS`, já validada).
    - "Ainda não sei. Explique a diferença." envia a dúvida, e o tutor responde com a explicação no balão.
  - **Tempo**: campo livre para horas e dias. Depois vem o objetivo, com o botão **Pular** (envia "pular").
  - **Confirmar**: "Confira antes de começar", com lista de trilha, horas, dias e objetivo (`resposta.dados`).
    - **Sim, está certo** envia "sim". **Não, quero refazer** envia "não" e recomeça.
    - "Quer corrigir só um item?" aceita "não, são 6 horas" e devolve o resumo atualizado.
    - A matrícula **continua exigindo o "sim"** no servidor (409 sem ele, `_cadastro_confirmado`).
  - **Diagnóstico**: questões com as mesmas alternativas-botão e, ao fim, **Montar minha trilha**.

## O que ficou diferente da prévia, e por quê

| Prévia | Na aplicação | Motivo |
|---|---|---|
| Nome e iniciais do aluno ("Adriano", "AP") | código do usuário e ícone | R08 (decisão 4) |
| "Questão 3 de 8", "60%" da competência | barra de etapas da trilha; nível N de 3 | a API não tem total de questões nem percentual por competência (decisão 5) |
| "2 de 3 acertos seguidos" | "Nesta visita: Acertos X de Y" | a API não expõe a sequência; o contador da página zera ao recarregar (decisão 7) |
| Menu com links `<a>` | botões `.aba` com `aria-current="page"` | a navegação é na mesma página (sem rotas no navegador); mantém `data-tela` e o JS |
| Alternativas como `<button>` | rádios estilizados como botões | mantém `name="alternativa"`, o teclado (setas) e o fieldset/legend |
| Cartões de trilha com `role=radio` | rádios reais estilizados | mesmo comportamento acessível, sem ARIA manual |
| 4 etapas (Senha, Trilha, Tempo, Confirmar) | 5, com Diagnóstico | o diagnóstico é obrigatório e a prévia não o mostrava (decisão 6) |
| Etapa "Objetivo" ausente | objetivo dentro de "Tempo", com "Pular" | a conversa do servidor pergunta o objetivo; não há etapa própria na barra |
| "Sim, criar meu plano" | "Sim, está certo" | depois do "sim" vem o diagnóstico, não o plano; o plano sai em "Montar minha trilha" |
| "Não, quero corrigir" volta à tela anterior | "Não, quero refazer" recomeça; campo para corrigir um item | é o comportamento do servidor ("não" sem correção recomeça) |
| Descrições curtas das trilhas na prévia | texto da explicação do tutor | texto já validado; a prévia trazia só os tópicos do piloto |
| Avisos "Sugestão do tutor: reforço de 5 minutos" | avisos reais do orquestrador e do Planejador | os textos da prévia são exemplos |
| Relatório só com competências e 2 avisos | mais Pontos a reforçar, Participação e Resumo do tutor | os indicadores do Agente 3 continuam visíveis, em cartões menores |
| Login com "Código de aluno" | "Usuário" | docentes e admins também entram por esta página (e são mandados ao painel) |
| Tema escuro | só claro | sem prioridade (decisão 8); a página declara `color-scheme: light` |

## O que não foi possível ou ficou de fora

- **"Esqueci a senha" e "Criar minha senha"**: não existem no sistema (a senha é redefinida pelo admin).
  Não foram criados fluxos novos, como pedido.
- **Sequência de acertos do servidor**: exige mudança na API, que fica como melhoria futura.
- **Tema escuro do aluno**: não feito.
- **Recarregar a página no meio do primeiro acesso** recomeça a conversa. É o comportamento de
  `/onboarding/iniciar` (já era assim antes), não do redesenho.
- **Capturas com etapas concluídas na Trilha**: os alunos com login (DEMO-W01, A2026-R01) não têm etapa concluída.
  O estilo "concluída" (✓ verde, linha verde) foi conferido só no código e no resumo do Início.
- **Teclado**: conferido o foco visível com Tab real (`final_foco_*.png`). Não houve teste com leitor de tela.

## Capturas (`docs/relatorios/redesign/`)

Todas em 1280 e 390 px, com dados reais da API local (`qwen3:1.7b` na correção da questão).

| Arquivos | Tela |
|---|---|
| `etapa1_*` | estrutura nova sobre as telas antigas (menu lateral) |
| `etapa2_inicio_*` | Início de DEMO-W01 |
| `etapa3_trilha_*`, `etapa3_trilha_porque_*` | Trilha, recolhida e com "Por que esta etapa?" aberto |
| `etapa4_estudar_*` | questão, alternativa marcada, resposta do tutor (59,4 s, fonte `funcoes.txt`), "Ver fonte" aberto |
| `etapa5_relatorio_*`, `etapa5_estudar_depois_*` | relatório; Estudar depois da resposta (revisão sugerida pelo orquestrador) |
| `etapa6_login_*`, `etapa6_senha_*` | login e troca da senha temporária (passo Senha) |
| `etapa6_trilha*`, `etapa6_tempo_*`, `etapa6_objetivo_*`, `etapa6_diagnostico*`, `etapa6_inicio_novo_*`, `etapa6_trilha_novo_*` | primeiro acesso completo do A2026-R01 até a matrícula em Dev |
| `etapa6b_*` | A2026-R02: confirmação já com o resumo único e o "Não, quero refazer" |
| `final_foco_menu_1280.png`, `final_foco_link_1280.png` | foco por teclado (Tab real) |

`etapa6_confirmar_*` é anterior a um ajuste: mostrava o resumo duas vezes (texto do tutor e lista). Hoje, na
confirmação, a lista substitui o texto (ver `etapa6b_confirmar_*`).

## Arquivos alterados

| Arquivo | O quê |
|---|---|
| `src/tia/web/static/tema.css` | bloco `body.app-aluno` com a paleta nova e os tokens antigos redefinidos (o `:root` do painel não mudou) |
| `src/tia/web/static/estilo.css` | regras novas, todas sob `.app-aluno` (as antigas, usadas pelo painel, ficaram) |
| `src/tia/web/static/index.html` | menu lateral, Início, Trilha, Estudar (com a pergunta ao tutor), Relatório, login e primeiro acesso em etapas; mesmos ids |
| `src/tia/web/static/app.js` | Início; barra, ícones e marcadores; Trilha em percurso; Estudar com balões e "Nesta visita"; relatório em números, barras e avisos; primeiro acesso em etapas; mostrar senha |

Não mudaram: `comum.js`, `painel/`, rotas, modelos, testes e `conteudo/`.

## Estado deixado na máquina

`data/tia.db` local (dados fictícios):

- DEMO-W01 respondeu uma questão para a captura (errou de propósito) e o orquestrador abriu uma revisão de "Laços de
  repetição".
- Usuários novos: A2026-R01 (matriculado em Dev) e A2026-R02 (cadastro recomeçado, sem matrícula), ambos com a senha
  "Nova-senha-teste-R-2026", válida só nesta máquina.

O servidor está parado.
