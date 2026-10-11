/*
 * Aplicação web standalone do TIA (EAP 1.4.4): JavaScript puro, sem build.
 *
 * Telas: entrada (código do aluno), trilha, estudo (questionário pelo
 * orquestrador), diálogo livre e relatório. Só consome as rotas da API
 * (docs/arquitetura/arquitetura.md, "Web standalone").
 *
 * Segurança: todo texto vindo da API entra na página por textContent (função
 * el, em comum.js), nunca por innerHTML; nada é escrito no console (R08); não há chave nem
 * segredo aqui. Login (1.4.6): o aluno entra com usuário e senha e só vê os
 * próprios dados (o código vem da sessão, não de um campo). Com TIA_AUTH=desligada
 * (modo de desenvolvimento), volta a entrada pelo código, com aviso.
 */
"use strict";

(function () {
  // Espera máxima do navegador por uma resposta. Uma resposta do aluno pode
  // acionar o Tutor e o Planejador em sequência (até TUTOR_TIMEOUT_LLM +
  // PLANEJADOR_TIMEOUT_LLM no servidor, 120 s cada em desenvolvimento).
  const ESPERA_MAXIMA_MS = 300000;
  const PADRAO_CODIGO = /^[A-Za-z0-9_-]{1,32}$/;
  const CHAVE_SESSAO = "tia.aluno"; // só o código (nunca nome), na aba atual

  const ORIGEM_FEEDBACK = {
    LLM: "Explicação escrita pelo tutor (IA local) e conferida pela verificação automática.",
    guarda: "A verificação automática barrou o texto da IA; abaixo vai o texto do material ou do item.",
    fallback: "Texto fixo: a IA não respondeu a tempo ou não havia trecho do material.",
    docente: "Resposta corrigida pelo professor.",
  };
  const ORIGEM_JUSTIFICATIVA = {
    LLM: "justificativa escrita pela IA local",
    fallback: "justificativa padrão (a IA não respondeu)",
  };
  const FALHA = { timeout: "a IA demorou demais (timeout)" };

  const estado = {
    aluno: null,
    autenticado: false,  // login ligado e aluno logado: o código vem da sessão
    etapas: [],          // EstadoAluno.etapas (nomes das competências)
    sessaoId: null,      // sessão do Tutor em andamento
    pergunta: null,      // pergunta em aberto
    eventoPendente: null // evento que falhou: reenviado com o mesmo evento_id (idempotente)
  };

  // utilidades compartilhadas com o painel do docente (comum.js): el, chamar, erros
  const { $, el, tempo, porcento, ErroApi, chamar, mostrarErro, esconderErro } = window.TIA;
  TIA.configurar({ esperaMaximaMs: ESPERA_MAXIMA_MS, quem: "O tutor", textoEspera: "Aguardando o tutor…" });

  function nomeCompetencia(id) {
    const etapa = estado.etapas.find((e) => e.competencia_id === id);
    return etapa ? etapa.nome : id;
  }

  function novoEventoId() {
    const aleatorio = Math.random().toString(36).slice(2, 10);
    return "web-" + Date.now().toString(36) + "-" + aleatorio;
  }

  // --- navegação ---

  const TELAS = ["login", "entrada", "trilha", "estudo", "dialogo", "relatorio"];
  const AO_ABRIR = {
    trilha: carregarTrilha,
    estudo: carregarEstudo,
    dialogo: carregarDialogo,
    relatorio: carregarRelatorio,
  };

  function irPara(tela) {
    for (const nome of TELAS) $("tela-" + nome).hidden = nome !== tela;
    document.querySelectorAll(".aba").forEach((aba) => {
      if (aba.dataset.tela === tela) aba.setAttribute("aria-current", "page");
      else aba.removeAttribute("aria-current");
    });
    $("conteudo").focus();
    if (AO_ABRIR[tela] && !TIA.estaOcupado()) AO_ABRIR[tela]().catch(mostrarErro);
  }

  function definirAluno(codigo) {
    estado.aluno = codigo;
    estado.sessaoId = null;
    estado.pergunta = null;
    estado.eventoPendente = null;
    try {
      if (codigo) sessionStorage.setItem(CHAVE_SESSAO, codigo);
      else sessionStorage.removeItem(CHAVE_SESSAO);
    } catch (_) { /* armazenamento indisponível: segue sem lembrar */ }
    $("aluno-codigo").textContent = codigo || "";
    $("aluno-atual").hidden = !codigo || estado.autenticado; // com login, a barra do usuário já mostra quem é
    $("abas").hidden = !codigo;
    $("conversa").replaceChildren();
  }

  function rota(caminho) { return caminho.replace("{id}", encodeURIComponent(estado.aluno)); }

  // --- login (1.4.6) ---

  function mostrarLogin(mensagem, paraDocente) {
    definirAluno(null);
    $("login-mensagem").textContent = mensagem || "";
    $("login-mensagem").hidden = !mensagem;
    $("form-login").hidden = !!paraDocente;
    TIA.esconderTrocaDeSenha();
    $("login-painel").hidden = !paraDocente;
    irPara("login");
    if (!paraDocente) $("campo-login").focus();
  }

  function mostrarTrocaDeSenha() {
    mostrarLogin();
    TIA.mostrarTrocaDeSenha();
  }

  async function iniciar() {
    let situacao;
    try { situacao = await TIA.obterSessao(); } catch (erro) { mostrarErro(erro); return; }
    TIA.mostrarSessao(situacao);
    $("trocar-aluno").hidden = situacao.autenticacao === "ligada";
    $("cancelar-matricula").hidden = situacao.autenticacao === "ligada";
    if (situacao.autenticacao === "desligada") {
      // modo de desenvolvimento: entrada pelo código, como antes do login
      estado.autenticado = false;
      let lembrado = null;
      try { lembrado = sessionStorage.getItem(CHAVE_SESSAO); } catch (_) { lembrado = null; }
      if (lembrado && PADRAO_CODIGO.test(lembrado)) await abrirAluno(lembrado);
      else irPara("entrada");
      return;
    }
    if (!situacao.usuario) { mostrarLogin(); return; }
    if (situacao.usuario.trocar_senha) { mostrarTrocaDeSenha(); return; }
    if (situacao.usuario.papel !== "aluno") {
      mostrarLogin("Esta aplicação é para alunos. Você entrou como " + situacao.usuario.papel + ".", true);
      return;
    }
    estado.autenticado = true;
    await abrirAluno(situacao.usuario.aluno_id);
  }

  async function entrarComSenha(evento) {
    evento.preventDefault();
    const login = $("campo-login").value.trim();
    const senha = $("campo-senha").value;
    if (!login || !senha) {
      mostrarErro(new ErroApi("Informe o usuário e a senha.", 0));
      return;
    }
    try {
      await TIA.entrar(login, senha);
    } catch (erro) {
      mostrarErro(erro);
      return;
    } finally {
      $("campo-senha").value = ""; // a senha não fica na página
    }
    $("login-mensagem").hidden = true;
    await iniciar();
  }

  async function encerrarSessao() {
    try { await TIA.sair(); } catch (erro) { mostrarErro(erro); }
    TIA.mostrarSessao({ autenticacao: "ligada", usuario: null });
    mostrarLogin("Você saiu.");
  }

  // --- a) entrada ---

  async function entrar(evento) {
    evento.preventDefault();
    const campo = $("campo-aluno");
    const codigo = campo.value.trim();
    if (!PADRAO_CODIGO.test(codigo)) {
      mostrarErro(new ErroApi("Código inválido: use só letras sem acento, números, \"-\" ou \"_\" (até 32).", 0));
      campo.focus();
      return;
    }
    await abrirAluno(codigo);
  }

  async function abrirAluno(codigo) {
    definirAluno(codigo);
    try {
      await chamar("GET", rota("/aluno/{id}/estado"), null, "Buscando seus dados…");
      irPara("trilha");
    } catch (erro) {
      if (erro.status === 404) {
        irPara("entrada");
        $("abas").hidden = true;
        $("form-entrada").hidden = estado.autenticado;
        $("form-matricula").hidden = false;
        $("campo-perfil").focus();
      } else if (erro.status !== 401) {
        definirAluno(null);
        mostrarErro(erro);
      }
    }
  }

  async function matricular(evento) {
    evento.preventDefault();
    const horas = Number($("campo-horas").value);
    if (!(horas > 0 && horas <= 60)) {
      mostrarErro(new ErroApi("Informe entre 1 e 60 horas por semana.", 0));
      $("campo-horas").focus();
      return;
    }
    try {
      await chamar("POST", rota("/aluno/{id}/iniciar"),
        { perfil_id: $("campo-perfil").value, horas_semanais: horas, diagnostico: {} },
        "O Planejador está montando sua trilha…");
      $("form-matricula").hidden = true;
      $("abas").hidden = false;
      irPara("trilha");
    } catch (erro) { mostrarErro(erro); }
  }

  function sair() {
    definirAluno(null);
    $("form-matricula").hidden = true;
    $("campo-aluno").value = "";
    irPara("entrada");
    $("campo-aluno").focus();
  }

  // --- b) trilha ---

  async function carregarTrilha() {
    const atual = await chamar("GET", rota("/aluno/{id}/estado"), null, "Carregando a trilha…");
    estado.etapas = atual.etapas;
    let trilha = null;
    try { trilha = await chamar("GET", rota("/alunos/{id}/trilha"), null, "Carregando a trilha…"); }
    catch (erro) { if (erro.status !== 404) throw erro; }
    const porId = {};
    for (const etapa of (trilha ? trilha.etapas : [])) porId[etapa.competencia_id] = etapa;

    const avisos = $("trilha-avisos");
    avisos.replaceChildren();
    if (atual.concluido) avisos.append(el("p", { classe: "aviso", texto: "Você concluiu todas as etapas da trilha." }));
    const decisao = atual.ultima_decisao;
    // o aviso da decisão de reforço já explica a revisão, com os nomes das competências
    if (atual.reforco && !(decisao && decisao.acao === "reforcar")) {
      avisos.append(el("p", { classe: "aviso aviso--alerta" },
        "Revisão em curso: \"" + nomeCompetencia(atual.reforco.competencia_reforco) + "\", antes de continuar \"" +
        nomeCompetencia(atual.reforco.competencia_original) + "\"."));
    }
    if (decisao && decisao.aviso) avisos.append(el("p", { classe: "aviso", texto: decisao.aviso }));

    const lista = $("trilha-etapas");
    lista.replaceChildren();
    for (const etapa of atual.etapas) {
      const detalhe = porId[etapa.competencia_id] || {};
      const ehAtual = etapa.competencia_id === atual.competencia_atual;
      const selo = etapa.concluida ? el("span", { classe: "selo selo--sucesso", texto: "✓ Concluída" })
        : ehAtual ? el("span", { classe: "selo selo--atual", texto: "Etapa atual" })
          : el("span", { classe: "selo", texto: "A fazer" });
      const dados = etapa.concluida ? null : el("p", { classe: "etapa__dados" },
        detalhe.horas !== undefined ? detalhe.horas + " h estimadas" : "",
        detalhe.semana_inicio ? " · começa na semana " + detalhe.semana_inicio : "");
      const origem = detalhe.origem_justificativa;
      lista.append(el("li", {
        classe: "cartao etapa" + (ehAtual ? " etapa--atual" : "") + (etapa.concluida ? " etapa--concluida" : ""),
        "aria-current": ehAtual ? "step" : null,
      },
      el("div", { classe: "etapa__cabeca" }, el("h3", { texto: etapa.ordem + ". " + etapa.nome }), selo),
      dados,
      detalhe.justificativa ? el("p", { texto: detalhe.justificativa }) : null,
      detalhe.justificativa && !etapa.concluida ? el("p", { classe: "origem" },
        "Origem: " + (ORIGEM_JUSTIFICATIVA[origem] || "não registrada")) : null));
    }

    const rodape = $("trilha-origem");
    rodape.textContent = "";
    if (decisao && decisao.origem_justificativas) {
      rodape.textContent = "Último planejamento: justificativas " +
        { LLM: "escritas pela IA local", parcial: "em parte pela IA local, em parte padrão",
          fallback: "padrão (a IA não respondeu)" }[decisao.origem_justificativas] +
        (decisao.falha_llm ? " — " + (FALHA[decisao.falha_llm] || decisao.falha_llm) : "") + ".";
    }
    $("ir-estudar").hidden = atual.concluido;
  }

  // --- c) estudo ---

  function mostrarAvisos(avisos) {
    const area = $("estudo-avisos");
    area.replaceChildren(...(avisos || []).map((texto) => el("p", { classe: "aviso", texto })));
  }

  async function carregarEstudo() {
    // pergunta em aberto nesta página: mostra de novo, sem chamar a API
    if (estado.pergunta && estado.sessaoId) { mostrarPergunta(); return; }
    const proxima = await chamar("GET", rota("/aluno/{id}/proximo"), null, "Buscando a próxima atividade…");
    seguir(proxima);
  }

  function seguir(proxima) {
    const area = $("estudo-conteudo");
    estado.pergunta = null;
    estado.sessaoId = null;
    if (proxima.acao === "concluido") {
      area.replaceChildren(el("div", { classe: "cartao" },
        el("h2", { texto: "Trilha concluída" }),
        el("p", { texto: "Você terminou todas as etapas. Veja seu relatório ou tire dúvidas com o tutor." })));
      return;
    }
    if (proxima.acao === "continuar_sessao") {
      if (proxima.pergunta) {
        estado.sessaoId = proxima.sessao_id;
        estado.pergunta = proxima.pergunta;
        mostrarPergunta(proxima.reforco);
        return;
      }
      area.replaceChildren(el("p", { classe: "aviso aviso--alerta", texto: proxima.motivo }));
      return;
    }
    const nome = nomeCompetencia(proxima.competencia_id);
    const botao = el("button", { type: "button", classe: "botao acao", texto: "Começar",
      onclick: () => abrirSessao(proxima.competencia_id).catch(mostrarErro) });
    area.replaceChildren(el("div", { classe: "cartao" },
      el("h2", { texto: (proxima.reforco ? "Revisão: " : "Próxima etapa: ") + nome }),
      proxima.reforco ? el("p", { texto: "Antes de continuar, vamos revisar este pré-requisito, a partir do nível 1." })
        : el("p", { texto: "As perguntas começam no nível 1 e ficam mais difíceis conforme você acerta." }),
      botao));
    botao.focus();
  }

  async function abrirSessao(competenciaId) {
    const aberta = await chamar("POST", rota("/aluno/{id}/sessao"), { competencia_id: competenciaId },
      "Abrindo a sessão…");
    estado.sessaoId = aberta.sessao.sessao_id;
    estado.pergunta = aberta.sessao.pergunta;
    mostrarAvisos([]);
    mostrarPergunta(aberta.reforco);
  }

  function mostrarPergunta(reforco) {
    const p = estado.pergunta;
    const grupo = el("fieldset", { classe: "alternativas" }, el("legend", { texto: "Escolha uma alternativa" }),
      p.alternativas.map((texto, indice) => el("label", { classe: "alternativa" },
        el("input", { type: "radio", name: "alternativa", value: indice, required: true }),
        el("span", { texto }))));
    const form = el("form", { classe: "cartao", novalidate: true, onsubmit: enviarResposta },
      el("p", { classe: "etapa__dados" }, nomeCompetencia(p.competencia_id) + " · nível " + p.nivel +
        (reforco ? " · revisão" : "")),
      el("h2", { classe: "enunciado", id: "enunciado", texto: p.enunciado }),
      grupo,
      el("button", { type: "submit", classe: "botao acao", texto: "Enviar resposta", disabled: TIA.estaOcupado() }));
    form.setAttribute("aria-labelledby", "enunciado");
    $("estudo-conteudo").replaceChildren(form);
    const primeira = form.querySelector("input");
    if (primeira) primeira.focus();
  }

  async function enviarResposta(evento) {
    evento.preventDefault();
    const form = evento.currentTarget;
    const marcada = form.querySelector("input[name=alternativa]:checked");
    if (!marcada) {
      mostrarErro(new ErroApi("Escolha uma alternativa antes de enviar.", 0));
      return;
    }
    const indice = Number(marcada.value);
    const p = estado.pergunta;
    // reenvio depois de erro: mesmo evento_id, o orquestrador não processa duas vezes
    const mesmo = estado.eventoPendente && estado.eventoPendente.item_id === p.item_id &&
      estado.eventoPendente.indice_escolhido === indice;
    const corpo = mesmo ? estado.eventoPendente : {
      evento_id: novoEventoId(), tipo: "resposta", sessao_id: estado.sessaoId,
      item_id: p.item_id, indice_escolhido: indice,
    };
    estado.eventoPendente = corpo;
    let resultado;
    try {
      resultado = await chamar("POST", rota("/aluno/{id}/evento"), corpo, "O tutor está corrigindo e explicando…");
    } catch (erro) {
      if (erro.status) {
        // recusado pela API (ex.: sessão pausada ou já respondida): não reenviar;
        // a atividade é buscada de novo no orquestrador
        estado.eventoPendente = null;
        estado.pergunta = null;
        estado.sessaoId = null;
        $("estudo-conteudo").replaceChildren(el("button", { type: "button", classe: "botao acao",
          texto: "Buscar a atividade atual", onclick: () => carregarEstudo().catch(mostrarErro) }));
      }
      throw erro;
    }
    estado.eventoPendente = null;
    mostrarFeedback(form, indice, resultado);
  }

  function mostrarFeedback(form, indice, resultado) {
    const f = resultado.feedback;
    form.querySelectorAll(".alternativa").forEach((rotulo, i) => {
      const entrada = rotulo.querySelector("input");
      entrada.disabled = true;
      if (i === f.indice_correto) {
        rotulo.classList.add("alternativa--correta");
        rotulo.append(el("span", { classe: "selo selo--sucesso", texto: "correta" }));
      } else if (i === indice) {
        rotulo.classList.add("alternativa--errada");
        rotulo.append(el("span", { classe: "selo", texto: "sua resposta" }));
      }
    });
    form.querySelector("button[type=submit]").remove();

    const continuar = el("button", { type: "button", classe: "botao acao", texto: "Continuar",
      onclick: () => seguir(resultado.proxima) });
    const bloco = el("div", { classe: "cartao", role: "region", "aria-label": "Correção" },
      el("p", { classe: "veredito " + (f.acertou ? "veredito--acerto" : "veredito--erro"),
        texto: (f.acertou ? "✓ " : "✗ ") + f.veredito }),
      el("p", { classe: "explicacao", texto: f.explicacao }),
      el("p", { classe: "origem" }, "Origem da explicação: " + f.origem + ". " + (ORIGEM_FEEDBACK[f.origem] || "") +
        (f.falha_llm ? " Motivo: " + (FALHA[f.falha_llm] || f.falha_llm) + "." : "") + tempo(f.tempo_ms)),
      blocoFontes(f.fontes),
      el("p", { classe: "etapa__dados", texto: f.concluida ? "Competência concluída!" : "Nível atual: " + f.nivel_atual }),
      continuar);
    $("estudo-conteudo").append(bloco);
    mostrarAvisos(resultado.avisos);
    estado.pergunta = null;
    continuar.focus();
  }

  function blocoFontes(fontes) {
    if (!fontes || !fontes.length) {
      return el("p", { classe: "fontes", texto: "Fonte: texto do próprio item (sem trecho do material)." });
    }
    return el("div", { classe: "fontes" }, "Fontes do material (R03):",
      el("ul", {}, fontes.map((fonte) => el("li", {}, el("code", { texto: fonte })))));
  }

  // --- d) diálogo livre ---

  function itemConversa(item) {
    const vetada = item.vetada || item.origem === "docente";
    return el("li", { classe: "cartao" },
      el("p", { classe: "conversa__pergunta", texto: item.pergunta }),
      el("p", { classe: "conversa__resposta", texto: item.resposta }),
      el("p", { classe: "origem" }, "Origem: " + (vetada ? "professor" : item.origem) + ". " +
        (ORIGEM_FEEDBACK[vetada ? "docente" : item.origem] || "") +
        (item.falha_llm ? " Motivo: " + (FALHA[item.falha_llm] || item.falha_llm) + "." : "") + tempo(item.tempo_ms)),
      item.origem === "fallback" && !vetada ? null : blocoFontes(item.fontes));
  }

  async function carregarDialogo() {
    const select = $("campo-competencia");
    const escolhida = select.value;
    select.replaceChildren(el("option", { value: "", texto: "Todo o material" }),
      ...estado.etapas.map((e) => el("option", { value: e.competencia_id, texto: e.nome })));
    select.value = escolhida;
    const historico = await chamar("GET", rota("/alunos/{id}/dialogo"), null, "Carregando a conversa…");
    $("conversa").replaceChildren(...historico.slice().reverse().map(itemConversa));
  }

  async function perguntar(evento) {
    evento.preventDefault();
    const campo = $("campo-pergunta");
    const pergunta = campo.value.trim();
    if (!pergunta) {
      mostrarErro(new ErroApi("Escreva a pergunta antes de enviar.", 0));
      campo.focus();
      return;
    }
    const competencia = $("campo-competencia").value || null;
    try {
      const resposta = await chamar("POST", "/tutor/perguntar",
        { aluno_id: estado.aluno, pergunta, competencia_id: competencia },
        "O tutor está procurando no material…");
      $("conversa").prepend(itemConversa({ ...resposta, pergunta, vetada: false }));
      campo.value = "";
      atualizarContador();
      $("conversa").firstElementChild.setAttribute("tabindex", "-1");
      $("conversa").firstElementChild.focus();
    } catch (erro) { mostrarErro(erro); }
  }

  function atualizarContador() {
    $("contador-pergunta").textContent = $("campo-pergunta").value.length + " de 500 caracteres";
  }

  // --- e) relatório ---

  const TENDENCIA = {
    subindo: "Seus acertos estão melhorando em relação às sessões anteriores.",
    caindo: "Seus acertos caíram em relação às sessões anteriores. Vale revisar.",
    estavel: "Seus acertos estão estáveis.",
    insuficiente: "Ainda não há respostas suficientes para ver a tendência.",
  };

  function indicador(titulo, ...conteudo) {
    return el("section", { classe: "cartao" }, el("h2", { texto: titulo }), ...conteudo);
  }

  async function carregarRelatorio() {
    const r = await chamar("GET", rota("/relatorio/aluno/{id}") + "?narrativa=false", null, "Calculando os indicadores…");
    const pr = r.progresso, de = r.desempenho, en = r.engajamento, qf = r.qualidade_feedback;
    const nomes = {};
    for (const c of pr.por_competencia) nomes[c.competencia_id] = c.nome;
    const nome = (id) => nomes[id] || nomeCompetencia(id);

    const progresso = indicador("1. Progresso na trilha",
      pr.tem_trilha ? el("p", { texto: "Você concluiu " + pr.concluidas + " de " + pr.etapas + " etapas (" +
        porcento(pr.percentual) + ")." }) : el("p", { texto: "Você ainda não tem trilha." }),
      pr.tem_trilha ? el("progress", { max: pr.etapas || 1, value: pr.concluidas,
        "aria-label": "Etapas concluídas" }) : null,
      el("ul", {}, pr.por_competencia.map((c) => el("li", { texto: c.nome + ": " +
        (c.concluida ? "concluída" : c.nivel_atual ? "em andamento, nível " + c.nivel_atual : "não iniciada") }))));

    const desempenho = indicador("2. Desempenho",
      el("p", { texto: de.geral.respostas ? "Você acertou " + de.geral.acertos + " de " + de.geral.respostas +
        " perguntas (" + porcento(de.geral.taxa) + ")." : "Você ainda não respondeu perguntas." }),
      el("p", { texto: TENDENCIA[de.tendencia.direcao] || "" }),
      de.por_competencia.length ? el("ul", {}, de.por_competencia.map((t) => el("li", {
        texto: nome(t.chave) + ": " + t.acertos + " de " + t.respostas + " (" + porcento(t.taxa) + ")" }))) : null);

    const engajamento = indicador("3. Participação",
      el("ul", {},
        el("li", { texto: en.sessoes + " sessões de estudo (" + en.sessoes_concluidas + " concluídas)" }),
        el("li", { texto: en.respostas + " respostas e " + en.perguntas_dialogo + " perguntas ao tutor" }),
        el("li", { texto: en.dias_ativos + " dia(s) com atividade" }),
        el("li", { texto: en.dias_inativo === null ? "Ainda sem atividade."
          : en.dias_inativo === 0 ? "Última atividade: hoje." : "Última atividade há " + en.dias_inativo + " dia(s)." })),
      en.inativo ? el("p", { classe: "aviso aviso--alerta", texto: "Faz alguns dias que você não estuda. Que tal retomar?" }) : null);

    const fracos = indicador("4. Pontos a reforçar",
      r.pontos_fracos.length ? el("ul", {}, r.pontos_fracos.map((p) => el("li", {
        texto: p.nome + ": " + p.erros + " erro(s) em " + p.respostas + " resposta(s)" }))) :
        el("p", { texto: "Nenhum ponto fraco identificado até agora." }),
      r.itens_fracos.length ? el("p", { classe: "dica", texto: r.itens_fracos.length +
        " pergunta(s) com erro repetido." }) : null);

    const total = qf.respostas_com_origem;
    const qualidade = indicador("5. Explicações do tutor",
      total ? el("ul", {},
        el("li", { texto: (qf.por_origem.LLM || 0) + " de " + total + " escritas pela IA local e conferidas" }),
        el("li", { texto: (qf.por_origem.guarda || 0) + " barradas pela verificação (trocadas pelo material)" }),
        el("li", { texto: (qf.por_origem.fallback || 0) + " com texto fixo" })) :
        el("p", { texto: "Ainda não há explicações registradas." }),
      qf.vetados ? el("p", { texto: qf.vetados + " resposta(s) do diálogo corrigida(s) pelo professor." }) : null);

    $("relatorio-indicadores").replaceChildren(el("div", { classe: "indicadores" },
      progresso, desempenho, engajamento, fracos, qualidade));
    mostrarNarrativa(null);
    await carregarCorrecoes();
  }

  // feedbacks de questões vetados pelo professor (R12): a correção substitui a explicação original
  async function carregarCorrecoes() {
    const feedbacks = await chamar("GET", rota("/alunos/{id}/feedbacks"), null, "Buscando as correções…");
    const vetados = feedbacks.filter((f) => f.vetada).reverse();
    $("relatorio-correcoes").replaceChildren(vetados.length ? el("ul", { classe: "correcoes" }, vetados.map((f) =>
      el("li", { classe: "cartao" },
        el("p", { classe: "etapa__dados", texto: nomeCompetencia(f.competencia_id) + " · questão " +
          (f.item_id || "") }),
        f.enunciado ? el("p", { classe: "enunciado", texto: f.enunciado }) : null,
        f.veredito ? el("p", { classe: "veredito", texto: f.veredito }) : null,
        el("p", { classe: "explicacao", texto: f.explicacao }),
        el("p", { classe: "origem", texto: "Origem: professor. " + ORIGEM_FEEDBACK.docente }))))
      : el("p", { texto: "Nenhuma explicação corrigida pelo professor." }));
  }

  function mostrarNarrativa(narrativa) {
    const area = $("relatorio-narrativa");
    if (!narrativa) {
      area.replaceChildren(el("p", { classe: "dica",
        texto: "Um parágrafo escrito pela IA local a partir dos números acima (pode levar mais de um minuto)." }));
      return;
    }
    area.replaceChildren(el("p", { classe: "explicacao", texto: narrativa.texto }),
      el("p", { classe: "origem" }, "Origem: " + narrativa.origem + ". " +
        ({ LLM: "Texto da IA local, conferido: os números batem com os indicadores.",
          guarda: "A verificação barrou o texto da IA; vai o texto fixo.",
          fallback: "Texto fixo: a IA não respondeu." }[narrativa.origem] || "") +
        (narrativa.falha_llm ? " Motivo: " + (FALHA[narrativa.falha_llm] || narrativa.falha_llm) + "." : "")));
  }

  async function gerarNarrativa() {
    try {
      const r = await chamar("GET", rota("/relatorio/aluno/{id}") + "?narrativa=true", null,
        "O tutor está escrevendo o resumo…");
      mostrarNarrativa(r.narrativa);
    } catch (erro) { mostrarErro(erro); }
  }

  // --- início ---

  document.addEventListener("DOMContentLoaded", () => {
    TIA.configurar({ aoExigirLogin: () => mostrarLogin("Sua sessão terminou. Entre de novo.") });
    $("form-login").addEventListener("submit", entrarComSenha);
    TIA.ligarTrocaDeSenha(iniciar);
    $("sair").addEventListener("click", encerrarSessao);
    $("form-entrada").addEventListener("submit", entrar);
    $("form-matricula").addEventListener("submit", matricular);
    $("cancelar-matricula").addEventListener("click", sair);
    $("trocar-aluno").addEventListener("click", sair);
    $("erro-fechar").addEventListener("click", esconderErro);
    $("ir-estudar").addEventListener("click", () => irPara("estudo"));
    $("atualizar-trilha").addEventListener("click", () => carregarTrilha().catch(mostrarErro));
    $("form-dialogo").addEventListener("submit", perguntar);
    $("campo-pergunta").addEventListener("input", atualizarContador);
    $("gerar-narrativa").addEventListener("click", gerarNarrativa);
    document.querySelectorAll(".aba").forEach((aba) => aba.addEventListener("click", () => irPara(aba.dataset.tela)));
    // erros de telas abertas por botão (ex.: "Começar") também aparecem na faixa de erro
    window.addEventListener("unhandledrejection", (e) => { e.preventDefault(); mostrarErro(e.reason); });

    iniciar().catch(mostrarErro);
  });
})();
