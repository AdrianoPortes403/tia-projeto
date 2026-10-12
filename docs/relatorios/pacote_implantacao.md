# Pacote de implantação na VM (EAP 1.4.1)

> Frente A3, 11/10/2026. Sem commit. Passo a passo para 15/10: `docs/implantacao_vm.md`. Segurança da VM:
> `docs/seguranca/implantacao.md`, seção 5.

## Resultado

- `./run_tests.sh`: **668 passados, 9 xfailed** (os 9 conhecidos), 0 falhas. São 44 testes novos em
  `tests/test_implantacao.py`. Num teste antigo, `test_pontos_de_rede_do_codigo`, a lista de endereços
  permitidos ganhou a API local (`127.0.0.1:8000`) usada pelo teste de fumaça; continua falhando para
  qualquer outro endereço.
- **Testado de verdade aqui, sem root e sem Ollama:**
  - `instalar.sh --simular`, `modelos.sh --simular` e `preparar_pacote.sh --simular`: nenhum arquivo
    criado;
  - `instalar.sh` sem root recusa;
  - `backup.sh` e `restaurar.sh` de verdade em pasta temporária: permissões 700/600, `.env` à parte,
    restauração que não apaga nada, backup alterado recusado, rotação;
  - `verificar.sh` de ponta a ponta contra a **API real num subprocesso** (ambiente de produção) e um
    **Ollama falso** (servidor HTTP do teste, com um modelo que vaza `<think>` e outro que não);
  - fumaça completa, login de verdade com `--usuario` e `--medir-r09` gravando o CSV.
- **Instalação sem rede conferida:**
  - gerei o pacote com `preparar_pacote.sh` (~80 MB; 86 dependências + o `tia` em wheels);
  - conferi o `SHA256SUMS` e instalei num venv temporário com `pip --no-index`, como o `instalar.sh` faz;
  - o TIA importou e o `pip check` não acusou nada;
  - apaguei o pacote e o venv depois.
- **O `verificar.sh` acusou, nesta máquina, as conexões de saída reais dela** (GitHub, Anthropic, Google), o
  que mostra que a verificação de rede funciona. Na VM, com a saída bloqueada, a lista deve ficar vazia.

## Arquivos

| Arquivo | O que é |
|---|---|
| `src/tia/core/config.py`, `.env.example` | `MODELOS_LLM`, `MODELO_PADRAO` (`CHAT_MODEL` ainda vale), `RACIOCINIO_POR_MODELO`, `RACIOCINIO_TAGS`, `BACKUP_DIR`, `BACKUP_DIAS`, `API_URL_LOCAL`, `R09_LIMITE_SEGUNDOS`; `avisos_de_configuracao()` (não bloqueia a API) |
| `src/tia/core/llm_client.py` | modo de raciocínio por modelo; `remover_raciocinio` antes de devolver o texto; `usar_modelo`, `coletar_chamadas` e `RespostaLLM` (tempo, raciocínio, corte, vazia, falha); `listar_modelos_instalados` (`GET /api/tags`) |
| `src/tia/implantacao/` (novo) | `modelos.py` (instalados e respondem), `verificar.py` (fumaça e R09), `backup.py` (backup, rotação e restauração) |
| `deploy/lib.sh` | funções comuns: `--simular`, `fazer`, `como_tia` (roda como o usuário do serviço, com o `.env`), `config_tia` |
| `deploy/preparar_pacote.sh` | na máquina de desenvolvimento, **com rede**: pacote com código, wheels, SHA256SUMS e VERSAO |
| `deploy/instalar.sh` | instalação idempotente e sem rede (9 passos, `--simular`, `--com-rede` só como exceção) |
| `deploy/modelos.sh` | **único passo com rede**: `ollama pull`, reindexação, cada modelo responde |
| `deploy/backup.sh`, `deploy/restaurar.sh` | backup e restauração (`--simular`, `--listar`, `--com-env`; recusa restaurar com a API no ar) |
| `deploy/verificar.sh` | fumaça e `--medir-r09 N` |
| `deploy/tia` | comando `/srv/tia/bin/tia <usuarios\|titular\|retencao\|limpeza\|inatividade\|indexar\|modelos\|verificar\|backup\|config>` |
| `deploy/systemd/` | `tia-api.service`; serviço e timer de limpeza, inatividade, retenção (simulação) e backup; `ollama.service.d/tia.conf` |
| `deploy/proxy/nginx-tia.conf` | exemplo comentado: TLS 1.2+, HSTS, cabeçalhos, 64 KB por pedido, limite de taxa no login, log sem IP completo, `/docs` fechado |
| `deploy/requirements.lock` | fechamento das dependências de execução, versões exatas (sem pytest) |
| `tests/test_implantacao.py` (novo) | testes |
| `docs/implantacao_vm.md` (novo), `docs/arquitetura/arquitetura.md`, `docs/seguranca/implantacao.md`, `docs/seguranca/lgpd.md`, `CLAUDE.md`, `.gitignore` | documentação; `dist/` e `medicoes/` fora do git |

## Decisões

1. **Raciocínio desligado por modelo, mas sempre removido do texto.**
   - O mapa diz como desligar: Qwen3 com `/nothink` mais `think: false`, como já era; qwen3.5 com `api`
     (PROVISÓRIO); desconhecido com `nada`. Assim não se manda um parâmetro que um modelo sem raciocínio
     poderia recusar.
   - Independentemente do modo, o `llm_client` remove `<think>` e afins: bloco completo, só o fechamento (a
     abertura veio no template) ou bloco aberto, quando a resposta foi cortada no meio do raciocínio. Antes,
     só o bloco completo era removido, e cada agente fazia a remoção por conta própria. O bloco aberto
     vazava.
   - Antes, as frases completas de um raciocínio cortado chegavam à guarda e podiam ir ao aluno. Agora o
     bloco aberto vira texto vazio, e portanto fallback. Há testes dos dois casos (bloco completo com número
     inventado, bloco cortado) e do texto limpo na narrativa e no Planejador.
2. **Medição sem tocar no código dos agentes.** `usar_modelo` e `coletar_chamadas` são variáveis de contexto
   do `llm_client`; o `--medir-r09` chama as mesmas funções que os agentes usam (`gerar_feedback`,
   `gerar_resposta`, `justificar_trilha`) e nada é gravado no banco.
3. **Sem rede na VM:**
   - as dependências vão em wheels dentro do pacote, conferidas por SHA256, e o `pip` roda com `--no-index`;
   - o `ollama pull` é o único passo com rede, isolado em `modelos.sh`, que tem `--sem-download` para quando
     os modelos chegarem de outro jeito;
   - a instalação do próprio Ollama fica com o Tiago (o instalador oficial usa rede).
4. **Nada destrutivo e reversível:**
   - versões lado a lado em `/srv/tia/versoes`, com `atual` e `anterior` como links;
   - o `.env` nunca é sobrescrito;
   - a restauração guarda o banco e o índice atuais;
   - a rotação de backup só apaga o que tem o formato de nome criado por ela e mantém sempre o mais recente.
5. **A retenção roda só em simulação no timer.** Aplicar apaga dados pessoais e depende da aprovação dos
   prazos pelo jurídico (`lgpd.md`): fica como comando manual.
6. **A configuração tem uma fonte só.** Os scripts em shell leem os valores pelo `core/config.py`
   (`config_tia`) e não repetem padrões. O valor de `RACIOCINIO_POR_MODELO` vai entre aspas no `.env`
   porque o shell, o systemd e o python-dotenv precisam ler o mesmo arquivo; isso está conferido.
7. **Endurecimento:**
   - usuário `tia` sem login;
   - código como root e só leitura;
   - `UMask=0077`, `ProtectSystem=strict`, `NoNewPrivileges`, escrita só em `data/` (e `backup/` no timer);
   - o wrapper e `como_tia` limpam `PYTHONPATH`. Nesta máquina, o do ROS 2 contaminava o `pip check`.
8. **Backup também por timer** (02:30, todo dia), além do `backup.sh` manual. Não estava pedido, mas sem
   ele o backup dependeria de lembrar de rodar.

## O que não foi possível testar sem a VM

- `instalar.sh` de verdade: `useradd`, `chown`, `install -o tia`, `systemctl enable` e `runuser` exigem
  root. Foram testados só o `--simular` e a recusa sem root; a instalação dos wheels sem rede foi conferida à
  parte.
- As unidades do systemd rodando, os timers e o endurecimento (ex.: se `ProtectSystem=strict` deixa o Chroma
  escrever em `data/chroma_db`).
- `modelos.sh` de verdade, que exige o Ollama e a rede para o `ollama pull`. A **etiqueta `qwen3.5:9b`**
  precisa ser confirmada.
- Se o modo `api` desliga mesmo o raciocínio do qwen3.5. A medição mostra nas colunas `raciocinio_*`.
- O R09 em si: tempos reais por modelo, em CPU e em GPU.
- O nginx com certificado real, o HSTS e o limite de taxa; o IP real chegando pelo `--proxy-headers`.
- A verificação de rede na VM com a saída bloqueada (aqui ela acusa as conexões desta máquina, como
  esperado).
- O backup do Chroma com a API escrevendo ao mesmo tempo. O tar não é atômico; o índice pode ser refeito com
  `tia indexar`.

## Observações para a medição

- O Planejador chama o LLM **sem `max_tokens`**, enquanto o Tutor e o Relatório limitam. Se o planejamento
  estourar os 15 s, o primeiro ajuste é um `PLANEJADOR_MAX_TOKENS`.
- O diálogo pode responder **sem chamar o LLM** (portão de cobertura ou sem trecho relevante). O resumo conta
  isso como "sem LLM", para não parecer mais rápido do que o LLM é.

## Perguntas para o Tiago

1. A VM terá GPU? Se não, há uma máquina com GPU na rede interna para o Ollama? Com quanta RAM e VRAM?
2. Como vamos baixar os modelos: janela temporária de saída para `registry.ollama.ai` (e o CDN dele), proxy
   de saída, ou você copia os modelos (`~/.ollama/models`) de outra máquina?
3. Você instala o Ollama, ou libera a rede para o instalador oficial? Que versão?
4. O apt da VM tem espelho interno (para `python3.12-venv` e `nginx`)?
5. Domínio e certificado: qual nome e quem renova? (O Let's Encrypt precisa de rede na renovação.)
6. Para onde vai a cópia diária de `/srv/tia/backup` fora da VM, e por quanto tempo?
7. Há monitoramento ou agente na VM que faça conexões de saída? (O `verificar.sh` vai acusá-las.)
8. Posso usar `/srv/tia` e o usuário `tia`, ou há um padrão da instituição para caminhos e nomes de serviço?
