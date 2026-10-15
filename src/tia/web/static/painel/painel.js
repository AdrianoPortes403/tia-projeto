/*
 * Painel do docente/instituição do TIA (EAP 1.4.5): JavaScript puro, sem build.
 *
 * Telas: visão geral (5 indicadores agregados do Agente 3 e a interpretação),
 * alertas de risco (com código de aluno; consulta auditada), desempenho por
 * competência (barras em SVG), revisão docente (aprovar/vetar o feedback das
 * questões e as respostas do diálogo, R12) e
 * auditoria (R11). Exportação em CSV pela API e impressão pelo navegador.
 * Rotas em docs/arquitetura/arquitetura.md, "Painel do docente".
 *
 * Segurança: todo texto vindo da API entra por textContent (el/svg de
 * comum.js), nunca por innerHTML; nada vai para o console (R08). Grupos abaixo
 * do mínimo já chegam suprimidos da API ("menos de N"); a tela só os mostra
 * como ocultos. Login (1.4.6): só o papel docente usa o painel; a auditoria
 * grava o usuário em cada consulta, aprovação e veto.
 */
"use strict";

(function () {
  const { $, el, svg, porcento, ErroApi, chamar, mostrarErro, esconderErro } = window.TIA;
  // a interpretação da turma chama o LLM (até RELATORIO_TIMEOUT_LLM, 120 s em desenvolvimento)
  TIA.configurar({ esperaMaximaMs: 180000, quem: "O servidor", textoEspera: "Carregando…" });

  const PADRAO_CODIGO = /^[A-Za-z0-9_-]{1,32}$/;
  const POR_PAGINA_REVISAO = 10;
  const POR_PAGINA_AUDITORIA = 25;

  const ORIGEM = {
    LLM: "escrita pela IA local e conferida pela verificação automática",
    guarda: "a verificação barrou o texto da IA; foi o trecho do material ou do item",
    fallback: "texto fixo (a IA não respondeu ou o material não cobre)",
    docente: "corrigida pelo docente",
  };
  const ORIGEM_NARRATIVA = {
    LLM: "texto da IA local, conferido: os números batem com os indicadores.",
    guarda: "a verificação barrou o texto da IA; vai o texto fixo.",
    fallback: "texto fixo (a IA não foi chamada ou não respondeu).",
  };
  const FALHA = { timeout: "a IA demorou demais (timeout)" };
  const MOTIVO = {
    inatividade: "Inatividade",
    desempenho_em_queda: "Desempenho em queda",
    desempenho_baixo: "Desempenho baixo",
    conclusao_sem_dominio: "Concluída com ressalvas",
  };
  const DIRECAO = {
    subindo: "↑ subindo",
    caindo: "↓ caindo",
    estavel: "→ estável",
    insuficiente: "sem dados suficientes",
  };
  const ALERTA_TURMA = {
    inatividade: "Inatividade",
    desempenho_em_queda: "Desempenho em queda",
    conclusao_sem_dominio: "Concluída com ressalvas (sem domínio)",
    competencia_com_erro_alto: "Competência com erro alto",
  };
  const SITUACAO = { a_revisar: "A revisar", aprovada: "Aprovada", vetada: "Vetada" };
  const AGENTE = {
    orquestrador: "Orquestrador", planejador: "Planejador", tutor: "Tutor", relatorio: "Relatório",
    painel: "Painel", seguranca: "Segurança",
  };
  const PAPEL = {
    aluno: "aluno", docente: "docente", admin: "admin", sistema: "sistema", sem_login: "sem login (desenvolvimento)",
    anonimo: "não logado",
  };
  const TIPO = {
    resposta_item: "resposta a questão",
    dialogo: "pergunta ao tutor",
    incentivo: "incentivo",
    relatorio_aluno: "relatório do aluno",
    relatorio_turma: "relatório da turma",
    decisao_orquestrador: "decisão do orquestrador",
    veto_docente: "revisão docente",
    consulta_painel: "consulta do painel",
    login: "login",
    login_falha: "login recusado",
    login_bloqueado: "login bloqueado (muitas tentativas)",
    logout: "saída",
    acesso_negado: "acesso negado",
    gestao_usuario: "gestão de usuário",
    resumo_anonimos: "resumo de pedidos sem login",
    limpeza_retencao: "limpeza por prazo de retenção",
    retencao: "retenção de dados (LGPD)",
    direito_titular: "direito do titular (LGPD)",
    onboarding: "cadastro inicial (onboarding)",
    diagnostico: "resposta ao diagnóstico inicial",
  };

  const estado = {
    nomes: {},          // competência -> nome (GET /conteudo/ementa)
    perfis: {},         // perfil -> nome (GET /conteudo/perfis)
    tela: null,
    risco: null,        // última ConsultaRisco (o filtro de motivo é feito aqui)
    paginaRevisao: 1,
    paginaAuditoria: 1,
  };

  // --- utilidades ---

  function nome(id) { return estado.nomes[id] || id || "todo o material"; }

  function perfil() { return $("campo-perfil").value; }

  function comPerfil(caminho) {
    const p = perfil();
    return p ? caminho + (caminho.includes("?") ? "&" : "?") + "perfil_id=" + encodeURIComponent(p) : caminho;
  }

  function descricaoGrupo(contagem, minGrupo) {
    const p = perfil();
    return "Grupo: " + (p ? "perfil " + (estado.perfis[p] || p) : "instituição inteira") + " · alunos: " +
      contagem.texto + " · grupo mínimo para exibir números: " + minGrupo + " alunos (LGPD, R08).";
  }

  function dataHora(ts) {
    return ts ? ts.replace("T", " ").slice(0, 16) : "";
  }

  function fracaoTexto(fracao) {
    return fracao === null || fracao === undefined ? "sem dados" : porcento(fracao);
  }

  function selo(texto, classe) { return el("span", { classe: "selo " + (classe || ""), texto }); }

  function tabela(legenda, cabecalhos, linhas) {
    const corpo = el("tbody", {}, linhas.map((celulas) => el("tr", {}, celulas.map((c, i) =>
      i === 0 ? el("th", { scope: "row" }, c) : el("td", {}, c)))));
    // rolagem horizontal acessível pelo teclado em telas estreitas
    return el("div", { classe: "tabela-rolagem", tabindex: "0", role: "region", "aria-label": legenda },
      el("table", { classe: "tabela" },
        el("caption", { classe: "visualmente-oculto", texto: legenda }),
        el("thead", {}, el("tr", {}, cabecalhos.map((c) => el("th", { scope: "col", texto: c })))),
        corpo));
  }

  /*
   * Barra horizontal em SVG. O valor sempre vai também em texto ao lado (o
   * gráfico não depende de cor) e o SVG é decorativo para leitores de tela
   * (aria-hidden): a descrição em texto está no item da lista. A linha
   * tracejada marca a referência (ex.: 50% de acerto).
   */
  function barra(fracao, referencia) {
    const largura = Math.max(0, Math.min(1, fracao || 0)) * 100;
    return svg("svg", { classe: "barra", viewBox: "0 0 100 12", preserveAspectRatio: "none",
      "aria-hidden": "true", focusable: "false" },
    svg("rect", { classe: "barra__trilho", x: 0, y: 0, width: 100, height: 12, rx: 2 }),
    svg("rect", { classe: "barra__valor", x: 0, y: 0, width: largura, height: 12, rx: 2 }),
    referencia === undefined ? null : svg("line", { classe: "barra__referencia", x1: referencia * 100,
      x2: referencia * 100, y1: 0, y2: 12 }));
  }

  function itemBarra(rotulo, fracao, texto, referencia, suprimido) {
    return el("li", { classe: "grafico__item" + (suprimido ? " grafico__item--oculto" : "") },
      el("div", { classe: "grafico__rotulo" }, el("span", { classe: "grafico__nome", texto: rotulo }),
        el("span", { classe: "grafico__valor", texto })),
      suprimido ? null : barra(fracao, referencia));
  }

  // --- navegação ---

  const TELAS = ["geral", "risco", "competencias", "revisao", "auditoria"];
  const AO_ABRIR = {
    geral: carregarGeral,
    risco: carregarRisco,
    competencias: carregarCompetencias,
    revisao: carregarRevisao,
    auditoria: carregarAuditoria,
  };

  function irPara(tela) {
    estado.tela = tela;
    try { history.replaceState(null, "", "#" + tela); } catch (_) { /* sem histórico: segue */ }
    for (const nomeTela of TELAS) $("tela-" + nomeTela).hidden = nomeTela !== tela;
    document.querySelectorAll(".aba").forEach((aba) => {
      if (aba.dataset.tela === tela) aba.setAttribute("aria-current", "page");
      else aba.removeAttribute("aria-current");
    });
    $("conteudo").focus();
    if (!TIA.estaOcupado()) AO_ABRIR[tela]().catch(mostrarErro);
  }

  // --- 1) visão geral ---

  function cartao(titulo, ...conteudo) {
    return el("section", { classe: "cartao indicador" }, el("h2", { texto: titulo }), ...conteudo);
  }

  function oculto(contagem) {
    return el("p", { classe: "oculto", texto: "Oculto: " + contagem.texto + " alunos neste grupo." });
  }

  async function carregarGeral() {
    $("exportar-csv").setAttribute("href", comPerfil("/painel/exportar/indicadores.csv"));
    const r = await chamar("GET", comPerfil("/relatorio/turma?narrativa=false"), null, "Calculando os indicadores…");
    mostrarGeral(r);
    mostrarNarrativa(null);
  }

  function mostrarGeral(r) {
    $("geral-grupo").textContent = descricaoGrupo(r.alunos, r.min_grupo) + " Gerado em " + dataHora(r.gerado_em) +
      ". Indicadores PROVISÓRIOS (critérios a validar com a Pessoa 4).";
    const area = $("geral-indicadores");
    if (r.suprimido) {
      area.replaceChildren(el("p", { classe: "aviso aviso--alerta", texto: "Este grupo tem " + r.alunos.texto +
        " alunos: nenhum indicador é exibido, para que nenhum aluno possa ser identificado (LGPD, R08)." }));
      $("geral-alertas").replaceChildren(el("p", { texto: "Sem alertas exibidos para grupos abaixo do mínimo." }));
      return;
    }

    const progresso = cartao("1. Progresso na trilha",
      el("p", { classe: "numero-grande", texto: fracaoTexto(r.progresso_medio) }),
      el("p", { texto: "Média das etapas concluídas entre os alunos com trilha (" + r.alunos_com_trilha.texto +
        " alunos)." }),
      r.progresso_medio === null ? null : el("ul", { classe: "grafico" },
        itemBarra("Progresso médio", r.progresso_medio, fracaoTexto(r.progresso_medio))));

    const desempenho = cartao("2. Desempenho por nível",
      el("p", { classe: "dica", texto: "Taxa de acerto em cada nível de dificuldade; linha tracejada em 50%." }),
      r.desempenho_por_nivel.length ? el("ul", { classe: "grafico" }, r.desempenho_por_nivel.map((g) =>
        itemBarra("Nível " + g.chave, g.taxa, g.suprimido ? "oculto (" + g.alunos.texto + " alunos)" :
          fracaoTexto(g.taxa) + " de " + g.respostas + " respostas", 0.5, g.suprimido)))
        : el("p", { texto: "Ainda não há respostas." }),
      el("p", { classe: "dica", texto: "Por competência: tela Competências." }));

    const e = r.engajamento;
    const engajamento = cartao("3. Engajamento",
      el("ul", {},
        el("li", { texto: "Sessões por aluno (média): " + String(e.media_sessoes).replace(".", ",") }),
        el("li", { texto: "Dias com atividade (média): " + String(e.media_dias_ativos).replace(".", ",") }),
        el("li", { texto: "Perguntas ao tutor (média): " + String(e.media_perguntas_dialogo).replace(".", ",") }),
        el("li", { texto: "Alunos inativos: " + e.inativos.texto })));

    const fracos = cartao("4. Pontos fracos",
      r.pontos_fracos.length ? el("ul", {}, r.pontos_fracos.map((g) => el("li", {
        texto: nome(g.chave) + ": ponto fraco de " + g.alunos.texto + " aluno(s)" +
          (g.suprimido ? " (taxa de erro oculta: grupo pequeno)" : "; erro agregado " + fracaoTexto(g.taxa)) })))
        : el("p", { texto: "Nenhuma competência aparece como ponto fraco." }),
      el("p", { texto: r.itens_fracos.length + " questão(ões) com erro repetido (ver Competências)." }));

    const q = r.qualidade_feedback;
    const total = Object.values(q.por_origem).reduce((a, b) => a + b, 0);
    const qualidade = cartao("5. Qualidade do feedback",
      total ? el("ul", { classe: "grafico" }, ["LLM", "guarda", "fallback"].map((o) => itemBarra(
        { LLM: "IA local (LLM)", guarda: "Barrado pela verificação", fallback: "Texto fixo" }[o],
        q.taxa_por_origem[o], fracaoTexto(q.taxa_por_origem[o]) + " (" + (q.por_origem[o] || 0) + ")")))
        : el("p", { texto: "Ainda não há feedbacks registrados." }),
      el("p", { texto: "Vetos do docente: " + q.feedbacks_vetados + " de " + q.feedbacks_com_texto +
        " feedbacks de questões (" + fracaoTexto(q.taxa_veto_feedback) + ") e " + q.vetados + " de " + q.dialogos +
        " respostas do diálogo (" + fracaoTexto(q.taxa_veto) + ")." }));

    area.replaceChildren(el("div", { classe: "indicadores" }, progresso, desempenho, engajamento, fracos, qualidade));
    $("geral-alertas").replaceChildren(r.alertas.length ? el("ul", { classe: "lista-alertas" }, r.alertas.map((a) =>
      el("li", {}, selo(ALERTA_TURMA[a.tipo] || a.tipo, "selo--alerta"), " ", a.descricao + " Alunos: " +
        a.alunos.texto + "."))) : el("p", { texto: "Nenhum alerta." }));
  }

  function mostrarNarrativa(narrativa) {
    const area = $("geral-narrativa");
    if (!narrativa) {
      area.replaceChildren(el("p", { classe: "dica",
        texto: "Parágrafo escrito pela IA local a partir dos números acima (pode levar mais de um minuto)." }));
      return;
    }
    area.replaceChildren(el("p", { classe: "explicacao", texto: narrativa.texto }),
      el("p", { classe: "origem" }, "Origem: " + narrativa.origem + " — " + (ORIGEM_NARRATIVA[narrativa.origem] || "") +
        (narrativa.falha_llm ? " Motivo: " + (FALHA[narrativa.falha_llm] || narrativa.falha_llm) + "." : "")));
  }

  async function gerarNarrativa() {
    try {
      const r = await chamar("GET", comPerfil("/relatorio/turma?narrativa=true"), null,
        "A IA local está escrevendo a interpretação…");
      mostrarGeral(r);
      mostrarNarrativa(r.narrativa);
    } catch (erro) { mostrarErro(erro); }
  }

  // --- 2) alertas de risco ---

  async function carregarRisco() {
    estado.risco = await chamar("GET", comPerfil("/painel/alunos-em-risco"), null, "Procurando alunos em risco…");
    mostrarRisco();
  }

  function mostrarRisco() {
    const r = estado.risco;
    if (!r) return;
    const c = r.criterios;
    $("risco-criterios").textContent = "Critérios (PROVISÓRIOS): sem atividade há " + c.inatividade_dias +
      " dias ou mais (quem concluiu a trilha não entra); queda de " + Math.round(c.queda_pontos * 100) +
      " pontos ou mais no acerto recente; acerto abaixo de " + porcento(c.desempenho_baixo) + " com pelo menos " +
      c.min_respostas + " respostas; questões de uma competência terminadas sem domínio (avança só com acerto de " +
      porcento(c.acerto_min_avanco) + " ou mais). Avaliados: " + r.alunos_avaliados + " alunos.";
    const filtro = $("filtro-motivo").value;
    const alunos = r.alunos.filter((a) => !filtro || a.motivos.some((m) => m.tipo === filtro));
    $("risco-lista").replaceChildren(alunos.length ? tabela("Alunos em risco",
      ["Código", "Motivos", "Dias sem atividade", "Acerto", "Tendência", "Progresso", ""],
      alunos.map((a) => [
        el("code", { texto: a.aluno_id }),
        el("ul", { classe: "motivos" }, a.motivos.map((m) => el("li", {},
          selo(MOTIVO[m.tipo] || m.tipo, "selo--alerta"), " ", m.descricao))),
        a.dias_inativo === null ? "—" : String(a.dias_inativo),
        fracaoTexto(a.taxa_acerto) + " (" + a.respostas + " resp.)",
        DIRECAO[a.tendencia] || a.tendencia,
        fracaoTexto(a.progresso),
        el("button", { type: "button", classe: "botao botao--link acao", texto: "Ver auditoria",
          "aria-label": "Ver auditoria do aluno " + a.aluno_id,
          onclick: () => auditoriaDoAluno(a.aluno_id) }),
      ])) : el("p", { classe: "aviso", texto: filtro ? "Nenhum aluno com este motivo." : "Nenhum aluno em risco." }));
    $("risco-auditoria").textContent = "Esta consulta foi registrada na auditoria em seu nome (registro nº " +
      r.auditoria_id + ", " + dataHora(r.gerado_em) + ").";
  }

  function auditoriaDoAluno(codigo) {
    $("filtro-agente").value = "";
    $("filtro-aluno").value = codigo;
    $("filtro-desde").value = "";
    $("filtro-ate").value = "";
    estado.paginaAuditoria = 1;
    irPara("auditoria");
  }

  // --- 3) desempenho por competência ---

  async function carregarCompetencias() {
    const r = await chamar("GET", comPerfil("/painel/competencias"), null, "Calculando por competência…");
    $("competencias-grupo").textContent = descricaoGrupo(r.alunos, r.min_grupo);
    $("itens-regra").textContent = "Só entram questões respondidas por pelo menos " + r.min_grupo +
      " alunos, com pelo menos 2 erros e metade ou mais das respostas erradas.";
    if (r.suprimido) {
      const texto = "Este grupo tem " + r.alunos.texto + " alunos: nada é exibido (LGPD, R08).";
      $("competencias-barras").replaceChildren(el("p", { classe: "aviso aviso--alerta", texto }));
      $("competencias-itens").replaceChildren(el("p", { texto }));
      return;
    }
    const exibidas = r.competencias.filter((c) => !c.suprimido);
    const resumo = exibidas.length ? "Acerto por competência: " + exibidas.map((c) => c.nome + " " +
      fracaoTexto(c.taxa)).join("; ") + "." : "Nenhuma competência tem alunos suficientes para exibir.";
    $("competencias-barras").replaceChildren(
      // descrição do gráfico para leitores de tela (o SVG é decorativo)
      el("p", { classe: "visualmente-oculto", texto: resumo }),
      el("p", { classe: "dica", "aria-hidden": "true",
        texto: "Barra: taxa de acerto agregada; linha tracejada: 50%. Competências com menos de " + r.min_grupo +
          " alunos ficam ocultas." }),
      r.competencias.length ? el("ul", { classe: "grafico" }, r.competencias.map((c) => {
        const item = itemBarra(c.nome, c.taxa, c.suprimido ? "oculto (" + c.alunos.texto + " alunos)" :
          fracaoTexto(c.taxa) + " de acerto · " + c.respostas + " respostas · " + c.alunos.texto + " alunos",
        0.5, c.suprimido);
        if (c.tendencia) {
          item.append(el("p", { classe: "grafico__detalhe", texto: "Tendência dos alunos: " +
            ["subindo", "caindo", "estavel", "insuficiente"].map((d) => DIRECAO[d] + " " + c.tendencia[d].texto)
              .join(" · ") }));
        }
        return item;
      })) : el("p", { texto: "Ainda não há respostas." }));

    $("competencias-itens").replaceChildren(r.itens_fracos.length ? tabela("Questões com erro repetido",
      ["Questão", "Competência", "Nível", "Enunciado", "Taxa de erro", "Alunos que erraram", "Respostas"],
      r.itens_fracos.map((i) => [el("code", { texto: i.item_id }), i.nome_competencia,
        i.nivel === null ? "—" : String(i.nivel), el("span", { classe: "enunciado-curto", texto: i.enunciado }),
        fracaoTexto(i.taxa_erro), i.alunos_com_erro.texto, String(i.respostas)]))
      : el("p", { texto: "Nenhuma questão com erro repetido entre as respondidas por alunos suficientes." }));
  }

  // --- 4) revisão docente (R12): feedback das questões e respostas do diálogo ---

  // rota do veto de cada tipo (as duas já existiam no Tutor; vetada=false numa resposta sem veto = aprovação)
  const ROTA_VETO = { dialogo: "/tutor/dialogo/{id}/veto", feedback: "/tutor/feedback/{id}/veto" };
  const TIPO_TEXTO = { dialogo: "Resposta do diálogo", feedback: "Feedback de questão" };

  function resumoTipo(titulo, resumo) {
    return el("div", { classe: "resumo-tipo" },
      el("h3", { texto: titulo }),
      el("p", { classe: "numero-grande", texto: fracaoTexto(resumo.taxa_veto) }),
      el("p", { texto: "Taxa de vetos: " + resumo.vetados + " de " + resumo.total + ". Aprovados: " +
        resumo.aprovados + ". A revisar: " + resumo.a_revisar + "." }));
  }

  async function carregarRevisao() {
    const parametros = new URLSearchParams({ situacao: $("filtro-situacao").value, pagina: estado.paginaRevisao,
      por_pagina: POR_PAGINA_REVISAO });
    for (const [chave, campo] of [["tipo", "filtro-tipo"], ["origem", "filtro-origem"],
      ["competencia_id", "filtro-competencia"]]) {
      if ($(campo).value) parametros.set(chave, $(campo).value);
    }
    const r = await chamar("GET", "/painel/revisao?" + parametros, null, "Carregando os textos…");
    const f = r.feedbacks_por_origem;
    $("revisao-resumo").replaceChildren(el("div", { classe: "cartao resumo-revisao" },
      el("div", { classe: "resumo-revisao__tipos" },
        resumoTipo("Feedback das questões", r.feedback), resumoTipo("Respostas do diálogo", r.dialogo)),
      el("p", { classe: "dica", texto: "Origem de todos os feedbacks de questões: IA local " + f.LLM +
        " · barrados pela verificação " + f.guarda + " · texto fixo " + f.fallback + "." +
        (r.feedbacks_sem_texto ? " " + r.feedbacks_sem_texto + " resposta(s) antiga(s) sem texto gravado " +
          "(não revisáveis)." : "") }),
      el("p", { classe: "dica", texto: "Consulta registrada na auditoria (registro nº " + r.auditoria_id + ")." })));
    $("revisao-total").textContent = r.total + " texto(s) com estes filtros, do mais recente para o mais antigo.";
    $("revisao-lista").replaceChildren(...(r.itens.length ? r.itens.map(itemRevisao)
      : [el("li", { classe: "aviso", texto: "Nenhum texto com este filtro." })]));
    paginacao($("revisao-paginas"), r.pagina, r.total, r.por_pagina, (pagina) => {
      estado.paginaRevisao = pagina;
      carregarRevisao().catch(mostrarErro);
    });
  }

  function blocoTexto(rotulo, texto, classe) {
    return el("p", { classe }, el("span", { classe: "rotulo", texto: rotulo }), texto || "");
  }

  function itemRevisao(item) {
    const chave = item.tipo + "-" + item.id;
    const id = "revisao-" + chave;
    const ehFeedback = item.tipo === "feedback";
    const acoes = el("div", { classe: "linha-botoes nao-imprimir" });
    const formVeto = formularioVeto(item, chave);
    if (item.situacao !== "aprovada" && !item.vetada) {
      acoes.append(el("button", { type: "button", classe: "botao acao", texto: "Aprovar",
        "aria-describedby": id, onclick: () => revisar(item, { vetada: false }, "Aprovando…") }));
    }
    if (item.vetada) {
      acoes.append(el("button", { type: "button", classe: "botao botao--secundario acao",
        texto: "Retirar veto (aprovar a original)", "aria-describedby": id,
        onclick: () => revisar(item, { vetada: false }, "Retirando o veto…") }));
    }
    acoes.append(el("button", { type: "button", classe: "botao botao--secundario acao",
      texto: item.vetada ? "Editar correção" : "Vetar…", "aria-describedby": id, "aria-expanded": "false",
      onclick: (e) => {
        formVeto.hidden = !formVeto.hidden;
        e.currentTarget.setAttribute("aria-expanded", String(!formVeto.hidden));
        if (!formVeto.hidden) formVeto.querySelector("textarea").focus();
      } }));
    const original = item.vetada ? (ehFeedback ? "Explicação original (vetada): " : "Resposta original (vetada): ")
      : (ehFeedback ? "Explicação que o aluno viu: " : "Resposta do tutor: ");
    return el("li", { classe: "cartao item-revisao" },
      el("div", { classe: "item-revisao__cabeca" },
        el("p", { classe: "etapa__dados", id },
          (TIPO_TEXTO[item.tipo] || item.tipo) + " nº " + item.id + " · aluno ", el("code", { texto: item.aluno_id }),
          " · " + nome(item.competencia_id) + (ehFeedback && item.item_id ? " · questão " + item.item_id +
            (item.nivel ? " (nível " + item.nivel + ")" : "") : "") + " · " + dataHora(item.ts)),
        selo(SITUACAO[item.situacao] || item.situacao,
          item.vetada ? "selo--erro" : item.situacao === "aprovada" ? "selo--sucesso" : "")),
      blocoTexto(ehFeedback ? "Questão: " : "Pergunta do aluno: ", item.pergunta, "conversa__pergunta"),
      ehFeedback && item.veredito ? blocoTexto("Veredito automático: ", item.veredito,
        "veredito-texto " + (item.acertou ? "veredito--acerto" : "veredito--erro")) : null,
      blocoTexto(original, item.resposta, "conversa__resposta" + (item.vetada ? " riscado" : "")),
      el("p", { classe: "origem", texto: "Origem: " + item.origem + " — " + (ORIGEM[item.origem] || "") +
        (item.falha_llm ? " Motivo: " + (FALHA[item.falha_llm] || item.falha_llm) + "." : "") }),
      item.explicacao_descartada ? el("div", { classe: "descartado" },
        blocoTexto("Texto da IA barrado pela verificação (o aluno não viu): ", item.explicacao_descartada),
        item.motivo_descarte ? blocoTexto("Motivo do descarte: ", item.motivo_descarte, "origem") : null) : null,
      item.fontes.length ? el("div", { classe: "fontes" }, "Fontes citadas (R03):",
        el("ul", {}, item.fontes.map((fonte) => el("li", {}, el("code", { texto: fonte })))))
        : el("p", { classe: "fontes", texto: ehFeedback ? "Sem fonte do material: texto do próprio item."
          : "Sem fonte citada." }),
      item.vetada ? blocoTexto("Correção do docente (o aluno vê esta): ", item.correcao_docente, "correcao") : null,
      acoes, formVeto);
  }

  function formularioVeto(item, chave) {
    const campo = "correcao-" + chave;
    const form = el("form", { classe: "form-veto", novalidate: true, hidden: true,
      onsubmit: (e) => {
        e.preventDefault();
        const texto = form.querySelector("textarea").value.trim();
        if (!texto) {
          mostrarErro(new ErroApi("Escreva a correção (o motivo do veto) que o aluno vai ver.", 0));
          form.querySelector("textarea").focus();
          return;
        }
        revisar(item, { vetada: true, correcao_docente: texto }, "Gravando o veto…");
      } },
    el("label", { for: campo, texto: "Correção que o aluno vai ver (explique o motivo do veto)" }),
    el("textarea", { id: campo, rows: 3, maxlength: 2000, required: true }),
    el("div", { classe: "linha-botoes" },
      el("button", { type: "submit", classe: "botao acao", texto: "Confirmar veto" }),
      el("button", { type: "button", classe: "botao botao--secundario", texto: "Cancelar",
        onclick: () => { form.hidden = true; } })));
    if (item.correcao_docente) form.querySelector("textarea").value = item.correcao_docente;
    return form;
  }

  // única escrita do painel: as rotas de veto do Tutor (cada uso grava veto_docente na auditoria)
  async function revisar(item, corpo, texto) {
    try {
      await chamar("PATCH", ROTA_VETO[item.tipo].replace("{id}", encodeURIComponent(item.id)), corpo, texto);
      await carregarRevisao();
      $("revisao-resumo").focus();
    } catch (erro) { mostrarErro(erro); }
  }

  // --- 5) auditoria (R11) ---

  async function carregarAuditoria() {
    const aluno = $("filtro-aluno").value.trim();
    if (aluno && !PADRAO_CODIGO.test(aluno)) {
      throw new ErroApi("Código inválido: use só letras sem acento, números, \"-\" ou \"_\" (até 32).", 0);
    }
    const parametros = new URLSearchParams({ pagina: estado.paginaAuditoria, por_pagina: POR_PAGINA_AUDITORIA });
    for (const [chave, campo] of [["agente", "filtro-agente"], ["desde", "filtro-desde"], ["ate", "filtro-ate"]]) {
      if ($(campo).value) parametros.set(chave, $(campo).value);
    }
    if (aluno) parametros.set("aluno_id", aluno);
    const r = await chamar("GET", "/painel/auditoria?" + parametros, null, "Consultando a auditoria…");
    $("auditoria-total").textContent = r.total + " registro(s) encontrado(s), do mais recente para o mais antigo.";
    $("auditoria-tabela").replaceChildren(r.registros.length ? tabela("Registros de auditoria",
      ["Data e hora", "Agente", "Tipo", "Usuário", "Aluno", "Origem / ação", "Referência", "Motivo", "Fontes"],
      r.registros.map((x) => [dataHora(x.ts), x.agentes.map((a) => AGENTE[a] || a).join(" + "),
        TIPO[x.tipo] || x.tipo,
        (x.usuario_id ? x.usuario_id + " " : "") + "(" + (PAPEL[x.usuario_papel] || x.usuario_papel || "sem registro") + ")",
        x.aluno_id ? el("code", { texto: x.aluno_id }) : "—",
        (x.origem || "—") + (x.origem_justificativas ? " (justificativas: " + x.origem_justificativas + ")" : ""),
        x.referencia_id || "—", x.motivo || "—", x.fontes.length ? x.fontes.join(", ") : "—"]))
      : el("p", { texto: "Nenhum registro com estes filtros." }));
    paginacao($("auditoria-paginas"), r.pagina, r.total, r.por_pagina, (pagina) => {
      estado.paginaAuditoria = pagina;
      carregarAuditoria().catch(mostrarErro);
    });
  }

  // --- paginação ---

  function paginacao(area, pagina, total, porPagina, ir) {
    const paginas = Math.max(1, Math.ceil(total / porPagina));
    area.replaceChildren(
      el("button", { type: "button", classe: "botao botao--secundario acao", texto: "← Anterior",
        disabled: pagina <= 1, onclick: () => ir(pagina - 1) }),
      el("span", { classe: "paginacao__texto", texto: "Página " + pagina + " de " + paginas }),
      el("button", { type: "button", classe: "botao botao--secundario acao", texto: "Próxima →",
        disabled: pagina >= paginas, onclick: () => ir(pagina + 1) }));
  }

  // --- login (1.4.6) ---

  function mostrarLogin(mensagem, semFormulario) {
    estado.tela = null;
    for (const nomeTela of TELAS) $("tela-" + nomeTela).hidden = true;
    $("abas").hidden = true;
    $("filtro-grupo").hidden = true;
    $("tela-login").hidden = false;
    $("form-login").hidden = !!semFormulario;
    TIA.esconderTrocaDeSenha();
    $("login-mensagem").textContent = mensagem || "";
    $("login-mensagem").hidden = !mensagem;
    if (!semFormulario) $("campo-login").focus();
  }

  function mostrarTrocaDeSenha() {
    mostrarLogin();
    TIA.mostrarTrocaDeSenha();
  }

  async function iniciar() {
    const situacao = await TIA.obterSessao();
    TIA.mostrarSessao(situacao);
    if (situacao.autenticacao === "ligada" && !situacao.usuario) { mostrarLogin(); return; }
    if (situacao.usuario && situacao.usuario.trocar_senha) { mostrarTrocaDeSenha(); return; }
    if (situacao.autenticacao === "ligada" && situacao.usuario.papel !== "docente") {
      mostrarLogin("O painel é só para docentes. Você entrou como " + situacao.usuario.papel + ".", true);
      return;
    }
    $("tela-login").hidden = true;
    $("abas").hidden = false;
    $("filtro-grupo").hidden = false;
    // a tela inicial pode vir no endereço (ex.: /app/painel/#risco)
    const inicial = TELAS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "geral";
    if (!Object.keys(estado.nomes).length) {
      try { await carregarConteudo(); } catch (erro) { mostrarErro(erro); }
    }
    irPara(inicial);
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
    await iniciar();
  }

  async function encerrarSessao() {
    try { await TIA.sair(); } catch (erro) { mostrarErro(erro); }
    TIA.mostrarSessao({ autenticacao: "ligada", usuario: null });
    mostrarLogin("Você saiu.");
  }

  // --- início ---

  async function carregarConteudo() {
    const ementa = await chamar("GET", "/conteudo/ementa", null, "Carregando a ementa…");
    const perfis = await chamar("GET", "/conteudo/perfis", null, "Carregando os perfis…");
    for (const c of ementa) {
      estado.nomes[c.id] = c.nome;
      $("filtro-competencia").append(el("option", { value: c.id, texto: c.nome }));
    }
    const select = $("campo-perfil");
    for (const p of perfis) {
      estado.perfis[p.id] = p.nome;
      select.append(el("option", { value: p.id, texto: "Perfil " + p.nome }));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("erro-fechar").addEventListener("click", esconderErro);
    document.querySelectorAll(".aba").forEach((aba) => aba.addEventListener("click", () => irPara(aba.dataset.tela)));
    $("campo-perfil").addEventListener("change", () => {
      if (["geral", "risco", "competencias"].includes(estado.tela)) AO_ABRIR[estado.tela]().catch(mostrarErro);
    });
    $("atualizar-geral").addEventListener("click", () => carregarGeral().catch(mostrarErro));
    $("gerar-narrativa").addEventListener("click", gerarNarrativa);
    $("imprimir").addEventListener("click", () => window.print());
    $("atualizar-risco").addEventListener("click", () => carregarRisco().catch(mostrarErro));
    $("filtro-motivo").addEventListener("change", mostrarRisco);
    $("atualizar-competencias").addEventListener("click", () => carregarCompetencias().catch(mostrarErro));
    $("form-revisao").addEventListener("submit", (e) => {
      e.preventDefault();
      estado.paginaRevisao = 1;
      carregarRevisao().catch(mostrarErro);
    });
    $("form-auditoria").addEventListener("submit", (e) => {
      e.preventDefault();
      estado.paginaAuditoria = 1;
      carregarAuditoria().catch(mostrarErro);
    });
    window.addEventListener("unhandledrejection", (e) => { e.preventDefault(); mostrarErro(e.reason); });
    $("revisao-resumo").setAttribute("tabindex", "-1");
    TIA.configurar({ aoExigirLogin: () => mostrarLogin("Sua sessão terminou. Entre de novo.") });
    $("form-login").addEventListener("submit", entrarComSenha);
    TIA.ligarTrocaDeSenha(iniciar);
    $("sair").addEventListener("click", encerrarSessao);
    iniciar().catch(mostrarErro);
  });
})();
