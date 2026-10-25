# Plug-in do TIA para o EBAULA (EAP 1.4.3)

Um botão "Tutor TIA" que o EBAULA mostra em suas páginas. Ao clicar, abre um painel com o TIA
dentro de um iframe (ou o TIA em uma nova aba, se o EBAULA não puder embutir).

> **Situação:** feito sem acesso ao EBAULA. Foi testado só em um navegador simulado (jsdom) e nos
> testes Python de cabeçalhos. Falta validar no EBAULA de verdade (ver "O que ainda precisa do EBAULA").

## Onde está o código

| Arquivo | Para quê |
|---|---|
| `src/tia/web/static/plugin/tia-ebaula.js` | o plug-in (sem dependências) |
| `src/tia/web/static/plugin/tia-ebaula.css` | estilo do botão e do painel (variáveis `--tia-cor-*`) |
| `plugin-ebaula/demo/ebaula_simulado.html` | página que imita o EBAULA, para ver o botão funcionando |
| `plugin-ebaula/teste/` | teste automático do plug-in (Node + jsdom) |
| `tests/test_plugin_ebaula.py` | testes do servidor: arquivos servidos e cabeçalhos |

O TIA já serve os dois arquivos em `/app/plugin/` (sem login), então o EBAULA só precisa de uma tag.

## Instalação (quem administra o EBAULA)

1. No servidor do TIA, defina em `.env` quem pode embutir o TIA e reinicie:
   `TIA_FRAME_ANCESTORS=https://ebaula.exemplo.eb.mil.br`
   (várias origens separadas por espaço; aceita `https://*.dominio`; `*` e http fora de localhost são recusados).
2. No nginx, remova a linha `X-Frame-Options DENY` (comentada em `deploy/proxy/nginx-tia.conf`).
3. No modelo de página do EBAULA, acrescente:
   ```html
   <script src="https://tia.exemplo.eb.mil.br/app/plugin/tia-ebaula.js"
           data-tia-url="https://tia.exemplo.eb.mil.br" defer></script>
   ```

## Opções

Atributos `data-` na tag, ou `window.TIA_EBAULA_CONFIG = {...}` definido antes (o global vale mais).

| Opção | Padrão | O que faz |
|---|---|---|
| `url` | (obrigatória) | endereço do TIA, sem `/app`. https (http só em localhost) |
| `modo` | `iframe` | `aba` abre o TIA em nova aba, sem painel |
| `titulo` | `Tutor TIA` | texto do botão e do painel |
| `posicao` | `direita` | ou `esquerda` |
| `aberto` | `0` | `1` abre o painel ao carregar |
| `caminho` | `/app/` | caminho da aplicação do aluno |
| `css` | ao lado do script | URL do CSS |
| `espera` | `15000` | ms até avisar que o TIA não carregou |

API em JavaScript: `TIAEbaula.abrir()`, `.fechar()`, `.alternar()`.

## Segurança

- O TIA só carrega depois do clique; o iframe usa `sandbox` (sem navegar a página do EBAULA), `referrerpolicy="no-referrer"` e sem permissões de câmera/microfone.
- Mensagens `postMessage` só são aceitas da origem do TIA e do próprio iframe.
- Nenhuma credencial, nome ou dado do aluno passa pelo plug-in: o login é feito dentro do TIA (R08).
- O script não usa `innerHTML`, `eval`, `localStorage`, cookies nem `fetch` (testado).
- `frame-ancestors` só é liberado nas páginas `/app`; a API continua `'none'`.

## Testes

```
./run_tests.sh tests/test_plugin_ebaula.py        # servidor
cd plugin-ebaula/teste && npm install && npm test  # navegador simulado (Node 18+)
```

Para ver o botão: abra `plugin-ebaula/demo/ebaula_simulado.html` (ajuste a URL do TIA dentro dela;
para teste local, rode o TIA em `http://localhost:8000` com `TIA_FRAME_ANCESTORS=http://localhost:8080`
e sirva a pasta com `python -m http.server 8080`).

## O que ainda precisa do EBAULA

1. **Cookies:** o login do TIA usa `SameSite=Strict`. No iframe só funciona se o TIA ficar no mesmo
   site do EBAULA (ex.: `tia.ebaula.eb.mil.br`). Se não, usar o modo `aba` ou rever a alternativa C/D
   de `docs/seguranca/implantacao.md`.
2. Confirmar se o EBAULA permite incluir um `<script>` externo (CSP do próprio EBAULA: `script-src`, `frame-src`).
3. Ajustar as cores ao tema do EBAULA (variáveis do CSS).
4. Lançamento automático (aluno já logado no EBAULA entra direto no TIA): depende do EBAULA oferecer
   LTI ou token; hoje o aluno faz login no TIA.
