# Correções pequenas e autenticação com papéis (EAP 1.4.6, etapa 1)

> Frente A3, 11/10/2026. Sem commit. Arquitetura: `docs/arquitetura/arquitetura.md`, seção "Segurança".

## Resultado

- `./run_tests.sh`: **539 passados, 9 xfailed** (os 9 xfails conhecidos do portão do diálogo), 0 falhas.
  São 51 testes novos: 46 em `tests/test_seguranca.py` e 5 em `tests/test_correcoes.py`.
- Os testes já existentes que verificam os agentes pelas rotas passaram a rodar com `TIA_AUTH=desligada`
  (fixture `auth_desligada` no `conftest`), sem mudar o que verificam. Ajustei três testes do front que
  procuravam o aviso antigo "Protótipo, sem login" ou proibiam as palavras "senha" e "token", que agora
  existem no login. Eles passaram a verificar a mesma intenção, de forma mais precisa:
  - não há senha nem token escritos no código;
  - nada sensível é guardado no `localStorage` ou no `sessionStorage`;
  - o JavaScript nunca lê `document.cookie`.
- Conferido num Chrome headless (roteiro pelo DevTools Protocol, fora do repositório), com os comandos de
  demonstração e a autenticação ligada:
  1. `/app/` abre no login e a senha errada mostra "Usuário ou senha incorretos." (o campo de senha é limpo);
  2. o aluno DEMO-W01 entra e vê a trilha e o próprio relatório, e `document.cookie` vem vazio (HttpOnly);
  3. "Sair" volta ao login;
  4. no painel, o aluno recebe "O painel é só para docentes" e o docente entra;
  5. a auditoria mostra a consulta de risco com "DEMO-DOCENTE (docente)";
  6. nenhuma exceção e nenhuma mensagem no console;
  7. com `TIA_AUTH=desligada`, as duas telas mostram o aviso do modo de desenvolvimento.
- Nada rodou contra `data/tia.db`. As tabelas e colunas novas são criadas quando a API sobe. **Atenção:**
  com o padrão (autenticação ligada), o banco atual não tem usuários. Antes de abrir as telas, rode um
  comando de demonstração ou `python -m tia.seguranca.usuarios criar ...`.

## Parte A

- **A1:** um evento reenviado com o mesmo `evento_id` passa por `eventos._aplicar_veto`. Se o feedback dessa
  resposta foi vetado, o resultado traz a correção do docente (`origem: "docente"`, sem fontes), nunca o
  texto vetado; se o veto for retirado, volta o original. `Feedback.origem` aceita `"docente"`.
- **A2:** `indicadores.engajamento` só marca como inativo quem **não** concluiu a trilha. Há um campo novo,
  `trilha_concluida`, e `dias_inativo` continua informado. Isso vale para o relatório do aluno, para a turma
  (visão geral do painel, alertas e CSV) e para o orquestrador. `GET /tutor/incentivo/{id}` devolve
  `inativo: false` para quem concluiu e mantém a mensagem de trilha concluída. Testado nos três lugares.

## Parte B: arquivos

| Arquivo | O que é |
|---|---|
| `src/tia/seguranca/__init__.py` | visão geral do pacote |
| `src/tia/seguranca/senhas.py` | scrypt com sal, conferência em tempo constante, senha mínima |
| `src/tia/seguranca/usuarios.py` | cadastro e linha de comando `criar\|desativar\|redefinir-senha\|listar`; usuários de demonstração |
| `src/tia/seguranca/sessoes.py` | sessão no servidor (hash do token, anti-CSRF, expiração) e limite de tentativas |
| `src/tia/seguranca/autenticador.py` | contrato `Autenticador`, provedor `local`, registro `PROVEDORES` |
| `src/tia/seguranca/acesso.py` | dependências: `usuario_atual`, `exigir_papel`, `acesso_ao_aluno`, `conferir_aluno`; recusa auditada |
| `src/tia/api/rotas_auth.py` | `/auth/login`, `/auth/logout`, `/auth/eu`, `/admin/usuarios` |
| `src/tia/api/rotas_*.py` | papéis em todas as rotas; os TODO 1.4.6 foram removidos |
| `src/tia/core/auditoria.py` | `usuario_id` e `usuario_papel` em toda linha (`USUARIO_ATUAL`, por requisição); tipos de segurança; agente `seguranca` |
| `src/tia/core/database.py` | tabelas `usuarios`, `auth_sessoes`, `auth_tentativas`; colunas da auditoria |
| `src/tia/core/config.py`, `.env.example` | `TIA_AUTH`, `AUTH_*` |
| `src/tia/web/static/comum.js` | `obterSessao`, `entrar`, `sair`, `mostrarSessao`; `X-CSRF-Token` nas escritas; 401 volta ao login |
| `src/tia/web/static/index.html`, `app.js` | tela de login, barra do usuário, aviso do modo de desenvolvimento; o código do aluno vem da sessão |
| `src/tia/web/static/painel/*` | login só para docente, barra do usuário, coluna "Usuário" e filtro "Segurança" na auditoria |
| `src/tia/web/dados_demo.py`, `dados_painel.py` | criam o aluno DEMO-W01 e o docente DEMO-DOCENTE (senha fictícia impressa pelo comando) |
| `src/tia/orquestrador/eventos.py`, `agentes/relatorio/*`, `agentes/tutor/incentivo.py`, `painel/consultas.py` | Parte A |
| `tests/conftest.py`, `test_seguranca.py` (novo), `test_correcoes.py` (novo), `test_web.py`, `test_painel.py` | testes |
| `docs/arquitetura/arquitetura.md`, `CLAUDE.md` | seção "Segurança" e pendências |

## Decisões

1. **Só biblioteca padrão:** `hashlib.scrypt` (n=2^14, r=8, p=1, sal de 16 bytes), `secrets` para os tokens e
   `hmac.compare_digest` nas comparações. Nenhuma dependência nova.
2. **Sessão no servidor**, com só o SHA-256 do token no banco: um vazamento do banco não dá sessões válidas.
   A expiração é absoluta, contada do login (não renova com o uso). É mais simples; se a Pessoa 4 preferir,
   dá para trocar por expiração por inatividade.
3. **Anti-CSRF com token por sessão** no cabeçalho `X-CSRF-Token`, além do `SameSite=Strict`. O token fica
   só em memória no front e é obtido de novo por `GET /auth/eu` ao recarregar a página. No login, que ainda
   não tem sessão, basta o cabeçalho existir (um site de terceiros não consegue enviá-lo, e a API não libera
   CORS).
4. **Usuário na auditoria por `ContextVar`.** A dependência de autenticação define o usuário da requisição
   e `auditoria.registrar` grava em toda linha, inclusive nas transações dos agentes, sem mudar a
   assinatura deles. Fora de requisição, o papel gravado é `sistema`.
5. **Matriz de acesso.** O docente **lê** os dados de um aluno (estado, trilha, diálogo, feedbacks,
   relatório) para acompanhar, mas **não age por ele** (não responde, não pergunta, não matricula). O
   incentivo é só do aluno, porque gera auditoria de incentivo. O admin **só gerencia usuários**: não vê
   painel nem dados de aluno. `/conteudo/*` fica aberto a qualquer usuário logado (não tem dado pessoal).
   `POST /orquestrador/verificar-inatividade` aceita docente ou admin; o agendador usa o comando.
6. **Login no lugar do código.** Com a autenticação ligada, a entrada pelo código e o botão "Trocar" somem.
   A matrícula continua na mesma tela (sem "Voltar").
7. **Privacidade na auditoria de login:** o login digitado só é gravado se tiver o formato de código. A
   mensagem de erro e o tempo de resposta são os mesmos para usuário inexistente, senha errada ou desativado.
   O IP fica só em `auth_tentativas` (para o limite), não na auditoria.
8. **Desligado só por variável:** `TIA_AUTH=desligada` mostra um aviso nas telas. O padrão é ligado; há
   teste que garante isso.

## Pendências

- **Etapa 2 do 1.4.6:** retenção e limpeza de `auth_tentativas` e `auth_sessoes`; limite de pedidos
  anônimos (hoje cada 401 grava auditoria); `/docs` e `/openapi.json` fechados na VM; cabeçalhos de
  segurança também nas rotas da API; política de senha; troca de senha pelo próprio usuário; tela de
  administração.
- **HTTPS na VM:** o cookie `Secure` depende dele (os navegadores só abrem exceção para `localhost`).
- **Docente restrito às próprias turmas:** não existe turma no banco; hoje todo docente vê a instituição.
- **Docs antigas:** `docs/relatorios/painel_docente.md` e `feedback_revisavel.md` descrevem o estado da
  época ("sem login"). Ficaram como histórico; a situação atual está no `arquitetura.md`.

## O que depende do EBAULA (1.4.3)

- **O provedor do login único:** uma classe com o contrato `Autenticador`, registrada em `PROVEDORES`. O
  resto (sessão, anti-CSRF, papéis, auditoria) já funciona com qualquer provedor (há teste com um provedor
  falso).
- **O mapeamento** do usuário do EBAULA para o papel e o `aluno_id` do TIA. Os papéis vêm do EBAULA? Como
  ligar o aluno ao código?
- **Rodar dentro do EBAULA:** um iframe exige liberar o domínio em `frame-ancestors`. Com
  `SameSite=Strict`, o cookie não vai em contexto de terceiros, então dentro de um iframe de outro domínio
  a sessão não funciona como está. O plug-in deve servir o TIA no mesmo site ou usar outra forma de sessão.

## Perguntas para a Pessoa 4

1. O docente deve ver os dados individuais de qualquer aluno (como agora) ou só os das próprias turmas?
2. A sessão de 8 horas, contada do login, serve para aula e estudo, ou é melhor expirar por inatividade?
3. Quem cadastra alunos e docentes no piloto (importação de lista, admin manual)? E como o aluno recebe a
   senha inicial?

## Perguntas para o Tiago

1. Teremos HTTPS na VM institucional (certificado e domínio)? Sem ele, o cookie `Secure` não funciona fora de
   `localhost`.
2. O EBAULA oferece login único (SAML, OAuth/OIDC, LTI ou outro)? Ele informa o papel (aluno ou professor) e
   um identificador estável do aluno?
3. Há política de senha e de bloqueio da instituição (tamanho mínimo, número de tentativas, tempo de
   bloqueio)? Hoje: 10 caracteres, 5 falhas por usuário ou 20 por IP em 15 minutos.
4. Guardar o IP das tentativas de login (só para o limite) é aceitável pela LGPD da instituição? Por quanto
   tempo?
