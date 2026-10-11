# LGPD, segurança geral e importação em lote (EAP 1.4.6, etapa 2 de 2)

> Frente A3, 11/10/2026. Sem commit. Documentos: `docs/seguranca/lgpd.md` (C4),
> `docs/seguranca/implantacao.md` (D3 e EBAULA), `docs/arquitetura/arquitetura.md` (seção "Segurança").

## Resultado

- `./run_tests.sh`: **624 passados, 9 xfailed** (os 9 conhecidos do portão do diálogo), 0 falhas.
  - 44 testes novos em `tests/test_seguranca_lgpd.py`.
  - Cinco asserções antigas mudaram por causa de comportamento que esta tarefa alterou de propósito:
    - **D4:** a contagem de `login_falha` em `test_seguranca.py` (2) e em `test_seguranca_etapa2.py` (1);
    - **D1:** em `test_web.py`, `/health` agora tem CSP, e `/docs` dá 404 por padrão.
- Conferido fora dos testes:
  - a API sobe com o `.env` desta máquina; os cabeçalhos aparecem em `/health`; `/docs` e `/openapi.json`
    dão 404;
  - com `TIA_AUTH=desligada` e sem `TIA_AMBIENTE`, a API recusa subir com mensagem clara;
  - os comandos `retencao --simular`, `titular exportar` e `titular eliminar` rodaram numa **cópia** de
    `data/tia.db`, apagada depois. O banco real não foi tocado.
- **Atenção na sua máquina:** o `.env` atual não define `TIA_AMBIENTE`, então vale `producao`. A API sobe
  normalmente, mas sem `/docs`. Para ter `/docs` ou rodar com `TIA_AUTH=desligada`, acrescente
  `TIA_AMBIENTE=desenvolvimento`.

## Arquivos

| Arquivo | O que é |
|---|---|
| `src/tia/seguranca/anonimizacao.py` (novo) | o que é anonimizar (desvincular e apagar textos); anonimização da auditoria; cópia do banco (700/600) e cópias vencidas |
| `src/tia/seguranca/retencao.py` (novo) | C1: `python -m tia.seguranca.retencao --simular\|--aplicar` |
| `src/tia/seguranca/titular.py` (novo) | C2: `python -m tia.seguranca.titular exportar\|eliminar --aluno ID` |
| `src/tia/seguranca/limpeza.py` | `aplicar(conexao, agora)` sem confirmar a transação, reaproveitado pela retenção |
| `src/tia/seguranca/anonimos.py` | D4: `login_falha` agregado; o resumo conta os logins diferentes |
| `src/tia/seguranca/usuarios.py` | E6: `importar`; validação e inserção separadas; um `aluno_id` só pode ligar-se a um usuário |
| `src/tia/api/main.py` | D1: `criar_app()`, cabeçalhos em toda resposta, `/docs` configurável, 422 sem o valor enviado, recusa de subir com configuração insegura |
| `src/tia/api/rotas_auth.py` | D4: falha de login pela agregação |
| `src/tia/core/config.py`, `.env.example` | `RETENCAO_*`, `COPIAS_DIR`, `TIA_AMBIENTE`, `API_DOCS`, `problemas_de_configuracao()` |
| `src/tia/core/database.py`, `core/auditoria.py` | coluna `auditoria.anonimizada`; tipos `retencao` e `direito_titular` |
| `src/tia/rag/retrieve.py`, `rag/ingest.py` | `abrir_cliente()` com a telemetria do Chroma desligada |
| `src/tia/agentes/tutor/feedback.py` | log do feedback barrado só com o tipo do motivo |
| `src/tia/painel/consultas.py` | revisão sem as linhas já anonimizadas |
| `src/tia/web/__init__.py`, `web/static/painel/painel.js` | cabeçalhos passam ao middleware geral; nomes dos tipos novos na auditoria |
| demos e avaliações do tutor (5 arquivos) | saiu a linha que silenciava o log da telemetria do Chroma |
| `docs/seguranca/lgpd.md` (novo), `docs/seguranca/implantacao.md`, `docs/arquitetura/arquitetura.md`, `CLAUDE.md` | documentação |

## Decisões

1. **Anonimizar = desvincular e apagar texto livre.**
   - `aluno_id`, `sessao_id` e `evento_id` viram NULL, e os textos também.
   - Ficam item, acerto, nível, data, origem e veto, que servem para estatística.
   - Na auditoria, todo código de aluno ou de usuário vira `[anonimizado]`: nas colunas, em `login=...`,
     nas rotas e nos motivos. A auditoria **nunca** perde linha.
2. **Prazos diferentes por tipo de dado** (PROVISÓRIOS):
   - textos do feedback e eventos guardados: 180 dias;
   - diálogo livre: 180 dias (texto e ligação);
   - respostas e o que liga a elas: 365 dias;
   - códigos na auditoria: 730 dias;
   - cópias do banco: 30 dias;
   - IPs: 30 dias (já existia).
   Os prazos contam da data de cada registro e precisam ser maiores que a duração do curso. Cadastro,
   matrícula e trilha não têm prazo por data.
3. **Simulação de verdade:** `--simular` executa as mesmas instruções numa transação e a desfaz. Assim, o
   que a simulação lista é exatamente o que o `--aplicar` faria, e há teste de que o banco fica igual
   byte a byte. `--aplicar` só copia o banco quando há algo a fazer.
4. **Eliminação do titular:**
   - apaga o estado individual: cadastro, matrícula, trilha, sessões, reforços e eventos;
   - desvincula e apaga os textos dos registros de estudo;
   - na auditoria, anonimiza só os códigos **dele**. O docente que vetou continua identificado, e o outro
     aluno citado numa consulta continua citado;
   - desativa o usuário e inutiliza a senha;
   - grava `direito_titular` **sem o código**, com um protocolo para responder ao titular;
   - faz cópia do banco antes e pede confirmação (digitar o código de novo, ou `--confirmar`).
5. **Exportação sem dados de outras pessoas:**
   - quem agiu sobre o aluno (docente, outro aluno) aparece só pelo papel;
   - códigos de outros em rotas e motivos viram `[anonimizado]`;
   - as tentativas de login vêm sem IP (o IP pode ser de um atacante);
   - as consultas do painel que mostraram o aluno vêm só com data, tipo e papel.
6. **`TIA_AMBIENTE=producao` como padrão** (seguro por padrão, como o `TIA_AUTH`). Em produção, `/docs`
   fica desligado. A API **não sobe** com autenticação desligada, cookie sem `Secure` ou `OLLAMA_URL` fora
   da máquina ou da rede interna. Esta última é uma trava para o R07; endereços privados são aceitos porque
   o LLM de produção pode estar em outra máquina interna.
7. **Cabeçalhos num middleware só:**
   - `/app` mantém a CSP dele;
   - a API ganhou `default-src 'none'`, `frame-ancestors 'none'` e `Cache-Control: no-store`;
   - `/docs`, quando ligado, tem uma CSP própria que libera o CDN do Swagger.
8. **D4:** a falha de login passa pela mesma agregação por IP e janela, com limite de 50 origens registradas
   por janela. O resumo da janela inclui quantos logins diferentes foram tentados. O bloqueio por usuário e
   por IP continua contando cada falha em `auth_tentativas`; há teste com 60 IPs e com bloqueio vindo de 5
   IPs.
9. **E6:**
   - CSV com cabeçalho e separador `,` ou `;`;
   - erros por número de linha, **sem repetir o conteúdo** (que pode ser um nome);
   - login repetido sem diferenciar maiúsculas;
   - `aluno_id` repetido também é recusado;
   - senha no formato `xxxx-xxxx-xxxx` (cerca de 59 bits, sem caracteres ambíguos);
   - o arquivo de saída é aberto **antes** de mexer no banco; ele e o banco ficam inteiros ou nada fica.

## C3: o que a revisão de minimização achou

| Achado | Situação |
|---|---|
| **O Chroma mandava telemetria para `https://us.i.posthog.com`** (padrão do chromadb 0.5.23). Isso fere o R07 e a LGPD; os demos só escondiam o log do erro | **corrigido**: `Settings(anonymized_telemetry=False)` em um único `abrir_cliente()`, com teste |
| O 422 padrão do FastAPI devolvia o valor enviado (`input`): uma senha longa demais ou o texto da pergunta voltavam na resposta de erro | **corrigido**: o handler devolve só `loc`, `msg` e `type`, com teste |
| O log do feedback barrado pela guarda trazia trecho do texto gerado | **corrigido**: só o tipo do motivo |
| Rotas agregadas (`/relatorio/turma`, `/painel/competencias`, CSV, `/conteudo/*`) | **sem códigos** (teste com a turma de 12 alunos); o prompt da narrativa da turma também não leva códigos |
| `/painel/alunos-em-risco`, `/painel/revisao` e `/painel/auditoria` mostram códigos | por desenho: só docente e auditadas (consulta com códigos) |
| O log de acesso do uvicorn grava IP e rotas com o código do aluno | **pendência de implantação:** `--no-access-log` na lista da VM; em desenvolvimento, continua |
| `python -m tia.painel.amostra` sai sem código, mas com o texto da pergunta livre | registrado em `lgpd.md`: tratar o CSV como dado pessoal |
| As linhas anonimizadas apareceriam na revisão com texto vazio (e quebrariam o modelo) | **corrigido**: saem da lista e continuam no resumo |

## D2: dependências e segredos

- **`pip-audit` não está instalado** e não instalei nada (**pendência**: rodar na VM ou autorizar a
  instalação aqui). Versões instaladas: Python 3.12.3, SQLite 3.45.1, fastapi 0.115.0, starlette 0.38.6,
  uvicorn 0.32.0, pydantic 2.9.2, requests 2.32.3, chromadb 0.5.23 (com posthog 7.64.1), python-dotenv
  1.0.1, urllib3 2.8.0, httpx 0.27.2, pytest 8.3.3.
- **Suspeitas a confirmar com `pip-audit`.** É o que lembro das bases de vulnerabilidades, e não foi
  verificado aqui:
  - **starlette 0.38.6:** CVE-2024-47874 (multipart; o TIA não recebe formulário multipart) e um problema
    de desempenho com o cabeçalho `Range` nos arquivos estáticos (relevante para `/app`). Corrigir pede
    subir o fastapi junto, que é quem fixa o starlette.
  - **requests 2.32.3:** CVE-2024-47081 (`.netrc`; o TIA só chama o Ollama local).
- **git:**
  - `.env`, `data/` e `venv/` continuam ignorados (`git check-ignore`), e nenhum `.env`, `.db` ou chave
    aparece nos 10 últimos commits;
  - o `.env.example` não tem segredo (só valores padrão);
  - os arquivos padrão de saída da importação e da exportação (`senhas_temporarias-*.csv`, `titular-*.json`)
    entraram no `.gitignore`, para não serem commitados por engano se o comando rodar na raiz;
  - a busca por padrões de chave e senha em `git log -p -10` achou só a senha **fictícia** dos testes e as
    listas de palavras proibidas dos testes do front.
  - A senha de demonstração (`usuarios.SENHA_DEMONSTRACAO`) é pública por desenho e nunca deve ir para a VM.
- **Nesta máquina:** `.env` está com permissão 644 e `data/` com 775. Não alterei; na VM, use 600 e 700
  (`implantacao.md` 5.3).

## Pendências

- Validar com o jurídico/DEP: bases legais, prazos, se desvincular basta como anonimização, aviso de
  privacidade e canal do titular (`lgpd.md`, seção 9).
- Evento de fim do vínculo (fim do curso) para eliminar cadastro e trilha; hoje só pela eliminação a pedido.
- `pip-audit` e a atualização do fastapi/starlette se as suspeitas se confirmarem.
- Agendar `retencao --aplicar` no cron da VM; backups externos com prazo (os backups guardam o que a
  retenção já apagou).
- Login único do EBAULA e a decisão da sessão em iframe (`implantacao.md`, seções 2 a 4).
- Tela de administração e de troca voluntária de senha (o comando basta por enquanto).
- Se o login for o próprio código do aluno, ele continua em `usuarios` (desativado) depois da eliminação.

## O que depende do jurídico e da VM

- **Jurídico/DEP:** bases legais, prazos (365, 180, 730 e 30 dias), forma de anonimização, consentimento
  para o diálogo livre, canal e prazo do titular, aviso de privacidade, prazo dos backups.
- **VM (Tiago):**
  - HTTPS e proxy;
  - usuário de serviço e systemd;
  - permissões;
  - firewall e Ollama só em `127.0.0.1`;
  - backup;
  - cron da retenção;
  - retenção dos logs do proxy e do journald;
  - `pip-audit`.

## Perguntas para a Pessoa 4

1. O curso dura quanto tempo? Os prazos de 180 dias (textos) e 365 dias (respostas) precisam ser maiores que
   a duração, senão os indicadores de quem ainda estuda mudam.
2. Quando o aluno termina o curso, cadastro e trilha devem ser eliminados automaticamente? Depois de quanto
   tempo?
3. A revisão docente precisa dos textos por mais de 180 dias (por exemplo, para a avaliação do projeto)?
4. Para a importação: a secretaria consegue gerar o CSV `login,papel,aluno_id` com códigos (sem nome)? Quem
   entrega as senhas temporárias aos alunos?

## Perguntas para o Tiago

1. Caminhos, usuário de serviço e proxy da VM (nginx ou Caddy?) para fechar a seção 5 de `implantacao.md`.
2. O Ollama fica na mesma VM ou numa máquina com GPU na rede interna? Isso muda o firewall.
3. Política de backup da instituição: onde, por quanto tempo e com criptografia?
4. Posso instalar `pip-audit` no venv de desenvolvimento, ou a varredura fica para a VM?
5. A instituição tem encarregado (DPO) e canal oficial para pedidos de titular?
