// Service worker: pergunta ao app (native messaging) se deve esconder os
// curtos e guarda a resposta. O app (host_curtos.py) lê o config_efetivo,
// então o modo restrito mantém ligado mesmo que o config.json seja editado.
const HOST = "com.bloqueadortela.curtos";
const PADRAO = { bloquear_shorts: false, restrito: false };

let ajuste = PADRAO;
let ultimaConsulta = 0;

async function perguntarAoApp(forcar) {
  // no máximo uma chamada ao app a cada 45 s, não importa quantas abas peçam
  // (cada chamada abre um processo do host): entre elas, devolve o cache
  const agora = Date.now();
  if (!forcar && agora - ultimaConsulta < 45000) return ajuste;
  ultimaConsulta = agora;
  try {
    const r = await chrome.runtime.sendNativeMessage(HOST, { pedido: "ajuste" });
    if (r && typeof r.bloquear_shorts === "boolean") {
      ajuste = r;
      await chrome.storage.local.set({ ajuste });
    }
  } catch (e) {
    // app fechado ou host não instalado: mantém o último conhecido.
    // Se nunca soube, fica no padrão (não esconde) para não "quebrar" o site.
  }
  return ajuste;
}

// cache inicial do disco (sobrevive a reinícios do service worker)
chrome.storage.local.get("ajuste").then((d) => {
  if (d && d.ajuste) ajuste = d.ajuste;
  perguntarAoApp(true);
});

// relê de tempos em tempos (o Painel pode ter mudado)
chrome.alarms.create("rever", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "rever") perguntarAoApp(true);
});

// os content scripts pedem o ajuste atual
chrome.runtime.onMessage.addListener((msg, _remetente, responder) => {
  if (msg === "ajuste") {
    perguntarAoApp().then(responder);
    return true; // resposta assíncrona
  }
});
