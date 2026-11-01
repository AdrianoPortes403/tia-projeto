# Evidência dos requisitos do TAP (M6)

> Frente A3, 31/10/2026. Tabela única de evidência para R03, R07, R08, R09, R11 e R12, a partir da seção 4.2 de
> `docs/relatorios/retomada_2026-10-31.md`. Nenhum número de piloto, de tempo na VM ou de avaliação docente
> foi produzido ainda: onde falta, está escrito "pendente". Limitações em `docs/limitacoes_conhecidas.md`.
>
> Status: **atendido** (implementado e com teste ou evidência no repositório), **parcial** (implementado, mas
> falta evidência em ambiente real ou validação externa), **pendente** (depende de algo que ainda não
> aconteceu).

| Req. | O que prova (arquivo ou teste) | Status | O que falta |
|---|---|---|---|
| **R03** fonte citada (RAG) | `tests/test_dialogo.py::test_pergunta_com_trecho_responde_com_fonte_dos_metadados_e_grava`; `tests/test_feedback_revisavel.py::test_texto_do_feedback_e_gravado_com_origem_fontes_item_e_sessao`; fontes gravadas na auditoria (`auditoria.fontes`); `docs/evidencias/tutor_feedback_2026-10-10.md` e `tutor_feedback_guarda_2026-10-10.md` (ainda com o material provisório). **RAG reindexado em 31/10 só no ambiente local:** 69 pedaços de 10 arquivos de `conteudo/materiais/`, incluindo os 4 tópicos do piloto (`dev_01`, `dev_02`, `cib_01`, `cib_02`) | parcial | ingestão na VM (num índice vazio); limpar do índice local os 13 pedaços antigos `provisorio_*` que o `upsert` não apagou; evidência nova com os 4 tópicos do piloto; % de respostas com fonte no banco do piloto |
| **R07** inferência local | `tests/test_seguranca_lgpd.py::test_pontos_de_rede_do_codigo` (varredura de endereços; corrigida no PR #5), `::test_ollama_so_local_ou_rede_interna`, `::test_chroma_sem_telemetria`; `core/llm_client.py` como única porta para o LLM; `docs/seguranca/lgpd.md` ("Pontos de rede") | atendido no código; parcial em ambiente real | na VM, registrar `OLLAMA_URL` e uma captura (`ss -ltnp`, regras do firewall) mostrando que não há saída |
| **R08** LGPD | `tests/test_seguranca_lgpd.py` (logs sem texto do aluno, 422 sem eco de dados, importação); `tests/test_seguranca_etapa2.py::test_ip_nunca_vai_para_a_auditoria`; retenção e direitos do titular (`src/tia/seguranca/`); `aluno_id` como código; `docs/seguranca/lgpd.md` | parcial | parecer do jurídico/DEP sobre prazos e bases legais (hoje PROVISÓRIOS); varredura dos logs reais da VM no fim do piloto |
| **R09** resposta em até 15 s | instrumentação (`tempo_*_ms`, `falha_llm`); `deploy/verificar.sh --medir-r09 N` (p50/p90/p95 por modelo contra 15 s); `tests/test_implantacao.py`; tempos em CPU em `docs/relatorios/orquestracao_tempos.md` (máquina de desenvolvimento, não valem para o R09) | **pendente** (VM) | medição na VM com o `MODELO_PADRAO` escolhido; distribuição real dos tempos no piloto. Nenhum número da VM existe ainda |
| **R11** auditoria | `tests/test_seguranca.py::test_auditoria_grava_o_usuario_em_toda_acao`, `::test_sem_login_401_auditado_e_rotas_publicas`; `tests/test_feedback_revisavel.py::test_aprovar_e_retirar_veto_do_feedback_gravam_auditoria`; `core/auditoria.py` | atendido no código; parcial em ambiente real | extrato agregado da auditoria do piloto (contagem por tipo, sem dados pessoais) |
| **R12** veto docente | `tests/test_dialogo.py` (veto substitui sem apagar, retirar veto, validações); `tests/test_feedback_revisavel.py`; `tests/test_seguranca.py::test_veto_so_docente`; painel do docente; `painel/amostra.py`; `docs/avaliacao/protocolo_amostra.md` | atendido no código; **pendente** a avaliação | **avaliação docente da amostra de 100** (meta ≥ 80%, critério do TAP) com o banco do piloto (`python -m tia.painel.amostra --n 100 --semente 2026`); respostas às perguntas do protocolo à Pessoa 4 (avaliadores, escopo da meta). Nenhum resultado existe ainda |

## Como reproduzir

- Testes: `source venv/bin/activate && ./run_tests.sh`. Resultado de 31/10 registrado em
  `docs/relatorios/retomada_2026-10-31.md` (seção 1).
- R03 local: `python -m tia.rag.ingest` (com o Ollama e o `nomic-embed-text`).
- R09 e R07 na VM: `deploy/verificar.sh --medir-r09 N` e `ss -ltnp` (ver `docs/implantacao_vm.md`).
