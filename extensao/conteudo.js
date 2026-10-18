// Esconde os vídeos curtos da página, sem cobrir: aplica um <style> que some
// com os elementos de Shorts/Reels/feed Para Você. Liga/desliga conforme o
// ajuste que o app manda (via fundo.js). Como os sites trocam de layout, as
// regras são por atributos estáveis (href, aria, data-e2e), não por classes.

const SITE = location.hostname.replace(/^www\./, "");

// --- regras de CSS por site ---
const REGRAS = {
  "youtube.com": `
    /* atalho lateral e miniatalho */
    ytd-guide-entry-renderer:has(a[title="Shorts"]),
    ytd-mini-guide-entry-renderer:has(a[title="Shorts"]),
    /* prateleiras de Shorts na home e nos resultados */
    ytd-rich-section-renderer:has(ytd-rich-shelf-renderer[is-shorts]),
    ytd-reel-shelf-renderer,
    grid-shelf-view-model:has(a[href*="/shorts/"]),
    /* itens avulsos que levam a /shorts/ */
    ytd-video-renderer:has(a[href^="/shorts/"]),
    ytd-rich-item-renderer:has(a[href^="/shorts/"]),
    ytd-grid-video-renderer:has(a[href^="/shorts/"]),
    /* aba "Shorts" nos canais */
    yt-tab-shape[tab-title="Shorts"],
    tp-yt-paper-tab:has(> .tab-content[title="Shorts"]) {
      display: none !important;
    }`,
  "instagram.com": `
    /* item "Reels" do menu lateral */
    a[href="/reels/"][role="link"],
    div[role="navigation"] a[href="/reels/"],
    /* reels na grade do explorar/perfil */
    a[href*="/reel/"] {
      display: none !important;
    }`,
  "tiktok.com": `
    /* só o feed "Para Você" da home (mantém busca, perfil, vídeo aberto) */
    [data-e2e="recommend-list-item-container"],
    div[class*="DivForYouFeed"],
    div[class*="DivVideoFeed"] {
      display: none !important;
    }`,
};

const ID_ESTILO = "bloqueador-curtos-estilo";

function aplicar(ligado) {
  const existente = document.getElementById(ID_ESTILO);
  if (ligado && REGRAS[SITE]) {
    if (!existente) {
      const s = document.createElement("style");
      s.id = ID_ESTILO;
      s.textContent = REGRAS[SITE];
      (document.head || document.documentElement).appendChild(s);
    }
    redirecionar();
  } else if (existente) {
    existente.remove();
  }
}

// YouTube: abre /shorts/ID como vídeo normal (/watch?v=ID), sem o feed viciante.
// Instagram: a aba /reels/ e cada reel aberto (/reel/ID) voltam para a home.
function redirecionar() {
  const p = location.pathname;
  if (SITE === "youtube.com") {
    const m = p.match(/^\/shorts\/([\w-]+)/);
    if (m) location.replace("/watch?v=" + m[1]);
  } else if (SITE === "instagram.com") {
    if (/^\/reels\/?$/.test(p) || /^\/reel\/[\w.-]+/.test(p)) location.replace("/");
  }
}

let ligadoAgora = false;

function pedirEaplicar() {
  chrome.runtime.sendMessage("ajuste", (a) => {
    if (chrome.runtime.lastError) return; // service worker reiniciando
    ligadoAgora = !!(a && a.bloquear_shorts);
    aplicar(ligadoAgora);
  });
}

pedirEaplicar();

// o YouTube/Instagram/TikTok trocam de página sem recarregar (SPA). Para o
// reel não chegar a tocar, intercepto a navegação na hora: quando o site
// chama history.pushState/replaceState (clicar num post abre /reel/...),
// redireciono no mesmo instante, antes de o vídeo carregar.
let ultimaUrl = location.href;
function aoNavegar() {
  if (location.href !== ultimaUrl) {
    ultimaUrl = location.href;
    if (ligadoAgora) redirecionar();
  }
}
for (const metodo of ["pushState", "replaceState"]) {
  const original = history[metodo];
  history[metodo] = function () {
    const r = original.apply(this, arguments);
    aoNavegar();
    return r;
  };
}
window.addEventListener("popstate", aoNavegar);
setInterval(aoNavegar, 300);  // rede de segurança
setInterval(pedirEaplicar, 30000);
