# Implantação: sessão, cookies e o EBAULA (EAP 1.4.6)

> Frente A3, 11/10/2026. Documento para **decisão com a equipe do EBAULA**. Arquitetura da segurança:
> `docs/arquitetura/arquitetura.md`, seção "Segurança".

## 1. Como a sessão funciona hoje

- O login (`POST /auth/login`) abre uma sessão no servidor e devolve o cookie `tia_sessao` com `HttpOnly`,
  `SameSite=Strict`, `Secure` (configurável) e `Path=/`.
- O JavaScript não lê o cookie. Toda escrita leva também o cabeçalho `X-CSRF-Token`, cujo valor fica só em
  memória.
- As telas (`/app/` e `/app/painel/`) mandam `Content-Security-Policy: frame-ancestors 'none'`, ou seja,
  hoje **nenhum site pode abrir o TIA dentro de um iframe**.

## 2. O impacto do `SameSite=Strict` dentro do EBAULA

O navegador só envia um cookie `SameSite=Strict` quando o pedido sai do **mesmo site**. "Site" é o esquema
mais o domínio registrável: `https://ebaula.exemplo.edu.br` e `https://tia.exemplo.edu.br` são o mesmo
site (`exemplo.edu.br`). Já `https://ebaula.com.br` e `https://tia.exemplo.edu.br` são sites diferentes.
`http` e `https` também contam como sites diferentes.

| Como o EBAULA abre o TIA | O que acontece com o `SameSite=Strict` |
|---|---|
| Link que abre o TIA em outra aba (navegação de topo) | **Funciona.** A primeira página não recebe o cookie, mas ela é estática. Os pedidos seguintes (`/auth/eu` e as rotas) já são do mesmo site e levam o cookie |
| iframe, com o TIA no **mesmo site** do EBAULA (subdomínio ou caminho) | **Funciona**, desde que `frame-ancestors` libere a origem do EBAULA (hoje está `'none'`) |
| iframe, com o TIA em **outro site** | **Não funciona.** Dentro do iframe, o navegador não envia o cookie `Strict` (nem o `Lax`) e recusa gravá-lo no login. O aluno entra, a tela pede o login de novo e fica nesse ciclo |

Trocar para `SameSite=None; Secure` não resolve com segurança. Com essa marca, o cookie vira "cookie de
terceiros":

- o Safari bloqueia esse tipo de cookie por padrão;
- outros navegadores particionam ou deixam o usuário bloquear;
- o atributo `Partitioned` (CHIPS) melhora a situação, mas o suporte varia entre navegadores e versões.

O resultado depende do navegador de cada aluno. Por isso, esse caminho não é recomendado como solução
principal. Se for usado, o anti-CSRF pelo cabeçalho continua valendo, porque não depende do `SameSite`.

## 3. Alternativas

| | A. Mesmo site, em iframe | B. Nova aba (link) | C. Outro transporte de sessão (token no cabeçalho) | D. `SameSite=None; Secure; Partitioned` |
|---|---|---|---|---|
| Ideia | servir o TIA num subdomínio do domínio do EBAULA (`tia.<domínio do EBAULA>`) ou num caminho por proxy reverso (`<EBAULA>/tia/`) | o EBAULA abre o TIA em outra aba, com o login único | o EBAULA entrega ao iframe um token de sessão (no lançamento, por exemplo LTI, ou por `postMessage`); o front guarda o token só em memória e o manda em `Authorization: Bearer`; sem cookie | manter o cookie, mas como cookie de terceiros |
| Funciona em iframe? | sim | não usa iframe | sim, em qualquer domínio | depende do navegador |
| Mudança no TIA | pequena: configurar `frame-ancestors` (nova variável em `core/config.py`) e, com caminho por proxy, o `Path` e o prefixo das rotas | nenhuma (só o provedor do login único) | média: `seguranca.acesso` aceita o token pelo cabeçalho; `comum.js` manda o cabeçalho; nova rota de troca do lançamento pelo token; o anti-CSRF deixa de ser preciso nesse modo (o navegador não envia o token sozinho) | pequena: `SameSite` configurável, `Partitioned` e `frame-ancestors` |
| Mudança no EBAULA | DNS do subdomínio ou regra de proxy; abrir o iframe | só o link | o plug-in gera o lançamento ou o token e conversa com o iframe | abrir o iframe |
| Riscos e custos | nenhum novo; o mais simples de manter | o aluno sai da tela do EBAULA | o token fica na memória do JavaScript: um XSS o leria (a CSP só com `'self'` e o uso de `textContent` reduzem o risco); recarregar a página perde a sessão, e o EBAULA precisa lançar de novo; `postMessage` exige conferir a origem | falha silenciosa em parte dos navegadores; mais suporte |

**Recomendação (para discutir):**

1. **A (mesmo site)**, se a equipe do EBAULA puder criar o subdomínio ou o proxy. Mantém tudo o que existe e
   funciona em iframe.
2. **B (nova aba)** como alternativa imediata. Já funciona hoje, faltando só o login único.
3. **C**, só se o iframe em outro domínio for obrigatório. Entra como outro transporte de sessão, ao lado do
   cookie. O contrato `Autenticador` cobre só a autenticação; a sessão e o cookie ficam em
   `tia.api.rotas_auth` e `seguranca.acesso`, que ganhariam essa segunda forma.
4. **Evitar D** como solução principal.

Nada disso foi implementado ainda: a escolha depende das respostas abaixo.

## 4. Perguntas para a equipe do EBAULA

1. Qual é o domínio do EBAULA em produção? O TIA pode ficar num subdomínio dele ou atrás de um proxy no mesmo
   host?
2. Como o plug-in vai abrir o TIA: iframe, nova aba ou lançamento LTI?
3. Qual login único o EBAULA oferece (SAML, OAuth/OIDC, LTI 1.3 ou outro)? Ele informa o papel (aluno ou
   professor) e um identificador estável do aluno, que vira o código do TIA (nunca o nome, R08)?
4. Há aplicativo móvel ou webview? O comportamento dos cookies muda nesses ambientes.
5. Quais navegadores os alunos usam (Safari no iPhone muda a conta da alternativa D)?

## 5. Lista de conferência para subir na VM

- HTTPS com certificado válido: `AUTH_COOKIE_SEGURO=1` (padrão) depende disso fora de `localhost`.
- `TIA_AUTH` ligada (padrão). **Nunca** `desligada` com dados reais.
- Primeiro admin pelo comando, no servidor:
  `python -m tia.seguranca.usuarios criar --id <código> --papel admin`. A senha é pedida sem eco e é
  temporária: precisa ser trocada no primeiro acesso.
- Não criar os usuários de demonstração (`dados_demo` e `dados_painel`) no banco real: a senha deles é
  fictícia e pública.
- Retenção: `AUTH_RETENCAO_IP_DIAS` (30, PROVISÓRIO) conforme a decisão de LGPD da instituição. A API limpa
  sozinha a cada `AUTH_LIMPEZA_MINUTOS` (60). Se a API ficar parada por muito tempo, agendar também
  `python -m tia.seguranca.limpeza` (cron ou systemd timer).
- Política de senha: `AUTH_SENHA_MINIMA` e `AUTH_SENHAS_COMUNS_EXTRA` (lista da instituição), se houver.
- Sessão: `AUTH_SESSAO_INATIVIDADE_MINUTOS` (30) e `AUTH_SESSAO_MAXIMA_MINUTOS` (480).
- Fechar ou proteger `/docs` e `/openapi.json`, e pôr os cabeçalhos de segurança também nas rotas da API
  (pendência).
- Atrás de um proxy reverso, o IP visto pela API é o do proxy. Para os limites por IP valerem, o uvicorn
  precisa de `--proxy-headers` e `--forwarded-allow-ips` com o endereço do proxy. Sem isso, todos os alunos
  parecem uma única origem: o bloqueio por IP pega todo mundo junto, e a agregação dos pedidos sem login
  junta todos numa linha.
