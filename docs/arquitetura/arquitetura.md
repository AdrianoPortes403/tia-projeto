# Arquitetura do Sistema TIA (EAP 1.3.1) e Orquestração (EAP 1.3.5)

> Protótipo integrado (fatia vertical) da frente A3. Situação em 10/10/2026.
> Dados pedagógicos (ementa, perfis, banco de itens, material) e regras marcadas como
> **PROVISÓRIO** dependem da Pessoa 2 (agentes) e da Pessoa 4 (conteúdo).

## Diagrama

Legenda: caixas com borda contínua **existem** e têm testes. Caixas tracejadas **ainda não existem**.

```mermaid
flowchart LR
    subgraph Clientes
        WEB["Web standalone<br/>(não existe)"]:::futuro
        DASH["Dashboard 1.4.5<br/>(não existe)"]:::futuro
        EBA["Plug-in EBAULA<br/>(não existe)"]:::futuro
        CLI["Demonstrações<br/>python -m tia..."]
    end

    AUTH["Autenticação 1.4.6<br/>(não existe: TODO nas rotas)"]:::futuro
    CRON["Agendador na VM (cron/timer)<br/>(não existe: depois de 15/10)"]:::futuro

    subgraph API["API FastAPI (src/tia/api)"]
        RORQ["/aluno/{id}/iniciar · proximo · sessao · evento · estado<br/>/orquestrador/verificar-inatividade"]
        RPLAN["/planejador/trilha · /alunos/{id}/trilha"]
        RTUT["/tutor/sessao · resposta · perguntar<br/>/tutor/dialogo/{id}/veto · /tutor/incentivo"]
        RREL["/relatorio/aluno/{id} · /relatorio/turma"]
        RAUD["/auditoria/{id}"]
    end

    ORQ["Orquestrador 1.3.5<br/>fluxo · eventos · regras"]

    subgraph Agentes
        A1["Agente 1: Planejador<br/>trilha determinística + justificativas"]
        A2["Agente 2: Tutor<br/>questionário adaptativo · feedback ·<br/>diálogo · incentivo · veto R12"]
        A3["Agente 3: Relatório<br/>5 indicadores (código) + narrativa"]
    end

    subgraph Infra["Infraestrutura local (R07)"]
        LLM["core/llm_client<br/>única porta para o LLM"]
        OLL["Ollama<br/>qwen3 (chat) · nomic-embed-text"]
        RAG["RAG: Chroma<br/>conteudo/materiais"]
        DB[("SQLite<br/>data/tia.db")]
        AUD[("auditoria R11<br/>(tabela no SQLite)")]
        CONT["conteudo/*.json<br/>ementa · perfis · itens (PROVISÓRIO)"]
    end

    WEB & DASH & EBA -.-> AUTH -.-> API
    CRON -.->|"verificar-inatividade"| RORQ
    CLI --> ORQ & A1 & A2 & A3
    RORQ --> ORQ
    RPLAN --> A1
    RTUT --> A2
    RREL --> A3
    RAUD --> AUD

    ORQ -->|"planejar_e_salvar"| A1
    ORQ -->|"responder · competências concluídas · sessão aberta"| A2
    ORQ -->|"tendência · engajamento (detecção)"| A3
    ORQ -->|"decisões com motivo"| AUD

    A1 --> LLM
    A2 --> LLM
    A3 --> LLM
    A2 --> RAG
    RAG --> LLM
    LLM --> OLL
    A1 & A2 & A3 & ORQ --> DB
    A2 & A3 --> AUD
    A1 & A2 & A3 --> CONT

    classDef futuro stroke-dasharray: 5 5,color:#777
```

## O que existe e o que não existe

| Parte | Situação |
|---|---|
| LLM local (Ollama, qwen3) via `core/llm_client` | **Real** (R07: nunca API externa) |
| RAG (Chroma + nomic-embed-text) | **Real**. O material é PROVISÓRIO (Pessoa 4) |
| Agente 1 Planejador | **Real**. Ementa e perfis são PROVISÓRIOS |
| Agente 2 Tutor (questionário, feedback com guarda, diálogo, incentivo, veto R12) | **Real**. O banco de itens é PROVISÓRIO |
| Agente 3 Relatório (5 indicadores, narrativa com guarda) | **Real**. Os indicadores são PROVISÓRIOS |
| Orquestrador (este documento) | **Real**. As regras são PROVISÓRIAS |
| Agendador da verificação de inatividade (cron/timer na VM) | **Não existe**. O comando e a rota que ele chamará existem (`python -m tia.orquestrador --verificar-inatividade`, `POST /orquestrador/verificar-inatividade`) |
| Auditoria (R11) | **Real** (tabela `auditoria`, `GET /auditoria/{id}`) |
| API FastAPI | **Real**, **sem autenticação** (TODO 1.4.6 nas rotas) |
| Autenticação de aluno/docente (1.4.6) | **Não existe** |
| Web standalone (`web/`) | **Não existe** |
| Dashboard institucional (1.4.5, `dashboard/`) | **Não existe**. Vai consumir o JSON de `/relatorio/...` |
| Plug-in EBAULA (`plugin-ebaula/`) | **Não existe** |
| VM institucional (medição do R09) | **Não disponível**. Os tempos foram medidos em notebook (CPU) |

## Fluxo de dados do aluno (orquestrado)

```mermaid
sequenceDiagram
    participant C as Cliente
    participant A as Agendador (VM)
    participant O as Orquestrador
    participant P as Planejador
    participant T as Tutor
    participant R as Relatório
    participant D as SQLite + auditoria

    C->>O: POST /aluno/{id}/iniciar (perfil, diagnóstico, horas)
    O->>P: planejar_e_salvar
    O->>D: matrícula + decisão "planejar" (auditoria)
    C->>O: GET /aluno/{id}/proximo
    O-->>C: iniciar_sessao (competência atual ou reforço)
    C->>O: POST /aluno/{id}/sessao (competência)
    O->>T: iniciar_sessao, só se for a competência atual ou o reforço
    O->>D: decisão "abrir_sessao" ou "recusar_sessao" (auditoria)
    loop cada resposta
        C->>O: POST /aluno/{id}/evento (resposta, evento_id)
        O->>T: responder (feedback com RAG + LLM + guarda)
        T->>D: histórico (item_id, sessao_id) + auditoria
        alt sessão concluída
            O->>P: R1: planejar_e_salvar com as concluídas (só o que falta) + aviso
        else sessão de reforço concluída
            O->>T: retomar a sessão pausada (mesmo nível)
        else queda (tendência do Relatório)
            O->>T: R2: pausar a sessão; reforço do pré-requisito direto
        end
        O->>D: decisão com motivo e aviso (auditoria)
        O-->>C: feedback + decisões + avisos + próxima ação
    end
    A->>O: POST /orquestrador/verificar-inatividade (todos os alunos)
    O->>R: engajamento (INATIVIDADE_DIAS)
    O->>T: R3: incentivo (>= 3 dias)
    O->>P: R3: refazer a trilha (>= 14 dias)
    O->>D: decisão por aluno (auditoria)
    C->>R: GET /relatorio/aluno/{id} · /relatorio/turma (sob demanda)
```

- **Abertura de sessão no fluxo gerenciado:** `POST /aluno/{id}/sessao`. Só abre a competência atual ou
  o reforço decidido pelo orquestrador; qualquer outra é recusada (409, com o motivo) e registrada na
  auditoria (`recusar_sessao`).
- **`POST /tutor/sessao`:** continua existindo para uso **standalone** e **não passa pelo orquestrador**.
  Não confere a competência atual, não avalia regras e não vincula reforço.
- **Respostas:** vão por `POST /aluno/{id}/evento`, para o orquestrador avaliar as regras. Uma resposta
  enviada direto a `/tutor/resposta` é registrada pelo Tutor, mas não passa pelas regras. Sessão pausada
  recusa resposta nas duas rotas.
- **Veto docente (R12):** fica na rota do Tutor, `PATCH /tutor/dialogo/{id}/veto`, e aparece no fluxo por
  `GET /aluno/{id}/estado`: `dialogos_vetados` e `rotas.veto_docente`.
- **Idempotência:** cada evento tem um `evento_id`. Reenviar o mesmo id devolve o resultado gravado
  (`repetido: true`) sem chamar o Tutor nem o Planejador de novo. Se o processamento falha, a reserva
  é desfeita e o evento pode ser reenviado.

## Decisões de orquestração

Tomadas em 10/10/2026. Quem decidiu, entre parênteses. As marcadas **PROVISÓRIO** dependem de validação
pedagógica da Pessoa 4 e têm limiar em `core/config.py`.

| # | Decisão | Como está implementada |
|---|---|---|
| D1 | **Replanejar só o que falta** (Pessoa 2) | `EntradaPlanejador.concluidas`: as competências concluídas entram na trilha marcadas `concluida` (horas 0, semana 0, sem justificativa do LLM) e nunca voltam a ficar pendentes. Contam como pré-requisito cumprido. Só as que faltam são agendadas, a partir da semana 1. Todo replanejamento do orquestrador passa as concluídas do Tutor |
| D2 | **Na queda: pausar, reforçar o pré-requisito direto a partir do nível 1 e retomar a original no nível em que parou, sem zerar** (Pessoa 2) | `tutor_sessoes.pausada` (ADD COLUMN): a sessão pausada guarda nível, item e itens usados, e recusa resposta. `orquestrador_reforcos` liga a sessão pausada à de reforço. A sessão de reforço é uma sessão nova do Tutor (nível 1). Ao concluí-la, a original é retomada (`retomar_original`) e o aluno é avisado do nível |
| D3 | **Abertura de sessão no fluxo gerenciado passa pelo orquestrador** (Pessoa 2) | `POST /aluno/{id}/sessao`. `/tutor/sessao` fica só para uso standalone |
| D4 | **Inatividade avaliada por comando/rota chamados por agendador externo** (cron/timer na VM, depois de 15/10; o agendador não faz parte deste pacote) (Pessoa 2) | `python -m tia.orquestrador --verificar-inatividade` e `POST /orquestrador/verificar-inatividade` percorrem os alunos matriculados e registram uma decisão por aluno (inclusive "nenhuma"). Rodar de novo não duplica nada. O `GET /proximo` não pede mais "replanejar" |
| D5 | **Concluir uma competência avança automaticamente e avisa o aluno.** PROVISÓRIO (Pessoa 4) | R1: `avancar` + aviso por template ("Parabéns! Você concluiu …. Próxima etapa: …") em `DecisaoReplanejamento.aviso` e `ResultadoEvento.avisos` |
| D6 | **Queda reforça só o pré-requisito direto.** PROVISÓRIO (Pessoa 4) | R2: primeiro pré-requisito da competência na ementa. Sem pré-requisito, não reforça (decisão "nenhuma"). Não há reforço do reforço |
| D7 | **Inatividade de 3 dias só retoma com incentivo, sem refazer a trilha; a trilha só é refeita após `ORQ_INATIVIDADE_REFAZER_DIAS`** (padrão 14). PROVISÓRIO (Pessoa 4) | R3: `incentivar` (mensagem do incentivo do Tutor, registrada na auditoria) a partir de `INATIVIDADE_DIAS`; `refazer_trilha` a partir de `ORQ_INATIVIDADE_REFAZER_DIAS`. Cada ação vale uma vez por período sem atividade |
| D8 | **Autenticação continua adiada** para o pacote 1.4.6 | TODO em todas as rotas abaixo |

### Rotas da orquestração que dependem da autenticação (1.4.6)

| Rota | Quem deve poder chamar |
|---|---|
| `POST /aluno/{id}/iniciar` | o próprio aluno ou um docente |
| `GET /aluno/{id}/proximo` | o próprio aluno ou um docente |
| `POST /aluno/{id}/sessao` | o próprio aluno |
| `POST /aluno/{id}/evento` | o próprio aluno (respostas); sistema (conclusão, inatividade) |
| `GET /aluno/{id}/estado` | o próprio aluno ou um docente |
| `POST /orquestrador/verificar-inatividade` | só o agendador/sistema ou um docente |

Também dependem dela, fora da orquestração: `/tutor/*` (incluindo o veto docente), `/relatorio/*` e
`/auditoria/{id}`.

## Regras (todas em `src/tia/orquestrador/regras.py`)

| Regra | Dispara quando | Ação | Limiares (config) | Status |
|---|---|---|---|---|
| R1 conclusão | Sessão do Tutor concluída na competência (2 acertos seguidos no nível 3), conclusão ainda não tratada | `avancar`: Planejador incremental (só o que falta) + aviso | (critério de conclusão do Tutor) | PROVISÓRIO (D5) |
| R2 queda | Tendência do Relatório "caindo" (última sessão contra as anteriores; sem sessão, janela de respostas). A sessão não é de reforço e ainda não causou reforço, há respostas suficientes desde o último reforço e existe pré-requisito direto | `reforcar`: pausa + reforço do pré-requisito direto no nível 1 (sem Planejador) | `RELATORIO_TENDENCIA_LIMIAR=0.15`, `RELATORIO_TENDENCIA_MIN_RESPOSTAS=3`, `RELATORIO_TENDENCIA_JANELA=5`, `ORQ_QUEDA_RESPOSTAS_ENTRE_REPLANOS=5` | PROVISÓRIO (D6) |
| Fim do reforço | A sessão de reforço foi concluída | `retomar_original`: a sessão pausada volta no mesmo nível | - | Decisão D2 |
| R3 inatividade | Engajamento do Relatório: dias sem atividade (sem atividade: desde a trilha). Avaliada pela verificação agendada | `incentivar` (>= `INATIVIDADE_DIAS`) ou `refazer_trilha` (>= `ORQ_INATIVIDADE_REFAZER_DIAS`, Planejador incremental). Uma vez por período | `INATIVIDADE_DIAS=3`, `ORQ_INATIVIDADE_REFAZER_DIAS=14` | PROVISÓRIO (D7) |

- **Próxima ação** (`GET /proximo`), por prioridade:
  1. reforço em curso (`iniciar_sessao` ou `continuar_sessao`, com `reforco: true`);
  2. `concluido`;
  3. `continuar_sessao` (sessão aberta, não pausada, na competência atual);
  4. `iniciar_sessao` (primeira etapa pendente da trilha).
- **Decisões:** toda decisão (`planejar`, `avancar`, `reforcar`, `retomar_original`, `incentivar`,
  `refazer_trilha`, `abrir_sessao`, `recusar_sessao` ou `nenhuma`) vai para `orquestrador_decisoes` e
  para a auditoria, com a regra e o motivo no campo `motivo`.

## Tabelas acrescentadas (só CREATE TABLE / ADD COLUMN)

- `orquestrador_matriculas`: perfil, horas e diagnóstico do aluno, que o Planejador não grava.
- `orquestrador_eventos`: `evento_id` e resultado (idempotência).
- `orquestrador_decisoes`: regra, ação, competência, motivo, aviso, sessão, evento, se replanejou,
  origem e tempo do Planejador.
- `orquestrador_reforcos`: sessão pausada, competência e sessão de reforço, estado
  (pendente, em_andamento ou concluido).
- `tutor_sessoes.pausada`: sessão suspensa durante um reforço.
- `trilha_estudo.concluida` e `trilha_estudo.origem_justificativa`.
- `auditoria.motivo`: motivo de cada decisão.

## Limitações conhecidas

- **Competência de reforço concluída entra na trilha** como etapa concluída nos replanejamentos
  seguintes. O replanejamento recebe todas as competências concluídas no Tutor, e a sessão de reforço é
  uma sessão normal. O indicador de progresso conta essa etapa ("4 de 4" na demonstração, com uma
  competência a mais que a trilha original).
- **Uma sessão de reforço aberta por `/tutor/sessao` (standalone)** não é vinculada ao reforço. O
  `proximo` continua pedindo para abrir o reforço por `/aluno/{id}/sessao`.
- **Sem agendador:** até a VM, a verificação de inatividade só acontece quando alguém roda o comando ou
  chama a rota.
- **Sem autenticação** (D8).
