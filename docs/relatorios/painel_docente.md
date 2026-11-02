# Painel do docente/instituição (EAP 1.4.5)

> Frente A3, 11/10/2026. Sem commit. Arquitetura, telas e rotas: `docs/arquitetura/arquitetura.md`, seção
> "Painel do docente/instituição".
>
> **01/11/2026:** o visual e a organização das telas mudaram (menu lateral; Visão geral, Revisar textos e
> Relatório da turma; rotas `GET /painel/alunos` e `GET /painel/revisao/contagem`). Ver
> `docs/relatorios/redesign_docente.md`. O texto abaixo descreve a versão de 11/10.

## Resultado

- `./run_tests.sh`: **464 passados, 9 xfailed** (os 9 xfails conhecidos do portão do diálogo), 0 falhas.
  São 66 testes novos: 62 em `tests/test_painel.py` e 4 em `tests/test_web.py` (por causa do `comum.js`).
- O painel abre em `http://localhost:8000/app/painel/`. Para ter o que mostrar:
  `python -m tia.web.dados_painel` (12 alunos fictícios, sem LLM, cerca de 0,5 s).
- Conferido num Chrome headless com a turma fictícia: as cinco telas, a impressão (PDF) e a largura de
  celular (390 px, sem rolagem horizontal da página). Um roteiro pelo DevTools Protocol (fora do
  repositório) aprovou e vetou uma resposta, filtrou a revisão e a auditoria e trocou o perfil para
  "iniciante". **Nenhuma exceção nem mensagem no console.** Uma correção com `<b>` apareceu como texto
  (nenhuma tag criada).

## Arquivos

| Arquivo | O que é |
|---|---|
| `src/tia/web/static/painel/index.html` | as cinco telas, aviso de protótipo, região de status e de erro |
| `src/tia/web/static/painel/painel.js` | chamadas às rotas e montagem das telas (sempre `textContent`); barras em SVG |
| `src/tia/web/static/painel/painel.css` | layout, gráficos, tabelas e CSS de impressão; só variáveis do tema |
| `src/tia/web/static/comum.js` | **novo, extraído de `app.js`**: `el`/`svg`, `chamar` (contador, botões desativados, erro), `mostrarErro` |
| `src/tia/painel/` (`__init__`, `modelos`, `consultas`) | consultas somente de leitura: risco, competências, revisão, CSV, ementa, perfis |
| `src/tia/api/rotas_painel.py` | `/painel/*` e `/conteudo/*` (só GET) |
| `src/tia/web/dados_painel.py` | `python -m tia.web.dados_painel`: turma fictícia DEMO-P01..P12 |
| `tests/test_painel.py` | testes do painel |
| Alterados | `app.js` e `index.html` (usam `comum.js`), `tema.css` (cores de impressão), `web/__init__.py` (redireciona `/app/painel`), `api/main.py`, `core/auditoria.py` (tipos novos, `consultar`, `registrar` devolve o id), `core/config.py` e `.env.example` (2 limiares), `tutor/repositorio.py` (veto auditado), `tutor/modelos.py` (tipos de auditoria), `tests/test_web.py`, `CLAUDE.md`, `README.md`, `arquitetura.md` |

## Decisões

1. **Lugar:** o painel fica em `src/tia/web/static/painel/`, servido em `/app/painel/` pelo mesmo mount
   (mesma CSP), como pedido. As pastas `web/` e `dashboard/` da raiz ficaram vazias. O `CLAUDE.md` foi
   corrigido.
2. **Reaproveitamento:** extraí as utilidades do `app.js` para `comum.js`, para não duplicar o padrão de
   carregamento. O comportamento do `app.js` não mudou (os 51 testes da web passam).
3. **Aprovar sem rota nova de escrita:** "Aprovar" chama a rota do veto com `vetada: false`. Numa resposta
   sem veto isso não muda nada no diálogo, mas agora a rota grava `veto_docente` na auditoria (`aprovada`,
   `vetada` ou "veto retirado"). É assim que a revisão separa "a revisar", "aprovadas" e "vetadas".
   **Mudança de comportamento:** o veto antes não deixava rastro na auditoria (R11).
4. **"Vetar com motivo":** o modelo `Veto` só tem `correcao_docente`, e é ela que o aluno vê. O campo da
   tela pede "a correção que o aluno vai ver (explique o motivo do veto)". Um motivo interno separado exige
   mudar o modelo (pendência).
5. **Alunos em risco**: inatividade e queda reutilizam as regras do Agente 3 e do
   orquestrador (`INATIVIDADE_DIAS`, `RELATORIO_TENDENCIA_*`). Desempenho baixo é acerto abaixo de
   `PAINEL_DESEMPENHO_BAIXO=0.5` com pelo menos `PAINEL_MIN_RESPOSTAS=5` respostas. Quem concluiu a trilha
   não entra por inatividade.
6. **Auditoria das consultas:** cada consulta de risco **e de revisão** (a revisão também mostra códigos e
   textos dos alunos) grava `consulta_painel` com o filtro e os códigos exibidos. A consulta da auditoria e
   as visões agregadas não são auditadas (as agregadas não têm código; a geração do relatório da turma já
   grava `relatorio_turma`).
7. **Grupo mínimo:** a regra pedida como "ORQ/RELATORIO_GRUPO_MINIMO" é a `RELATORIO_MIN_GRUPO` que já
   existe (padrão 5). O painel não recalcula nada: usa `indicadores.agregar_turma`. Questões com erro
   repetido só entram se respondidas por pelo menos 5 alunos. A tendência por competência sai como
   contagem de alunos por direção, com a mesma regra ("menos de 5").
8. **Exportação:** CSV gerado no servidor (`GET /painel/exportar/indicadores.csv`), com `;`, vírgula
   decimal e BOM, para abrir direto no Excel ou no LibreOffice em pt-BR. Proteção contra fórmula: célula
   que começa com `= + - @` leva `'` antes. Impressão: `window.print()` com CSS próprio (só a tela aberta,
   tema claro).
9. **Gráficos:** barras em SVG escritas à mão, decorativas (`aria-hidden`). Valor, rótulo e "oculto" sempre
   em texto ao lado e um resumo em texto para leitores de tela, então nada depende só de cor. Cores pelas
   variáveis do tema.
10. **Dados de demonstração:** matrícula pelo orquestrador (trilha real, texto padrão). Sessões, respostas e
    diálogos são sintéticos e têm datas no passado, como em `python -m tia.agentes.relatorio --demo`. A
    origem dos feedbacks é sorteada e os textos do diálogo trazem "[demonstração]". Duas respostas do
    diálogo estão erradas de propósito: uma já sai vetada e a outra fica para o docente vetar. No fim, a
    verificação de inatividade do orquestrador roda de verdade.

## Pendências

- **Login (1.4.6):** hoje qualquer pessoa com o endereço vê códigos e pode vetar. A auditoria não sabe
  quem consultou nem quem vetou. Com o login: papel docente em `/painel/*`, `/relatorio/turma` e no veto,
  usuário gravado na auditoria e docente restrito às próprias turmas.
- **Turma no banco:** o grupo é a instituição ou um perfil (como no Agente 3); não existe "turma".
- **Texto do feedback das questões não é gravado:** a revisão mostra só a origem e as fontes desses
  feedbacks. Para revisar e vetar o feedback, o Tutor (Pessoa 2) precisa gravar a explicação e ganhar uma
  rota de veto própria.
- **Motivo interno do veto**, separado da correção que o aluno vê (mudança no modelo `Veto`).
- **Visual do EBAULA:** trocar `tema.css`; para embutir no EBAULA, liberar o domínio em `frame-ancestors`.
- **`app.js` ainda não usa `/conteudo/ementa`** (nomes de competência fora da trilha).
- **Observação sobre o orquestrador (não mexi):** a verificação de inatividade (R3) mandou incentivo ao
  DEMO-P02, que já concluiu a trilha. O painel não o lista como risco, mas a regra R3 não olha a conclusão.
- **Banco real:** antes de passar aos testes com banco temporário, uma conferência rápida das rotas rodou
  contra `data/tia.db` e gravou 3 linhas de auditoria (ids 23, 24 e 25: duas `consulta_painel` e um
  `relatorio_turma`, sem dados novos de aluno). Deixei as linhas no banco, porque apagar registros de
  auditoria não me pareceu certo. Se preferir, dá para removê-las.

## Perguntas para a Pessoa 4

1. **O que o docente vê primeiro?** Hoje a tela inicial é a Visão geral (os 5 indicadores agregados). Seria
   melhor abrir em "Alertas de risco"? Em que ordem vêm os indicadores?
2. **Critérios de risco:** 3 dias sem atividade, queda de 15 pontos, acerto abaixo de 50% com pelo menos 5
   respostas. Estão bons? Falta algum motivo (ex.: muitas perguntas ao tutor sem progresso)?
3. **Formato da exportação:** serve um CSV com `;` e vírgula decimal? Ou a instituição prefere XLSX, PDF
   ou outro layout (uma linha por indicador, como hoje, ou uma por competência)? Que campos são
   obrigatórios num relatório para a coordenação?
4. **Grupo mínimo:** 5 alunos está bom para a instituição? E para itens, 5 alunos que responderam?
5. **Revisão:** quem revisa? Todas as respostas do LLM ou uma amostra? Aprovar precisa de comentário?
