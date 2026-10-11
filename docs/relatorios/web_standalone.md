# Web standalone (EAP 1.4.4) e correção do progresso do reforço

> Frente A3, 11/10/2026. Sem commit. Arquitetura e telas: `docs/arquitetura/arquitetura.md`, seção
> "Web standalone".

## Resultado

- `./run_tests.sh`: **398 passados, 9 xfailed** (os 9 xfails conhecidos do portão do diálogo), 0 falhas.
  São 48 testes novos: 47 em `tests/test_web.py` e 1 em `tests/test_orquestrador.py`.
- A aplicação abre em `http://localhost:8000/app/`. As cinco telas foram percorridas num Chrome headless
  (roteiro pelo DevTools Protocol, fora do repositório; ver "Teste no navegador"), sem LLM e com o LLM
  real, sem nenhuma exceção nem mensagem no console.

## 0. Correção: o reforço não conta no progresso

**Problema:** o replanejamento recebia todas as competências concluídas no Tutor. Um reforço (R2) de um
pré-requisito dispensado no diagnóstico (ex.: `repeticao`) entrava na trilha como etapa concluída, e o
progresso passava de "3 de 3" para "4 de 4".

**Correção** (`orquestrador/fluxo.py`): `_planejar` passa ao Planejador só as concluídas que pertencem
à **trilha original**. Essa trilha é calculada por `competencias_originais`, com `gerar_trilha` sobre o
perfil e o diagnóstico da matrícula e sem concluídas (determinístico, sem LLM). Trilha, `estado` e
indicadores do Relatório passam a contar só as competências originais. O reforço continua no histórico
do Tutor (sessões, respostas, desempenho por competência).

**Teste:** `test_reforco_concluido_nao_conta_no_progresso_da_trilha` faz o ciclo completo (conclui,
cai, reforça, retoma, conclui) e confere a trilha, o `estado` e o relatório: 3 etapas, "2 de 3" e depois
"3 de 3". Esse teste **falha sem a correção**, porque a trilha passa a começar por `repeticao`.

## Arquivos

| Arquivo | O que é |
|---|---|
| `src/tia/web/__init__.py` | monta `/app` (StaticFiles), redireciona `/app` para `/app/`, cabeçalhos de segurança |
| `src/tia/web/static/index.html` | telas: entrada, trilha, estudo, diálogo livre, relatório |
| `src/tia/web/static/tema.css` | só variáveis de tema (claro e escuro) |
| `src/tia/web/static/estilo.css` | layout responsivo, só com as variáveis |
| `src/tia/web/static/app.js` | lógica do front (JavaScript puro) |
| `src/tia/web/dados_demo.py` | `python -m tia.web.dados_demo [--com-llm]`: alunos fictícios DEMO-W01..W03 |
| `src/tia/api/main.py` | `web.montar(app)` |
| `src/tia/orquestrador/fluxo.py` | correção do progresso; `proxima` preenche a pergunta em `continuar_sessao` |
| `src/tia/orquestrador/modelos.py` | `ProximaAcao.pergunta` (opcional) |
| `pyproject.toml` | `package-data` para os estáticos irem junto no pacote |
| `tests/test_web.py` | rotas `/app` e estáticos, segurança do JS, tema, contrato, percurso, dados fictícios |
| `tests/test_orquestrador.py` | teste da correção; a retomada após o reforço devolve a pergunta |
| `docs/arquitetura/arquitetura.md` | diagrama, seção "Web standalone", D1 e limitação corrigida |
| `README.md` | como subir a demonstração |

## Decisões

1. **Mudança na API, só uma e indispensável: `ProximaAcao.pergunta`.** Nenhuma rota devolvia a pergunta
   de uma sessão já aberta. Depois de recarregar a página ou na retomada após um reforço, o aluno ficava
   preso: `POST /aluno/{id}/sessao` responde 409 ("continue-a") e o cliente não tinha a pergunta. O campo
   é opcional e só vem em `continuar_sessao`, sem gabarito (usa `tutor.pergunta_atual`).
2. **Fluxo gerenciado:** o front abre sessões e envia respostas **só pelo orquestrador** (`/aluno/{id}/...`),
   nunca por `/tutor/sessao` nem por `/tutor/resposta`. Assim as regras R1, R2 e reforço valem na web.
3. **Reenvio idempotente:** se uma resposta falha por rede ou por tempo, o próximo envio da mesma
   alternativa usa o mesmo `evento_id`, e o orquestrador não processa duas vezes. Se a API recusa (4xx),
   o evento é descartado e a tela oferece "Buscar a atividade atual".
4. **Espera de 300 s no navegador**, constante em `app.js`. Não é timeout de LLM (esses continuam em
   `core/config.py`): uma resposta pode acionar Tutor e Planejador, 120 s cada no servidor.
5. **Uma chamada por vez:** durante a chamada, os botões de ação ficam desativados e a página continua
   navegável. O LLM local atende em série, então chamadas paralelas só aumentariam a espera.
6. **Narrativa do relatório sob demanda** (botão "Gerar resumo"). Os 5 indicadores carregam na hora,
   com `narrativa=false`. Gerar a narrativa automaticamente bloquearia as ações por até um minuto só
   para olhar o relatório.
7. **Diálogo:** o "trecho do material" é a própria resposta de origem `guarda` (trecho transcrito com a
   fonte). `LLM` mostra a resposta ancorada com as fontes. `fallback` mostra a mensagem fixa de que o
   material não cobre. Nenhum campo novo foi preciso.
8. **Matrícula na web** com perfil e horas e diagnóstico vazio (todas as notas 0). A lista de perfis
   está fixa no HTML e marcada PROVISÓRIO, porque não há rota que liste os perfis.
9. **Segurança:**
   - todo texto da API entra por `textContent`, pela função `el`; um teste proíbe `innerHTML`,
     `insertAdjacentHTML`, `document.write`, `eval` e `console.`;
   - CSP só com a própria origem, sem script ou estilo inline, mais `nosniff` e `no-referrer`;
   - sem chaves, tokens ou URL absoluta no JS (também testado);
   - o código do aluno fica só no `sessionStorage` da aba; o campo de pergunta avisa para não escrever
     dados pessoais.
10. **Acessibilidade:**
    - todo campo tem `<label>` (testado);
    - alternativas num `fieldset` com `legend`;
    - foco visível;
    - link "Pular para o conteúdo";
    - faixa de carregamento com `role=status` e faixa de erro com `role=alert`;
    - veredito com ✓/✗ e texto, não só cor;
    - contraste AA na paleta provisória;
    - respeito a `prefers-reduced-motion` e tema escuro por `prefers-color-scheme`.
11. **Lugar dos arquivos:** `src/tia/web/`, como pedido, para irem junto no `pip install`. O `CLAUDE.md`
    ainda cita `web/` na raiz (pasta vazia). Sugiro atualizar essa linha.
12. **Tempo na tela:** feedback e diálogo mostram o tempo do servidor (`tempo_ms`), além do contador
    durante a espera (CLAUDE.md: toda demonstração mostra o tempo).

## Teste no navegador

O **Playwright não está instalado** e não foi instalado. O roteiro mínimo fica como pendência no
repositório.

Para não ficar sem teste de navegador, rodei localmente um roteiro com o Google Chrome headless, pelo
DevTools Protocol, usando o `websockets` que já vem no `uvicorn[standard]`. O roteiro ficou fora do
repositório (scratchpad) e percorreu:

1. entrada com código inválido;
2. DEMO-W02 (trilha, continuar a sessão, responder, Continuar, diálogo, relatório, gerar resumo);
3. DEMO-W03 (aviso de reforço e abertura da revisão);
4. código novo com matrícula;
5. recarregar a página.

Dois defeitos achados por ele foram corrigidos:

- o filtro de competência do diálogo ficava vazio (`replaceChildren` recebia uma lista sem `...`);
- o aviso de reforço aparecia duplicado na trilha.

Com o LLM real (qwen3:1.7b, CPU do notebook), o roteiro levou **2 min 23 s**:

| Chamada | Origem | Tempo no servidor |
|---|---|---|
| Feedback de uma resposta | LLM, fonte `provisorio_listas_strings.txt` | 33,2 s |
| Pergunta livre "O que é uma lista?" | LLM, 2 fontes | 36,1 s |
| Matrícula (justificativas do Planejador) | LLM | 43,8 s |
| Narrativa do relatório | LLM, aprovada pela guarda | (não medido em separado) |

R09 a medir na VM.

## Pendências

- **Login (1.4.6):** a entrada é um campo livre de código, com o aviso "Protótipo, sem login (TODO 1.4.6)".
- **Roteiro Playwright:** depende de instalar o Playwright (não instalado, como pedido).
- **Diagnóstico na matrícula:** depende de quem aplica o diagnóstico (Pessoa 2/4).
- **Nome de competência fora da trilha:** o cartão de revisão mostra o código (`repeticao`), porque não
  há rota da ementa. O aviso do orquestrador já traz o nome. Resolver com uma rota da ementa ou com o
  nome em `Reforco` (mudança de API não indispensável, por isso não foi feita).
- **Lista de perfis fixa no HTML** (PROVISÓRIO), pelo mesmo motivo.
- **Plug-in EBAULA (1.4.3):** a CSP proíbe iframe (`frame-ancestors 'none'`) e terá de liberar o domínio
  do EBAULA.

## O que depende da definição visual do EBAULA

- Paleta, fontes, raio de borda, espaçamentos e sombras: trocar `tema.css` (só variáveis).
- Logotipo e cabeçalho (hoje o texto "TIA Tutoria Inteligente").
- Componentes padrão do EBAULA (botões, abas, cartões, alertas), se houver: ajustar `estilo.css`. As
  classes do HTML são neutras (`cartao`, `botao`, `aba`, `aviso`, `selo`).
- Se o EBAULA tiver tema escuro próprio ou não tiver nenhum: hoje o tema segue o
  `prefers-color-scheme` do sistema.
- Textos de interface e tom (hoje em português simples, segunda pessoa).
