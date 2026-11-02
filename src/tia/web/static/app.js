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
  const FALHA = { timeout: "a IA demorou demais (timeout)",
    copia_do_prompt: "a IA repetiu o pedido em vez de justificar" };

  const estado = {
    aluno: null,
    autenticado: false,  // login ligado e aluno logado: o código vem da sessão
    etapas: [],          // EstadoAluno.etapas (nomes das competências)
    sessaoId: null,      // sessão do Tutor em andamento
    pergunta: null,      // pergunta em aberto
    eventoPendente: null, // evento que falhou: reenviado com o mesmo evento_id (idempotente)
    nomes: {},           // tópico -> nome (GET /conteudo/ementa), para o diagnóstico antes da matrícula
    diagnostico: null,   // SituacaoDiagnostico em andamento no primeiro acesso
    visita: { respostas: 0, acertos: 0 } // contados só nesta página ("Nesta visita"); a API não expõe a sequência
  };
  const PERFIL = { iniciante: "Iniciante", intermediario: "Intermediário" };
  const TRILHA = { dev: "Desenvolvimento de Software", defesa_cibernetica: "Defesa Cibernética" };

  // utilidades compartilhadas com o painel do docente (comum.js): el, chamar, erros
  const { $, el, svg, tempo, porcento, ErroApi, chamar, mostrarErro, esconderErro } = window.TIA;
  TIA.configurar({ esperaMaximaMs: ESPERA_MAXIMA_MS, quem: "O tutor", textoEspera: "Aguardando o tutor…" });

  function nomeCompetencia(id) {
    const etapa = estado.etapas.find((e) => e.competencia_id === id);
    return etapa ? etapa.nome : (estado.nomes[id] || id);
  }

  function novoEventoId() {
    const aleatorio = Math.random().toString(36).slice(2, 10);
    return "web-" + Date.now().toString(36) + "-" + aleatorio;
  }

  // --- navegação ---

  // a pergunta livre ao tutor (antes uma tela própria, de diálogo) fica dentro de Estudar
  const TELAS = ["login", "entrada", "inicio", "trilha", "estudo", "relatorio"];
  const AO_ABRIR = {
    inicio: carregarInicio,
    trilha: carregarTrilha,
    estudo: carregarEstudar,
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
    estado.visita = { respostas: 0, acertos: 0 };
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
      if ($("mostrar-senha").getAttribute("aria-pressed") === "true") $("mostrar-senha").click();
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
      irPara("inicio");
    } catch (erro) {
      if (erro.status === 404) {
        irPara("entrada");
        $("abas").hidden = true;
        $("form-entrada").hidden = estado.autenticado;
        await mostrarPrimeiroAcesso();
      } else if (erro.status !== 401) {
        definirAluno(null);
        mostrarErro(erro);
      }
    }
  }

  // --- a2) primeiro acesso em etapas: Trilha > Tempo > Confirmar (conversa) > Diagnóstico > trilha ---
  // Cada cartão ou botão envia um TEXTO para /onboarding/mensagem, como se o aluno escrevesse:
  // quem entende e decide é o servidor (regras do onboarding), e a matrícula exige o "sim" explícito.

  const PASSOS_ACESSO = ["senha", "trilha", "tempo", "confirmar", "diagnostico"];
  const PASSO_DA_PERGUNTA = { trilha: "trilha", horas: "tempo", objetivo: "tempo", confirmacao: "confirmar",
    fim: "diagnostico" };
  // descrições das trilhas: as mesmas do tutor (EXPLICACAO_TRILHAS em planejador/onboarding.py, validadas)
  const OPCOES_TRILHA = [
    { texto: "Desenvolvimento de Software", titulo: TRILHA.dev,
      descricao: "Algoritmos, arquitetura, testes, bancos de dados, DevOps e APIs, para quem quer construir sistemas." },
    { texto: "Defesa Cibernética", titulo: TRILHA.defesa_cibernetica,
      descricao: "Redes, criptografia, segurança de aplicações, ataque e defesa em laboratório e nuvem, para quem " +
        "quer proteger e analisar sistemas." },
  ];
  const NOME_DIA = { seg: "segunda", ter: "terça", qua: "quarta", qui: "quinta", sex: "sexta", sab: "sábado",
    dom: "domingo" };
  const TITULO_PASSO = {
    trilha: ["Qual trilha você quer seguir?", "As duas começam pela mesma base de Python. Escolha a que mais combina " +
      "com seu objetivo agora."],
    horas: ["Quanto tempo você tem para estudar?", "Com isso, o Planejador distribui as etapas pelas semanas."],
    objetivo: ["Qual é o seu objetivo?", "Opcional: ajuda o tutor a entender o que você busca."],
    confirmacao: ["Confira antes de começar", "Seu plano só será criado depois que você confirmar."],
    fim: ["Diagnóstico rápido", "Cerca de 15 minutos. Com ele, o Planejador escolhe seu perfil e tira da trilha " +
      "o que você já domina."],
  };

  function marcarPassoAcesso(pergunta) {
    const atual = PASSOS_ACESSO.indexOf(PASSO_DA_PERGUNTA[pergunta] || "trilha");
    $("acesso-etapas").querySelectorAll("li").forEach((li) => {
      const i = PASSOS_ACESSO.indexOf(li.dataset.passo);
      li.classList.toggle("etapas-acesso__item--feito", i < atual);
      li.classList.toggle("etapas-acesso__item--atual", i === atual);
      if (i === atual) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    const [titulo, sub] = TITULO_PASSO[pergunta] || TITULO_PASSO.trilha;
    $("titulo-primeiro-acesso").textContent = titulo;
    $("acesso-sub").textContent = sub;
  }

  function mostrarConversaAcesso(visivel) {
    $("onboarding-conversa").hidden = !visivel;
    $("titulo-onboarding").hidden = !visivel;
  }

  function falaNaConversa(papel, texto) {
    $("onboarding-conversa").append(papel === "aluno"
      ? el("li", { classe: "conversa__item" }, el("p", { classe: "conversa__pergunta", texto }))
      : el("li", { classe: "conversa__item" }, balaoDoTutor(el("p", { classe: "conversa__resposta", texto }))));
  }

  // escolhas da etapa e o campo livre: o que aparece depende da pergunta da vez
  function mostrarOpcoes(pergunta, dados) {
    marcarPassoAcesso(pergunta);
    // na confirmação, o resumo em lista substitui o mesmo resumo em texto do tutor
    mostrarConversaAcesso(!(pergunta === "confirmacao" && dados));
    const opcoes = $("acesso-opcoes");
    const form = $("form-onboarding");
    opcoes.replaceChildren();
    form.hidden = false;
    $("pular-onboarding").hidden = pergunta !== "objetivo";
    $("enviar-onboarding").classList.toggle("botao--secundario", pergunta === "confirmacao");
    const rotulo = { horas: "Horas por semana e dias de estudo", objetivo: "Seu objetivo",
      confirmacao: "Quer corrigir só um item? Escreva aqui" }[pergunta] || "Sua resposta";
    const dica = { horas: "Exemplo: 2h por dia, menos no fim de semana. Não escreva dados pessoais.",
      objetivo: "Exemplo: estágio, projeto final, certificação. Não escreva dados pessoais.",
      confirmacao: "Exemplo: não, são 6 horas por semana." }[pergunta] || "Responda do seu jeito. Não escreva dados pessoais.";
    $("rotulo-onboarding").textContent = rotulo;
    $("dica-onboarding").textContent = dica;
    $("enviar-onboarding").textContent = pergunta === "confirmacao" ? "Enviar correção" : "Continuar";

    if (pergunta === "trilha") {
      form.hidden = true;
      const escolha = el("form", { classe: "formulario", novalidate: true, onsubmit: (e) => {
        e.preventDefault();
        const marcada = e.currentTarget.querySelector("input[name=trilha-escolha]:checked");
        if (!marcada) { mostrarErro(new ErroApi("Escolha uma trilha antes de continuar.", 0)); return; }
        enviarFala(OPCOES_TRILHA[Number(marcada.value)].texto).catch(mostrarErro);
      } },
      el("fieldset", { classe: "escolhas" }, el("legend", { classe: "rotulo", texto: "Trilha" }),
        OPCOES_TRILHA.map((o, i) => el("label", { classe: "escolha" },
          el("input", { type: "radio", name: "trilha-escolha", value: i }),
          el("span", { classe: "escolha__marca", "aria-hidden": "true" }),
          el("span", { classe: "escolha__texto" },
            el("span", { classe: "escolha__titulo", texto: o.titulo }),
            el("span", { classe: "escolha__descricao", texto: o.descricao }))))),
      el("button", { type: "button", classe: "botao botao--link acao", texto: "Ainda não sei. Explique a diferença.",
        onclick: () => enviarFala("Ainda não sei, qual a diferença entre as duas?").catch(mostrarErro) }),
      el("div", { classe: "linha-botoes linha-botoes--fim" },
        el("button", { type: "submit", classe: "botao botao--grande acao", texto: "Continuar" })));
      opcoes.append(escolha);
      const primeira = escolha.querySelector("input");
      if (primeira) primeira.focus();
      return;
    }
    if (pergunta === "confirmacao" && dados) {
      const linha = (rotuloLinha, valor) => el("div", { classe: "resumo__linha" },
        el("dt", { texto: rotuloLinha }), el("dd", { texto: valor }));
      const nao = el("button", { type: "button", classe: "botao botao--secundario acao", texto: "Não, quero refazer",
        onclick: () => enviarFala("não").catch(mostrarErro) });
      const sim = el("button", { type: "button", classe: "botao botao--grande acao", texto: "Sim, está certo",
        onclick: () => enviarFala("sim").catch(mostrarErro) });
      opcoes.append(
        el("dl", { classe: "resumo" },
          linha("Trilha", TRILHA[dados.trilha] || dados.trilha || "—"),
          linha("Tempo por semana", dados.horas_semana ? dados.horas_semana + " horas" : "—"),
          dados.dias_disponiveis && dados.dias_disponiveis.length
            ? linha("Dias de estudo", dados.dias_disponiveis.map((d) => NOME_DIA[d] || d).join(", ")) : null,
          linha("Seu objetivo", dados.objetivo || "Não informado")),
        el("p", { classe: "cabeca__sub", texto: "As informações acima foram ditas por você. \"Não\" recomeça as " +
          "perguntas; para mudar só um item, escreva a correção abaixo." }),
        el("div", { classe: "linha-botoes linha-botoes--separadas" }, nao, sim));
      sim.focus();
      return;
    }
    $("campo-onboarding").focus();
  }

  async function carregarNomes() {
    if (Object.keys(estado.nomes).length) return;
    try {
      for (const c of await chamar("GET", "/conteudo/ementa", null, "Carregando…")) estado.nomes[c.id] = c.nome;
    } catch (erro) { if (erro.status !== 401 && erro.status !== 403) throw erro; }
  }

  async function mostrarPrimeiroAcesso() {
    $("primeiro-acesso").hidden = false;
    $("onboarding-conversa").replaceChildren();
    mostrarConversaAcesso(true);
    $("acesso-opcoes").replaceChildren();
    $("diagnostico-conteudo").replaceChildren();
    $("titulo-diagnostico").hidden = true;
    $("diagnostico-progresso").hidden = true;
    $("concluir-primeiro-acesso").hidden = true;
    $("form-onboarding").hidden = true;
    await carregarNomes();
    const situacao = await chamar("GET", rota("/aluno/{id}/primeiro-acesso"), null, "Buscando seu cadastro…");
    if (situacao.passo === "onboarding") {
      const inicio = await chamar("POST", rota("/aluno/{id}/onboarding/iniciar"), null, "Abrindo a conversa…");
      falaNaConversa("tutor", inicio.resposta);
      mostrarOpcoes(inicio.proxima_pergunta);
    } else {
      marcarPassoAcesso("fim");
      falaNaConversa("tutor", "Seu cadastro já foi feito: trilha " + (TRILHA[situacao.onboarding.trilha] || "") +
        ", " + situacao.onboarding.horas_semana + " h por semana.");
      if (situacao.passo === "concluir") mostrarFimDoDiagnostico(null);
      else await iniciarDiagnostico();
    }
  }

  async function enviarOnboarding(evento) {
    evento.preventDefault();
    const campo = $("campo-onboarding");
    const texto = campo.value.trim();
    if (!texto) { campo.focus(); return; }
    await enviarFala(texto);
  }

  // uma fala do aluno (escrita ou escolhida num cartão/botão) -> resposta do tutor e a próxima etapa
  async function enviarFala(texto) {
    const resposta = await chamar("POST", rota("/aluno/{id}/onboarding/mensagem"), { texto }, "O tutor está lendo…");
    $("onboarding-conversa").replaceChildren(); // só a última troca: as etapas mostram o resto
    falaNaConversa("aluno", texto);
    falaNaConversa("tutor", resposta.resposta);
    $("campo-onboarding").value = "";
    if (resposta.concluido) {
      $("form-onboarding").hidden = true;
      $("acesso-opcoes").replaceChildren();
      mostrarConversaAcesso(true);
      marcarPassoAcesso("fim");
      await iniciarDiagnostico();
    } else {
      mostrarOpcoes(resposta.proxima_pergunta, resposta.dados);
    }
  }

  async function iniciarDiagnostico() {
    $("titulo-diagnostico").hidden = false;
    $("diagnostico-progresso").hidden = false;
    const situacao = await chamar("POST", rota("/aluno/{id}/diagnostico/iniciar"), null, "Preparando o diagnóstico…");
    if (situacao.concluido) mostrarFimDoDiagnostico(situacao); else mostrarQuestaoDiagnostico(situacao);
  }

  function mostrarQuestaoDiagnostico(situacao) {
    estado.diagnostico = situacao;
    const p = situacao.pergunta;
    $("diagnostico-progresso").textContent = "Tópico " + situacao.topico_atual + " de " + situacao.total_topicos +
      " · " + nomeCompetencia(p.competencia_id) + " · nível " + p.nivel +
      (situacao.acertou === null ? "" : situacao.acertou ? " · você acertou a anterior" : "");
    const grupo = alternativas("alternativa-diagnostico", p.alternativas);
    const form = el("form", { classe: "questao questao--diagnostico", novalidate: true, onsubmit: responderDiagnostico },
      el("h4", { classe: "enunciado", id: "enunciado-diagnostico", texto: p.enunciado }),
      grupo,
      el("button", { type: "submit", classe: "botao botao--grande acao", texto: "Responder",
        disabled: TIA.estaOcupado() }));
    form.setAttribute("aria-labelledby", "enunciado-diagnostico");
    $("diagnostico-conteudo").replaceChildren(form);
    const primeira = form.querySelector("input");
    if (primeira) primeira.focus();
  }

  async function responderDiagnostico(evento) {
    evento.preventDefault();
    const marcada = evento.currentTarget.querySelector("input[name=alternativa-diagnostico]:checked");
    if (!marcada) {
      mostrarErro(new ErroApi("Escolha uma alternativa antes de responder.", 0));
      return;
    }
    const situacao = await chamar("POST", rota("/aluno/{id}/diagnostico/responder"),
      { item_id: estado.diagnostico.pergunta.item_id, indice_escolhido: Number(marcada.value) }, "Registrando…");
    if (situacao.concluido) mostrarFimDoDiagnostico(situacao); else mostrarQuestaoDiagnostico(situacao);
  }

  function mostrarFimDoDiagnostico(situacao) {
    estado.diagnostico = null;
    $("titulo-diagnostico").hidden = false;
    $("diagnostico-progresso").hidden = false;
    $("diagnostico-progresso").textContent = "Diagnóstico concluído" +
      (situacao ? " (" + situacao.total_topicos + " tópicos avaliados)." : ".");
    $("diagnostico-conteudo").replaceChildren(el("p", { classe: "aviso",
      texto: "Com o diagnóstico, o Planejador escolhe seu perfil e tira da trilha o que você já domina." }));
    $("concluir-primeiro-acesso").hidden = false;
    $("concluir-primeiro-acesso").focus();
  }

  async function concluirPrimeiroAcesso() {
    await chamar("POST", rota("/aluno/{id}/primeiro-acesso/concluir"), null,
      "O Planejador está montando sua trilha…");
    $("primeiro-acesso").hidden = true;
    $("abas").hidden = false;
    irPara("inicio");
  }

  function sair() {
    definirAluno(null);
    estado.diagnostico = null;
    $("primeiro-acesso").hidden = true;
    $("campo-aluno").value = "";
    irPara("entrada");
    $("campo-aluno").focus();
  }

  // --- peças visuais (redesenho): barra de progresso, ícones, grupos da trilha ---

  // barra com papel de progressbar; a largura vai pelo CSSOM (a CSP não aceita atributo style)
  function barra(valor, maximo, rotulo, classe) {
    const fracao = maximo > 0 ? Math.max(0, Math.min(1, valor / maximo)) : 0;
    const preenchida = el("span", { classe: "barra__valor" + (classe ? " " + classe : "") });
    preenchida.style.width = Math.round(fracao * 100) + "%";
    return el("div", { classe: "barra", role: "progressbar", "aria-valuenow": valor, "aria-valuemin": 0,
      "aria-valuemax": maximo, "aria-label": rotulo }, preenchida);
  }

  const ICONES = {
    feito: [["path", { d: "M5 12l5 5 9-10" }]],
    bloqueado: [["rect", { x: 5, y: 11, width: 14, height: 9, rx: 2 }], ["path", { d: "M8 11V8a4 4 0 0 1 8 0v3" }]],
  };

  function icone(nome) {
    return svg("svg", { class: "icone", viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" },
      ICONES[nome].map(([tag, atributos]) => svg(tag, atributos)));
  }

  // tópicos das trilhas têm prefixo (dev_, cib_); o resto é a base comum de Python
  function grupoDaEtapa(competenciaId) {
    if (/^dev_/.test(competenciaId)) return "Trilha " + TRILHA.dev;
    if (/^cib_/.test(competenciaId)) return "Trilha " + TRILHA.defesa_cibernetica;
    return "Base comum";
  }

  // marcador redondo de uma etapa: concluída (✓), atual (número) ou bloqueada (cadeado)
  function marcadorEtapa(situacao, numero) {
    const rotulo = { feito: "Concluída", atual: "Etapa atual", bloqueado: "Bloqueada" }[situacao];
    return el("span", { classe: "marcador marcador--" + situacao, role: "img", "aria-label": rotulo },
      situacao === "atual" ? el("span", { "aria-hidden": "true", texto: numero }) : icone(situacao));
  }

  function situacaoDaEtapa(etapa, atual) {
    return etapa.concluida ? "feito" : etapa.competencia_id === atual.competencia_atual ? "atual" : "bloqueado";
  }

  // --- início ---

  async function carregarInicio() {
    const atual = await chamar("GET", rota("/aluno/{id}/estado"), null, "Carregando…");
    estado.etapas = atual.etapas;
    let trilha = null;
    try { trilha = await chamar("GET", rota("/alunos/{id}/trilha"), null, "Carregando…"); }
    catch (erro) { if (erro.status !== 404) throw erro; }
    const proxima = await chamar("GET", rota("/aluno/{id}/proximo"), null, "Carregando…");

    const total = atual.etapas.length;
    const feitas = atual.etapas.filter((e) => e.concluida).length;
    const indiceAtual = atual.etapas.findIndex((e) => e.competencia_id === atual.competencia_atual);
    $("titulo-inicio").textContent = "Olá, " + estado.aluno;
    const nomeTrilha = trilha && trilha.trilha ? TRILHA[trilha.trilha] || trilha.trilha : null;
    $("inicio-situacao").textContent = atual.concluido ? "Você concluiu todas as etapas da sua trilha." :
      (nomeTrilha ? "Trilha " + nomeTrilha + ", " : "Você está na ") +
      (indiceAtual >= 0 ? "etapa " + (indiceAtual + 1) + " de " + total + "." : feitas + " de " + total + " etapas.");

    // cartão "continue de onde parou": a próxima atividade do orquestrador
    const continuar = $("inicio-continuar");
    if (proxima.acao === "concluido") {
      $("inicio-rotulo").textContent = "Trilha concluída";
      $("inicio-etapa").textContent = "Parabéns!";
      $("inicio-detalhe").textContent = "Você terminou todas as etapas. Veja seu relatório ou tire dúvidas com o tutor.";
      continuar.hidden = true;
    } else {
      const id = proxima.competencia_id || atual.competencia_atual;
      $("inicio-rotulo").textContent = proxima.acao === "continuar_sessao" ? "Continue de onde parou" :
        proxima.reforco ? "Revisão antes de seguir" : "Próxima etapa";
      $("inicio-etapa").textContent = id ? nomeCompetencia(id) : "Sua trilha";
      $("inicio-detalhe").textContent = proxima.acao === "continuar_sessao"
        ? (proxima.pergunta ? "Você tem uma questão em aberto nesta etapa." : proxima.motivo || "")
        : proxima.reforco ? "Antes de continuar, vamos revisar este pré-requisito, a partir do nível 1."
          : "As perguntas começam no nível 1 e ficam mais difíceis conforme você acerta.";
      continuar.hidden = false;
    }
    $("inicio-progresso").replaceChildren(el("div", { classe: "progresso-linha" },
      barra(feitas, total, "Etapas concluídas da trilha"),
      el("span", { classe: "progresso-linha__numero", texto: feitas + " de " + total + " etapas" })));

    // trilha resumida: até 5 etapas em volta da atual
    const inicio = Math.max(0, Math.min((indiceAtual >= 0 ? indiceAtual : feitas) - 2, total - 5));
    $("inicio-trilha").replaceChildren(...atual.etapas.slice(inicio, inicio + 5).map((etapa) => {
      const situacao = situacaoDaEtapa(etapa, atual);
      return el("li", { classe: "resumo-trilha__item resumo-trilha__item--" + situacao,
        "aria-current": situacao === "atual" ? "step" : null },
      marcadorEtapa(situacao, etapa.ordem),
      el("span", { classe: "resumo-trilha__nome", texto: etapa.nome }),
      el("span", { classe: "resumo-trilha__estado",
        texto: { feito: "Concluída", atual: "Em andamento", bloqueado: "Bloqueada" }[situacao] }));
    }));

    // próximos passos: avisos reais do orquestrador e do Planejador
    const passos = [];
    const decisao = atual.ultima_decisao;
    if (atual.reforco) {
      passos.push(["Sugestão do tutor", "Revisão de " + nomeCompetencia(atual.reforco.competencia_reforco),
        "Antes de seguir em " + nomeCompetencia(atual.reforco.competencia_original) + "."]);
    }
    if (decisao && decisao.aviso) passos.push(["Aviso do tutor", null, decisao.aviso]);
    if (trilha && trilha.cabe_no_prazo === false && trilha.opcoes_prazo) {
      passos.push(["Prazo", "A trilha não cabe no prazo", "Seriam " + trilha.opcoes_prazo.horas_semanais_necessarias +
        " h por semana. Fale com o docente."]);
    }
    const proximaEtapa = atual.etapas.find((e) => !e.concluida && e.competencia_id !== atual.competencia_atual);
    if (proximaEtapa && !atual.reforco) {
      passos.push(["Depois desta etapa", proximaEtapa.nome, "A próxima etapa é liberada quando você concluir a atual."]);
    }
    $("inicio-passos").replaceChildren(...passos.map(([rotulo, titulo, texto]) => el("div", { classe: "cartao cartao--mini" },
      el("p", { classe: "rotulo", texto: rotulo }),
      titulo ? el("p", { classe: "cartao__titulo", texto: titulo }) : null,
      el("p", { classe: "cartao__texto", texto }))));
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
    const partes = [];
    if (trilha) {
      if (trilha.trilha) partes.push("Trilha " + (TRILHA[trilha.trilha] || trilha.trilha));
      partes.push("perfil " + (PERFIL[trilha.perfil_id] || trilha.perfil_id) +
        (trilha.pontuacao_enquadramento !== null && trilha.pontuacao_enquadramento !== undefined
          ? " (pelo diagnóstico)" : ""));
      if (trilha.prazo_dias) partes.push("prazo de " + trilha.prazo_dias + " dias");
      if (trilha.cabe_no_prazo === false && trilha.opcoes_prazo) {
        avisos.append(el("p", { classe: "aviso aviso--alerta", texto: "Com as horas atuais, a trilha não cabe no " +
          "prazo. Para caber, seriam " + trilha.opcoes_prazo.horas_semanais_necessarias + " h por semana; ou dá " +
          "para focar nas " + trilha.opcoes_prazo.recorte_que_cabe.length + " primeiras etapas. Fale com o docente." }));
      }
      for (const aviso of trilha.avisos || []) avisos.append(el("p", { classe: "aviso", texto: aviso }));
    }
    $("trilha-resumo").textContent = (partes.length ? partes.join(" · ") + ". " : "") +
      "Siga na ordem. Cada etapa libera a próxima.";
    const total = atual.etapas.length;
    const feitas = atual.etapas.filter((e) => e.concluida).length;
    $("trilha-progresso").replaceChildren(el("div", { classe: "progresso-linha" },
      barra(feitas, total, "Progresso na trilha"),
      el("span", { classe: "progresso-linha__numero", texto: feitas + " de " + total })));

    // o botão "Continuar" volta para o rodapé antes de redesenhar a lista (senão sairia junto)
    const continuar = $("ir-estudar");
    $("trilha-botoes").prepend(continuar);
    const lista = $("trilha-etapas");
    lista.replaceChildren();
    let grupoAnterior = null;
    atual.etapas.forEach((etapa, indice) => {
      const detalhe = porId[etapa.competencia_id] || {};
      const situacao = situacaoDaEtapa(etapa, atual);
      const grupo = grupoDaEtapa(etapa.competencia_id);
      const dados = [];
      if (!etapa.concluida && detalhe.horas !== undefined) dados.push(detalhe.horas + " h estimadas");
      if (!etapa.concluida && detalhe.semana_inicio) dados.push("começa na semana " + detalhe.semana_inicio);
      const origem = detalhe.origem_justificativa;
      const porque = [
        detalhe.justificativa ? el("p", { texto: detalhe.justificativa }) : null,
        !etapa.concluida && detalhe.revisar_antes && detalhe.revisar_antes.length ? el("p", { classe: "etapa__dados",
          texto: "Antes, revise: " + detalhe.revisar_antes.map(nomeCompetencia).join(", ") + "." }) : null,
        !etapa.concluida && detalhe.desafio_pratico ? el("p", { classe: "etapa__dados",
          texto: "Desafio prático opcional ao fim da etapa: " + detalhe.desafio_pratico }) : null,
        detalhe.justificativa && !etapa.concluida ? el("p", { classe: "origem" },
          "Origem: " + (ORIGEM_JUSTIFICATIVA[origem] || "não registrada")) : null,
      ].filter(Boolean);
      const item = el("li", { classe: "passo passo--" + situacao, "aria-current": situacao === "atual" ? "step" : null },
        grupo !== grupoAnterior ? el("p", { classe: "rotulo passo__grupo", texto: grupo }) : null,
        el("div", { classe: "passo__linha" },
          el("div", { classe: "passo__trilho" }, marcadorEtapa(situacao, etapa.ordem),
            indice < total - 1 ? el("span", { classe: "passo__conector", "aria-hidden": "true" }) : null),
          el("div", { classe: "passo__cartao" },
            el("div", { classe: "passo__cabeca" },
              el("div", { classe: "passo__texto" },
                el("h3", { texto: etapa.ordem + ". " + etapa.nome }),
                dados.length ? el("p", { classe: "passo__dados", texto: dados.join(" · ") }) : null),
              situacao === "atual" ? null : el("span", { classe: "passo__estado",
                texto: situacao === "feito" ? "Concluída" : "Bloqueada" })),
            porque.length ? el("details", { classe: "passo__porque" },
              el("summary", { texto: "Por que esta etapa?" }), ...porque) : null)));
      if (situacao === "atual") item.querySelector(".passo__cabeca").append(continuar);
      lista.append(item);
      grupoAnterior = grupo;
    });

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

  // --- c) estudar: questão, resposta do tutor e perguntas livres ---

  const LETRAS = "ABCDEFGH";
  const NIVEL_MAXIMO = 3; // níveis do banco de itens (1 a 3)

  function mostrarAvisos(avisos) {
    const area = $("estudo-avisos");
    area.replaceChildren(...(avisos || []).map((texto) => el("p", { classe: "aviso", texto })));
  }

  // cabeçalho e painel lateral: competência, grupo, nível e os acertos desta visita
  function atualizarRitmo(competenciaId, nivel, reforco) {
    if (competenciaId) {
      const etapa = estado.etapas.find((e) => e.competencia_id === competenciaId);
      $("estudo-grupo").textContent = grupoDaEtapa(competenciaId) + (etapa ? " · Etapa " + etapa.ordem : "") +
        (reforco ? " · Revisão" : "");
      $("titulo-estudo").textContent = nomeCompetencia(competenciaId);
    } else {
      $("estudo-grupo").textContent = "";
      $("titulo-estudo").textContent = "Estudar";
    }
    if (typeof nivel === "number") {
      $("estudo-nivel").textContent = "Nível " + nivel + " de " + NIVEL_MAXIMO;
      $("estudo-nivel-barra").replaceChildren(barra(nivel, NIVEL_MAXIMO, "Nível " + nivel + " de " + NIVEL_MAXIMO));
    }
    const v = estado.visita;
    $("estudo-visita").textContent = v.respostas ? "Acertos: " + v.acertos + " de " + v.respostas + "." :
      "Nenhuma resposta ainda.";
  }

  async function carregarEstudar() {
    await carregarEstudo();
    await carregarDialogo();
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
      atualizarRitmo(null);
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
      atualizarRitmo(null);
      area.replaceChildren(el("p", { classe: "aviso aviso--alerta", texto: proxima.motivo }));
      return;
    }
    const nome = nomeCompetencia(proxima.competencia_id);
    atualizarRitmo(proxima.competencia_id, null, proxima.reforco);
    const botao = el("button", { type: "button", classe: "botao botao--grande acao", texto: "Começar",
      onclick: () => abrirSessao(proxima.competencia_id).catch(mostrarErro) });
    area.replaceChildren(el("div", { classe: "cartao questao" },
      el("p", { classe: "rotulo", texto: proxima.reforco ? "Revisão" : "Próxima etapa" }),
      el("h2", { texto: nome }),
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

  // alternativas: rádios de verdade (teclado e leitor de tela), com aparência de botões grandes
  function alternativas(nome, lista) {
    return el("fieldset", { classe: "alternativas" }, el("legend", { texto: "Escolha uma alternativa" }),
      lista.map((texto, indice) => el("label", { classe: "alternativa" },
        el("input", { type: "radio", name: nome, value: indice, required: true }),
        el("span", { classe: "alternativa__letra", "aria-hidden": "true", texto: LETRAS[indice] || "" }),
        el("span", { classe: "alternativa__texto", texto }))));
  }

  function mostrarPergunta(reforco) {
    const p = estado.pergunta;
    atualizarRitmo(p.competencia_id, p.nivel, reforco);
    const form = el("form", { classe: "cartao questao", novalidate: true, onsubmit: enviarResposta },
      el("p", { classe: "rotulo" }, "Nível " + p.nivel + (reforco ? " · revisão" : "")),
      el("h2", { classe: "enunciado", id: "enunciado", texto: p.enunciado }),
      alternativas("alternativa", p.alternativas),
      el("button", { type: "submit", classe: "botao botao--grande acao", texto: "Enviar resposta",
        disabled: TIA.estaOcupado() }));
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

  // balão do tutor: avatar "T" e o conteúdo
  function balaoDoTutor(...conteudo) {
    return el("div", { classe: "balao" },
      el("span", { classe: "balao__avatar", "aria-hidden": "true", texto: "T" }),
      el("div", { classe: "balao__corpo" }, ...conteudo));
  }

  // fontes recolhidas em "Ver fonte" (R03: o nome do material continua na página)
  function verFonte(bloco) {
    return el("details", { classe: "ver-fonte" }, el("summary", { texto: "Ver fonte" }), bloco);
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
        rotulo.append(el("span", { classe: "selo selo--erro", texto: "sua resposta" }));
      }
    });
    form.querySelector("button[type=submit]").remove();
    estado.visita.respostas += 1;
    if (f.acertou) estado.visita.acertos += 1;
    atualizarRitmo(estado.pergunta.competencia_id, f.nivel_atual);

    const continuar = el("button", { type: "button", classe: "botao botao--grande acao", texto: "Continuar",
      onclick: () => seguir(resultado.proxima) });
    const bloco = el("div", { classe: "resposta-tutor", role: "region", "aria-label": "Correção" },
      balaoDoTutor(
        el("p", { classe: "veredito " + (f.acertou ? "veredito--acerto" : "veredito--erro"),
          texto: (f.acertou ? "✓ " : "✗ ") + f.veredito }),
        el("p", { classe: "explicacao", texto: f.explicacao }),
        el("p", { classe: "origem" }, "Origem da explicação: " + f.origem + ". " + (ORIGEM_FEEDBACK[f.origem] || "") +
          (f.falha_llm ? " Motivo: " + (FALHA[f.falha_llm] || f.falha_llm) + "." : "") + tempo(f.tempo_ms)),
        verFonte(blocoFontes(f.fontes)),
        el("p", { classe: "etapa__dados", texto: !f.concluida ? "Nível atual: " + f.nivel_atual :
          f.com_ressalvas ? "As questões desta competência acabaram antes do domínio (concluída com ressalvas)." :
          "Competência concluída!" })),
      continuar);
    $("estudo-conteudo").append(bloco);
    mostrarAvisos(resultado.avisos);
    estado.pergunta = null;
    continuar.focus();
  }

  // semFonte: texto quando não há trecho do material (no feedback de questão, a explicação é a do item;
  // no diálogo não há item, e o texto é outro)
  const SEM_FONTE_ITEM = "Fonte: texto do próprio item (sem trecho do material).";
  const SEM_FONTE_DIALOGO = "Esta resposta não usou trecho do material do curso.";

  function blocoFontes(fontes, semFonte = SEM_FONTE_ITEM) {
    if (!fontes || !fontes.length) {
      return el("p", { classe: "fontes", texto: semFonte });
    }
    return el("div", { classe: "fontes" }, "Fontes do material (R03):",
      el("ul", {}, fontes.map((fonte) => el("li", {}, el("code", { texto: fonte })))));
  }

  // --- d) pergunta livre ao tutor (dentro de Estudar) ---

  function itemConversa(item) {
    const vetada = item.vetada || item.origem === "docente";
    const fontes = item.origem === "fallback" && !vetada ? null : blocoFontes(item.fontes, SEM_FONTE_DIALOGO);
    return el("li", { classe: "conversa__item" },
      el("p", { classe: "conversa__pergunta", texto: item.pergunta }),
      balaoDoTutor(
        vetada ? el("p", { classe: "rotulo rotulo--professor", texto: "Corrigida pelo professor" }) : null,
        el("p", { classe: "conversa__resposta", texto: item.resposta }),
        el("p", { classe: "origem" }, "Origem: " + (vetada ? "professor" : item.origem) + ". " +
          (ORIGEM_FEEDBACK[vetada ? "docente" : item.origem] || "") +
          (item.falha_llm ? " Motivo: " + (FALHA[item.falha_llm] || item.falha_llm) + "." : "") + tempo(item.tempo_ms)),
        fontes ? verFonte(fontes) : null));
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

  // cartão pequeno da coluna de avisos
  function indicador(titulo, ...conteudo) {
    return el("section", { classe: "cartao cartao--mini" }, el("h3", { classe: "rotulo", texto: titulo }), ...conteudo);
  }

  function numeroGrande(rotulo, valor, complemento) {
    return el("div", { classe: "numero" },
      el("span", { classe: "numero__rotulo", texto: rotulo }),
      el("span", { classe: "numero__valor" }, String(valor),
        complemento ? el("span", { classe: "numero__complemento", texto: " " + complemento }) : null));
  }

  async function carregarRelatorio() {
    // nomes da ementa: o desempenho pode ter competências fora da trilha (ex.: tópicos do piloto
    // praticados pela rota avulsa), que não estão em progresso.por_competencia
    await carregarNomes();
    const r = await chamar("GET", rota("/relatorio/aluno/{id}") + "?narrativa=false", null, "Calculando os indicadores…");
    const pr = r.progresso, de = r.desempenho, en = r.engajamento, qf = r.qualidade_feedback;
    const nomes = {};
    for (const c of pr.por_competencia) nomes[c.competencia_id] = c.nome;
    const nome = (id) => nomes[id] || nomeCompetencia(id);

    // 1. os três números: respondidas, taxa de acerto, etapas concluídas
    $("relatorio-indicadores").replaceChildren(
      numeroGrande("Questões respondidas", de.geral.respostas),
      numeroGrande("Taxa de acerto", de.geral.respostas ? porcento(de.geral.taxa) : "—"),
      pr.tem_trilha ? numeroGrande("Etapas concluídas", pr.concluidas, "de " + pr.etapas)
        : numeroGrande("Etapas concluídas", "—", "sem trilha"));

    // 2. barras por competência, com o nome (nunca o código)
    const barras = de.por_competencia.map((t) => {
      const texto = t.acertos + " de " + t.respostas + " (" + porcento(t.taxa) + ")";
      return el("div", { classe: "competencia" },
        el("div", { classe: "competencia__linha" },
          el("span", { classe: "competencia__nome", texto: nome(t.chave) }),
          el("span", { classe: "competencia__numero", texto })),
        barra(t.acertos, t.respostas, nome(t.chave) + ": " + texto, (t.taxa || 0) < 0.8 ? "barra__valor--atencao" : null));
    });
    const etapas = pr.tem_trilha ? el("div", { classe: "etapas-relatorio" },
      el("h3", { classe: "rotulo", texto: "Etapas da trilha" }),
      el("ul", {}, pr.por_competencia.map((c) => el("li", { texto: c.nome + ": " +
        (c.concluida ? "concluída" : c.nivel_atual ? "em andamento, nível " + c.nivel_atual : "não iniciada") +
        (c.com_ressalvas ? " (com ressalvas: as questões acabaram sem domínio)" : "") }))))
      : el("p", { texto: "Você ainda não tem trilha." });
    $("relatorio-competencias").replaceChildren(
      el("p", { classe: "cabeca__sub", texto: de.geral.respostas ? "Você acertou " + de.geral.acertos + " de " +
        de.geral.respostas + " perguntas (" + porcento(de.geral.taxa) + "). " + (TENDENCIA[de.tendencia.direcao] || "")
        : "Você ainda não respondeu perguntas." }),
      barras.length ? el("div", { classe: "competencias" }, barras) : null,
      etapas);

    // 3. avisos: inatividade, pontos a reforçar, participação e os textos do tutor
    const avisos = [];
    if (en.inativo) {
      avisos.push(el("p", { classe: "aviso aviso--alerta", texto: "Faz alguns dias que você não estuda. Que tal retomar?" }));
    }
    avisos.push(indicador("Pontos a reforçar",
      r.pontos_fracos.length ? el("ul", {}, r.pontos_fracos.map((p) => el("li", {
        texto: p.nome + ": " + p.erros + " erro(s) em " + p.respostas + " resposta(s)" }))) :
        el("p", { classe: "cartao__texto", texto: "Nenhum ponto fraco identificado até agora." }),
      r.itens_fracos.length ? el("p", { classe: "cartao__texto", texto: r.itens_fracos.length +
        " pergunta(s) com erro repetido." }) : null));
    avisos.push(indicador("Participação",
      el("ul", {},
        el("li", { texto: en.sessoes + " sessões de estudo (" + en.sessoes_concluidas + " concluídas)" }),
        el("li", { texto: en.respostas + " respostas e " + en.perguntas_dialogo + " perguntas ao tutor" }),
        el("li", { texto: en.dias_ativos + " dia(s) com atividade" }),
        el("li", { texto: en.dias_inativo === null ? "Ainda sem atividade."
          : en.dias_inativo === 0 ? "Última atividade: hoje." : "Última atividade há " + en.dias_inativo + " dia(s)." }))));

    // mesma base no numerador e no denominador: por_origem soma as explicações das questões e as
    // respostas do diálogo, então o total é a soma dele (não respostas_com_origem, que conta só questões)
    const total = Object.values(qf.por_origem).reduce((soma, n) => soma + n, 0);
    avisos.push(indicador("Sobre os textos do tutor",
      total ? el("ul", {},
        el("li", { texto: (qf.por_origem.LLM || 0) + " de " + total +
          " textos do tutor (explicações e respostas às suas perguntas) escritos pela IA local e conferidos" }),
        el("li", { texto: (qf.por_origem.guarda || 0) + " barradas pela verificação (trocadas pelo material)" }),
        el("li", { texto: (qf.por_origem.fallback || 0) + " com texto fixo" })) :
        el("p", { classe: "cartao__texto", texto: "Ainda não há explicações registradas." }),
      qf.vetados ? el("p", { classe: "cartao__texto", texto: qf.vetados +
        " resposta(s) do diálogo corrigida(s) pelo professor." }) : null));
    $("relatorio-avisos").replaceChildren(...avisos);
    mostrarNarrativa(null);
    await carregarCorrecoes();
  }

  // feedbacks de questões vetados pelo professor (R12): a correção substitui a explicação original
  async function carregarCorrecoes() {
    const feedbacks = await chamar("GET", rota("/alunos/{id}/feedbacks"), null, "Buscando as correções…");
    const vetados = feedbacks.filter((f) => f.vetada).reverse();
    $("relatorio-correcoes").replaceChildren(vetados.length ? el("ul", { classe: "correcoes" }, vetados.map((f) =>
      el("li", { classe: "correcao" },
        el("p", { classe: "etapa__dados", texto: nomeCompetencia(f.competencia_id) + " · questão " +
          (f.item_id || "") }),
        f.enunciado ? el("p", { classe: "enunciado", texto: f.enunciado }) : null,
        f.veredito ? el("p", { classe: "veredito", texto: f.veredito }) : null,
        el("p", { classe: "explicacao", texto: f.explicacao }),
        el("p", { classe: "origem", texto: "Origem: professor. " + ORIGEM_FEEDBACK.docente }))))
      : el("p", { classe: "cartao__texto", texto: "Nenhuma explicação corrigida pelo professor." }));
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
    $("pular-onboarding").addEventListener("click", () => enviarFala("pular").catch(mostrarErro));
    // mostrar a senha: o tipo original vem do HTML (o campo volta a ele ao esconder e depois do envio)
    const tipoOculto = $("campo-senha").type;
    $("mostrar-senha").addEventListener("click", () => {
      const campo = $("campo-senha");
      const mostrar = $("mostrar-senha").getAttribute("aria-pressed") !== "true";
      campo.type = mostrar ? "text" : tipoOculto;
      $("mostrar-senha").setAttribute("aria-pressed", mostrar ? "true" : "false");
      $("mostrar-senha").setAttribute("aria-label", mostrar ? "Esconder senha" : "Mostrar senha");
    });
    $("form-onboarding").addEventListener("submit", (e) => enviarOnboarding(e).catch(mostrarErro));
    $("concluir-primeiro-acesso").addEventListener("click", () => concluirPrimeiroAcesso().catch(mostrarErro));
    $("cancelar-matricula").addEventListener("click", sair);
    $("trocar-aluno").addEventListener("click", sair);
    $("erro-fechar").addEventListener("click", esconderErro);
    $("ir-estudar").addEventListener("click", () => irPara("estudo"));
    $("inicio-continuar").addEventListener("click", () => irPara("estudo"));
    $("inicio-ver-trilha").addEventListener("click", () => irPara("trilha"));
    $("inicio-ver-relatorio").addEventListener("click", () => irPara("relatorio"));
    $("estudo-voltar-trilha").addEventListener("click", () => irPara("trilha"));
    $("relatorio-estudar").addEventListener("click", () => irPara("estudo"));
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
