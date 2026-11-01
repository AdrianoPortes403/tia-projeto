# Fechamento da documentação do M6 (31/10/2026)

> Frente A3, branch `docs-fechamento`. Só documentação e comentários de configuração: nada em `src/` nem em
> `conteudo/` foi alterado. Sem commit.

## O que mudou

| Arquivo | Mudança |
|---|---|
| `docs/limitacoes_conhecidas.md` (novo) | consolida os 10 pontos da seção 4.1 de `retomada_2026-10-31.md`, mais: recomeço de competência sem limite, taxa de acerto só da sessão, iframe do EBAULA dependente de mesmo site e SSO pendente (alternativa: nova aba), erro de telemetria do Chroma no log (sem tráfego externo) e os itens PROVISÓRIO restantes. Cada ponto tem descrição, impacto, mitigação e responsável |
| `docs/avaliacao/evidencia_requisitos.md` (novo) | tabela de R03, R07, R08, R09, R11 e R12: o que prova cada um, status e o que falta. R09 e a amostra de 100 do R12 ficam **pendentes** (VM e avaliação docente), sem números inventados. R03 registra a reindexação local de 31/10 |
| `deploy/perfil_piloto.env` | cabeçalho sem "PROVISÓRIO": os valores constam como validados (D7); fica em aberto só o duplo papel de `INATIVIDADE_DIAS` |
| `.env.example` | o comentário de `INATIVIDADE_DIAS` saiu de cima do bloco 3/2/3, foi para junto da variável e passa a dizer que ela vale para o incentivo, o painel, o Relatório e a narrativa |
| `docs/seguranca/implantacao.md` | seção 1: o iframe do plug-in existe (`TIA_FRAME_ANCESTORS`), mas o login só funciona no mesmo site; alternativa: nova aba; nota sobre o `X-Frame-Options` do nginx. Seção 3: "Nada disso foi implementado" trocado pelo estado atual de cada alternativa (A implementada no TIA, B funcionando, C e D não implementadas) e a ressalva sobre caminho na mesma origem |
| `docs/relatorios/retomada_2026-10-31.md` | resultado real do `./run_tests.sh` na seção 1 |

## Achado durante o fechamento: pedaços antigos no índice do Chroma

O índice local (`data/chroma_db`, reindexado em 31/10) tem **82 pedaços**: os 69 da reindexação (10 arquivos,
incluindo `dev_01`, `dev_02`, `cib_01` e `cib_02`) e **13 pedaços antigos** de `provisorio_condicionais`,
`provisorio_funcoes`, `provisorio_listas_strings`, `provisorio_repeticao` e `provisorio_variaveis_tipos`, com o
mesmo texto dos arquivos renomeados. O `rag/ingest.py` usa `upsert` e não apaga ids de arquivos que sumiram.
Consequência: uma resposta da base comum pode citar a fonte com o nome antigo (R03).

Não foi corrigido aqui (fora do escopo: dados locais e `src/`). Correção: apagar `data/chroma_db` e rodar
`python -m tia.rag.ingest`; na VM, ingerir num índice vazio. Registrado em `limitacoes_conhecidas.md` (item 10)
e em `evidencia_requisitos.md` (R03).

## Testes

`./run_tests.sh` em 31/10 (sobre `add838b`, com o PR #5): **745 passed, 9 xfailed, 1 warning in 294.28s
(0:04:54)**. A rodada começou antes das edições do `.env.example` e do `deploy/perfil_piloto.env`. Por isso,
o arquivo que lê o `.env.example` (`tests/test_tutor.py`) rodou de novo depois delas: 78 passed. Em 01/11, a
suíte completa rodou de novo com todas as edições: **745 passed, 9 xfailed, 1 warning in 328.67s (0:05:28)**.
Na mesma revisão, a referência à política de senha em `limitacoes_conhecidas.md` foi corrigida para
`.env.example:113`. A seção 1 de
`retomada_2026-10-31.md` traz o resultado e o histórico (antes do PR #5: 1 failed, 744 passed).

## Pendências que seguem

- Mesclar esta branch (sem commit até a revisão).
- Limpar o índice do Chroma (acima).
- `arquitetura.md:138` (diagrama, "R3: refazer a trilha (>= 14 dias)") continua desatualizado: não estava no
  pedido.
- Relatório do piloto: depende do piloto e da VM (`retomada_2026-10-31.md`, seção 4.3).
