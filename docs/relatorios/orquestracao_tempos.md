# Tempos da orquestração e origem das respostas do LLM (10/10/2026)

Sem commit. Continuação de `docs/relatorios/orquestracao.md`.

## 1. Por que o Planejador levava ~12 s fixos

**Confirmado: as justificativas estouravam o timeout e caíam no texto padrão.**
`PLANEJADOR_TIMEOUT_LLM` tinha padrão 12 s, herdado de quando o R09 era otimizado em
desenvolvimento. Em CPU, a chamada única que justifica a trilha toda leva mais que isso.

| Timeout | Tempo da chamada | Resultado |
|---|---|---|
| 12 s | 12,0 s | `ReadTimeout` → texto padrão nas 3 etapas |
| 120 s | 8,7 s | LLM justificou as 3 etapas |

Medição isolada de `justificar_trilha` com a trilha da demonstração, qwen3:1.7b em CPU.

O log `WARNING ... Justificativas do LLM indisponíveis (ReadTimeout)` não aparecia na demonstração,
porque ela usa o nível ERROR.

**Correção:**
- **Padrão:** `PLANEJADOR_TIMEOUT_LLM` passou para **120** em `core/config.py` (decisão de 10/10: valores
  altos em desenvolvimento; R09 medido na VM). Os outros timeouts não mudaram.
- **`.env.example`:** também passou de 12 para 120. Quem copiasse o `.env.example` antigo voltaria ao
  problema. O `.env` local não define a variável.

## 2. Origem de cada justificativa e feedback, com aviso de timeout

Um único classificador de falha, `llm_client.descrever_falha`, devolve `"timeout"` para
`requests.Timeout`/`TimeoutError` e, nos outros casos, o nome do erro (ex.: `ConnectionError`).

| Onde | Campos novos na resposta |
|---|---|
| Planejador: `Trilha` (`POST /planejador/trilha`, `POST /aluno/{id}/iniciar`) | `etapas[].origem_justificativa` (`LLM` ou `fallback`; gravado em `trilha_estudo` por ADD COLUMN) e `falha_llm` (`timeout`, outro erro, ou `formato` quando o LLM não deu frase válida para todas as etapas) |
| Tutor: `Feedback` (`/tutor/resposta`, evento `resposta`) | `falha_llm` (`timeout`, outro erro, ou `rag: <erro>`), ao lado de `origem` (LLM, guarda ou fallback) |
| Tutor: diálogo (`/tutor/perguntar`) | `falha_llm` |
| Relatório: `Narrativa` | `falha_llm` |
| Orquestrador: `DecisaoReplanejamento` (todas as rotas `/aluno/...`) | `origem_justificativas` (`LLM`, `parcial` ou `fallback`), `falha_llm` e `tempo_planejador_ms` (também gravados em `orquestrador_decisoes`) |

O Planejador não tem guarda de saída: uma frase fora do formato é descartada, e a etapa fica com o
texto padrão (`fallback`, motivo `formato`).

A demonstração imprime a origem de cada feedback e de cada justificativa. Quando foi tempo, marca
**(TIMEOUT do LLM)** e, no fim, conta os fallbacks por timeout de cada agente.

## 3. Tempo por etapa (Tutor x Planejador)

A demonstração termina com uma tabela por etapa:
- **Tutor:** soma de `Feedback.tempo_ms`.
- **Planejador:** soma de `tempo_planejador_ms` das decisões.
- **Relatório:** geração dos relatórios.
- **Resto:** orquestração, banco e regras.

### Sem LLM (`--sem-llm`)

| Etapa | Total | Tutor | Planejador | Relatório | Resto |
|---|---|---|---|---|---|
| Matrícula | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| Acertos | 0,3 | 0,2 | 0,0 | 0,0 | 0,1 |
| Queda | 0,1 | 0,0 | 0,0 | 0,0 | 0,1 |
| Inatividade | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| Retomada | 0,3 | 0,0 | 0,0 | 0,0 | 0,2 |
| Relatórios | 0,0 | 0,0 | 0,0 | 0,0 | 0,0 |
| **Total** | **0,7** | 0,2 | 0,0 | 0,0 | 0,4 |

Todo feedback e toda justificativa saem como `fallback (ConnectionError)` / `(rag: ConnectionError)`,
porque `--sem-llm` simula o Ollama fora do ar.

### Com LLM (qwen3:1.7b em CPU, notebook; `PLANEJADOR_TIMEOUT_LLM=120`)

| Etapa | Total | Tutor | Planejador | Relatório | Resto |
|---|---|---|---|---|---|
| Matrícula | 9,7 | 0,0 | 9,7 | 0,0 | 0,0 |
| Acertos (4 respostas, 1 replanejamento) | 140,9 | 127,3 | 13,4 | 0,0 | 0,1 |
| Queda (3 respostas, 1 replanejamento) | 134,4 | 102,5 | 31,7 | 0,0 | 0,2 |
| Inatividade (1 replanejamento) | 24,6 | 0,0 | 24,5 | 0,0 | 0,1 |
| Retomada (11 respostas, 3 replanejamentos) | 507,5 | 436,0 | 70,8 | 0,0 | 0,6 |
| Relatórios (aluno e turma) | 23,4 | 0,0 | 0,0 | 23,4 | 0,0 |
| **Total** | **840,5** | **665,9** (79%) | **150,1** (18%) | **23,4** (3%) | **1,1** |

- **Origem:**
  - 18 de 18 feedbacks do Tutor vieram do LLM;
  - as 7 chamadas do Planejador tiveram as justificativas do LLM em todas as etapas;
  - a interpretação do relatório veio do LLM.
- **Fallbacks:** nenhum, nem por timeout nem por outro motivo.
- **Tutor:** cerca de 37 s por resposta, em média. É o que mais pesa.
- **Planejador:** de 9,7 a 31,7 s por chamada (média de 21,4 s). Com o timeout antigo de 12 s, 6 das 7
  chamadas teriam estourado.
- **Comparação com a rodada anterior (timeout 12 s):** o total subiu de 752,8 s para 840,5 s, porque o
  Planejador passou a esperar o LLM terminar em vez de desistir aos 12 s. A orquestração em si (resto)
  custa cerca de 1 s.
- **R09:** nenhuma interação com LLM cabe em 15 s nesta máquina. A medição vale na VM.

## 4. Testes

`./run_tests.sh`: **327 passed, 9 xfailed**. As 9 falhas esperadas são do portão do diálogo, já
documentadas.

**Novos:**
- origem por etapa e `falha_llm` (`timeout`, `formato`, sem falha) no Planejador;
- `descrever_falha`;
- `falha_llm` no feedback, no diálogo e na narrativa;
- a decisão do orquestrador com origem, falha e tempo;
- timeout simulado no Planejador e no Tutor, aparecendo na rota.

**Atualizados:**
- O teste que exigia `timeout <= 15` agora confere o valor da config.
- As comparações exatas incluem os campos novos.
