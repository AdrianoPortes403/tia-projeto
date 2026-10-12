# Implantação do TIA na VM, passo a passo (EAP 1.4.1, 15/10/2026)

> Frente A3. Scripts em `deploy/`; a parte em Python, com testes, fica em `src/tia/implantacao/`. A
> segurança da VM (variáveis, systemd, firewall, logs) está em `docs/seguranca/implantacao.md`, seção 5. A
> LGPD está em `docs/seguranca/lgpd.md`. Os tempos são estimativas para uma VM com 8 vCPUs e um link de
> 100 Mbit/s; **a confirmar no dia**.

## 0. Antes do dia: o que pedir ao Tiago

| Item | Pedido | Por quê |
|---|---|---|
| Acesso | SSH com `sudo` para o Adriano; IP fixo ou nome interno | instalar, systemd, firewall |
| Sistema | Ubuntu 24.04 LTS, com `python3.12`, `python3.12-venv` e `nginx` instalados pelo apt (ou espelho interno) | os scripts não instalam pacotes do sistema |
| CPU | 8 vCPUs ou mais (x86_64) | o LLM em CPU é o gargalo do R09 |
| RAM | 16 GB mínimo; **32 GB** para medir `qwen3:8b` e `qwen3.5:9b` | o modelo inteiro fica na memória (`OLLAMA_KEEP_ALIVE`) |
| GPU | Opcional, mas decisiva para o R09: NVIDIA com 8 GB de VRAM ou mais, driver instalado. Ou uma máquina com GPU na rede interna rodando o Ollama | em CPU, os modelos de 8B e 9B dificilmente ficam em 15 s |
| Disco | 40 GB livres (modelos ~15 GB, aplicação, backups) | |
| HTTPS | Domínio interno (por exemplo `tia.<domínio>`) e certificado da instituição | o cookie de sessão é `Secure` |
| Firewall de entrada | só 443 (e 22 da rede interna) | |
| Firewall de **saída** | **bloqueada**, com uma janela temporária para baixar os modelos (`registry.ollama.ai:443` e o CDN dele) ou um proxy de saída | R07: o TIA não chama nada de fora; o único passo com rede é o download |
| Ollama | instalação do Ollama (o instalador oficial usa rede) | prefere instalar ele mesmo, ou libera a janela? |
| Backup | um destino fora da VM para `/srv/tia/backup` (cópia diária) e a política de quanto tempo guardar | os backups têm dados pessoais (`lgpd.md`) |
| Hora | NTP ativo | auditoria e prazos de retenção usam a hora local |

## 1. Na máquina de desenvolvimento (com rede), antes de ir para a VM: ~5 min

```bash
source venv/bin/activate
./run_tests.sh                        # 668 passados, 9 xfailed
./deploy/preparar_pacote.sh           # USA REDE (PyPI): dist/tia-<versão>.tar.gz, ~80 MB
scp dist/tia-<versão>.tar.gz* <usuário>@<vm>:/tmp/
```

O pacote leva o código, as 86 dependências travadas (`deploy/requirements.lock`) mais o próprio `tia` em
wheels, o `SHA256SUMS` dos wheels e a `VERSAO`. **A VM não precisa de PyPI.**

## 2. Na VM

| # | Passo | Comando | Root | Rede | Tempo |
|---|---|---|---|---|---|
| 1 | Conferir o pacote e descompactar | `cd /tmp && sha256sum -c tia-<versão>.tar.gz.sha256 && tar xzf tia-<versão>.tar.gz && cd tia-<versão>` | não | não | 1 min |
| 2 | Ollama instalado e no ar (Tiago) | `systemctl status ollama` | sim | **sim, se for instalar agora** | 5 min |
| 3 | Simular a instalação | `sudo ./deploy/instalar.sh --simular` | não* | não | 1 min |
| 4 | Instalar | `sudo ./deploy/instalar.sh` | sim | não | 3 a 5 min |
| 5 | Baixar modelos, reindexar e conferir | `sudo /srv/tia/atual/deploy/modelos.sh --simular`, depois sem `--simular` | sim | **SIM (único passo)** | 20 a 40 min (~15 GB) |
| 6 | Fechar a saída de novo (Tiago) | firewall | sim | — | — |
| 7 | Primeiro admin (senha temporária, troca no primeiro acesso) | `sudo /srv/tia/bin/tia usuarios criar --id <código> --papel admin` | sim | não | 1 min |
| 8 | Proxy HTTPS | ajustar `/srv/tia/atual/deploy/proxy/nginx-tia.conf` e criar o snippet; `nginx -t && systemctl reload nginx` | sim | não | 15 min |
| 9 | Teste de fumaça | `sudo /srv/tia/atual/deploy/verificar.sh` e `sudo /srv/tia/atual/deploy/verificar.sh --usuario <admin> < arquivo_com_a_senha` | sim | não | 2 min |
| 10 | Conferência de fora | no navegador: `https://<domínio>/app/` e `/app/painel/`; `/docs` dá 404 | não | — | 5 min |
| 11 | Medir o R09 | `sudo /srv/tia/atual/deploy/verificar.sh --medir-r09 10` | sim | não | 30 min (GPU) a 2 h (CPU) |
| 12 | Backup inicial | `sudo /srv/tia/atual/deploy/backup.sh` | sim | não | 1 min |
| 13 | Turma (quando houver o CSV) | `sudo /srv/tia/bin/tia usuarios importar --arquivo usuarios.csv --saida /root/senhas.csv`; entregar e **apagar** | sim | não | 5 min |

\* A simulação roda sem root, mas o `sudo` permite ver tudo como será feito.

### O que a instalação faz (`deploy/instalar.sh`)

1. Confere Ubuntu 24.04, Python 3.12 com venv, o pacote e as somas SHA256 dos wheels (só leitura).
2. Cria o usuário de serviço `tia`, sem login e sem `sudo`.
3. Cria `/srv/tia/{versoes,bin}` (root, 755), `config/` (root:tia, 750) e `data/`, `backup/` e
   `medicoes/` (tia, 700).
4. Copia a versão para `/srv/tia/versoes/<VERSAO>` (root, só leitura para o serviço) e cria o venv dela com
   `pip --no-index`.
5. Aponta `/srv/tia/atual` para a versão nova e guarda a anterior em `/srv/tia/anterior`.
6. Cria o `.env` a partir do `.env.example`, com os valores de produção (`TIA_AMBIENTE=producao`, auth
   ligada, cookie `Secure`, `/docs` fechado, Ollama e API em 127.0.0.1, caminhos em `/srv/tia/data`),
   com permissão 640 (root:tia). **Nunca sobrescreve** um `.env` que já exista; só lista as chaves novas.
7. Instala o comando `/srv/tia/bin/tia`, que roda os módulos como `tia`, com o `.env`.
8. Instala as unidades do systemd e o ajuste do Ollama (só 127.0.0.1); ativa a API e os timers.
9. Cria as tabelas do banco (permissão 600) e reinicia a API.

Rodar de novo é seguro: cada passo confere antes e só faz o que falta.

### Serviços e timers (`deploy/systemd/`)

| Unidade | O que faz | Quando |
|---|---|---|
| `tia-api.service` | uvicorn em 127.0.0.1:8000, com `--proxy-headers` e `--no-access-log`, ambiente de produção, reinício automático, usuário `tia`, sistema de arquivos só leitura exceto `data/` | sempre |
| `tia-limpeza.timer` | `python -m tia.seguranca.limpeza`: sessões vencidas e IPs fora do prazo (a API já faz isso; o timer cobre a API parada) | a cada hora |
| `tia-inatividade.timer` | `python -m tia.orquestrador --verificar-inatividade`: regra R3 (incentivo e trilha refeita) | todo dia, 06:00 |
| `tia-retencao.timer` | `python -m tia.seguranca.retencao --simular`: só **lista** o que passou do prazo (no journal). Aplicar é decisão humana, depois de o jurídico aprovar os prazos | segunda, 04:00 |
| `tia-backup.timer` | `python -m tia.implantacao.backup fazer`: banco, índice e `.env` à parte; rotação por `BACKUP_DIAS` | todo dia, 02:30 |
| `ollama.service.d/tia.conf` | `OLLAMA_HOST=127.0.0.1:11434` | — |

Para ver o resultado: `journalctl -u tia-retencao.service` (e assim por diante); `systemctl list-timers 'tia-*'`.

## 3. Modelos e raciocínio

- **Modelos:** `MODELOS_LLM` (padrão `qwen3:1.7b,qwen3:4b,qwen3:8b,qwen3.5:9b`). **A etiqueta do 9B é
  PROVISÓRIA:** se o `ollama pull qwen3.5:9b` falhar, procurar a etiqueta certa na biblioteca do Ollama e
  corrigir no `.env`. Também `EMBED_MODEL` (`nomic-embed-text`).
- **Modelo padrão:** `MODELO_PADRAO` é o que os agentes usam; escolher depois da medição do R09.
- **Raciocínio:** `RACIOCINIO_POR_MODELO` diz, por modelo, como desligar o raciocínio: `/nothink` no prompt,
  opção `think: false` da API, os dois, ou nada.
  - Qwen3 usa os dois.
  - Para o qwen3.5 o valor é `api`, PROVISÓRIO: conferir na medição (colunas `raciocinio_*`) e trocar se
    vazar.
  - Os blocos `<think>` que vierem no texto são sempre removidos antes das guardas.

## 4. Medição do R09 (`verificar.sh --medir-r09 N`)

Para cada modelo, faz uma chamada de aquecimento (carrega o modelo; fica fora do resumo) e N interações reais
de cada tipo, pelas mesmas funções dos agentes:

- **feedback:** feedback de uma questão, com RAG, LLM e guarda;
- **diálogo:** pergunta livre fixa;
- **planejamento:** justificativas da trilha.

**Nada é gravado no banco e nenhum dado de aluno é usado.**

Saída:

- `/srv/tia/medicoes/r09-<data>.csv`, uma linha por interação, com:
  - tempo de ponta a ponta e tempo só do LLM;
  - origem: LLM, guarda, fallback ou parcial;
  - tipo do motivo de descarte e falha;
  - raciocínio no texto, bloco aberto, raciocínio pela API;
  - resposta cortada, vazia, e tokens;
- `r09-<data>-resumo.csv`, com média, p50, p90, p95, máximo, fração dentro de 15 s e as contagens, por
  modelo e tipo.

Leitura: o R09 vale para a interação inteira. Prefira o **p90/p95 abaixo de 15 s** à média. Um modelo
rápido com muito descarte da guarda ou muito fallback não serve. Raciocínio vazando aponta para o modo
errado no mapa.

Comandos úteis:

- um modelo só: `--modelos qwen3:4b`;
- um tipo só: `--tipos feedback`.

## 5. Como reverter

| Situação | O que fazer |
|---|---|
| Versão nova com problema | `sudo ln -sfn "$(readlink /srv/tia/anterior)" /srv/tia/atual && sudo systemctl restart tia-api` (as versões antigas ficam em `/srv/tia/versoes/`) |
| Dados estragados | `sudo systemctl stop tia-api && sudo /srv/tia/atual/deploy/restaurar.sh /srv/tia/backup/<data> --simular`, depois sem `--simular`. Nada é apagado: o banco e o índice atuais ficam como `*.antes-restauracao-<data>`. O `.env` só volta com `--com-env` |
| `.env` errado | editar `/srv/tia/config/.env`; `sudo /srv/tia/bin/tia config` mostra os valores e os avisos; `sudo systemctl restart tia-api` |
| Retirar o TIA | `sudo systemctl disable --now tia-api tia-limpeza.timer tia-inatividade.timer tia-retencao.timer tia-backup.timer`. Os dados ficam em `/srv/tia/data` e `/srv/tia/backup` até a decisão de apagar (LGPD) |
| Desfazer o ajuste do Ollama | apagar `/etc/systemd/system/ollama.service.d/tia.conf`, `daemon-reload`, reiniciar o Ollama |

## 6. Quando o `verificar.sh` acusa falha

| Verificação | Causa provável |
|---|---|
| configuracao | `.env` com `TIA_AUTH=desligada`, `AUTH_COOKIE_SEGURO=0` ou `OLLAMA_URL` fora da rede interna (a API nem sobe) |
| banco | permissão diferente de 600 (`chmod 600 /srv/tia/data/tia.db`); falta de admin é só aviso |
| api | `systemctl status tia-api` e `journalctl -u tia-api`; porta errada em `API_URL_LOCAL` |
| login | com `--usuario`: senha errada ou temporária (a troca é pelo navegador) |
| ollama | modelo faltando (`modelos.sh`); Ollama parado; etiqueta errada em `MODELOS_LLM` |
| chroma | `sudo /srv/tia/bin/tia indexar` (precisa do modelo de embeddings) |
| rede | lista as conexões de saída da **máquina** para fora de 127.0.0.1 e do Ollama: atualização automática, agente de monitoramento, a sessão do próprio download. Com a saída bloqueada no firewall, deve ficar vazia |
