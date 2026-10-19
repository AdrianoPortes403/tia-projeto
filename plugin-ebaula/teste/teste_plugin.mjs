/*
 * Teste do plug-in do EBAULA (EAP 1.4.3) em um navegador simulado (jsdom).
 *
 * Como rodar (precisa de Node 18 ou mais novo):
 *     cd plugin-ebaula/teste
 *     npm install
 *     npm test
 * Para testar outro arquivo: TIA_PLUGIN_JS=/caminho/tia-ebaula.js npm test
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const CAMINHO = process.env.TIA_PLUGIN_JS ||
  new URL("../../src/tia/web/static/plugin/tia-ebaula.js", import.meta.url).pathname;
const CODIGO = readFileSync(CAMINHO, "utf-8");
const TIA = "https://tia.exemplo.eb.mil.br";

// monta uma página do "EBAULA" e executa o plug-in nela
function pagina({ config = { url: TIA }, atributos = "", url = "https://ebaula.exemplo.eb.mil.br/curso/1", carregar = true } = {}) {
  const dom = new JSDOM(`<!doctype html><html><head></head><body><main>Curso</main>
    ${atributos ? `<script ${atributos}></script>` : ""}</body></html>`,
    { url, runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  const abertas = [];
  w.open = (...args) => { abertas.push(args); return null; };
  if (config) w.TIA_EBAULA_CONFIG = config;
  // o jsdom devolve readyState "loading" por um instante; dispara o DOMContentLoaded já.
  // (o plug-in ignora a segunda execução, então não há duplicidade)
  const carregarPlugin = () => {
    w.eval(CODIGO);
    if (w.document.readyState === "loading") { w.document.dispatchEvent(new w.Event("DOMContentLoaded")); }
  };
  if (carregar) carregarPlugin();
  const d = w.document;
  return {
    w, d, abertas, carregarPlugin,
    botao: () => d.querySelector(".tia-ebaula__botao"),
    painel: () => d.querySelector(".tia-ebaula__painel"),
    iframe: () => d.querySelector(".tia-ebaula__iframe"),
  };
}

test("mostra o botão, mas não carrega o TIA antes do clique", () => {
  const p = pagina();
  assert.equal(p.botao().textContent, "Tutor TIA");
  assert.equal(p.botao().getAttribute("aria-expanded"), "false");
  assert.equal(p.painel().hidden, true);
  assert.equal(p.iframe(), null);               // nada de TIA até o aluno pedir
  assert.equal(p.d.querySelector('link[rel="stylesheet"]').href, `${TIA}/app/plugin/tia-ebaula.css`);
});

test("ao clicar, abre o painel com o iframe do TIA, com sandbox e sem referer", () => {
  const p = pagina();
  p.botao().click();
  assert.equal(p.painel().hidden, false);
  assert.equal(p.botao().getAttribute("aria-expanded"), "true");
  const f = p.iframe();
  assert.equal(f.src, `${TIA}/app/?origem=ebaula`);
  assert.match(f.getAttribute("sandbox"), /allow-scripts/);
  assert.doesNotMatch(f.getAttribute("sandbox"), /allow-top-navigation/);
  assert.equal(f.getAttribute("referrerpolicy"), "no-referrer");
  assert.equal(f.getAttribute("allow"), "");
  assert.equal(f.title, "Tutor TIA");
  assert.equal(p.d.querySelector(".tia-ebaula__acao[target]").href, `${TIA}/app/?origem=ebaula`);
  assert.equal(p.d.querySelector(".tia-ebaula__acao[target]").rel, "noopener noreferrer");
});

test("abrir de novo não cria outro iframe; alternar abre e fecha", () => {
  const p = pagina();
  p.w.TIAEbaula.abrir(); p.w.TIAEbaula.abrir();
  assert.equal(p.d.querySelectorAll("iframe").length, 1);
  p.w.TIAEbaula.alternar();
  assert.equal(p.painel().hidden, true);
  p.w.TIAEbaula.alternar();
  assert.equal(p.painel().hidden, false);
  assert.equal(p.d.querySelectorAll("iframe").length, 1);
});

test("Esc e o botão Fechar fecham o painel e devolvem o foco ao botão", () => {
  const p = pagina();
  p.d.body.focus();
  p.botao().click();
  p.d.dispatchEvent(new p.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(p.painel().hidden, true);
  assert.equal(p.d.activeElement, p.botao());
  p.botao().click();
  [...p.d.querySelectorAll("button.tia-ebaula__acao")].find((b) => b.textContent === "Fechar").click();
  assert.equal(p.painel().hidden, true);
});

test("ampliar alterna a classe e o estado do botão", () => {
  const p = pagina();
  p.botao().click();
  const ampliar = [...p.d.querySelectorAll("button.tia-ebaula__acao")].find((b) => b.textContent === "Ampliar");
  ampliar.click();
  assert.ok(p.d.querySelector(".tia-ebaula").classList.contains("tia-ebaula--ampliado"));
  assert.equal(ampliar.getAttribute("aria-pressed"), "true");
  assert.equal(ampliar.textContent, "Reduzir");
});

test("modo aba: não cria painel nem iframe e abre o TIA com noopener", () => {
  const p = pagina({ config: { url: TIA, modo: "aba" } });
  assert.equal(p.painel(), null);
  p.botao().click();
  assert.equal(p.iframe(), null);
  assert.deepEqual(p.abertas, [[`${TIA}/app/?origem=ebaula`, "_blank", "noopener,noreferrer"]]);
});

test("lê a configuração dos atributos data- da tag script", () => {
  const p = pagina({ config: null, atributos: `data-tia-url="${TIA}/tia" data-tia-titulo="Tutor do curso" data-tia-posicao="esquerda"` });
  assert.equal(p.botao().textContent, "Tutor do curso");
  assert.ok(p.d.querySelector(".tia-ebaula").classList.contains("tia-ebaula--esquerda"));
  p.botao().click();
  assert.equal(p.iframe().src, `${TIA}/tia/app/?origem=ebaula`);   // TIA atrás de um caminho de proxy
});

test("a configuração global vale mais que os atributos", () => {
  const p = pagina({ config: { url: TIA, titulo: "Global" }, atributos: `data-tia-url="https://outro.exemplo.org" data-tia-titulo="Atributo"` });
  assert.equal(p.botao().textContent, "Global");
});

for (const [nome, url] of [
  ["sem URL", ""],
  ["http fora de localhost", "http://tia.exemplo.eb.mil.br"],
  ["javascript:", "javascript:alert(1)"],
  ["data:", "data:text/html,<script>alert(1)</script>"],
  ["com usuário e senha", "https://aluno:senha@tia.exemplo.eb.mil.br"],
]) {
  test(`URL recusada (${nome}): o plug-in não aparece`, () => {
    const p = pagina({ config: { url } });
    assert.equal(p.d.querySelector(".tia-ebaula"), null);
    assert.equal(p.w.TIAEbaula, undefined);
  });
}

test("http em localhost é aceito (desenvolvimento)", () => {
  const p = pagina({ config: { url: "http://localhost:8000" } });
  p.botao().click();
  assert.equal(p.iframe().src, "http://localhost:8000/app/?origem=ebaula");
});

test("caminho que tenta sair da origem é ignorado", () => {
  const p = pagina({ config: { url: TIA, caminho: "//evil.example/x" } });
  p.botao().click();
  assert.equal(new URL(p.iframe().src).origin, TIA);
});

test("só obedece mensagens da origem do TIA e do próprio iframe", () => {
  const p = pagina();
  p.botao().click();
  const msg = (origin, source, data) => p.w.dispatchEvent(new p.w.MessageEvent("message", { origin, source, data }));
  msg("https://evil.example", p.iframe().contentWindow, { tipo: "tia:fechar" });
  assert.equal(p.painel().hidden, false);                          // origem errada
  msg(TIA, p.w, { tipo: "tia:fechar" });
  assert.equal(p.painel().hidden, false);                          // não veio do iframe
  msg(TIA, p.iframe().contentWindow, "tia:fechar");
  assert.equal(p.painel().hidden, false);                          // formato inválido
  msg(TIA, p.iframe().contentWindow, { tipo: "tia:fechar" });
  assert.equal(p.painel().hidden, true);                           // tudo certo
  p.botao().click();
  msg(TIA, p.iframe().contentWindow, { tipo: "tia:abrir-em-aba" });
  assert.equal(p.abertas.length, 1);
});

test("se o TIA não carregar, avisa e aponta a nova aba", async () => {
  const p = pagina({ config: { url: TIA, espera: 1000 } });
  p.botao().click();
  const estado = p.d.querySelector(".tia-ebaula__estado");
  assert.equal(estado.hidden, false);
  assert.match(estado.textContent, /Carregando/);
  await new Promise((ok) => setTimeout(ok, 1100));
  assert.match(estado.textContent, /Abrir em nova aba/);
});

test("quando o iframe carrega, o aviso some e o temporizador é cancelado", async () => {
  const p = pagina({ config: { url: TIA, espera: 1000 } });
  p.botao().click();
  p.iframe().dispatchEvent(new p.w.Event("load"));
  const estado = p.d.querySelector(".tia-ebaula__estado");
  assert.equal(estado.hidden, true);
  await new Promise((ok) => setTimeout(ok, 1100));
  assert.equal(estado.hidden, true);
});

test("lembra que o painel estava aberto na mesma sessão do navegador", () => {
  const p = pagina();
  p.botao().click();
  assert.equal(p.w.sessionStorage.getItem("tia-ebaula:aberto"), "1");
  // outra página da mesma sessão
  const q = pagina({ carregar: false });
  q.w.sessionStorage.setItem("tia-ebaula:aberto", "1");
  q.carregarPlugin();
  assert.equal(q.painel().hidden, false);
  assert.ok(q.iframe());
});

test("funciona sem sessionStorage (janela privativa ou bloqueado)", () => {
  const p = pagina({ carregar: false });
  Object.defineProperty(p.w, "sessionStorage", { get() { throw new Error("bloqueado"); } });
  p.carregarPlugin();
  p.botao().click();
  assert.equal(p.painel().hidden, false);
});

test("carregar o script duas vezes não duplica o botão", () => {
  const p = pagina();
  p.carregarPlugin();
  assert.equal(p.d.querySelectorAll("[data-tia-ebaula]").length, 1);
});

test("aberto=1 abre o painel ao carregar, sem roubar o foco", () => {
  const p = pagina({ config: { url: TIA, aberto: "1" } });
  assert.equal(p.painel().hidden, false);
  assert.notEqual(p.d.activeElement, p.painel());
});

test("o texto do título entra como texto, nunca como HTML", () => {
  const p = pagina({ config: { url: TIA, titulo: "<img src=x onerror=alert(1)>" } });
  assert.equal(p.d.querySelector("img"), null);
  assert.equal(p.botao().textContent, "<img src=x onerror=alert(1)>");
});
