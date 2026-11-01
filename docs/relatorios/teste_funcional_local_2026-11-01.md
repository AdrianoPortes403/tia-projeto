# Teste funcional ponta a ponta, local (01/11/2026)

> Frente A3, branch `docs-fechamento`. **Teste LOCAL**, na máquina de desenvolvimento (CPU), com o modelo
> pequeno **`qwen3:1.7b`** (`CHAT_MODEL` do `.env`) e `nomic-embed-text`. A qualidade das respostas **não
> representa o modelo final da VM**: erros de redação do 1.7b são esperados e não avaliam o conteúdo. O que
> se testou foi o **fluxo**: fontes certas, regras aplicadas, telas funcionando e nenhum erro de servidor.
> Tempo não foi medido (R09 fica para a VM). Nada em `src/` nem em `conteudo/` foi alterado; sem commit.
> Nenhuma falha foi corrigida: este documento só relata.

## Resumo

| Parte | Resultado |
|---|---|
| 1. Ollama e índice do Chroma | **funcionou** |
| 2. Bancos de demonstração, uvicorn, `/app` e `/app/painel/` | **funcionou** |
| 3. Percurso do aluno DEMO-W01 (API e navegador) | **funcionou**, com 3 problemas de exibição (abaixo) |
| 4. Percurso do docente (painel, alerta da ressalva, aprovar e vetar) | **funcionou** |
| 5. Relatório do aluno e da turma (grupo mínimo de 5) | **funcionou**, com 1 número incoerente na tela do aluno |
| Erros de servidor (5xx) | **nenhum** na API nem no log do uvicorn |
| Fontes com nome antigo (`provisorio_*`) | **nenhuma**, em 27 respostas com fonte |

Falhas a corrigir (todas de exibição na tela do aluno, `src/tia/web/static/app.js`):

1. **"Meu relatório", item 5: "26 de 21 escritas pela IA local e conferidas"** (numerador maior que o total).
2. **"Meu relatório", item 2: os tópicos do piloto aparecem pelo código** (`dev_01: 12 de 14 (86%)`), não pelo
   nome.
3. **"Perguntar ao tutor": resposta do diálogo sem fonte mostra "Fonte: texto do próprio item (sem trecho do
   material)."**, texto pensado para o feedback de questão.

## Como foi feito

- API percorrida por um roteiro Python (httpx) com login real (`TIA_AMBIENTE=producao`, autenticação ligada,
  cookie `tia_sessao` e cabeçalho `X-CSRF-Token`). O banco de itens foi lido só como gabarito, para escolher
  de propósito respostas certas ou erradas e conferir o veredito e o nível devolvidos pelo código.
- Telas abertas no Chrome headless (153), com login pelo formulário e clique em cada aba; conferidos o
  texto visível, os erros de console/JavaScript, os pedidos com status ≥ 400 e uma captura por aba.
- uvicorn com `TUTOR_TIMEOUT_LLM`, `PLANEJADOR_TIMEOUT_LLM`, `ONBOARDING_TIMEOUT_LLM` e
  `RELATORIO_TIMEOUT_LLM` = 300 s, passados por variável de ambiente (o `.env` não foi alterado).
  Nenhuma chamada ao LLM estourou o tempo (`falha_llm` nulo em todas).

## 1. Ollama e índice do Chroma

- `POST /api/chat` com `qwen3:1.7b` e `/nothink`: resposta em português, coerente.
- Coleção `material_curso`: **69 pedaços de 10 arquivos, 0 `provisorio_*`** (cib_01 16, cib_02 15, dev_02 14,
  dev_01 10, listas_strings 3, repeticao 3, variaveis_tipos 3, funcoes 2, condicionais 2, exemplo_recursao 1).
  O índice foi refeito depois do achado de 31/10 (82 pedaços, com 13 antigos).

## 2. Bancos de demonstração e servidor

- Já existia um `data/tia.db.bak` (11/10, 6 alunos), diferente do banco atual. Para não sobrescrevê-lo, ele
  foi renomeado para **`data/tia.db.bak.2026-10-11`**. Depois, `data/tia.db` (15/10) → **`data/tia.db.bak`**.
- `python -m tia.web.dados_demo`: criou DEMO-W01, W02 e W03 e os usuários DEMO-W01 e DEMO-DOCENTE.
- `python -m tia.web.dados_painel`: criou a turma DEMO-P01..P12 (8 intermediários e 4 iniciantes), para
  conferir o grupo mínimo. Verificação de inatividade: 1 incentivo, 2 trilhas refeitas.
- `/health` 200; `/app` 307 → `/app/`; `/app/` 200; `/app/painel/` 200; `/docs` 404 (esperado em produção).

## 3. Percurso do aluno DEMO-W01

**Login e primeiro acesso.** `POST /auth/login` 200 (`trocar_senha: false`). `GET /aluno/DEMO-W01/primeiro-acesso`
→ `passo: "matriculado"`: o `dados_demo` já matricula o aluno, então o onboarding e o diagnóstico **não se
aplicaram e não foram testados**.

**Trilha.** Perfil intermediário, só a base comum: Funções → Listas e strings → Recursão (`trilha: null`,
`escopo: completa`, porque o `.env` local não tem o perfil do piloto). Tela "Sua trilha" mostra as 3 etapas.
"Origem: justificativa padrão (a IA não respondeu)": esperado, porque o `dados_demo` roda sem LLM.

**Sessão gerenciada (orquestrador).** `POST /aluno/DEMO-W01/sessao` em `funcoes`: 200, decisão
`sessao/abrir_sessao`, **nível inicial 2**, que vem do diagnóstico (`EtapaTrilha.nivel_inicial`, nota 0,34).
Resposta pelo evento `resposta`: acerto, veredito "Você acertou.", fonte `funcoes.txt`, origem LLM.

**Tópicos do piloto.** Os 4 tópicos não estão na trilha do DEMO-W01. Pedir sessão gerenciada em `dev_01`
é recusado, como previsto:

> 409 `Sessão recusada: agora só é possível estudar 'funcoes' (competência atual); pedido: 'dev_01'.`

Por isso os 4 foram abertos pela rota avulsa `POST /tutor/sessao` (200 nos 4). Em cada um: uma pergunta ao
Tutor e respostas a itens.

| Tópico | Pergunta ao Tutor | Fonte citada | Itens respondidos |
|---|---|---|---|
| dev_01 | "O que significa dizer que um algoritmo é O(n)?" | `dev_01_complexidade.txt` | 14 (regra 3/2/3 completa) |
| dev_02 | "Qual a diferença entre pilha e fila?" | `dev_02_estruturas_lineares.txt` | 2 (1 certa, 1 errada) |
| cib_01 | "O que o handshake de três vias do TCP faz?" | `cib_01_tcpip_captura.txt` | 2 (1 certa, 1 errada) |
| cib_02 | "Para que serve o DNS?" | `cib_02_dns_http_tls.txt` | 2 (1 certa, 1 errada) |

- **Respostas do diálogo:** coerentes e em português nas 5 perguntas sobre o material (ex.: DNS "traduz nomes
  de domínio em endereços IP"; TCP "SYN, SYN-ACK e ACK"). Origem LLM, fonte do tópico certo.
- **Pergunta fora do material** ("Qual é a capital da França?"): origem `fallback`, sem fonte, "Não encontrei
  isso no material disponível; vale perguntar ao professor."
- **Veredito pelo código:** nas 21 respostas, `acertou` e `indice_correto` bateram com o gabarito do banco de
  itens. O veredito é o texto fixo do código ("Você acertou." / "Você marcou: C) O(n). A resposta correta é:
  B) O(log n).").
- **Fontes:** as 21 explicações de item citaram o arquivo do próprio tópico, com o nome novo. Origem LLM em
  todas; nenhuma barrada pela guarda.
- **Regra 3/2/3 (dev_01):** os 14 níveis bateram com o esperado:

| Respostas | Nível depois |
|---|---|
| 3 certas no nível 1 | sobe para 2 |
| 2 erradas no nível 2 | desce para 1 |
| 3 certas no nível 1 | sobe para 2 |
| 3 certas no nível 2 | sobe para 3 |
| 3 certas no nível 3 | `concluida: true`, `com_ressalvas: false` (domínio) |

Nos outros 3 tópicos, 1 certa e 1 errada mantiveram o nível 1, como previsto.

**Controle de acesso do aluno:** `/painel/alunos-em-risco` e `/relatorio/turma` → 403 "Acesso permitido só ao
papel docente."; `/aluno/DEMO-W02/estado` → 403 "Você só pode acessar os seus próprios dados."

**Telas (Chrome headless):** login pelo formulário e as abas Trilha, Estudo, Perguntar ao tutor e Meu
relatório abriram sem erro, sem exceção de JavaScript e sem chamada da API com erro. Único 404:
`/favicon.ico`.

## 4. Percurso do docente (DEMO-DOCENTE)

- Login 200. Telas Visão geral, Alertas de risco, Competências, Revisão docente e Auditoria abriram sem erro
  nem 4xx/5xx.
- **Alunos DEMO e alertas:** 15 avaliados, 8 com alerta. **Alerta da ressalva** em DEMO-P06:
  `conclusao_sem_dominio`, "Terminou as questões de Funções e modularização sem atingir o domínio, com acerto
  33% (mínimo para avançar 60%): não avançou e recomeça a competência." O DEMO-W01 recebeu
  `desempenho_em_queda` (40% contra 88%), consequência das respostas erradas de propósito.
- **Revisão:** 167 itens a revisar.
  - **Aprovar** o feedback 152: 200, e ele aparece em "aprovadas" (total 1).
  - **Vetar sem correção**: recusado, como previsto, com 422 `Value error, Ao vetar, informe a
    correcao_docente que o aluno vai ver.`
  - **Vetar com correção** o feedback 151 e o diálogo 16: 200. Aparecem em "vetadas" (total 3, com 1 da demo).
    O aluno vê a correção, com origem "docente"/"professor", na tela e em `/alunos/DEMO-W01/feedbacks`.
- **Auditoria:** consultas, aprovação e veto registrados com o usuário DEMO-DOCENTE.
- **CSV** (`/painel/exportar/indicadores.csv`): 200, cabeçalho com grupo mínimo 5.
- **Logout:** 204; o pedido seguinte dá 401 "Faça login para continuar (sessão ausente, expirada ou encerrada
  por inatividade)."

## 5. Relatório (Agente 3)

- **Aluno DEMO-W01:** 200, `provisorio: true`. Progresso 0 de 3 etapas (Funções em andamento, nível 2).
  Desempenho 16 de 21 (76%), por competência inclusive os 4 tópicos do piloto. Narrativa com origem LLM.
- **Aluno DEMO-P06:** `com_ressalvas: 1`, Funções com `taxa_sem_dominio` 0,333, coerente com o alerta do painel.
- **Turma** (`min_grupo: 5`):

| Grupo | Alunos | Resultado |
|---|---|---|
| todos | 15 | exibido. Por competência, só Funções (11 alunos, 74%) e Listas e strings (7, 77%); as outras 8, inclusive os 4 do piloto, "menos de 5" e suprimidas |
| intermediario | 11 | exibido, mesma supressão por competência |
| iniciante | 4 | **suprimido**: "menos de 5"; narrativa fixa "Grupo com poucos alunos: os indicadores não são exibidos, para proteger a privacidade (LGPD)." |

O painel aplica a mesma supressão (nível 3 "oculto (menos de 5 alunos)" na Visão geral; competências com
menos de 5 ocultas; filtro iniciante com `suprimido: true`).

## 6. Falhas, estranhezas e o que não foi testado

### Falhas (exibição; nenhum erro de servidor)

1. **Contagem incoerente em "Meu relatório" → "5. Explicações do tutor"**: a tela mostra "26 de 21 escritas
   pela IA local e conferidas". Em `qualidade_feedback`, `por_origem` soma questões e diálogo
   (`{"LLM": 26, "guarda": 0, "fallback": 1}`, 27 = 21 + 6), mas a tela divide por `respostas_com_origem` (21)
   (`app.js`, por volta da linha 651).
2. **Código em vez do nome do tópico** em "Meu relatório" → "2. Desempenho": "dev_01: 12 de 14 (86%)",
   "dev_02", "cib_01", "cib_02", enquanto a competência da base comum aparece como "Funções e modularização".
   Afeta os tópicos que estão fora da trilha do aluno (praticados pela rota avulsa).
3. **Rótulo de fonte errado no diálogo:** em "Perguntar ao tutor", a resposta vetada ("Origem: professor") e a
   resposta sem material mostram "Fonte: texto do próprio item (sem trecho do material).", que é o texto do
   feedback de questão (`blocoFontes` em `app.js`, por volta da linha 542). No diálogo não há item.

### Estranhezas (provavelmente do modelo pequeno ou da configuração local)

4. **Explicação circular:** 7 das 21 explicações começam com "A resposta correta é a correta porque…". O
   restante da explicação está certo.
5. **Narrativa do aluno confusa:** "A maioria das respostas está em progresso… Aproveite para revisar os temas
   que não tiveram erros repetidos". As narrativas da turma estão corretas e respeitam a supressão ("com menos
   de 5 alunos inativos").
6. **Prática avulsa fora da trilha:** o domínio em dev_01 pela rota `/tutor/sessao` não aparece no progresso da
   trilha (esperado: a rota é standalone), mas entra no desempenho do Relatório e no alerta de queda do painel.
   Isso pode confundir o docente. No piloto real (`PILOTO_ESCOPO=piloto`), os tópicos estariam na trilha.
7. **Alertas individuais em grupo pequeno:** com o filtro "iniciante" (4 alunos), os alertas de risco listam
   DEMO-P11 por código, enquanto os indicadores agregados do mesmo grupo ficam suprimidos. Parece intencional
   (a tela de risco é por código, para o docente), mas vale confirmar com a Pessoa 4.
8. **Ruído conhecido:** erros de telemetria do Chroma no log (`capture() takes 1 positional argument but 3 were
   given`; item 11 de `docs/limitacoes_conhecidas.md`) e 404 do `/favicon.ico`.
9. **Critério de inatividade 3 dias** no painel: o `.env` local não aplica o perfil do piloto (2 dias).

### Não testado

- Onboarding e diagnóstico do primeiro acesso: o DEMO-W01 já vem matriculado. Seria preciso um aluno novo.
- Os 4 tópicos do piloto pelo fluxo gerenciado: exigiria um aluno matriculado com `PILOTO_ESCOPO=piloto`.
- Troca de senha, administração de usuários e plug-in do EBAULA.

## Estado deixado na máquina

- `data/tia.db`: banco de demonstração novo, com os dados deste teste (DEMO-W01 com 5 sessões, 21 respostas,
  6 perguntas; 1 aprovação e 3 vetos).
- `data/tia.db.bak`: o banco anterior (15/10). `data/tia.db.bak.2026-10-11`: o backup que já existia.
- Índice do Chroma não alterado.
