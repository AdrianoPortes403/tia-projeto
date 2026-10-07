# Briefing do Projeto: Sistema TIA (Areté / IME), versão 2

Fonte de verdade: TAP, EAP e Cronograma oficiais (v1.0, 27/08/2026), em `docs/referencia/`.
Este briefing resume o TAP e o estado do trabalho técnico da Pessoa 3 (A3).
Em caso de conflito, vale o TAP.

## 1. Visão geral

- **Projeto:** Sistema TIA, Tutoria Inteligente baseada em Agentes de IA. Código ARETE-TIA-2026-01.
- **Executora:** Areté, Engenharia de Sistemas Inteligentes. **Patrocinador:** DEP / Exército Brasileiro.
- **Beneficiado:** IME, piloto na graduação em Computação. **Orientador:** TC Leandro de Mattos Ferreira.
- **Janela:** 30/07/2026 a 12/11/2026. **Orçamento:** R$ 138.600,00.
- **Objetivo:** MVP operacional com 3 agentes, validado em piloto com no mínimo 30 alunos
  e 2 docentes, 100% do processamento em infraestrutura do contratante.

## 2. Equipe

| Código | Pessoa | Papel |
|---|---|---|
| A1 | Tiago Alves Porto Lima | Gerente do projeto |
| A2 | Pedro Henrique Barreto Rodrigues | Arquitetura e agentes de IA |
| A3 | Adriano Reis Portes Pinto | Infraestrutura e integração |
| A4 | Ítalo Adeodato Correia | Pedagogia e base do conhecimento |
| A5 | Samuel dos Santos Coelho | Negócio e comunicação |

## 3. Os três agentes

1. **Planejador:** trilha personalizada a partir do perfil base, da ementa e do diagnóstico inicial.
2. **Tutor:** diálogo, questionário adaptativo (errou difícil, desce; foi bem, sobe), feedback
   com fontes citadas, incentivo quando o aluno para de estudar.
3. **Relatório:** painel individual e dashboard por turma e por competência (mínimo 5 indicadores).

## 4. Requisitos que mais pesam na parte técnica

- **R03** feedback com fontes institucionais citadas.
- **R07** inferência exclusivamente em infraestrutura do contratante. Sem API externa de LLM, nem em desenvolvimento.
- **R08** LGPD (coleta, retenção, anonimização). **R09** resposta em até 15 s. **R10** 50 usuários simultâneos.
- **R11** trilha de auditoria das interações. **R12** docente pode corrigir ou vetar respostas do tutor.

## 5. Decisões técnicas (estado atual)

- Python 3.12, FastAPI, SQLite (`sqlite3` puro, sem ORM), Chroma para RAG.
- LLM local: Qwen3 via Ollama. Embeddings: `nomic-embed-text` via Ollama.
- Toda chamada ao modelo passa por `llm_client` (chat e embedding). `/nothink` é acrescentado
  automaticamente quando `think=False`, porque o parâmetro `think` da API não é confiável.
- Modelos medidos em notebook sem GPU (8 núcleos, 7,6 GB RAM): `qwen3:4b` levou mais de 400 s
  com raciocínio estendido; `qwen3:1.7b` com `/nothink` respondeu em cerca de 0,7 s.
  Padrão de desenvolvimento: `qwen3:1.7b`. Modelos maiores só com GPU (VM oficial).
- Hospedagem: VM dedicada da instituição. Não usar nuvem pública para dados de alunos.
- `aluno_id` é código, nunca nome. Nenhum dado pessoal em log.

## 6. Marcos

| Marco | Data | Descrição |
|---|---|---|
| M3 | 17/09 | Requisitos e fundamentação pedagógica homologados |
| M4 | 08/10 | Arquitetura e ambiente de IA validados (prova de conceito) |
| M5 | 22/10 | MVP integrado, feature freeze |
| M6 | 05/11 | Piloto concluído e pitch parcial |
| M7 | 12/11 | Encerramento e pitch final |

## 7. Estado do ramo 1.4 (A3) em 07/10/2026

| Pacote | Estado |
|---|---|
| 1.4.1 LLM local | Validado em notebook (Linux) e testado com RTX 3050. Entregável formal na VM adiado: a VM só estará disponível em 15/10. |
| 1.4.2 RAG | Implementado e testado ponta a ponta com material de exemplo. Falta o material real (A4). |
| 1.4.3 Plug-in EBAULA | Não iniciado (tem folga no cronograma). |
| 1.4.4 App standalone | Esqueleto com `/health` e banco. Rotas de negócio pendentes. |
| 1.4.5 Dashboard | Não iniciado, depende do Agente 3 (A2). |
| 1.4.6 Segurança/LGPD | Não iniciado. Janela 10/09 a 22/10. |

## 8. Repositório e pastas

O protótipo integrado fica em `tia-sistema` (privado), com `src/tia/{core,rag,agentes,api}`,
`conteudo/`, `web/`, `dashboard/`, `plugin-ebaula/`, `infra/`, `docs/`, `tests/`.
Dados e lógica de A2 e A4 nesse repositório são **provisórios** até as entregas reais.
Testes: `./run_tests.sh` (contorna conflito do pytest com ROS 2).

## 9. Como usar este arquivo

Anexar ao Project Knowledge do Claude de cada pessoa. Ao mudar uma decisão, atualizar este
arquivo e substituir a versão antiga em todos os projetos, para os Claudes não divergirem.
