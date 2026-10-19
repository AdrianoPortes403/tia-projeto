/*
 * Plug-in do TIA para o EBAULA (EAP 1.4.3).
 *
 * O que faz: acrescenta às páginas do EBAULA um botão flutuante "Tutor TIA". Ao clicar, abre
 * um painel lateral com a aplicação do aluno (/app/) dentro de um iframe, ou, no modo "aba",
 * abre o TIA em outra aba. Não tem dependências e não precisa de build.
 *
 * Como instalar no EBAULA (uma linha, em qualquer lugar que a página carregue script, como o
 * "HTML adicional" do rodapé ou do tema):
 *
 *   <script src="https://tia.exemplo.eb.mil.br/app/plugin/tia-ebaula.js"
 *           data-tia-url="https://tia.exemplo.eb.mil.br" defer></script>
 *
 * Configuração (atributos data- da tag script, ou window.TIA_EBAULA_CONFIG definido antes do
 * script, que tem prioridade). Tudo é opcional, menos a URL do TIA:
 *   url      (data-tia-url)      endereço do TIA, sem o /app. Obrigatório. https, ou http só em localhost
 *   modo     (data-tia-modo)     "iframe" (padrão) ou "aba"
 *   titulo   (data-tia-titulo)   texto do botão e do painel (padrão "Tutor TIA")
 *   posicao  (data-tia-posicao)  "direita" (padrão) ou "esquerda"
 *   aberto   (data-tia-aberto)   "1" abre o painel ao carregar a página (padrão "0")
 *   caminho  (data-tia-caminho)  caminho da aplicação do aluno (padrão "/app/")
 *   css      (data-tia-css)      URL do tia-ebaula.css (padrão: ao lado deste script)
 *   espera   (data-tia-espera)   ms até avisar que o painel não carregou (padrão 15000)
 *
 * API: window.TIAEbaula.abrir(), .fechar(), .alternar().
 *
 * Segurança (R08, R07): nenhum dado do aluno ou do EBAULA vai na URL nem é lido por este script;
 * o iframe usa sandbox, sem referer e sem permissões de câmera, microfone ou localização. Todo
 * texto entra por textContent. O TIA só aceita ser embutido nas origens listadas em
 * TIA_FRAME_ANCESTORS (docs/seguranca/implantacao.md, alternativa A).
 *
 * Mensagens opcionais do TIA para o plug-in (window.parent.postMessage): {tipo: "tia:fechar"} e
 * {tipo: "tia:abrir-em-aba"}. Só são aceitas da origem do TIA e do próprio iframe.
 */
(function () {
  "use strict";

  if (window.TIAEbaula) { return; }  // script carregado duas vezes

  var VERSAO = "1.0.0";
  var CHAVE_ESTADO = "tia-ebaula:aberto";
  var SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-downloads";

  // --- configuração ---------------------------------------------------------------

  var scriptAtual = document.currentScript;  // só existe durante a carga; guardado para usar depois

  function acharScript() {
    if (scriptAtual) { return scriptAtual; }
    return document.querySelector("script[data-tia-url]") ||
      document.querySelector('script[src*="tia-ebaula"]');
  }

  function lerConfig(script) {
    var dados = (script && script.dataset) || {};
    var global = window.TIA_EBAULA_CONFIG || {};
    function pegar(nome, padrao) {
      var valor = global[nome];
      if (valor === undefined || valor === null || valor === "") {
        var d = dados["tia" + nome.charAt(0).toUpperCase() + nome.slice(1)];
        valor = (d === undefined || d === "") ? padrao : d;
      }
      return valor;
    }
    var espera = parseInt(pegar("espera", 15000), 10);
    var aberto = pegar("aberto", "0");
    return {
      url: String(pegar("url", "")),
      modo: pegar("modo", "iframe") === "aba" ? "aba" : "iframe",
      titulo: String(pegar("titulo", "Tutor TIA")).slice(0, 60),
      posicao: pegar("posicao", "direita") === "esquerda" ? "esquerda" : "direita",
      aberto: aberto === true || aberto === "1" || aberto === "true",
      caminho: String(pegar("caminho", "/app/")),
      css: String(pegar("css", "")),
      espera: isNaN(espera) ? 15000 : Math.max(1000, espera)
    };
  }

  function ehLocal(host) {
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  }

  // Devolve {base, origem} se a URL do TIA é aceitável; senão null (o plug-in não aparece).
  function validarUrl(valor) {
    if (!valor) { return null; }
    try {
      var u = new URL(valor, window.location.href);
      var seguro = u.protocol === "https:" || (u.protocol === "http:" && ehLocal(u.hostname));
      if (!seguro || u.username || u.password) { return null; }
      return { base: u.origin + u.pathname.replace(/\/+$/, ""), origem: u.origin };
    } catch (erro) {
      return null;
    }
  }

  function montarUrlApp(base, caminho) {
    var c = caminho.charAt(0) === "/" ? caminho : "/" + caminho;
    if (c.indexOf("//") === 0) { c = "/app/"; }
    // origem=ebaula só avisa de onde veio; nunca carrega dado de aluno (R08)
    return base + c + (c.indexOf("?") === -1 ? "?" : "&") + "origem=ebaula";
  }

  // --- estado guardado (só uma conveniência; pode falhar em janela privativa) ---------

  function lerEstado() {
    try { return window.sessionStorage.getItem(CHAVE_ESTADO) === "1"; } catch (e) { return false; }
  }
  function gravarEstado(aberto) {
    try { window.sessionStorage.setItem(CHAVE_ESTADO, aberto ? "1" : "0"); } catch (e) { /* ignora */ }
  }

  // --- DOM ---------------------------------------------------------------------------

  function criar(tag, classe, texto) {
    var no = document.createElement(tag);
    if (classe) { no.className = classe; }
    if (texto) { no.textContent = texto; }
    return no;
  }

  function iniciar() {
    if (document.querySelector("[data-tia-ebaula]")) { return; }  // já montado
    var script = acharScript();
    var cfg = lerConfig(script);
    var destino = validarUrl(cfg.url);
    if (!destino) {
      if (window.console && console.warn) {
        console.warn("[TIA] Plug-in desativado: informe data-tia-url com https (ou http em localhost).");
      }
      return;
    }
    var urlApp = montarUrlApp(destino.base, cfg.caminho);

    // folha de estilo ao lado do script (ou a indicada)
    var hrefCss = cfg.css;
    if (!hrefCss && script && script.src) { hrefCss = script.src.replace(/[^\/?#]*([?#].*)?$/, "tia-ebaula.css"); }
    if (!hrefCss) { hrefCss = destino.base + "/app/plugin/tia-ebaula.css"; }
    var link = criar("link");
    link.rel = "stylesheet";
    link.href = hrefCss;
    document.head.appendChild(link);

    var raiz = criar("div", "tia-ebaula tia-ebaula--" + cfg.posicao);
    raiz.setAttribute("data-tia-ebaula", "");
    var botao = criar("button", "tia-ebaula__botao", cfg.titulo);
    botao.type = "button";
    raiz.appendChild(botao);

    var estado = { aberto: false, ampliado: false, iframe: null, temporizador: null };
    var painel = null, areaEstado = null, corpo = null, botaoAmpliar = null;

    function abrirAba() {
      window.open(urlApp, "_blank", "noopener,noreferrer");
    }

    if (cfg.modo === "aba") {
      botao.setAttribute("aria-label", cfg.titulo + " (abre em uma nova aba)");
      botao.addEventListener("click", abrirAba);
      document.body.appendChild(raiz);
      window.TIAEbaula = { versao: VERSAO, abrir: abrirAba, fechar: function () {}, alternar: abrirAba };
      return;
    }

    // painel com iframe
    var idPainel = "tia-ebaula-painel";
    painel = criar("section", "tia-ebaula__painel");
    painel.id = idPainel;
    painel.setAttribute("role", "dialog");
    painel.setAttribute("aria-modal", "false");
    painel.setAttribute("aria-label", cfg.titulo);
    painel.tabIndex = -1;
    painel.hidden = true;

    var cabecalho = criar("div", "tia-ebaula__cabecalho");
    cabecalho.appendChild(criar("h2", "tia-ebaula__titulo", cfg.titulo));
    var acoes = criar("div", "tia-ebaula__acoes");
    var abrirNova = criar("a", "tia-ebaula__acao", "Abrir em nova aba");
    abrirNova.href = urlApp;
    abrirNova.target = "_blank";
    abrirNova.rel = "noopener noreferrer";
    botaoAmpliar = criar("button", "tia-ebaula__acao", "Ampliar");
    botaoAmpliar.type = "button";
    botaoAmpliar.setAttribute("aria-pressed", "false");
    var botaoFechar = criar("button", "tia-ebaula__acao", "Fechar");
    botaoFechar.type = "button";
    botaoFechar.setAttribute("aria-label", "Fechar " + cfg.titulo);
    acoes.appendChild(abrirNova);
    acoes.appendChild(botaoAmpliar);
    acoes.appendChild(botaoFechar);
    cabecalho.appendChild(acoes);

    corpo = criar("div", "tia-ebaula__corpo");
    areaEstado = criar("p", "tia-ebaula__estado", "Carregando o tutor…");
    areaEstado.setAttribute("role", "status");
    corpo.appendChild(areaEstado);

    painel.appendChild(cabecalho);
    painel.appendChild(corpo);
    raiz.appendChild(painel);
    botao.setAttribute("aria-expanded", "false");
    botao.setAttribute("aria-controls", idPainel);
    document.body.appendChild(raiz);

    function criarIframe() {
      var f = criar("iframe", "tia-ebaula__iframe");
      f.title = cfg.titulo;
      f.setAttribute("sandbox", SANDBOX);
      f.setAttribute("referrerpolicy", "no-referrer");
      f.setAttribute("allow", "");
      f.addEventListener("load", function () {
        window.clearTimeout(estado.temporizador);
        areaEstado.hidden = true;
      });
      f.src = urlApp;
      corpo.appendChild(f);
      estado.iframe = f;
      // se o TIA não responder (ou recusar o iframe), o aluno ainda tem a nova aba
      estado.temporizador = window.setTimeout(function () {
        areaEstado.hidden = false;
        areaEstado.textContent = "O tutor não carregou dentro desta página. Use “Abrir em nova aba”.";
      }, cfg.espera);
    }

    function abrir(foco) {
      if (estado.aberto) { return; }
      estado.aberto = true;
      painel.hidden = false;
      raiz.classList.add("tia-ebaula--aberto");
      botao.setAttribute("aria-expanded", "true");
      if (!estado.iframe) { criarIframe(); }  // só carrega o TIA quando o aluno pede
      gravarEstado(true);
      if (foco !== false) { painel.focus(); }
    }

    function fechar(devolverFoco) {
      if (!estado.aberto) { return; }
      estado.aberto = false;
      painel.hidden = true;
      raiz.classList.remove("tia-ebaula--aberto");
      botao.setAttribute("aria-expanded", "false");
      gravarEstado(false);
      if (devolverFoco !== false) { botao.focus(); }
    }

    function alternar() { if (estado.aberto) { fechar(); } else { abrir(); } }

    function ampliar() {
      estado.ampliado = !estado.ampliado;
      raiz.classList.toggle("tia-ebaula--ampliado", estado.ampliado);
      botaoAmpliar.setAttribute("aria-pressed", String(estado.ampliado));
      botaoAmpliar.textContent = estado.ampliado ? "Reduzir" : "Ampliar";
    }

    botao.addEventListener("click", alternar);
    botaoFechar.addEventListener("click", function () { fechar(); });
    botaoAmpliar.addEventListener("click", ampliar);
    document.addEventListener("keydown", function (e) {
      if (estado.aberto && (e.key === "Escape" || e.key === "Esc")) { fechar(); }
    });

    // mensagens opcionais do TIA (só da origem do TIA e do nosso iframe)
    window.addEventListener("message", function (e) {
      if (e.origin !== destino.origem) { return; }
      if (!estado.iframe || e.source !== estado.iframe.contentWindow) { return; }
      var d = e.data;
      if (!d || typeof d !== "object") { return; }
      if (d.tipo === "tia:fechar") { fechar(); }
      else if (d.tipo === "tia:abrir-em-aba") { abrirAba(); }
    });

    window.TIAEbaula = { versao: VERSAO, abrir: function () { abrir(); }, fechar: function () { fechar(); }, alternar: alternar };

    if (cfg.aberto || lerEstado()) { abrir(false); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
