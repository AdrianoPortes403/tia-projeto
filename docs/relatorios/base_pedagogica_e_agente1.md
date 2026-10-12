# Base pedagógica alinhada à EAP e Agente 1 Planejador (1.2.x e 1.3.2): resumo (12/10/2026)

Branch `agente1-tiago`, 3 commits sobre `4262f99` (o `main` não foi tocado). Testes: 666 → **695 passando**
(2 pulados, 9 xfail, como antes). Arquitetura, nomes e recursos do protótipo foram mantidos: a mudança
é de **conteúdo, Agente 1 e regras**. No código, `competencia_id` continua sendo o nome do "tópico" da EAP.

| Commit | Bloco |
|---|---|
| `9599439` | Conteúdo (ementa, itens, perfis) e Planejador com trilha, perfil pelo diagnóstico e prazo |
| `451a17c` | Primeiro acesso: onboarding conversacional, diagnóstico inicial e matrícula |
| `8399094` | Regras da avaliação adaptativa do 1.2.5, lacuna de aprendizagem, nível inicial e inatividade de 7 dias |

## Conceitos (como a EAP usa os termos)

| Termo | Significado | No código |
|---|---|---|
| **Trilha** | O caminho escolhido pelo aluno: Desenvolvimento ou Defesa Cibernética | `trilha`: `dev` ou `defesa_cibernetica` |
| **Base comum** (etapa 0) | 6 tópicos de Python comuns às duas trilhas (ementa do protótipo) | `variaveis_tipos`, `condicionais`, `repeticao`, `funcoes`, `listas_strings`, `recursao` |
| **Perfil** | Nível e ritmo do aluno, **não** a trilha. Definido pelo diagnóstico | `iniciante` (perfil A) e `intermediario` (perfil B) |
| **Tópico** | Unidade da ementa, com pré-requisitos, horas e itens | `competencia_id` |

## Arquivos

**Novos:**

| Arquivo | Conteúdo |
|---|---|
| `src/tia/agentes/planejador/diagnostico.py` | Diagnóstico inicial: tópicos da base comum + etapa 1 da trilha, níveis 1→2→3 parando no primeiro erro; tabela `planejador_diagnosticos`; auditoria `diagnostico` |
| `src/tia/agentes/planejador/onboarding.py` | Cadastro conversacional (trilha, horas/semana, dias, objetivo): regras + extração pelo LLM local em JSON, com validação e queda para regras; o texto da conversa é apagado ao concluir (R08); tabela `planejador_onboarding`; auditoria `onboarding` |
| `src/tia/api/rotas_primeiro_acesso.py` | As 6 rotas do primeiro acesso (abaixo) |
| `tests/test_planejador_eap.py` | 8 testes (seleção por trilha, enquadramento, nível inicial, prazo, avisos) |
| `tests/test_primeiro_acesso.py` | 9 testes (diagnóstico, onboarding com e sem LLM, percurso completo, LGPD) |
| `tests/test_regras_eap.py` | 5 testes (lacuna, material-base, nível inicial, itens do diagnóstico evitados) |

**Alterados:**

- `conteudo/ementa/ementa.json`: 48 tópicos (6 da base comum + 23 `dev_XX` + 19 `cib_XX`), com `trilha`,
  `etapa`, `horas_estimadas`, `prerequisitos`, `materiais`, `palavras_chave`, `dificuldade_base`,
  `no_piloto`, `disciplinas_ime` e `desafio_pratico`.
- `conteudo/banco_itens/itens.json`: 120 itens (84 do piloto + 36 da A3), com `uso` (`diagnostico` ou
  `tutoria`), `fonte` e `status`. Gabarito balanceado (21 por posição nos itens do piloto).
- `conteudo/perfis/perfis.json`: `iniciante` e `intermediario` com `regras_enquadramento` (limiar 1,5),
  ritmo 1,0 e as flags `revisar_prerequisitos` e `desafio_pratico`.
- Planejador: `modelos.py` (`trilha`, `prazo_dias`, `escopo`, `perfil_id` opcional; etapa com
  `revisar_antes`, `nivel_inicial`, `desafio_pratico`; trilha com `pontuacao_enquadramento`,
  `perfil_automatico`, `cabe_no_prazo`, `opcoes_prazo`, `avisos`), `planejar.py`, `repositorio.py`,
  `justificar.py`.
- Tutor: `adaptativo.py` (limiares 3/2/3 configuráveis, lacuna, nível inicial, itens a evitar),
  `repositorio.py` (sequências gravadas), `modelos.py` (`nivel_inicial`, `Feedback.lacuna`), `__init__.py`.
- Orquestrador: `modelos.py` (matrícula com trilha/prazo/escopo; regra `lacuna`; ação `revisar_material`),
  `regras.py` (`regra_lacuna`), `eventos.py`, `fluxo.py`, `repositorio.py`, `__main__.py`.
- `core/config.py`, `.env.example`, `core/database.py` (só CREATE TABLE / ADD COLUMN), `core/auditoria.py`.
- LGPD: `seguranca/titular.py` (exporta e elimina cadastro e diagnóstico) e `seguranca/anonimizacao.py`.
- Web: `index.html` e `app.js` (cartão de primeiro acesso no lugar do seletor de perfil; trilha mostra
  perfil, prazo, revisões e desafios); `painel/painel.js` (nomes dos tipos novos); `dados_demo.py`,
  `dados_painel.py`.

## Primeiro acesso (contrato 1.3.2)

Onboarding → diagnóstico → matrícula. Todas as rotas devolvem 409 depois da matrícula (a partir daí quem
replaneja são as regras do orquestrador). Só o próprio aluno escreve; a leitura do passo também é do docente.

| Rota | Faz |
|---|---|
| `GET /aluno/{id}/primeiro-acesso` | Passo atual: `onboarding`, `diagnostico`, `concluir` ou `matriculado` |
| `POST /aluno/{id}/onboarding/iniciar` | Primeira mensagem (recomeça se já havia) |
| `POST /aluno/{id}/onboarding/mensagem` | Resposta do aluno → próxima pergunta |
| `POST /aluno/{id}/diagnostico/iniciar` | Primeira questão, na trilha do cadastro |
| `POST /aluno/{id}/diagnostico/responder` | Resposta → próxima questão ou fim (notas) |
| `POST /aluno/{id}/primeiro-acesso/concluir` | Matricula com cadastro + notas + prazo/escopo do piloto |

`POST /aluno/{id}/iniciar` continua existindo (uso direto e testes); agora aceita `trilha`, `prazo_dias`,
`escopo` e `perfil_id` opcional.

## Regras do Agente 1

| Regra | Como está |
|---|---|
| Seleção | Base comum + tópicos da trilha (`trilha` ausente → só a base comum). Escopo `piloto` → só `no_piloto` |
| Notas do diagnóstico | 0, 1/3, 2/3 ou 1 (nível em que errou pela primeira vez; 1 = dominado) |
| Enquadramento | P = 3 × média das notas dos tópicos das etapas 0 e 1. P ≥ 1,5 → `intermediario`; senão `iniciante`; sem diagnóstico → `iniciante` |
| Dominados | Tópico com nota 1 sai da trilha e conta como pré-requisito cumprido |
| Nível inicial | Nota ≥ 0,66 → 3; ≥ 0,33 → 2; senão 1. Sem diagnóstico: iniciante 1, intermediário 2 |
| Revisão | Perfil iniciante: tópico com pré-requisito não dominado ganha `revisar_antes` |
| Desafio prático | Perfil intermediário: tópicos com `desafio_pratico` na ementa |
| Prazo | Com `prazo_dias`: `cabe_no_prazo` e `opcoes_prazo` (horas/semana necessárias ou tópicos que cabem) |
| Avisos | Pré-requisito fora do escopo (ex.: no piloto) vira aviso, não erro |
| Ritmo | 1,0 para os dois perfis (os 1,25/0,8 anteriores foram retirados) |

## Regras do Tutor e do orquestrador (1.2.5)

| Regra | Como está | Config |
|---|---|---|
| Subir de nível | 3 acertos seguidos | `TUTOR_ACERTOS_SUBIR=3` |
| Descer de nível | 2 erros seguidos | `TUTOR_ERROS_DESCER=2` |
| Concluir o tópico | 3 acertos seguidos no nível 3 (ou fim dos itens) | `TUTOR_ACERTOS_CONCLUIR=3` |
| Lacuna de aprendizagem | 2 erros seguidos já no nível 1 → `Feedback.lacuna`. Orquestrador (regra `lacuna`, prioridade sobre a queda): com pré-requisito direto → `reforcar` (uma vez por sessão); sem pré-requisito ou já reforçada → `revisar_material` (aviso com o material-base e a sessão segue) | `TUTOR_ERROS_DESCER` |
| Nível inicial | A sessão começa no `nivel_inicial` da etapa; o reforço começa no nível 1 | — |
| Itens do diagnóstico | Ficam de fora do questionário enquanto houver outros | — |
| Falta de itens no nível | Vai para o nível mais próximo; empate na direção da resposta (para cima depois de acerto) | — |
| Inatividade | Incentivo a partir de 3 dias; trilha refeita a partir de **7** (era 14). No piloto: 2 e 4 pelo `.env` | `INATIVIDADE_DIAS`, `ORQ_INATIVIDADE_REFAZER_DIAS` |

## Tabelas e colunas acrescentadas

- `planejador_onboarding`: dados do cadastro (trilha, horas, dias, objetivo), sem o texto da conversa depois de concluído.
- `planejador_diagnosticos`: estado e notas do diagnóstico.
- `trilha_estudo`: colunas da trilha nova (trilha, pontuação, prazo, revisões, nível inicial, desafios, avisos).
- `orquestrador_matriculas`: `trilha`, `prazo_dias`, `escopo`.
- `tutor_sessoes`: `acertos_seguidos`, `erros_seguidos`.

## Configuração nova (`core/config.py`, `.env.example`)

`ONBOARDING_USA_LLM=1`, `ONBOARDING_TIMEOUT_LLM=60`, `PILOTO_PRAZO_DIAS=0` (piloto: 8),
`PILOTO_ESCOPO=completa` (piloto: `piloto`), `TUTOR_ACERTOS_SUBIR=3`, `TUTOR_ERROS_DESCER=2`,
`TUTOR_ACERTOS_CONCLUIR=3`, `ORQ_INATIVIDADE_REFAZER_DIAS=7`.

## Decisões a validar com o time (PROVISÓRIAS)

| Decisão | Quem valida |
|---|---|
| Limiares 3/2/3 da avaliação adaptativa | A4 (conteúdo) |
| Inatividade: refazer a trilha com 7 dias (2/4 no piloto) | A4 e A2 |
| Ritmo 1,0 nos dois perfis | A4 |
| Limiar de enquadramento P ≥ 1,5 | A4 |
| `palavras_chave` dos tópicos Dev/Cyber (usadas pela guarda de cobertura do RAG) | A4 |
| Lacuna sem pré-requisito → material-base em vez de reforço | A4 e A2 |

## Limitações conhecidas

- Tópicos Dev/Cyber fora do piloto (`dev_03`…, `cib_03`…) ainda **não têm itens**: abrir sessão neles
  dá `SemItens`. No piloto (`dev_01`, `dev_02`, `cib_01`, `cib_02`) há itens.
- Tópicos Dev/Cyber **não têm material** no RAG até o pacote 1.5.2; o feedback cita só o material da base comum.
- A base comum tem só 2 itens por nível; o questionário pode cair no nível vizinho quando eles acabam.
- O onboarding por regras entende frases simples; frases livres dependem do LLM local.
