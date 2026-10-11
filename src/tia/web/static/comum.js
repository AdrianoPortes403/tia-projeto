/*
 * Utilidades compartilhadas da aplicação do aluno (app.js, EAP 1.4.4) e do
 * painel do docente (painel/painel.js, EAP 1.4.5): JavaScript puro, sem build.
 *
 *   el / svg      montam elementos; texto SEMPRE por textContent (nunca innerHTML)
 *   chamar        fetch com faixa "Aguardando…", contador de segundos, botões
 *                 .acao desativados durante a chamada e erro claro (ErroApi)
 *   mostrarErro   faixa de erro (role=alert) com o detail da API
 *
 * A página precisa dos ids: carregando, carregando-texto, carregando-segundos,
 * erro, erro-texto e erro-fechar. Nada é escrito no console (R08).
 */
"use strict";

window.TIA = (function () {
  const config = {
    esperaMaximaMs: 300000,         // espera máxima do navegador por uma resposta
    quem: "O tutor",                // quem demorou, na mensagem de estouro de tempo
    textoEspera: "Aguardando o tutor…",
  };
  let ocupado = false;

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

  async function chamar(metodo, caminho, corpo, textoEspera) {
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
        resposta = await fetch(caminho, {
          method: metodo,
          headers: corpo ? { "Content-Type": "application/json" } : {},
          body: corpo ? JSON.stringify(corpo) : undefined,
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
      if (!resposta.ok) throw new ErroApi(detalheDoErro(dados, resposta.status), resposta.status);
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

  return { configurar, estaOcupado, $, el, svg, tempo, porcento, ErroApi, chamar, mostrarErro, esconderErro };
})();
