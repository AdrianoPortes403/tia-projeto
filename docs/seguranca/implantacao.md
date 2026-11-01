# Implantação: sessão, cookies e o EBAULA (EAP 1.4.6)

> Frente A3, 11/10/2026 (atualizado em 31/10/2026: iframe do plug-in). Documento para **decisão com a equipe do EBAULA**. Arquitetura da segurança:
> `docs/arquitetura/arquitetura.md`, seção "Segurança".

## 1. Como a sessão funciona hoje

- O login (`POST /auth/login`) abre uma sessão no servidor e devolve o cookie `tia_sessao` com `HttpOnly`,
  `SameSite=Strict`, `Secure` (configurável) e `Path=/`.
- O JavaScript não lê o cookie. Toda escrita leva também o cabeçalho `X-CSRF-Token`, cujo valor fica só em
  memória.
- As telas (`/app/` e `/app/painel/`) mandam `Content-Security-Policy: frame-ancestors`, com as origens de
  `TIA_FRAME_ANCESTORS` (`core/config.py`; vazio = `'none'`). A API continua `frame-ancestors 'none'`.
- **O plug-in do EBAULA já abre o TIA em iframe** (`plugin-ebaula/`, commit `f06586b`), mas o
  login dentro dele **só funciona com o TIA no mesmo site do EBAULA** (seção 2). Em outro site, a alternativa
  é o modo `aba` do plug-in: **abrir o TIA em nova aba**, que funciona em qualquer domínio.
- No nginx (`deploy/proxy/nginx-tia.conf`), o `X-Frame-Options: DENY` precisa sair para o iframe funcionar;
  prefira tirá-lo só de um `location /app/`, em vez de apagar a linha de todas as rotas.

## 2. O impacto do `SameSite=Strict` dentro do EBAULA

O navegador só envia um cookie `SameSite=Strict` quando o pedido sai do **mesmo site**. "Site" é o esquema
mais o domínio registrável: `https://ebaula.exemplo.edu.br` e `https://tia.exemplo.edu.br` são o mesmo
site (`exemplo.edu.br`). Já `https://ebaula.com.br` e `https://tia.exemplo.edu.br` são sites diferentes.
`http` e `https` também contam como sites diferentes.

| Como o EBAULA abre o TIA | O que acontece com o `SameSite=Strict` |
|---|---|
| Link que abre o TIA em outra aba (navegação de topo) | **Funciona.** A primeira página não recebe o cookie, mas ela é estática. Os pedidos seguintes (`/auth/eu` e as rotas) já são do mesmo site e levam o cookie |
| iframe, com o TIA no **mesmo site** do EBAULA (subdomínio ou caminho) | **Funciona**, desde que `TIA_FRAME_ANCESTORS` libere a origem do EBAULA (padrão: `'none'`) |
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

**Estado em 31/10/2026:**

- **A**: implementada no TIA. `TIA_FRAME_ANCESTORS` libera as origens do EBAULA e o plug-in abre o iframe.
  Falta o EBAULA confirmar o domínio. Prefira **subdomínio** (`tia.<domínio>`): por caminho
  (`<EBAULA>/tia/`) o TIA fica na mesma origem do EBAULA, e o sandbox `allow-scripts allow-same-origin` do
  iframe deixa de isolar os dois.
- **B**: funciona hoje (modo `aba` do plug-in). Falta só o login único; até lá, o aluno usa o login local.
- **C** e **D**: não implementadas.
- O plug-in foi testado só em jsdom. Falta conferir num navegador real se o aviso "O tutor não carregou"
  aparece quando o login em iframe falha (provavelmente não aparece, porque a página carrega).

## 4. Perguntas para a equipe do EBAULA

1. Qual é o domínio do EBAULA em produção? O TIA pode ficar num subdomínio dele ou atrás de um proxy no mesmo
   host?
2. Como o plug-in vai abrir o TIA: iframe, nova aba ou lançamento LTI?
3. Qual login único o EBAULA oferece (SAML, OAuth/OIDC, LTI 1.3 ou outro)? Ele informa o papel (aluno ou
   professor) e um identificador estável do aluno, que vira o código do TIA (nunca o nome, R08)?
4. Há aplicativo móvel ou webview? O comportamento dos cookies muda nesses ambientes.
5. Quais navegadores os alunos usam (Safari no iPhone muda a conta da alternativa D)?

## 5. Lista de conferência para subir na VM

> Os scripts de `deploy/` aplicam quase tudo desta seção: usuário de serviço, permissões, `.env` de
> produção, systemd com `--proxy-headers` e `--no-access-log`, Ollama só em 127.0.0.1, backup, timers e
> exemplo de nginx. Passo a passo e reversão: `docs/implantacao_vm.md`. Esta lista continua sendo a
> conferência final.

Caminhos de exemplo: código em `/srv/tia/app`, dados em `/srv/tia/data`, usuário de serviço `tia`. A
confirmar com o Tiago.

### 5.1 Variáveis obrigatórias (`/srv/tia/app/.env`, permissão 600, dono `tia`)

| Variável | Valor na VM | Por quê |
|---|---|---|
| `TIA_AMBIENTE` | `producao` (padrão) | a API recusa subir com configuração insegura; `/docs` desligado |
| `TIA_AUTH` | `ligada` (padrão) | **nunca** `desligada` com dados reais (em produção, a API nem sobe) |
| `AUTH_COOKIE_SEGURO` | `1` (padrão) | cookie só por HTTPS (em produção, `0` impede a API de subir) |
| `API_DOCS` | `0` (padrão em produção) | `/docs` e `/openapi.json` respondem 404 |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | R07; um endereço fora da máquina ou da rede interna impede a API de subir |
| `DB_PATH`, `CHROMA_DIR`, `COPIAS_DIR` | caminhos absolutos em `/srv/tia/data/...` | fora da pasta do código |
| `RETENCAO_*`, `AUTH_RETENCAO_IP_DIAS` | os valores aprovados pelo jurídico/DEP | hoje PROVISÓRIOS (`docs/seguranca/lgpd.md`) |
| `AUTH_SENHA_MINIMA`, `AUTH_SENHAS_COMUNS_EXTRA` | política da instituição, se houver | |
| `AUTH_SESSAO_INATIVIDADE_MINUTOS`, `AUTH_SESSAO_MAXIMA_MINUTOS` | 30 e 480 (padrão), ou o que a Pessoa 4 decidir | |

Conferir com `python -m tia.core.config`: nenhuma linha "ATENÇÃO" pode aparecer.

### 5.2 HTTPS e proxy reverso

- Proxy (nginx ou Caddy) na porta 443, com certificado válido; HTTP (80) só redireciona para HTTPS. O
  cabeçalho `Strict-Transport-Security` é posto no proxy.
- O uvicorn escuta só em `127.0.0.1:8000`, sem `--reload`, com `--proxy-headers --forwarded-allow-ips=127.0.0.1`.
  Sem isso, o IP visto pela API é o do proxy: todos os alunos parecem uma única origem, o bloqueio por IP
  pega todo mundo junto e a agregação dos pedidos sem login junta todos numa linha.
- `--no-access-log` no uvicorn: o log de acesso dele grava IP e rotas com o código do aluno. O log do proxy
  também grava IP: retenção curta (por exemplo 30 dias), ou formato sem IP.

### 5.3 Usuário do serviço, permissões e systemd

- Usuário `tia` sem login (`useradd --system --shell /usr/sbin/nologin tia`). O código é do root, só para
  leitura; `/srv/tia/data` é do `tia`, com permissão 700.
- O banco e o `.env` ficam com permissão 600. As cópias (`COPIAS_DIR`) e os arquivos de exportação e de
  senhas temporárias já são criados com 700 e 600 pelo próprio TIA.
- Exemplo de unidade (`/etc/systemd/system/tia.service`):

```ini
[Service]
User=tia
Group=tia
WorkingDirectory=/srv/tia/app
EnvironmentFile=/srv/tia/app/.env
ExecStart=/srv/tia/app/venv/bin/uvicorn tia.api.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/srv/tia/data
Restart=on-failure
```

### 5.4 Ollama e firewall

- O Ollama escuta só em `127.0.0.1:11434` (`OLLAMA_HOST=127.0.0.1:11434`, que é o padrão). **Nunca**
  `0.0.0.0`: a API do Ollama não tem autenticação.
- Firewall: entrada só na 443 (e na 22 para administração, só da rede interna). A 11434 e a 8000 ficam
  fechadas para fora.
- Se o Ollama ficar em outra máquina da rede interna (máquina com GPU), libere a 11434 só para o IP da VM do
  TIA.

### 5.5 Backup, retenção e logs

- Backup diário do banco a quente (`sqlite3 /srv/tia/data/tia.db ".backup /caminho/tia-AAAAMMDD.db"`) para
  outro disco, com permissão 600, criptografado se sair da VM. Testar a restauração antes do piloto.
- Os backups guardam dados pessoais, inclusive os que a retenção ou a eliminação já apagaram do banco. O
  prazo dos backups precisa estar na política da instituição (pergunta ao jurídico em `lgpd.md`). As cópias
  automáticas de `COPIAS_DIR` saem após `RETENCAO_COPIAS_DIAS`.
- Cron diário: `python -m tia.seguranca.retencao --aplicar`, como usuário `tia` e com o venv. A limpeza de
  sessões e IPs já roda dentro da API, a cada `AUTH_LIMPEZA_MINUTOS`.
- Logs da aplicação (journald): sem dado pessoal (testado). Defina uma retenção, por exemplo
  `MaxRetentionSec=30day` em `journald.conf`.

### 5.6 Usuários

- Primeiro admin pelo comando, no servidor: `python -m tia.seguranca.usuarios criar --id <código> --papel
  admin`. A senha é pedida sem eco, é temporária e precisa ser trocada no primeiro acesso.
- Turma e docentes: `python -m tia.seguranca.usuarios importar --arquivo usuarios.csv`. O arquivo de senhas
  temporárias sai com permissão 600: entregue cada senha ao dono e **apague o arquivo**.
- Não criar os usuários de demonstração (`dados_demo` e `dados_painel`) no banco real: a senha deles é
  fictícia e pública.

### 5.7 Conferência final

- `python -m tia.core.config` não mostra nenhuma "ATENÇÃO".
- `curl -sI https://<host>/health` traz `Content-Security-Policy`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` e `Strict-Transport-Security` (este vem do proxy).
- `https://<host>/docs` e `/openapi.json` respondem 404.
- `ss -ltnp` mostra 11434 e 8000 só em `127.0.0.1`.
- `python -m tia.seguranca.retencao --simular` roda sem erro.
- `pip-audit` (instalar na VM com o Tiago) sem vulnerabilidade aberta nas dependências
  (`docs/relatorios/seguranca_lgpd.md`).
