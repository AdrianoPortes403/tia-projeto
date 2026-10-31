# LGPD no Sistema TIA (EAP 1.4.6)

> Frente A3, 11/10/2026 (inventário atualizado em 15/10/2026 com o primeiro acesso do Agente 1). **Proposta técnica, a validar com o jurídico/DEP da instituição.** Os prazos e as
> bases legais abaixo são PROVISÓRIOS. Implantação: `docs/seguranca/implantacao.md`. Arquitetura:
> `docs/arquitetura/arquitetura.md`, seção "Segurança".

## 1. Princípios aplicados

- **Pseudonimização na origem (R08):** o aluno é identificado só por um código (`aluno_id`), nunca pelo
  nome. O TIA não guarda nome, e-mail, CPF, telefone nem foto. A ligação código ↔ pessoa fica com a
  instituição (secretaria ou EBAULA), fora do TIA. Mesmo assim, o código é **dado pessoal**: com a tabela da
  instituição, ele identifica a pessoa. Por isso tudo abaixo vale para ele.
- **Minimização:** as visões agregadas (relatório da turma, competências, CSV) não mostram códigos e
  suprimem grupos com menos de 5 alunos (`RELATORIO_MIN_GRUPO`). Os textos livres ficam só nas telas do
  docente, e cada consulta que mostra códigos é auditada.
- **Inferência local (R07):** o LLM roda no Ollama da própria máquina ou da rede interna; nenhum dado sai
  para serviço externo (seção 8).
- **Prestação de contas:** toda interação, consulta com códigos, veto, login e ação de LGPD vai para a
  auditoria, com o usuário e o papel.

## 2. Inventário: quais dados pessoais existem e onde ficam

Todos ficam no banco SQLite (`DB_PATH`, padrão `data/tia.db`), salvo indicação.

| Dado | Tabela / local | Finalidade | Prazo (PROVISÓRIO) |
|---|---|---|---|
| Código do aluno, conhecimento prévio, horas por semana | `alunos` | planejar a trilha | enquanto o aluno estuda; sai na eliminação a pedido |
| Perfil, horas, diagnóstico, trilha escolhida, prazo e escopo | `orquestrador_matriculas` | replanejar a trilha | idem |
| **Cadastro inicial (primeiro acesso, Agente 1):** trilha, horas, dias, contadores de mensagens e, enquanto não conclui, a **conversa** (texto livre do aluno e do tutor) | `planejador_onboarding` (`estado`, JSON) | coletar o que o aluno declara para o plano | a conversa é apagada ao concluir; cadastro **não concluído** apagado após `RETENCAO_DIALOGO_DIAS` (180) sem atividade; o concluído fica enquanto o aluno estuda e sai na eliminação a pedido |
| **Objetivo do aluno** (texto livre opcional, até 200 caracteres; a tela pede para não pôr dados pessoais) | `planejador_onboarding` (`estado.dados.objetivo`) | contexto do plano | tirado do cadastro após `RETENCAO_DIALOGO_DIAS` (180); só o próprio aluno o recebe (o docente não, em `GET /aluno/{id}/primeiro-acesso`) |
| Diagnóstico inicial (itens respondidos, acerto por nível, notas por tópico; sem texto livre) | `planejador_diagnosticos` (`estado`, JSON) | enquadrar o perfil e evitar repetir itens no Tutor | enquanto o aluno estuda; sai na eliminação a pedido |
| Trilha de estudo | `trilha_estudo` | mostrar e acompanhar a trilha | idem |
| Respostas às questões (item, acerto, nível, data, sessão) | `historico_respostas` | questionário adaptativo e indicadores do Agente 3 | desvinculadas do aluno após `RETENCAO_RESPOSTAS_DIAS` (365) |
| Sessões do questionário (inclusive se terminou sem domínio e o acerto da sessão) | `tutor_sessoes` | retomar o questionário; decidir o avanço (R1) | idem (365) |
| Feedback das questões (texto que o aluno viu, texto barrado, correção do docente) | `tutor_feedbacks` | revisão docente (R12) | textos apagados após `RETENCAO_FEEDBACK_TEXTO_DIAS` (180); ligação com o aluno, 365 |
| **Perguntas livres ao tutor** e respostas, correção do docente | `tutor_dialogo` | diálogo (R03) e revisão docente (R12) | textos apagados e linha desvinculada após `RETENCAO_DIALOGO_DIAS` (180) |
| Resultado guardado de cada evento (repete o feedback) | `orquestrador_eventos` | idempotência | apagado após 180 dias |
| Decisões e reforços do orquestrador | `orquestrador_decisoes`, `orquestrador_reforcos` | explicar decisões ao aluno e ao docente | desvinculados após 365 dias |
| Auditoria (quem, quando, o quê; códigos de aluno e de usuário; nunca texto livre: no primeiro acesso, só o passo, os **nomes** dos campos coletados e o acerto por item do diagnóstico) | `auditoria` | prestação de contas (R11, R12) | **nunca apagada**; códigos anonimizados após `RETENCAO_AUDITORIA_DIAS` (730) |
| Usuário: login (código), papel, hash da senha (scrypt), situação | `usuarios` | autenticação | enquanto ativo; na eliminação, desativado, com a ligação e a senha apagadas |
| Sessões de login (hash do token) | `auth_sessoes` | manter o login | 30 min sem uso ou 8 h (apagadas pela limpeza) |
| Tentativas de login (login digitado, **IP**, sucesso) | `auth_tentativas` | limite de tentativas | `AUTH_RETENCAO_IP_DIAS` (30) |
| Pedidos sem login contados (**IP**, janela, quantidade) | `auth_anonimos` | impedir que encham a auditoria | 30 dias |
| Cópias do banco antes de apagar dados | `COPIAS_DIR` (padrão `data/copias/`) | desfazer um erro operacional | `RETENCAO_COPIAS_DIAS` (30) |
| Arquivos de exportação do titular e de senhas temporárias | onde o operador indicar (permissão 600) | entregar ao titular | **apagar logo após a entrega** (manual) |
| Log de acesso do servidor web (IP, rota com código) | log do uvicorn ou do proxy, fora do banco | operação | desligado no uvicorn (`--no-access-log`); proxy: política da VM (pendência) |

O índice do Chroma (`CHROMA_DIR`) guarda só o material do curso, sem dado de aluno. Os logs da aplicação
registram só o tipo de falha (por exemplo "LLM indisponível"), nunca texto do aluno, senha ou código. Há
teste para isso.

## 3. Bases legais propostas (a validar com o jurídico/DEP)

| Tratamento | Base proposta (LGPD) | Observação |
|---|---|---|
| Tutoria, trilha, questionário, relatório ao aluno | execução de política pública educacional ou de contrato de ensino (art. 7º, III ou V), conforme a natureza da instituição | depende de a instituição ser pública ou privada |
| Acompanhamento pelo docente (painel, alertas de risco) | idem, como parte da atividade de ensino | o aluno deve ser informado (transparência, art. 9º) |
| Diálogo livre com o tutor (texto que o aluno escreve) | idem; avaliar se convém **consentimento** específico, porque o texto é livre e pode conter qualquer coisa | orientar o aluno a não escrever dados pessoais |
| Auditoria, limite de tentativas, IP | legítimo interesse ou cumprimento de obrigação de segurança (art. 7º, IX ou II; art. 46) | prazos curtos para o IP |
| Uso de dados anônimos para estatística e avaliação do projeto | dado anonimizado não é dado pessoal (art. 12), desde que a anonimização seja efetiva | ver a limitação na seção 5 |
| Avaliação acadêmica do protótipo (amostra de feedbacks) | pesquisa (art. 7º, IV), com anonimização sempre que possível | `python -m tia.painel.amostra` sai sem `aluno_id`, mas traz o texto da pergunta livre do diálogo, que pode conter dado pessoal: quem avalia deve tratar o CSV como dado pessoal (`docs/avaliacao/protocolo_amostra.md`) |

## 4. Quem acessa o quê

| Papel | Acesso |
|---|---|
| aluno | só os próprios dados (trilha, estudo, diálogo, relatório) |
| docente | painel: agregados (sem código), alunos em risco e revisão (com código e texto, auditados), dados de um aluno para leitura; não age em nome do aluno |
| admin | só gestão de usuários (comando ou `/admin/usuarios`); não vê dados de estudo |
| operador do servidor (sistema) | banco, cópias, comandos de retenção e do titular; tudo que apaga ou exporta vai para a auditoria |
| LLM local | recebe o texto da pergunta e trechos do material, na máquina ou na rede interna; nada é guardado pelo Ollama além da memória da chamada |

Matriz completa por rota: `docs/arquitetura/arquitetura.md`, "Quem pode chamar o quê".

## 5. Retenção, anonimização e o que sobra

`python -m tia.seguranca.retencao --simular` mostra o que seria afetado sem alterar nada. `--aplicar` faz
uma cópia do banco e aplica os prazos (agendar no cron; `docs/seguranca/implantacao.md`).

**O que "anonimizar" significa no TIA:**

- o `aluno_id` e as ligações que levam a ele (`sessao_id`, `evento_id`) viram NULL;
- os textos livres viram NULL;
- ficam item, competência, acerto, nível, data, origem e veto;
- na auditoria, os códigos de aluno e de usuário (em qualquer campo) viram `[anonimizado]`, mas o tipo, a
  data, o papel e a origem ficam.

**Limitação conhecida:** numa turma pequena, a data e o item de uma resposta sem dono podem, em tese,
ajudar a reidentificar alguém. Isso pede cruzamento com outra fonte, e o risco é baixo. Mesmo assim, o
jurídico deve dizer se basta ou se essas linhas devem ser apagadas em vez de desvinculadas.

Os indicadores do Agente 3 são calculados **por aluno**: uma linha desvinculada deixa de contar no relatório
da turma. Ela continua nas contagens por item, por origem e por veto.

Cadastro concluído (sem o objetivo), diagnóstico inicial, matrícula e trilha não têm prazo por data. O
cadastro inicial não concluído (com a conversa) e o objetivo saem no prazo do diálogo (`RETENCAO_DIALOGO_DIAS`). Falta definir com a Pessoa 4 e com a instituição o
evento de fim (fim do curso, desligamento) que dispara a eliminação (pendência).

## 6. Direitos do titular (art. 18)

O pedido chega pelo canal da instituição (encarregado/DEP). A identificação da pessoa e a conversão nome →
código são feitas pela instituição, fora do TIA. No servidor:

| Direito | Como |
|---|---|
| Confirmação e acesso (I, II) | `python -m tia.seguranca.titular exportar --aluno <código>` gera um JSON com todos os dados do aluno, sem dados de outras pessoas (outros códigos e o login de quem agiu viram `[anonimizado]`; o docente aparece só pelo papel), mais as consultas do painel que mostraram o código dele. Permissão 600; entregar por canal seguro e apagar |
| Portabilidade (V) | o mesmo JSON (formato aberto) |
| Correção (III) | perfil e horas: refazendo a matrícula pelo próprio aluno; dados de estudo são registros do que aconteceu e não se corrigem (a auditoria registra) |
| Eliminação (VI) e anonimização (IV) | `python -m tia.seguranca.titular eliminar --aluno <código>`: pede o código de novo para confirmar, copia o banco, apaga cadastro, cadastro inicial e diagnóstico do primeiro acesso, matrícula, trilha, sessões e eventos, desvincula e apaga os textos de respostas, feedbacks, diálogo e decisões, anonimiza os códigos dele na auditoria e desativa o usuário. A auditoria ganha um registro **sem o código**, com um **protocolo** para a resposta ao titular |
| Informação sobre compartilhamento (VII) | nenhum compartilhamento com terceiros; LLM local (seção 8) |
| Revogação do consentimento (IX) | se o diálogo livre passar a depender de consentimento: eliminação dos diálogos (pendência de tela) |

O id de login fica no cadastro, desativado, para não ser reaproveitado. Se a instituição usar o próprio
código do aluno como login, esse código continua em `usuarios` (pergunta ao jurídico na seção 9). A cópia
feita antes da eliminação guarda os dados apagados por até `RETENCAO_COPIAS_DIAS` e sai pela retenção.

## 7. Segurança (art. 46)

As medidas são as da arquitetura, seção "Segurança":

- senha com scrypt e política mínima;
- sessão no servidor com expiração;
- anti-CSRF;
- papéis;
- limite de tentativas;
- auditoria agregada contra enchimento;
- cabeçalhos de segurança;
- `/docs` desligado em produção;
- a API não sobe com configuração insegura.

A lista de conferência da VM está em `implantacao.md`. Em caso de incidente, a auditoria e as cópias
permitem reconstruir o que aconteceu. A comunicação à ANPD e aos titulares (art. 48) é processo da
instituição.

## 8. R07: inferência local e todos os pontos de rede do código

**Confirmação:** o código não chama nenhuma API externa.

- O cliente HTTP da aplicação é o `requests`, só em `src/tia/core/llm_client.py` (Ollama) e no teste de
  fumaça da VM (`src/tia/implantacao/verificar.py`, que só chama a própria API em `API_URL_LOCAL`).
- A API não faz chamadas de saída.
- O teste `test_pontos_de_rede_do_codigo` varre `src/tia` e falha se aparecer qualquer outro endereço ou
  biblioteca de rede.
- Os endereços `https://ebaula.exemplo.eb.mil.br`, `https://tia.exemplo.eb.mil.br` e `https://host`
  aparecem apenas em comentários e na documentação do plug-in EBAULA (`config.py` e `tia-ebaula.js`);
  não geram tráfego de rede.

| # | Ponto | Direção | Host e porta | Onde no código | Observação |
|---|---|---|---|---|---|
| 1 | API do TIA (FastAPI/uvicorn) | entrada | padrão `127.0.0.1:8000`; na VM, atrás do proxy HTTPS | `tia.api.main` (`uvicorn ...`) | as telas `/app` e `/app/painel` vêm do mesmo endereço |
| 2 | Ollama, chat | saída | `OLLAMA_URL` (padrão `http://localhost:11434`), `POST /api/chat` | `core/llm_client.chamar_llm` | local ou rede interna; a API não sobe em produção se `OLLAMA_URL` apontar para fora (`config.problemas_de_configuracao`) |
| 3 | Ollama, embeddings | saída | mesmo host, `POST /api/embeddings` | `core/llm_client.gerar_embedding` | idem |
| 3b | Ollama, lista de modelos | saída | mesmo host, `GET /api/tags` | `core/llm_client.listar_modelos_instalados` | só na verificação da VM (`implantacao.modelos` e `verificar`) |
| 4 | Chroma (índice do RAG) | nenhuma | arquivos em `CHROMA_DIR` | `rag/retrieve.abrir_cliente` | **telemetria desligada.** O chromadb 0.5 manda, por padrão, eventos de uso para `https://us.i.posthog.com` (443). Isso acontecia até esta etapa e foi corrigido com `Settings(anonymized_telemetry=False)`; há teste |
| 5 | SQLite | nenhuma | arquivo `DB_PATH` | `core/database` | |
| 6 | Navegador do usuário | — | só a própria origem (CSP `'self'`) | `web/static` | nenhuma fonte, script ou imagem externa |
| 7 | `/docs` (só com `API_DOCS=1`) | saída **do navegador** | `cdn.jsdelivr.net:443`, `fastapi.tiangolo.com:443` | FastAPI | desligado por padrão em produção |
| 8 | Teste de fumaça da VM | saída local | `API_URL_LOCAL` (padrão `http://127.0.0.1:8000`) | `implantacao/verificar.py` | só a própria API; avisa se apontar para fora da máquina |
| 9 | Download dos modelos | saída, **só na implantação** | `registry.ollama.ai:443` e o CDN dele | `deploy/modelos.sh` (`ollama pull`) | único passo com rede da VM, isolado e marcado; o resto é instalado sem rede (wheels do pacote) |

Fora da aplicação, só na instalação:

- `pip install`, a partir do PyPI;
- `ollama pull` dos modelos, a partir do registro do Ollama.

Na VM, o firewall deve liberar só a porta do proxy (HTTPS) para fora. A porta 11434 do Ollama fica só em
`127.0.0.1` (`implantacao.md`).

## 9. Perguntas ao jurídico/DEP

1. As bases legais da seção 3 (a instituição é pública ou privada?). O diálogo livre precisa de
   consentimento específico?
2. Os prazos de retenção (365, 180, 730 e 30 dias). Há tabela de temporalidade da instituição para registros
   acadêmicos?
3. Desvincular basta como anonimização das respostas (seção 5), ou é melhor apagá-las?
4. Na eliminação, o login desativado pode ficar (para não ser reaproveitado), mesmo quando é igual ao código
   do aluno?
5. Qual é o canal oficial do titular e o prazo de resposta? Quem confere a identidade?
6. É preciso aviso de privacidade nas telas do TIA, ou o aviso do EBAULA cobre?
7. O objetivo do cadastro inicial (texto livre opcional) pode seguir o prazo do diálogo (180 dias), ou deve
   ser apagado logo depois da matrícula? (Hoje: 180 dias, sem acesso do docente.)
