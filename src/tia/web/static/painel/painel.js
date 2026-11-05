/*
 * Painel do docente/instituição do TIA (EAP 1.4.5): JavaScript puro, sem build.
 *
 * Redesenho de 01/11/2026 (docs/design/prototipo_redesign/): menu lateral com
 * Visão geral (4 números, alertas por aluno e tabela de alunos com filtro de
 * nível; COM código, abertura auditada), Revisar textos (fila e texto do tutor;
 * aprovar ou vetar com correção obrigatória, R12; o contador do menu é só um
 * número, sem código e sem auditoria) e Relatório da turma (resumo escrito pela
 * IA local, indicadores do Agente 3 e desempenho por grupo; só agregados).
 * Competências (barras em SVG) e Auditoria (R11) continuam como itens
 * secundários. Exportação em CSV pela API e impressão pelo navegador.
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
  const COR_ALERTA_TURMA = {
    desempenho_em_queda: "alerta--grave", competencia_com_erro_alto: "alerta--grave",
    conclusao_sem_dominio: "alerta--atencao", inatividade: "alerta--neutro",
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
    alunos: null,       // última ListaAlunos (o filtro de nível é feito aqui)
    nivel: "",          // perfil escolhido nos botões da tabela de alunos ("" = todos)
    revisao: null,      // última ListaRevisao
    selecionado: null,  // texto aberto na revisão ("tipo-id")
    grupos: [],         // [nome do perfil, RelatorioTurma do perfil] para "Desempenho por grupo"
    inatividadeDias: null, // INATIVIDADE_DIAS, dos critérios da consulta de risco (visão geral)
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

  // menu lateral: Visão geral, Revisar textos e Relatório da turma (prévia de 01/11/2026);
  // Competências e Auditoria continuam como itens secundários
  const TELAS = ["geral", "revisao", "relatorio", "competencias", "auditoria"];
  const AO_ABRIR = {
    geral: carregarVisaoGeral,
    revisao: carregarRevisao,
    relatorio: carregarRelatorio,
    competencias: carregarCompetencias,
    auditoria: carregarAuditoria,
  };
  // endereços antigos (/app/painel/#risco) continuam abrindo a tela certa
  const TELA_ANTIGA = { risco: "geral" };
  // o filtro de grupo só vale para as visões agregadas
  const COM_GRUPO = ["relatorio", "competencias"];

  function irPara(tela) {
    estado.tela = tela;
    try { history.replaceState(null, "", "#" + tela); } catch (_) { /* sem histórico: segue */ }
    for (const nomeTela of TELAS) $("tela-" + nomeTela).hidden = nomeTela !== tela;
    $("filtro-grupo").hidden = !COM_GRUPO.includes(tela);
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

  async function carregarRelatorio() {
    $("exportar-csv").setAttribute("href", comPerfil("/painel/exportar/indicadores.csv"));
    const r = await chamar("GET", comPerfil("/relatorio/turma?narrativa=false"), null, "Calculando os indicadores…");
    // desempenho por grupo: o mesmo relatório agregado em cada perfil (a API já oculta grupo pequeno)
    estado.grupos = [];
    for (const [id, nomePerfil] of Object.entries(estado.perfis)) {
      const g = await chamar("GET", "/relatorio/turma?narrativa=false&perfil_id=" + encodeURIComponent(id), null,
        "Calculando o perfil " + nomePerfil + "…");
      estado.grupos.push([nomePerfil, g]);
    }
    mostrarRelatorio(r);
    mostrarNarrativa(null);
  }

  function decimal(valor) { return String(valor).replace(".", ","); }

  function mostrarNumerosRelatorio(r) {
    const e = r.engajamento;
    $("relatorio-numeros").replaceChildren(
      numero("Progresso médio na trilha", fracaoTexto(r.progresso_medio), "etapas concluídas, média dos alunos",
        "numero--progresso"),
      numero("Alunos com trilha", r.alunos_com_trilha.texto, "de " + r.alunos.texto + " alunos no grupo"),
      numero("Sessões por aluno", decimal(e.media_sessoes), "média; " + decimal(e.media_perguntas_dialogo) +
        " pergunta(s) ao tutor por aluno"),
      numero("Alunos inativos", e.inativos.texto, estado.inatividadeDias ? "sem atividade há " +
        estado.inatividadeDias + " dias ou mais" : "pelo critério de inatividade do sistema",
        "numero--alerta"));
  }

  // progresso médio de cada perfil; grupo abaixo do mínimo aparece só como oculto (com cadeado)
  function mostrarGrupos(minGrupo) {
    $("grupos-regra").textContent = "Progresso médio na trilha em cada perfil. Grupos com menos de " + minGrupo +
      " alunos ficam ocultos para proteger a privacidade.";
    const visiveis = estado.grupos.filter(([, g]) => !g.suprimido);
    const ocultos = estado.grupos.filter(([, g]) => g.suprimido);
    $("relatorio-grupos").replaceChildren(...[
      visiveis.length ? el("ul", { classe: "grupos" }, visiveis.map(([nomePerfil, g]) => {
        const pct = g.progresso_medio === null ? 0 : Math.round(g.progresso_medio * 100);
        const rotulo = nomePerfil + " (" + g.alunos.texto + " alunos)";
        return el("li", { classe: "grupo" },
          el("div", { classe: "grupo__linha" }, el("span", { classe: "grupo__nome", texto: rotulo }),
            el("span", { classe: "grupo__valor", texto: fracaoTexto(g.progresso_medio) + " de progresso" })),
          el("div", { classe: "barra-grupo", role: "progressbar", "aria-label": rotulo, "aria-valuemin": "0",
            "aria-valuemax": "100", "aria-valuenow": String(pct) },
          el("span", { classe: "barra-grupo__valor", "data-pct": String(pct) })));
      })) : null,
      ...ocultos.map(([nomePerfil, g]) => el("p", { classe: "grupo-oculto" },
        svg("svg", { classe: "icone", viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" },
          svg("rect", { x: 5, y: 11, width: 14, height: 9, rx: 2 }), svg("path", { d: "M8 11V8a4 4 0 0 1 8 0v3" })),
        nomePerfil + " (" + g.alunos.texto + " alunos): oculto por ter menos de " + g.min_grupo + " alunos.")),
      estado.grupos.length ? null : el("p", { texto: "Nenhum perfil cadastrado." }),
    ].filter(Boolean));
    // largura da barra pela propriedade de estilo (a CSP não permite atributo style escrito como texto)
    document.querySelectorAll(".barra-grupo__valor").forEach((b) => { b.style.width = b.dataset.pct + "%"; });
  }

  function mostrarRelatorio(r) {
    $("relatorio-grupo").textContent = descricaoGrupo(r.alunos, r.min_grupo) + " Gerado em " + dataHora(r.gerado_em) + ".";
    mostrarGrupos(r.min_grupo);
    const area = $("relatorio-indicadores");
    if (r.suprimido) {
      const aviso = "Este grupo tem " + r.alunos.texto +
        " alunos: nenhum indicador é exibido, para que nenhum aluno possa ser identificado (LGPD, R08).";
      $("relatorio-numeros").replaceChildren(el("li", { classe: "aviso aviso--alerta", texto: aviso }));
      area.replaceChildren(el("p", { classe: "aviso aviso--alerta", texto: aviso }));
      $("relatorio-alertas").replaceChildren(el("p", { texto: "Sem alertas exibidos para grupos abaixo do mínimo." }));
      return;
    }
    mostrarNumerosRelatorio(r);

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
    $("relatorio-alertas").replaceChildren(r.alertas.length ? el("ul", { classe: "alertas alertas--turma" },
      r.alertas.map((a) => el("li", { classe: "alerta " + (COR_ALERTA_TURMA[a.tipo] || "") },
        el("span", { classe: "alerta__titulo", texto: ALERTA_TURMA[a.tipo] || a.tipo }),
        el("span", { classe: "alerta__detalhe", texto: a.descricao + " Alunos: " + a.alunos.texto + "." }))))
      : el("p", { texto: "Nenhum alerta." }));
  }

  function mostrarNarrativa(narrativa) {
    const area = $("relatorio-narrativa");
    $("gerar-narrativa").textContent = narrativa ? "Gerar de novo (IA local)" : "Gerar resumo (IA local)";
    if (!narrativa) {
      area.replaceChildren(el("p", { classe: "dica",
        texto: "Parágrafo escrito pela IA local a partir dos indicadores abaixo, só quando você pedir (pode levar " +
          "mais de um minuto)." }));
      return;
    }
    area.replaceChildren(el("p", { classe: "resumo-turma__texto", texto: narrativa.texto }),
      el("p", { classe: "origem" }, "Origem: " + narrativa.origem + " — " + (ORIGEM_NARRATIVA[narrativa.origem] || "") +
        (narrativa.falha_llm ? " Motivo: " + (FALHA[narrativa.falha_llm] || narrativa.falha_llm) + "." : "")));
  }

  async function gerarNarrativa() {
    try {
      const r = await chamar("GET", comPerfil("/relatorio/turma?narrativa=true"), null,
        "A IA local está escrevendo o resumo…");
      mostrarRelatorio(r);
      mostrarNarrativa(r.narrativa);
    } catch (erro) { mostrarErro(erro); }
  }

  // --- visão geral: números, alertas e alunos (COM código; abertura auditada) ---

  async function carregarVisaoGeral() {
    // as duas consultas com código gravam consulta_painel; o relatório (sem código) grava relatorio_turma
    estado.risco = await chamar("GET", "/painel/alunos-em-risco", null, "Procurando alunos em risco…");
    estado.alunos = await chamar("GET", "/painel/alunos", null, "Carregando os alunos…");
    const turma = await chamar("GET", "/relatorio/turma?narrativa=false", null, "Calculando os indicadores…");
    const contagem = await atualizarContador();
    mostrarNumeros(turma, contagem);
    mostrarAlertas();
    mostrarAlunos();
    $("geral-auditoria").textContent = "Registros desta abertura: nº " + estado.risco.auditoria_id + " e nº " +
      estado.alunos.auditoria_id + " (" + dataHora(estado.alunos.gerado_em) + ").";
  }

  function numero(rotulo, valor, detalhe, classe, aoClicar) {
    const conteudo = [el("span", { classe: "numero__rotulo", texto: rotulo }),
      // "menos de 5" e "oculto" (grupo mínimo) em corpo menor que um número
      el("span", { classe: "numero__valor" + (/[a-z]/i.test(valor) ? " numero__valor--texto" : ""), texto: valor }),
      detalhe ? el("span", { classe: "numero__detalhe", texto: detalhe }) : null];
    return el("li", { classe: "numero " + (classe || "") }, aoClicar
      ? el("button", { type: "button", classe: "numero__botao", onclick: aoClicar }, ...conteudo) : conteudo);
  }

  function mostrarNumeros(turma, contagem) {
    const total = estado.alunos.alunos.length;
    const inativos = estado.risco.alunos.filter((a) => a.motivos.some((m) => m.tipo === "inatividade")).length;
    // progresso médio: o indicador 1 do Agente 3 (oculto se o grupo estiver abaixo do mínimo)
    const progresso = turma.suprimido ? "oculto" : fracaoTexto(turma.progresso_medio);
    $("geral-numeros").replaceChildren(
      numero("Alunos ativos", String(total - inativos), "de " + total + "; inativo: sem atividade há " +
        estado.risco.criterios.inatividade_dias + " dias ou mais"),
      numero("Precisam de atenção", String(estado.risco.alunos.length), "com pelo menos um alerta",
        "numero--alerta"),
      numero("Progresso médio na trilha", progresso, turma.suprimido ? "grupo com menos de " + turma.min_grupo +
        " alunos" : "etapas concluídas, média da turma", "numero--progresso"),
      numero("Textos para revisar", contagem === null ? "—" : String(contagem), "escritos pela IA local",
        "numero--aviso", () => irPara("revisao")));
  }

  // um cartão por motivo; a cor acompanha a gravidade (o texto diz o motivo: nada depende só de cor)
  const COR_MOTIVO = {
    desempenho_em_queda: "alerta--grave", desempenho_baixo: "alerta--grave",
    conclusao_sem_dominio: "alerta--atencao", inatividade: "alerta--neutro",
  };
  const ORDEM_GRAVIDADE = ["desempenho_em_queda", "desempenho_baixo", "conclusao_sem_dominio", "inatividade"];

  function mostrarAlertas() {
    const r = estado.risco;
    if (!r) return;
    const c = r.criterios;
    estado.inatividadeDias = c.inatividade_dias;
    $("risco-criterios").textContent = "Sem atividade há " + c.inatividade_dias +
      " dias ou mais (quem concluiu a trilha não entra); queda de " + Math.round(c.queda_pontos * 100) +
      " pontos ou mais no acerto recente; acerto abaixo de " + porcento(c.desempenho_baixo) + " com pelo menos " +
      c.min_respostas + " respostas; questões de uma competência terminadas sem domínio (avança só com acerto de " +
      porcento(c.acerto_min_avanco) + " ou mais). Avaliados: " + r.alunos_avaliados + " alunos.";
    const filtro = $("filtro-motivo").value;
    // um cartão por aluno (a API já ordena: mais motivos primeiro), com a cor do motivo mais grave
    const alunos = r.alunos.filter((a) => !filtro || a.motivos.some((m) => m.tipo === filtro));
    $("geral-alertas").replaceChildren(...(alunos.length ? alunos.map((a) => {
      const cor = ORDEM_GRAVIDADE.find((tipo) => a.motivos.some((m) => m.tipo === tipo));
      return el("li", { classe: "alerta " + (COR_MOTIVO[cor] || "") },
        el("span", { classe: "alerta__aluno" }, el("code", { texto: a.aluno_id })),
        ...a.motivos.flatMap((m) => [el("span", { classe: "alerta__titulo", texto: MOTIVO[m.tipo] || m.tipo }),
          el("span", { classe: "alerta__detalhe", texto: m.descricao })]),
        el("button", { type: "button", classe: "botao botao--link acao nao-imprimir", texto: "Ver auditoria",
          "aria-label": "Ver auditoria do aluno " + a.aluno_id, onclick: () => auditoriaDoAluno(a.aluno_id) }));
    }) : [el("li", { classe: "aviso", texto: filtro ? "Nenhum aluno com este motivo." : "Nenhum aluno em risco." })]));
  }

  // situação de cada aluno na tabela (uma só, a mais urgente; regras dos alertas)
  const SITUACAO_ALUNO = {
    no_ritmo: ["No ritmo", "chip--ok"],
    trilha_concluida: ["Trilha concluída", "chip--ok"],
    desempenho_em_queda: ["Queda", "chip--alerta"],
    desempenho_baixo: ["Desempenho baixo", "chip--alerta"],
    conclusao_sem_dominio: ["Com ressalvas", "chip--atencao"],
    inatividade: ["Inativo", "chip--atencao"],
    sem_trilha: ["Sem trilha", "chip--atencao"],
  };

  function botoesDeNivel() {
    const opcoes = [["", "Todos"]].concat(Object.entries(estado.perfis));
    $("filtro-nivel").replaceChildren(...opcoes.map(([id, nomePerfil]) => el("button", {
      type: "button", classe: "chip-filtro", texto: nomePerfil, "aria-pressed": String(id === estado.nivel),
      onclick: () => { estado.nivel = id; botoesDeNivel(); mostrarAlunos(); } })));
  }

  function mostrarAlunos() {
    if (!estado.alunos) return;
    botoesDeNivel();
    const alunos = estado.alunos.alunos.filter((a) => !estado.nivel || a.perfil_id === estado.nivel);
    $("geral-alunos").replaceChildren(alunos.length ? tabela("Alunos da turma",
      ["Aluno", "Competência atual", "Acerto", "Situação"],
      alunos.map((a) => {
        const [texto, classe] = SITUACAO_ALUNO[a.situacao] || [a.situacao, ""];
        return [el("code", { texto: a.aluno_id }),
          a.competencia_atual ? nome(a.competencia_atual) : "—",
          fracaoTexto(a.taxa_acerto),
          el("span", { classe: "chip " + classe, texto })];
      })) : el("p", { classe: "aviso", texto: "Nenhum aluno neste nível." }));
  }

  // contador do menu: só o número de textos a revisar (rota sem códigos, não auditada)
  async function atualizarContador() {
    try {
      const r = await chamar("GET", "/painel/revisao/contagem?origem=LLM", null, "Contando os textos a revisar…");
      $("contador-revisao").textContent = String(r.a_revisar);
      $("contador-revisao").hidden = !r.a_revisar;
      $("contador-revisao").setAttribute("aria-label", r.a_revisar + " a revisar");
      return r.a_revisar;
    } catch (erro) {
      $("contador-revisao").hidden = true;
      return null;
    }
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

  // --- revisar textos (R12): feedback das questões e respostas do diálogo ---

  // rota do veto de cada tipo (as duas já existiam no Tutor; vetada=false numa resposta sem veto = aprovação)
  const ROTA_VETO = { dialogo: "/tutor/dialogo/{id}/veto", feedback: "/tutor/feedback/{id}/veto" };
  const TIPO_TEXTO = { dialogo: "Resposta a pergunta", feedback: "Explicação de questão" };
  const TITULO_FILA = { a_revisar: "Aguardando revisão", aprovadas: "Aprovados", vetadas: "Vetados",
    todas: "Todos os textos" };

  function chaveDe(item) { return item.tipo + "-" + item.id; }

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
    estado.revisao = r;
    const f = r.feedbacks_por_origem;
    $("revisao-resumo").replaceChildren(el("div", { classe: "resumo-revisao" },
      el("div", { classe: "resumo-revisao__tipos" },
        resumoTipo("Feedback das questões", r.feedback), resumoTipo("Respostas do diálogo", r.dialogo)),
      el("p", { classe: "dica", texto: "Origem de todos os feedbacks de questões: IA local " + f.LLM +
        " · barrados pela verificação " + f.guarda + " · texto fixo " + f.fallback + "." +
        (r.feedbacks_sem_texto ? " " + r.feedbacks_sem_texto + " resposta(s) antiga(s) sem texto gravado " +
          "(não revisáveis)." : "") }),
      el("p", { classe: "dica", texto: "Consulta registrada na auditoria (registro nº " + r.auditoria_id + ")." })));
    $("titulo-fila").textContent = (TITULO_FILA[$("filtro-situacao").value] || "Textos") + " (" + r.total + ")";
    $("revisao-total").textContent = r.total ? "Do mais recente para o mais antigo; " + r.por_pagina +
      " por página." : "";
    // mantém o texto aberto se ele ainda está na lista; senão abre o primeiro
    if (!r.itens.some((i) => chaveDe(i) === estado.selecionado)) {
      estado.selecionado = r.itens.length ? chaveDe(r.itens[0]) : null;
    }
    mostrarFila();
    mostrarTextoSelecionado();
    paginacao($("revisao-paginas"), r.pagina, r.total, r.por_pagina, (pagina) => {
      estado.paginaRevisao = pagina;
      estado.selecionado = null;
      carregarRevisao().catch(mostrarErro);
    });
  }

  function mostrarFila() {
    const r = estado.revisao;
    $("revisao-lista").replaceChildren(...(r.itens.length ? r.itens.map((item) => {
      const atual = chaveDe(item) === estado.selecionado;
      return el("li", {}, el("button", { type: "button", classe: "fila__item",
        "aria-current": atual ? "true" : null,
        "aria-label": (TIPO_TEXTO[item.tipo] || item.tipo) + " do aluno " + item.aluno_id + ", " +
          nome(item.competencia_id) + (item.situacao === "a_revisar" ? "" : ", " + SITUACAO[item.situacao]),
        onclick: () => {
          estado.selecionado = chaveDe(item);
          mostrarFila();
          mostrarTextoSelecionado();
          $("revisao-detalhe").focus();
        } },
      el("span", { classe: "fila__aluno" }, el("code", { texto: item.aluno_id })),
      el("span", { classe: "fila__competencia", texto: nome(item.competencia_id) }),
      el("span", { classe: "fila__tipo" }, (TIPO_TEXTO[item.tipo] || item.tipo) + " · " + dataHora(item.ts),
        item.situacao === "a_revisar" ? null : el("span", {
          classe: "chip " + (item.vetada ? "chip--alerta" : "chip--ok"), texto: SITUACAO[item.situacao] }))));
    }) : [el("li", { classe: "aviso", texto: "Nenhum texto com este filtro." })]));
  }

  function bloco(rotulo, ...conteudo) {
    return el("div", { classe: "bloco" }, el("span", { classe: "bloco__rotulo", texto: rotulo }), ...conteudo);
  }

  function mostrarTextoSelecionado() {
    const area = $("revisao-detalhe");
    const item = estado.revisao && estado.revisao.itens.find((i) => chaveDe(i) === estado.selecionado);
    if (!item) {
      area.replaceChildren(el("p", { classe: "dica", texto: "Nenhum texto para revisar com este filtro." }));
      return;
    }
    const ehFeedback = item.tipo === "feedback";
    const titulo = "titulo-texto-" + chaveDe(item);
    const campo = "correcao-" + chaveDe(item);
    const textoTutor = el("div", { classe: "texto-tutor" + (item.vetada ? " texto-tutor--vetado" : "") },
      el("span", { classe: "bloco__rotulo", texto: item.vetada ? "Texto original do tutor (vetado)"
        : "Texto escrito pelo tutor" }),
      el("p", { classe: "texto-tutor__texto" + (item.vetada ? " riscado" : ""), texto: item.resposta || "" }),
      el("details", { classe: "fonte" }, el("summary", { texto: "Ver fonte" }),
        item.fontes.length ? el("ul", {}, item.fontes.map((fonte) => el("li", {}, "Material: ",
          el("code", { texto: fonte })))) : el("p", { texto: ehFeedback ? "Sem fonte do material: texto do próprio item."
          : "Sem fonte citada." }),
        el("p", { classe: "origem", texto: "Origem: " + item.origem + " — " + (ORIGEM[item.origem] || "") +
          (item.falha_llm ? " Motivo: " + (FALHA[item.falha_llm] || item.falha_llm) + "." : "") })));

    const acoes = el("div", { classe: "linha-botoes texto-revisao__acoes nao-imprimir" });
    const vetar = (rotulo) => el("button", { type: "button", classe: "botao botao--vetar acao", texto: rotulo,
      "aria-describedby": titulo, onclick: () => {
        const correcao = $(campo).value.trim();
        if (!correcao) {
          mostrarErro(new ErroApi("Escreva a correção que o aluno vai ver: ela é obrigatória para vetar.", 0));
          $(campo).focus();
          return;
        }
        revisar(item, { vetada: true, correcao_docente: correcao }, "Gravando o veto…");
      } });
    if (item.vetada) {
      acoes.append(el("button", { type: "button", classe: "botao botao--secundario acao",
        texto: "Retirar veto (aprovar a original)", "aria-describedby": titulo,
        onclick: () => revisar(item, { vetada: false }, "Retirando o veto…") }), vetar("Salvar correção"));
    } else {
      acoes.append(vetar("Vetar com correção"));
      if (item.situacao !== "aprovada") {
        acoes.append(el("button", { type: "button", classe: "botao acao", texto: "Aprovar", "aria-describedby": titulo,
          onclick: () => revisar(item, { vetada: false }, "Aprovando…") }));
      }
    }

    // replaceChildren nativo escreveria "null": os blocos ausentes saem antes
    area.replaceChildren(...[
      el("div", { classe: "texto-revisao__cabeca" },
        el("h2", { id: titulo }, el("code", { texto: item.aluno_id }), " · " + nome(item.competencia_id)),
        el("span", { classe: "dica" }, (TIPO_TEXTO[item.tipo] || item.tipo) + " nº " + item.id + " · ",
          el("span", { classe: "chip " + (item.vetada ? "chip--alerta" : item.situacao === "aprovada" ? "chip--ok"
            : "chip--atencao"), texto: SITUACAO[item.situacao] || item.situacao }))),
      bloco(ehFeedback ? "Questão" + (item.item_id ? " " + item.item_id + (item.nivel ? " (nível " + item.nivel +
        ")" : "") : "") : "Pergunta do aluno", el("p", { classe: "bloco__texto", texto: item.pergunta || "" })),
      ehFeedback && item.veredito ? bloco("Veredito automático", el("p", {
        classe: "bloco__texto veredito-texto " + (item.acertou ? "veredito--acerto" : "veredito--erro"),
        texto: item.veredito })) : null,
      textoTutor,
      item.explicacao_descartada ? el("details", { classe: "descartado" },
        el("summary", { texto: "Texto da IA barrado pela verificação (o aluno não viu)" }),
        el("p", { classe: "bloco__texto", texto: item.explicacao_descartada }),
        item.motivo_descarte ? el("p", { classe: "origem", texto: "Motivo do descarte: " + item.motivo_descarte })
          : null) : null,
      item.vetada ? bloco("Correção atual (o aluno vê esta)", el("p", { classe: "correcao",
        texto: item.correcao_docente || "" })) : null,
      el("div", { classe: "campo-correcao nao-imprimir" },
        el("label", { for: campo, texto: item.vetada ? "Nova correção (obrigatória para salvar)"
          : "Correção (obrigatória para vetar)" }),
        el("textarea", { id: campo, rows: 4, maxlength: 2000,
          placeholder: "Escreva aqui o texto correto que o aluno deve ver." })),
      acoes].filter(Boolean));
    if (item.correcao_docente) $(campo).value = item.correcao_docente;
  }

  // única escrita do painel: as rotas de veto do Tutor (cada uso grava veto_docente na auditoria)
  async function revisar(item, corpo, texto) {
    try {
      await chamar("PATCH", ROTA_VETO[item.tipo].replace("{id}", encodeURIComponent(item.id)), corpo, texto);
      await carregarRevisao();
      await atualizarContador();
      $("revisao-detalhe").focus();
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
    $("login-outro-papel").hidden = !semFormulario;
    TIA.esconderTrocaDeSenha();
    $("login-mensagem").textContent = mensagem || "";
    $("login-mensagem").hidden = !mensagem;
    if (semFormulario) $("sair-outro-papel").focus();
    else $("campo-login").focus();
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
      mostrarLogin(TIA.mensagemOutroPapel(situacao.usuario.papel, "docente"), true);
      return;
    }
    $("tela-login").hidden = true;
    $("abas").hidden = false;
    // a tela inicial pode vir no endereço (ex.: /app/painel/#revisao)
    const pedida = TELA_ANTIGA[location.hash.slice(1)] || location.hash.slice(1);
    const inicial = TELAS.includes(pedida) ? pedida : "geral";
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
    try { await TIA.sair(); } catch (erro) { mostrarErro(erro); return; } // não saiu: continua onde estava
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
      if (COM_GRUPO.includes(estado.tela)) AO_ABRIR[estado.tela]().catch(mostrarErro);
    });
    $("atualizar-relatorio").addEventListener("click", () => carregarRelatorio().catch(mostrarErro));
    $("gerar-narrativa").addEventListener("click", gerarNarrativa);
    // a impressão leva todos os indicadores (o detalhe recolhido abre antes)
    $("imprimir").addEventListener("click", () => { $("relatorio-detalhes").open = true; window.print(); });
    $("atualizar-geral").addEventListener("click", () => carregarVisaoGeral().catch(mostrarErro));
    $("filtro-motivo").addEventListener("change", mostrarAlertas);
    $("atualizar-competencias").addEventListener("click", () => carregarCompetencias().catch(mostrarErro));
    $("form-revisao").addEventListener("submit", (e) => {
      e.preventDefault();
      estado.paginaRevisao = 1;
      estado.selecionado = null;
      carregarRevisao().catch(mostrarErro);
    });
    $("form-auditoria").addEventListener("submit", (e) => {
      e.preventDefault();
      estado.paginaAuditoria = 1;
      carregarAuditoria().catch(mostrarErro);
    });
    window.addEventListener("unhandledrejection", (e) => { e.preventDefault(); mostrarErro(e.reason); });
    $("revisao-detalhe").setAttribute("tabindex", "-1");
    TIA.configurar({ aoExigirLogin: () => mostrarLogin("Sua sessão terminou. Entre de novo.") });
    $("form-login").addEventListener("submit", entrarComSenha);
    TIA.ligarTrocaDeSenha(iniciar);
    $("sair").addEventListener("click", encerrarSessao);
    $("sair-outro-papel").addEventListener("click", encerrarSessao);
    iniciar().catch(mostrarErro);
  });
})();
