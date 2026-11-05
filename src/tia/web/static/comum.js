/*
 * Utilidades compartilhadas da aplicação do aluno (app.js, EAP 1.4.4) e do
 * painel do docente (painel/painel.js, EAP 1.4.5): JavaScript puro, sem build.
 *
 *   el / svg      montam elementos; texto SEMPRE por textContent (nunca innerHTML)
 *   chamar        fetch com faixa "Aguardando…", contador de segundos, botões
 *                 .acao desativados durante a chamada e erro claro (ErroApi)
 *   mostrarErro   faixa de erro (role=alert) com o detail da API
 *   sessão (1.4.6) obterSessao, entrar, sair, mensagemOutroPapel, mostrarSessao: login com cookie de
 *                 sessão HttpOnly (o JavaScript nunca vê o cookie); o token
 *                 anti-CSRF fica só em memória e vai no cabeçalho X-CSRF-Token
 *                 de toda escrita; 401 chama configurar({ aoExigirLogin }) (menos no
 *                 login e na saída). Sessão de outro perfil na tela de login: as
 *                 páginas mostram mensagemOutroPapel com um botão Sair.
 *   troca de senha mostrarTrocaDeSenha, esconderTrocaDeSenha, ligarTrocaDeSenha:
 *                 troca obrigatória da senha temporária (form-senha dentro da
 *                 tela de login)
 *
 * A página precisa dos ids: carregando, carregando-texto, carregando-segundos,
 * erro, erro-texto, erro-fechar, aviso-dev, usuario-barra, usuario-nome,
 * usuario-papel, titulo-login, login-mensagem, form-login, form-senha, campo-senha-atual,
 * campo-senha-nova e campo-senha-repetir. Nada é escrito no console (R08).
 */
"use strict";

window.TIA = (function () {
  const config = {
    esperaMaximaMs: 300000,         // espera máxima do navegador por uma resposta
    quem: "O tutor",                // quem demorou, na mensagem de estouro de tempo
    textoEspera: "Aguardando o tutor…",
    aoExigirLogin: null,            // chamado quando a API responde 401 (sessão ausente ou vencida)
  };
  const CABECALHO_CSRF = "X-CSRF-Token";
  const METODOS_SEGUROS = ["GET", "HEAD", "OPTIONS"];
  const PAPEL = { aluno: "aluno", docente: "docente", admin: "administrador" };
  const ROTAS_SEM_AVISO_401 = ["/auth/login", "/auth/logout"];
  let ocupado = false;
  let csrf = null; // token anti-CSRF da sessão: só em memória, nunca em armazenamento

  function configurar(opcoes) { Object.assign(config, opcoes); }
  function estaOcupado() { return ocupado; }

  // --- utilidades de DOM (sempre textContent) ---

  function $(id) { return document.getElementById(id); }

  function atribuir(no, atributos) {
    for (const [nome, valor] of Object.entries(atributos || {})) {
      if (valor === null || valor === undefined || valor === false) continue;
      if (nome === "classe") no.setAttribute("class", valor);
      else if (nome === "texto") no.textContent = String(valor);
      else if (nome.startsWith("on")) no.addEventListener(nome.slice(2), valor);
      else no.setAttribute(nome, valor === true ? "" : String(valor));
    }
  }

  function anexar(no, filhos) {
    for (const filho of filhos.flat()) {
      if (filho === null || filho === undefined || filho === false) continue;
      no.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
    }
  }

  function el(tag, atributos, ...filhos) {
    const no = document.createElement(tag);
    atribuir(no, atributos);
    anexar(no, filhos);
    return no;
  }

  // elementos SVG (gráficos do painel): mesmos atributos de el, texto por textContent
  function svg(tag, atributos, ...filhos) {
    const no = document.createElementNS("http://www.w3.org/2000/svg", tag);
    atribuir(no, atributos);
    anexar(no, filhos);
    return no;
  }

  // tempo gasto no servidor (R09 a medir na VM; a tela sempre mostra o número)
  function tempo(ms) {
    return typeof ms === "number" ? " Tempo: " + (ms / 1000).toFixed(1).replace(".", ",") + " s." : "";
  }

  function porcento(fracao) {
    return fracao === null || fracao === undefined ? "sem dados" : Math.round(fracao * 100) + "%";
  }

  // --- chamadas à API, com contador de segundos e erros claros ---

  class ErroApi extends Error {
    constructor(mensagem, status) { super(mensagem); this.status = status; }
  }

  function detalheDoErro(corpo, status) {
    const detalhe = corpo && corpo.detail;
    if (typeof detalhe === "string") return detalhe;
    if (Array.isArray(detalhe) && detalhe.length) {
      return "Dados inválidos: " + detalhe.map((d) => d.msg).join("; ");
    }
    return "O servidor respondeu com erro " + status + ".";
  }

  function marcarOcupado(estado, texto) {
    ocupado = estado;
    document.querySelectorAll(".acao").forEach((b) => { b.disabled = estado; });
    document.body.setAttribute("aria-busy", estado ? "true" : "false");
    $("carregando").hidden = !estado;
    if (estado) $("carregando-texto").textContent = texto || config.textoEspera;
  }

  async function chamar(metodo, caminho, corpo, textoEspera, cabecalhosExtras) {
    if (ocupado) throw new ErroApi("Aguarde a resposta anterior.", 0);
    esconderErro();
    marcarOcupado(true, textoEspera);
    const inicio = Date.now();
    const segundos = $("carregando-segundos");
    segundos.textContent = "0 s";
    const relogio = setInterval(() => {
      segundos.textContent = Math.floor((Date.now() - inicio) / 1000) + " s";
    }, 1000);
    const controle = new AbortController();
    const limite = setTimeout(() => controle.abort(), config.esperaMaximaMs);
    try {
      let resposta;
      try {
        const cabecalhos = Object.assign(corpo ? { "Content-Type": "application/json" } : {}, cabecalhosExtras);
        if (!METODOS_SEGUROS.includes(metodo) && csrf) cabecalhos[CABECALHO_CSRF] = csrf;
        resposta = await fetch(caminho, {
          method: metodo,
          headers: cabecalhos,
          body: corpo ? JSON.stringify(corpo) : undefined,
          credentials: "same-origin",
          signal: controle.signal,
        });
      } catch (erro) {
        if (erro.name === "AbortError") {
          throw new ErroApi(config.quem + " demorou mais de " + config.esperaMaximaMs / 1000 +
            " s para responder. Tente de novo em instantes.", 0);
        }
        throw new ErroApi("Sem conexão com o servidor do TIA. Confira se a API está no ar e tente de novo.", 0);
      }
      let dados = null;
      try { dados = await resposta.json(); } catch (_) { dados = null; }
      if (!resposta.ok) {
        const erro = new ErroApi(detalheDoErro(dados, resposta.status), resposta.status);
        // no login e na saída, o 401 é tratado por quem chamou (não é "sessão terminou")
        if (resposta.status === 401 && !ROTAS_SEM_AVISO_401.includes(caminho) && config.aoExigirLogin) {
          csrf = null;
          setTimeout(() => config.aoExigirLogin(erro.message), 0);
        }
        throw erro;
      }
      return dados;
    } finally {
      clearTimeout(limite);
      clearInterval(relogio);
      marcarOcupado(false);
    }
  }

  function mostrarErro(erro) {
    $("erro-texto").textContent = erro instanceof ErroApi ? erro.message : "Erro inesperado na página.";
    $("erro").hidden = false;
    $("erro-fechar").focus();
  }

  function esconderErro() { $("erro").hidden = true; }

  // --- sessão (EAP 1.4.6) ---

  // situação: { autenticacao: "ligada" | "desligada", usuario: {id, papel, aluno_id} | null, csrf }
  async function obterSessao() {
    const situacao = await chamar("GET", "/auth/eu", null, "Verificando a sessão…");
    csrf = situacao.csrf || null;
    return situacao;
  }

  async function entrar(login, senha) {
    // sem sessão ainda: o cabeçalho só precisa existir (um site de terceiros não consegue enviá-lo)
    const situacao = await chamar("POST", "/auth/login", { login, senha }, "Entrando…", { [CABECALHO_CSRF]: "login" });
    csrf = situacao.csrf || null;
    return situacao;
  }

  // encerra a sessão no servidor (que apaga o cookie); 401 = a sessão já tinha acabado, então já saiu.
  // Outro erro (rede, 403): propaga, e a sessão continua como estava (a página não diz "Você saiu.")
  async function sair() {
    try {
      await chamar("POST", "/auth/logout", null, "Saindo…");
    } catch (erro) {
      if (!(erro instanceof ErroApi && erro.status === 401)) throw erro;
    }
    csrf = null;
  }

  // tela de login com sessão de outro perfil: "Você está conectado como docente. Sair para entrar como aluno."
  function mensagemOutroPapel(papelDaSessao, papelDaPagina) {
    return "Você está conectado como " + (PAPEL[papelDaSessao] || papelDaSessao) + ". Sair para entrar como " +
      (PAPEL[papelDaPagina] || papelDaPagina) + ".";
  }

  // --- troca obrigatória da senha temporária ---

  const CAMPOS_TROCA = ["campo-senha-atual", "campo-senha-nova", "campo-senha-repetir"];

  // chamar depois de a página mostrar a tela de login: troca o formulário de login pelo de troca
  function mostrarTrocaDeSenha() {
    const titulo = $("titulo-login");
    if (!titulo.dataset.original) titulo.dataset.original = titulo.textContent;
    titulo.textContent = "Troca da senha temporária";
    $("form-login").hidden = true;
    $("form-senha").hidden = false;
    $("login-mensagem").textContent = "Sua senha é temporária. Crie uma senha nova para continuar.";
    $("login-mensagem").hidden = false;
    $("campo-senha-atual").focus();
  }

  // volta a tela de login ao normal (as páginas chamam ao mostrar o login)
  function esconderTrocaDeSenha() {
    const titulo = $("titulo-login");
    if (titulo.dataset.original) titulo.textContent = titulo.dataset.original;
    $("form-senha").hidden = true;
  }

  async function trocarSenha(atual, nova) {
    const situacao = await chamar("POST", "/auth/senha", { senha_atual: atual, nova_senha: nova }, "Trocando a senha…");
    csrf = situacao.csrf || null; // a troca abre uma sessão nova
    return situacao;
  }

  // aoConcluir: chamado depois da troca (normalmente o início da página, que relê a sessão)
  function ligarTrocaDeSenha(aoConcluir) {
    $("form-senha").addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const [atual, nova, repetida] = CAMPOS_TROCA.map((id) => $(id).value);
      const limpar = () => CAMPOS_TROCA.forEach((id) => { $(id).value = ""; }); // a senha não fica na página
      if (!atual || !nova) {
        mostrarErro(new ErroApi("Preencha a senha atual e a nova senha.", 0));
        return;
      }
      if (nova !== repetida) {
        $("campo-senha-nova").value = "";
        $("campo-senha-repetir").value = "";
        mostrarErro(new ErroApi("A nova senha e a repetição não conferem.", 0));
        return;
      }
      try {
        await trocarSenha(atual, nova);
      } catch (erro) {
        mostrarErro(erro);
        return;
      } finally {
        limpar();
      }
      esconderTrocaDeSenha();
      $("login-mensagem").hidden = true;
      await aoConcluir();
    });
  }

  // barra do usuário logado e aviso do modo de desenvolvimento
  function mostrarSessao(situacao) {
    $("aviso-dev").hidden = !situacao || situacao.autenticacao !== "desligada";
    const usuario = situacao && situacao.usuario;
    $("usuario-barra").hidden = !usuario;
    $("usuario-nome").textContent = usuario ? usuario.id : "";
    $("usuario-papel").textContent = usuario ? "(" + (PAPEL[usuario.papel] || usuario.papel) + ")" : "";
  }

  return { configurar, estaOcupado, $, el, svg, tempo, porcento, ErroApi, chamar, mostrarErro, esconderErro,
    obterSessao, entrar, sair, mensagemOutroPapel, mostrarSessao, mostrarTrocaDeSenha, esconderTrocaDeSenha, ligarTrocaDeSenha };
})();
