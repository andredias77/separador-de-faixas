const MAXV = 150, NDOTS = 22, NBARRAS = 120, GUARDA = "mesa-beatles-v2";
// canais da mesa, na ordem do design; ids = arquivos gerados pelo separar.py
const CANAIS = [["vocals", "voz"], ["guitar", "guitarra"], ["bass", "baixo"], ["drums", "bateria"], ["piano", "piano"], ["other", "outros"]];
const NUM = ["I", "II", "III", "IV", "V", "VI"];
const ATALHOS = [
  ["Original", [100, 100, 100, 100, 100, 100]], ["Voz + baixo", [100, 0, 100, 0, 0, 0]], ["Só baixo", [0, 0, 100, 0, 0, 0]],
  ["Karaokê", [0, 100, 100, 100, 100, 100]], ["Só a voz", [100, 0, 0, 0, 0, 0]], ["Baixo e bateria", [0, 0, 100, 100, 0, 0]],
  ["Sem guitarra", [100, 0, 100, 100, 100, 100]], ["Guitarra em destaque", [80, 150, 80, 80, 80, 80]],
];
const $ = id => document.getElementById(id);
const romano = n => { let r = ""; for (const [v, s] of [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]]) while (n >= v) { r += s; n -= v; } return r; };
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const seg = d => { const [m, s] = (d || "0:00").split(":"); return +m * 60 + +s; };
const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- estado (mixagem e posição ficam guardadas no navegador) ---------- */
const est = { vista: "discos", album: 0, faixa: 0, versao: "", vols: [100, 100, 100, 100, 100, 100], geral: 100,
              mute: [0, 0, 0, 0, 0, 0], solo: [0, 0, 0, 0, 0, 0] };
try { Object.assign(est, JSON.parse(localStorage.getItem(GUARDA) || "{}"), { mute: [0, 0, 0, 0, 0, 0], solo: [0, 0, 0, 0, 0, 0] }); } catch {}
const guardar = () => { try { localStorage.setItem(GUARDA, JSON.stringify({ vista: est.vista, album: est.album, faixa: est.faixa, versao: est.versao, vols: est.vols, geral: est.geral })); } catch {} };

let cat = { albuns: [] };
let repintarLista = null, repintarPagina = null;   // trilhos de rolagem (montados mais abaixo)
const albumAtual = () => cat.albuns[est.album] || { titulo: "", ano: "", capa: "", faixas: [] };
const faixaAtual = () => albumAtual().faixas[est.faixa];

/* ---------- áudio ----------
   Passagem sem lacuna entre faixas: enquanto uma toca, a próxima do álbum já é baixada e decodificada e
   fica agendada no relógio do áudio para começar na amostra exata em que a atual termina. O contexto roda
   em 44,1 kHz (a taxa das faixas), então nada é reamostrado. Os 6 canais da mesa são fixos: cada faixa
   nova entra neles, e volume/mudo/solo continuam iguais. */
const ctx = new AudioContext({ sampleRate: 44100, latencyHint: "playback" });
const ganhoGeral = ctx.createGain();
// limitador: segura os picos logo abaixo do máximo (volumes acima de 100% não saturam nem chiam)
const limitador = ctx.createDynamicsCompressor();
limitador.threshold.value = -1.5; limitador.knee.value = 0; limitador.ratio.value = 20; limitador.attack.value = 0.002; limitador.release.value = 0.15;
ganhoGeral.connect(limitador); limitador.connect(ctx.destination);
const anGeral = ctx.createAnalyser(); anGeral.fftSize = 1024; ganhoGeral.connect(anGeral);
const canal = CANAIS.map(() => {
  const g = ctx.createGain(), an = ctx.createAnalyser();
  an.fftSize = 1024; g.connect(an); g.connect(ganhoGeral);
  return { g, an };
});
let faixas = [], tocando = false, inicio = 0, offset = 0, duracao = 0, picos = [], carregada = "", pedido = 0;
let fontesAtual = [], fontesProx = [];   // fontes de áudio da faixa atual e da próxima (já agendada)
let prox = null, pedidoProx = 0;         // próxima faixa: { j, pasta, faixas, duracao, agendada }
const niveis = [0, 0, 0, 0, 0, 0]; let nivelGeral = 0;

async function baixarCanal(pasta, id, i) {
  const r = await fetch(`faixas/${encodeURIComponent(pasta)}/${id}.flac`);
  if (!r.ok) return null;
  return { i, buffer: await ctx.decodeAudioData(await r.arrayBuffer()) };
}
async function baixar(pasta, devagar = false) {
  // a faixa que vai tocar já: tudo em paralelo (mais rápido). A próxima (devagar): um canal por vez,
  // para não dar pico de CPU/memória enquanto a música toca
  let fs;
  if (!devagar) fs = await Promise.all(CANAIS.map(([id], i) => baixarCanal(pasta, id, i)));
  else { fs = []; for (const [i, [id]] of CANAIS.entries()) fs.push(await baixarCanal(pasta, id, i)); }
  return { faixas: fs, duracao: Math.max(...fs.filter(Boolean).map(f => f.buffer.duration)) };
}
async function carregar(pasta, tocarDepois) {
  const meu = ++pedido;
  pedidoProx++; parar(); prox = null; offset = 0; duracao = 0; picos = []; montarOnda();
  $("play").disabled = $("inicio").disabled = true;
  $("aviso").textContent = "Carregando as faixas…";
  try {
    const r = await baixar(pasta);
    if (meu !== pedido) return;   // o usuário já trocou de faixa
    faixas = r.faixas; duracao = r.duracao; carregada = pasta;
    calcularPicos(); montarOnda(); aplicar(); montarCabecalhoFaixa();
    $("play").disabled = $("inicio").disabled = false;
    $("aviso").textContent = "";
    if (tocarDepois) tocar();
    prepararProxima();
  } catch (e) {
    if (meu === pedido) $("aviso").textContent = "Não consegui carregar as faixas desta versão.";
  }
}
function agendar(fs, quando, desde) {
  return fs.filter(Boolean).map(f => {
    const s = ctx.createBufferSource(); s.buffer = f.buffer; s.connect(canal[f.i].g); s.start(quando, desde);
    return s;
  });
}
function tocar() {
  if (!duracao) return;
  ctx.resume();
  const t = ctx.currentTime + 0.05;   // todos os canais começam no mesmo instante → sincronizados
  fontesAtual = agendar(faixas, t, offset);
  inicio = t - offset; tocando = true; marcarPlay();
  agendarProxima();
}
function agendarProxima() {
  if (!tocando || !prox || !prox.faixas || prox.agendada) return;
  const fim = inicio + duracao;   // instante exato (no relógio do áudio) em que a atual acaba
  if (fim - ctx.currentTime < 0.05) return;   // tarde demais para emendar sem corte
  fontesProx = agendar(prox.faixas, fim, 0);
  prox.agendada = true;
}
function prepararProxima() {
  const meu = ++pedidoProx;
  const j = proximaDisponivel(1);
  if (j < 0) { prox = null; return; }
  const f = albumAtual().faixas[j];
  prox = { j, pasta: f.versoes[0].pasta, faixas: null, agendada: false };
  const espera = Math.max(0, Math.min(8, duracao - agora() - 30)) * 1000;   // deixa a música assentar antes de pré-carregar
  new Promise(ok => setTimeout(ok, espera)).then(() => meu === pedidoProx ? baixar(prox.pasta, true) : Promise.reject()).then(r => {
    if (meu !== pedidoProx || !prox) return;
    prox.faixas = r.faixas; prox.duracao = r.duracao;
    agendarProxima();
  }).catch(() => { if (meu === pedidoProx) prox = null; });
}
function parar() {
  if (!tocando) return;
  offset = Math.min(ctx.currentTime - inicio, duracao);
  for (const s of [...fontesAtual, ...fontesProx]) { try { s.stop(); } catch {} }
  fontesAtual = []; fontesProx = [];
  if (prox) prox.agendada = false;
  tocando = false; marcarPlay();
}
// fim da faixa: se a próxima já estava agendada, ela começou sozinha, sem lacuna — só atualiza a tela
function verificarFim() {
  if (!tocando || ctx.currentTime < inicio + duracao) return;
  if (prox && prox.agendada) {
    inicio += duracao;
    faixas = prox.faixas; duracao = prox.duracao; carregada = prox.pasta;
    est.faixa = prox.j; est.versao = prox.pasta;
    fontesAtual = fontesProx; fontesProx = []; prox = null;
    guardar(); calcularPicos(); montarOnda(); montarAlbum();
    prepararProxima();   // e já começa a preparar a seguinte
  } else {               // a próxima não chegou a tempo (ou é a última): para e carrega do jeito normal
    parar(); offset = 0;
    const j = proximaDisponivel(1);
    if (j >= 0) escolherFaixa(j, true);
  }
}
setInterval(verificarFim, 100);   // fora do desenho da tela: funciona mesmo com a aba em segundo plano
function marcarPlay() {
  $("play").textContent = tocando ? "❚❚" : "▶";
  $("play").setAttribute("aria-label", tocando ? "Pausar" : "Tocar");
  $("ponto").classList.toggle("tocando", tocando);
}
function irPara(s) { const t = tocando; parar(); offset = Math.max(0, Math.min(s, duracao)); if (t) tocar(); }
const agora = () => (tocando ? ctx.currentTime - inicio : offset);

/* ---------- forma de onda (nível real da mistura) ---------- */
function calcularPicos() {
  const p = new Float32Array(NBARRAS);
  for (const f of faixas.filter(Boolean)) {
    const d = f.buffer.getChannelData(0), passo = Math.floor(d.length / NBARRAS);
    for (let i = 0; i < NBARRAS; i++) { let s = 0, n = 0; for (let j = i * passo; j < (i + 1) * passo; j += 64) { s += d[j] * d[j]; n++; } p[i] += Math.sqrt(s / n); }
  }
  const max = Math.max(...p) || 1;
  picos = Array.from(p, v => Math.max(3, Math.round(4 + 24 * (v / max))));
}
let barraAnterior = -1;
function montarOnda() {
  const hs = picos.length ? picos : Array(NBARRAS).fill(3);
  $("onda").innerHTML = hs.map(h => `<i style="height:${h}px"></i>`).join("") + `<div class="cabeca" id="cabeca"></div>`;
  barraAnterior = -1;
}
$("onda").addEventListener("click", e => { const r = e.currentTarget.getBoundingClientRect(); irPara((e.clientX - r.left) / r.width * duracao); });
$("onda").addEventListener("keydown", e => { const d = { ArrowRight: 5, ArrowLeft: -5 }[e.key]; if (d) { e.preventDefault(); e.stopPropagation(); irPara(agora() + d); } });

/* ---------- mesa de som ---------- */
function canalHTML(i) {
  const geral = i === 6, nome = geral ? "geral" : CANAIS[i][1];
  const riscos = [0, 33.333, 66.667, 100].map(t => `<div class="risco${t === 33.333 ? " cem" : ""}" style="${t === 100 ? "bottom:0" : `top:${t}%`}"></div>`).join("");
  return `<div class="canal${geral ? " geral" : ""}" data-i="${i}">
    <div class="numeral">${geral ? "Ω" : NUM[i]}</div>
    <div class="nome">${nome}</div>
    <div class="ms">${geral ? "" : `<button class="m" title="Mudo (${i + 1})" aria-pressed="false">m</button><button class="s" title="Solo" aria-pressed="false">s</button>`}</div>
    <div class="trilho">
      <div class="pontos">${"<i></i>".repeat(NDOTS)}</div>
      <div class="fader" role="slider" tabindex="0" aria-label="Volume: ${nome}" aria-valuemin="0" aria-valuemax="${MAXV}" title="Arraste · duplo clique volta a 100%">
        <div class="linha"></div>${riscos}<div class="botao"><div><div></div></div></div>
      </div>
    </div>
    <div class="valor">100%</div>
  </div>`;
}
function montarMesa() {
  $("canais").innerHTML = [0, 1, 2, 3, 4, 5, 6].map(canalHTML).join("");
  document.querySelectorAll(".canal").forEach(el => {
    const i = +el.dataset.i, fader = el.querySelector(".fader");
    fader.addEventListener("pointerdown", e => {
      e.preventDefault(); fader.focus();
      const r = fader.getBoundingClientRect();
      const upd = ev => definir(i, Math.round((1 - (ev.clientY - r.top) / r.height) * MAXV));
      upd(e);
      const solta = () => { removeEventListener("pointermove", upd); removeEventListener("pointerup", solta); };
      addEventListener("pointermove", upd); addEventListener("pointerup", solta);
    });
    fader.addEventListener("dblclick", () => definir(i, 100));
    fader.addEventListener("keydown", e => {
      const p = { ArrowUp: 5, ArrowRight: 5, ArrowDown: -5, ArrowLeft: -5, PageUp: 25, PageDown: -25 }[e.key];
      if (p) { e.preventDefault(); e.stopPropagation(); definir(i, valor(i) + p, false); }
    });
    if (i < 6) { el.querySelector(".m").onclick = () => alternar("mute", i); el.querySelector(".s").onclick = () => alternar("solo", i); }
  });
  $("atalhos").innerHTML = `<span class="sc">mixagem</span>` + ATALHOS.map(([n], k) => `<button class="pilula" data-k="${k}">${n}</button>`).join("");
  $("atalhos").querySelectorAll("button").forEach(b => b.onclick = () => { est.vols = ATALHOS[+b.dataset.k][1].slice(); est.mute.fill(0); est.solo.fill(0); aplicar(); });
}
const valor = i => (i === 6 ? est.geral : est.vols[i]);
function definir(i, v, imantar = true) {
  v = Math.max(0, Math.min(MAXV, v));
  if (imantar && Math.abs(v - 100) <= 3) v = 100;   // gruda em 100%
  if (i === 6) est.geral = v; else est.vols[i] = v;
  aplicar();
}
function alternar(k, i) { est[k][i] = est[k][i] ? 0 : 1; aplicar(); }
const audivel = i => !est.mute[i] && (!est.solo.some(Boolean) || est.solo[i]);
function aplicar() {
  const t = ctx.currentTime;
  canal.forEach((c, i) => c.g.gain.setTargetAtTime(audivel(i) ? est.vols[i] / 100 : 0, t, 0.02));
  ganhoGeral.gain.setTargetAtTime(est.geral / 100, t, 0.02);
  document.querySelectorAll(".canal").forEach(el => {
    const i = +el.dataset.i, v = valor(i);
    el.querySelector(".botao").style.top = ((1 - v / MAXV) * 100).toFixed(2) + "%";
    el.querySelector(".valor").textContent = v + "%";
    const fd = el.querySelector(".fader"); fd.setAttribute("aria-valuenow", v); fd.setAttribute("aria-valuetext", v + "%");
    if (i === 6) return;
    el.classList.toggle("calado", !audivel(i));
    for (const [c, k] of [["m", "mute"], ["s", "solo"]]) { const b = el.querySelector("." + c); b.classList.toggle("on", !!est[k][i]); b.setAttribute("aria-pressed", !!est[k][i]); }
  });
  const semMS = !est.mute.some(Boolean) && !est.solo.some(Boolean);
  $("atalhos").querySelectorAll("button").forEach(b => b.classList.toggle("ativa", semMS && ATALHOS[+b.dataset.k][1].every((x, i) => x === est.vols[i])));
  guardar();
}

/* ---------- discos (página 1) ---------- */
function montarEstante() {
  $("estante").innerHTML = cat.albuns.map((a, i) => {
    const prontas = a.faixas.filter(f => f.versoes.length).length;
    return `<button class="disco" data-i="${i}">
      <div class="moldura-capa"><img src="${a.capa}" alt="${esc(a.titulo)}" loading="lazy"></div>
      <div class="linha1"><span class="num">${romano(i + 1)}</span><span class="nome">${esc(a.titulo)}</span></div>
      <div class="sc">${a.ano ? a.ano + " · " : ""}${a.faixas.length} faixas${prontas ? ` · ${prontas} na mesa` : ""}</div>
    </button>`;
  }).join("");
  $("estante").querySelectorAll(".disco").forEach(b => b.onclick = () => abrirAlbum(+b.dataset.i));
}

/* ---------- álbum + faixas (página 2) ---------- */
function montarAlbum() {
  const a = albumAtual();
  $("capa").src = a.capa; $("capa").alt = a.titulo;
  $("al-titulo").textContent = a.titulo;
  const total = a.faixas.reduce((s, f) => s + seg(f.duracao), 0);
  const prontas = a.faixas.filter(f => f.versoes.length).length;
  $("al-info").textContent = `${a.ano ? a.ano + " · " : ""}${a.faixas.length} faixas · ${Math.round(total / 60)} min · ${prontas} na mesa`;
  const n = cat.albuns.length;
  $("al-ant").title = n ? cat.albuns[(est.album - 1 + n) % n].titulo : "";
  $("al-prox").title = n ? cat.albuns[(est.album + 1) % n].titulo : "";
  $("lista").innerHTML = a.faixas.map((f, j) => {
    const ok = f.versoes.length > 0;
    return `<button class="faixa${j === est.faixa ? " atual" : ""}" data-j="${j}" ${ok ? "" : 'disabled title="ainda não separada"'}>
      <span class="n">${String(j + 1).padStart(2, "0")}</span>
      <span class="t">${esc(f.titulo)}${f.album || f.versoes.length > 1 ? `<span class="v">${[f.album ? esc(f.album) : "", f.versoes.length > 1 ? f.versoes.length + " versões" : ""].filter(Boolean).join(" · ")}</span>` : ""}</span>
      <span class="d">${f.duracao || ""}</span></button>`;
  }).join("");
  $("lista").querySelectorAll(".faixa").forEach(b => b.onclick = () => escolherFaixa(+b.dataset.j, true));
  const atual = $("lista").querySelector(".atual"); if (atual) atual.scrollIntoView({ block: "nearest" });
  if (repintarLista) repintarLista();
  montarCabecalhoFaixa();
}
function montarCabecalhoFaixa() {
  const a = albumAtual(), f = faixaAtual();
  const nome = f ? f.titulo : "";
  $("cap-faixa").textContent = nome[0] || ""; $("resto").textContent = nome.slice(1); $("resto").title = nome;
  $("posicao").textContent = f ? `faixa ${est.faixa + 1} de ${a.faixas.length}` : "";
  $("agora").textContent = carregada ? nome : "";
  const vs = f ? f.versoes : [];
  $("versoes").innerHTML = vs.length ? `<span class="sc">versão</span>` + vs.map(v =>
    `<button class="pilula versao${v.pasta === est.versao ? " ativa" : ""}" data-p="${esc(v.pasta)}">${esc(v.rotulo)}</button>`).join("") : "";
  $("versoes").querySelectorAll("button").forEach(b => b.onclick = () => {
    if (b.dataset.p === est.versao) return;
    est.versao = b.dataset.p; guardar(); montarCabecalhoFaixa(); carregar(est.versao, tocando);
  });
  $("proxima").disabled = proximaDisponivel(1) < 0;
  if (!vs.length && f) $("aviso").textContent = "Esta faixa ainda não foi separada.";
}
function proximaDisponivel(d) {
  const fs = albumAtual().faixas;
  for (let j = est.faixa + d; j >= 0 && j < fs.length; j += d) if (fs[j].versoes.length) return j;
  return -1;
}
function escolherFaixa(j, tocarDepois) {
  const f = albumAtual().faixas[j];
  if (!f || !f.versoes.length) return;
  est.faixa = j;
  if (!f.versoes.some(v => v.pasta === est.versao)) est.versao = f.versoes[0].pasta;   // a versão mais nova vem primeiro
  guardar(); montarAlbum(); carregar(est.versao, tocarDepois);
}
function abrirAlbum(i) {
  est.album = i; est.faixa = 0; mostrar("mesa");
  const primeira = albumAtual().faixas.findIndex(f => f.versoes.length);
  if (primeira >= 0) escolherFaixa(primeira, false);
  else { pedido++; pedidoProx++; parar(); prox = null; faixas = []; carregada = ""; duracao = 0; picos = []; montarOnda(); montarAlbum(); $("play").disabled = $("inicio").disabled = true; }
}
function passo(d) {
  if (d < 0 && agora() > 3) { irPara(0); return; }
  const j = proximaDisponivel(d);
  if (j >= 0) escolherFaixa(j, true);
}
function mostrar(v) {
  est.vista = v; guardar();
  $("pg-discos").hidden = v !== "discos"; $("pg-mesa").hidden = v !== "mesa"; $("pg-enviar").hidden = v !== "enviar";
  $("aba-discos").classList.toggle("ativa", v === "discos"); $("aba-mesa").classList.toggle("ativa", v === "mesa");
  $("aba-enviar").classList.toggle("ativa", v === "enviar");
  scrollTo(0, 0); ajustarAltura();
}

/* ---------- catálogo dinâmico: músicas recém-separadas aparecem sozinhas ---------- */
let catTexto = "";
async function lerCatalogo() {
  try {
    const texto = await (await fetch("catalogo.json", { cache: "no-store" })).text();
    if (texto === catTexto) return;
    catTexto = texto; cat = JSON.parse(texto);
    if (est.album >= cat.albuns.length) est.album = 0;
    montarEstante();
    const f = faixaAtual();
    if (f && f.versoes.length && !f.versoes.some(v => v.pasta === est.versao)) est.versao = f.versoes[0].pasta;
    montarAlbum();
    // a lista mudou (música nova separada): se a próxima ainda não foi agendada, prepara a certa
    if (carregada && (!prox || (!prox.agendada && prox.j !== proximaDisponivel(1)))) prepararProxima();
  } catch { $("aviso").textContent = "Não consegui ler o catálogo (o servidor está rodando? Abra pelo iniciar.bat)."; }
}

/* ---------- medidores, relógio, avanço automático ---------- */
const amostra = new Float32Array(1024);
function nivel(an) {
  an.getFloatTimeDomainData(amostra);
  let s = 0; for (const v of amostra) s += v * v;
  return Math.max(0, Math.min(1, (20 * Math.log10(Math.sqrt(s / amostra.length) + 1e-6) + 48) / 48));
}
function pintar(el, lv, geral) {
  const acesos = Math.round(lv * NDOTS);
  if (el._acesos === acesos) return;   // nada mudou: não toca no DOM
  el._acesos = acesos;
  el._pontos = el._pontos || [...el.querySelectorAll(".pontos i")];
  el._pontos.forEach((d, k) => {
    const on = k < acesos, quente = k >= NDOTS - 3, morno = k >= NDOTS - 8;
    d.style.background = !on ? "" : quente ? "var(--vermelho)" : morno ? (geral ? "var(--amarelo-escuro)" : "var(--amarelo)") : (geral ? "var(--tinta)" : "var(--papel)");
  });
}
let ultimo = performance.now();
function quadro(ms) {
  const queda = Math.pow(0.8, (ms - ultimo) / 80); ultimo = ms;   // ~0,8× a cada 80 ms
  for (let i = 0; i < 6; i++) niveis[i] = Math.max(tocando && faixas[i] ? nivel(canal[i].an) : 0, niveis[i] * queda);
  nivelGeral = Math.max(tocando ? nivel(anGeral) : 0, nivelGeral * queda);
  if (est.vista === "mesa") {
    document.querySelectorAll(".canal").forEach(el => { const i = +el.dataset.i; pintar(el, i === 6 ? nivelGeral : niveis[i], i === 6); });
    const pos = duracao ? agora() / duracao : 0;
    const cab = $("cabeca"); if (cab) cab.style.left = (pos * 100).toFixed(2) + "%";
    const b = Math.floor(pos * NBARRAS);
    if (b !== barraAnterior) { $("onda").querySelectorAll("i").forEach((x, k) => x.classList.toggle("tocada", (k + 0.5) / NBARRAS <= pos)); barraAnterior = b; }
    $("onda").setAttribute("aria-valuenow", Math.round(pos * 100));
    $("tempo").textContent = `${fmt(agora())} / ${fmt(duracao || seg(faixaAtual()?.duracao))}`;
  }
  requestAnimationFrame(quadro);
}

/* ---------- tamanho: tudo cabe na janela do notebook, sem rolar ---------- */
function ajustarAltura() {
  const raiz = document.documentElement;
  if (innerWidth <= 900) { raiz.style.removeProperty("--h-fader"); raiz.style.removeProperty("--h-lado"); }
  else {
    const pag = getComputedStyle(document.querySelector(".pagina"));
    const pads = parseFloat(pag.paddingTop) + parseFloat(pag.paddingBottom);
    const cab = document.querySelector("header").getBoundingClientRect().height + 14;
    raiz.style.setProperty("--h-lado", Math.max(380, innerHeight - pads - cab - 4) + "px");
    if (est.vista === "mesa") {
      const atual = document.querySelector(".fader").getBoundingClientRect().height;
      const ocupado = document.querySelector(".principal").getBoundingClientRect().height + cab + pads;
      raiz.style.setProperty("--h-fader", Math.max(80, Math.min(320, atual + innerHeight - ocupado - 2)) + "px");
    }
  }
  // estante: 5 colunas × 3 linhas cabendo na janela — começa pelo máximo da largura e mede de verdade
  if (innerWidth > 900 && est.vista === "discos") {
    let capa = Math.floor((document.querySelector(".conteudo").getBoundingClientRect().width - 4 * 40) / 5);
    for (let k = 0; k < 6; k++) {
      raiz.style.setProperty("--capa", capa + "px");
      const sobra = raiz.scrollHeight - innerHeight;
      if (sobra <= 0 || capa <= 90) break;
      capa = Math.max(90, capa - Math.ceil(sobra / 3) - 1);   // (título em 1 linha: a altura do texto é fixa)   // 3 linhas dividem o excesso
    }
  }
  if (repintarPagina) { repintarPagina(); repintarLista(); }   // trilhos medem de novo depois do ajuste
  // figuras só nas margens laterais, nunca por baixo do conteúdo
  const larg = document.querySelector(".conteudo").getBoundingClientRect().width;
  const h = Math.min(innerHeight * 0.94, 980), w = h * 0.342, margem = (innerWidth - larg) / 2 - 16;
  const visivel = Math.max(0, Math.min(w, margem)), mostra = visivel >= 70, esconde = mostra ? w - visivel : w + 20;
  for (const [id, sinal] of [["fig-esq", -1], ["fig-dir", 1]]) {
    const im = $(id); im.style.height = Math.round(h) + "px"; im.style.transform = `translateX(${sinal * Math.round(esconde)}px)`; im.style.opacity = mostra ? 1 : 0;
  }
}
addEventListener("resize", ajustarAltura);

/* ---------- teclado e botões ---------- */
$("aba-discos").onclick = () => mostrar("discos");
$("aba-mesa").onclick = () => mostrar("mesa");
$("play").onclick = () => (tocando ? parar() : tocar());
$("inicio").onclick = () => irPara(0);
$("proxima").onclick = () => passo(1);
$("al-ant").onclick = () => abrirAlbum((est.album - 1 + cat.albuns.length) % cat.albuns.length);
$("al-prox").onclick = () => abrirAlbum((est.album + 1) % cat.albuns.length);
addEventListener("keydown", e => {
  if (/SELECT|INPUT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === "Escape") { mostrar("discos"); return; }
  if (est.vista !== "mesa") return;
  if (e.code === "Space" && e.target.tagName !== "BUTTON") { e.preventDefault(); if (!$("play").disabled) $("play").click(); }
  else if (e.key === "Home") { e.preventDefault(); irPara(0); }
  else if (e.key === "ArrowRight" && !e.target.closest(".fader, .onda")) passo(1);
  else if (e.key === "ArrowLeft" && !e.target.closest(".fader, .onda")) passo(-1);
  else if (/^[1-6]$/.test(e.key)) alternar("mute", +e.key - 1);
});

/* ---------- rolagem decadente (lista de faixas e, se precisar, a página) ---------- */
function rolagemDecadente(alvo, ondeMontar, daPagina) {
  const INSET = 10, MIN = 30;
  const trilho = document.createElement("div");
  trilho.className = "trilho-rol" + (daPagina ? " pagina-rol" : "");
  trilho.setAttribute("role", "scrollbar"); trilho.setAttribute("aria-orientation", "vertical"); trilho.title = "Rolar";
  trilho.innerHTML = `<div class="fio"></div><div class="losango cima"></div><div class="losango baixo"></div>
    <div class="capsula"><div class="olho"><i></i></div></div>`;
  ondeMontar.appendChild(trilho);
  const cap = trilho.querySelector(".capsula");
  const vis = () => (daPagina ? innerHeight : alvo.clientHeight);
  const topo = () => (daPagina ? (document.scrollingElement || document.documentElement).scrollTop : alvo.scrollTop);
  const rolar = (y, suave) => (daPagina ? window : alvo).scrollTo({ top: y, behavior: suave ? "smooth" : "auto" });
  const total = () => (daPagina ? (document.scrollingElement || document.documentElement).scrollHeight : alvo.scrollHeight);
  function geo() {
    const vh = vis(), sh = total(), range = trilho.clientHeight - INSET * 2, max = Math.max(1, sh - vh);
    const th = Math.max(MIN, Math.round(range * vh / sh)), room = Math.max(0, range - th);
    return { mostra: sh > vh + 4, th, room, max, top: Math.round(INSET + room * Math.min(1, topo() / max)), pct: Math.round(100 * Math.min(1, topo() / max)) };
  }
  let raf = 0;
  const pintar = () => { raf = 0; const g = geo(); trilho.style.display = g.mostra ? "" : "none"; cap.style.height = g.th + "px"; cap.style.top = g.top + "px"; trilho.setAttribute("aria-valuenow", g.pct); };
  const agendar = () => { if (!raf) raf = requestAnimationFrame(pintar); };
  cap.addEventListener("pointerdown", e => {
    e.stopPropagation(); e.preventDefault();
    const g = geo(), y0 = e.clientY, t0 = topo();
    cap.classList.add("arrastando");
    const mv = ev => rolar(t0 + (ev.clientY - y0) * g.max / Math.max(1, g.room));
    const up = () => { cap.classList.remove("arrastando"); removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });
  trilho.addEventListener("pointerdown", e => {   // clique no fio: centraliza a cápsula ali
    const g = geo(), r = trilho.getBoundingClientRect();
    rolar(Math.max(0, Math.min(1, (e.clientY - r.top - INSET - g.th / 2) / Math.max(1, g.room))) * g.max, true);
  });
  (daPagina ? window : alvo).addEventListener("scroll", agendar, { passive: true });
  addEventListener("resize", agendar);
  new ResizeObserver(agendar).observe(daPagina ? document.body : alvo);
  new ResizeObserver(agendar).observe(trilho);   // o próprio trilho também muda de altura
  new MutationObserver(agendar).observe(alvo === document.body ? document.body : alvo, { childList: true });
  pintar();
  return agendar;
}
repintarLista = rolagemDecadente($("lista"), $("lista").parentElement, false);
repintarPagina = rolagemDecadente(document.body, document.body, true);

/* ---------- aba enviar: solta um arquivo, o servidor separa e a música entra na estante ---------- */
const ETAPAS_ENV = [["envio", "envio", "Enviando o arquivo…"], ["preparo", "preparo", "Preparando o áudio…"],
  ["voz", "voz", "Separando a voz…"], ["voz2", "voz (2º modelo)", "Conferindo a voz com o segundo modelo…"],
  ["instrumentos", "instrumentos", "Separando os instrumentos…"], ["acabamento", "acabamento", "Acabamento final…"]];
const env = { arquivo: null, dur: 0, id: null, envio: 0, lista: [] };
const simplesJS = t => t.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
const semParenteses = t => t.replace(/\s*\((mono|\d{4} (mix|remaster)|original single version)\)/gi, "").trim();
function destinoJS(titulo) {   // mesmo critério do servidor: disco com faixa de mesmo nome, ou All Songs
  const alvo = simplesJS(semParenteses(titulo));
  const al = cat.albuns.slice(0, -1).find(a => a.faixas.some(f => simplesJS(semParenteses(f.titulo)) === alvo));
  return al ? al.titulo : "All Songs";
}
function tituloDoArquivo(nome) {   // "The Beatles - Taxman (Official Audio) [abc].mp3" -> "Taxman"
  let t = nome.replace(/\.[^.]+$/, "").replace(/\[[^\]]*\]/g, "")
    .replace(/\((official|audio|lyric|visuali[sz]er|video|hd|hq)[^)]*\)/gi, "").replace(/_/g, " ");
  if (t.includes(" - ")) t = t.split(" - ").pop();
  return t.replace(/\s+/g, " ").trim();
}
function revelar(frac, andando) {   // os quatro atravessam da esquerda para a direita conforme a separação anda
  $("ilustra").style.setProperty("--falta", ((1 - frac) * 100).toFixed(1) + "%");
  $("ilustra").classList.toggle("parada", !andando);
}
function escolherArquivos(lista) {
  const fs = [...lista].filter(Boolean);
  if (!fs.length) return;
  $("env-erro").textContent = "";
  if (fs.length > 1) { fs.forEach(f => subir(f, tituloDoArquivo(f.name))); return; }   // vários: vão direto para a fila
  const f = fs[0];
  env.arquivo = f; env.dur = 0; env.id = null; env.envio = 0;
  const a = new Audio(); a.preload = "metadata";
  a.onloadedmetadata = () => { env.dur = isFinite(a.duration) ? a.duration : 0; $("env-dur").textContent = env.dur ? fmt(env.dur) : "—"; URL.revokeObjectURL(a.src); };
  a.src = URL.createObjectURL(f);
  $("env-titulo").value = tituloDoArquivo(f.name);
  $("env-nome").textContent = f.name; $("env-dur").textContent = "—";
  atualizarDestino(); revelar(0, false); desenharEnvio();
  $("env-titulo").focus();
}
function atualizarDestino() { $("env-vai").textContent = destinoJS($("env-titulo").value || "").toLowerCase(); }
function subir(arquivo, titulo) {   // envia o arquivo ao servidor (o progresso do envio é a primeira etapa)
  const x = new XMLHttpRequest();
  x.open("POST", `enviar?titulo=${encodeURIComponent(titulo)}&arquivo=${encodeURIComponent(arquivo.name)}`);
  const meu = arquivo === env.arquivo;
  if (meu) { env.envio = 0.001; desenharEnvio(); }
  x.upload.onprogress = e => { if (meu && e.lengthComputable) { env.envio = Math.max(0.001, e.loaded / e.total); desenharEnvio(); } };
  x.onload = () => {
    let r = {}; try { r = JSON.parse(x.responseText); } catch {}
    if (x.status !== 200) { $("env-erro").textContent = "Não deu para enviar: " + (r.erro || x.status); if (meu) { env.envio = 0; desenharEnvio(); } return; }
    if (meu) { env.id = r.id; env.envio = 0; }
    lerEnvios();
  };
  x.onerror = () => { $("env-erro").textContent = "Não deu para enviar (o servidor está rodando? Abra pelo iniciar.bat)."; if (meu) { env.envio = 0; desenharEnvio(); } };
  x.send(arquivo);
}
let jaAbriuCatalogo = new Set();
async function lerEnvios() {
  try {
    env.lista = (await (await fetch("envios.json", { cache: "no-store" })).json()).envios;
    for (const e of env.lista) if (e.estado === "pronta" && !jaAbriuCatalogo.has(e.id)) { jaAbriuCatalogo.add(e.id); catTexto = ""; lerCatalogo(); }
    desenharEnvio();
  } catch {}
}
setInterval(() => { if (est.vista === "enviar" || env.lista.some(e => e.estado === "espera" || e.estado === "separando")) lerEnvios(); }, 1000);
function desenharEnvio() {
  const e = env.id && env.lista.find(x => x.id === env.id);
  const temArquivo = !!env.arquivo, enviando = env.envio > 0;
  $("env-livre").hidden = temArquivo;
  $("env-form").hidden = !temArquivo;
  $("env-pronto-para").hidden = !(temArquivo && !enviando && !e);
  $("env-prog").hidden = !(enviando || e);
  $("env-titulo").readOnly = !!(enviando || e);
  if (enviando || e) {
    let i, frac, frase;
    if (enviando) { i = 0; frac = 0.02 * env.envio; frase = ETAPAS_ENV[0][2]; }
    else if (e.estado === "espera") { i = 1; frac = 0.02; frase = "Na fila: começa quando a anterior terminar."; }
    else if (e.estado === "separando") { i = Math.max(1, ETAPAS_ENV.findIndex(x => x[0] === e.etapa)); frac = 0.02 + 0.98 * e.total; frase = ETAPAS_ENV[i][2]; }
    else if (e.estado === "pronta") { i = ETAPAS_ENV.length; frac = 1; frase = "Pronta: seis canais separados."; }
    else { i = -1; frac = e.total || 0; frase = e.estado === "erro" ? "Algo deu errado na separação." : "Cancelada."; }
    $("env-frase").textContent = frase;
    $("env-pct").textContent = Math.round(frac * 100) + "%";
    $("env-cheio").style.width = `calc((100% - 20px) * ${frac.toFixed(4)})`;
    $("env-olho").style.left = `calc(10px + (100% - 20px) * ${frac.toFixed(4)})`;
    $("env-etapas").innerHTML = ETAPAS_ENV.map((x, k) => `<span class="${k < i ? "feita" : k === i ? "agora" : ""}">${x[1]}</span>`).join("");
    revelar(frac, !!(enviando || (e && e.estado === "separando")));
    let eta = "";
    if (e && e.estado === "separando" && e.inicio && e.total > 0.03) {
      const resta = (Date.now() / 1000 - e.inicio) * (1 - e.total) / e.total;
      eta = resta > 90 ? `faltam cerca de ${Math.round(resta / 60)} min` : "falta menos de 2 min";
    }
    $("env-eta").textContent = eta;
    if (e && e.estado === "erro") $("env-erro").textContent = e.erro || "";
    $("env-acoes").innerHTML = e && (e.estado === "espera" || e.estado === "separando") ? `<button class="link" id="env-cancelar">cancelar</button>`
      : e && e.estado === "pronta" ? `<button class="btn-cheio" id="env-abrir">abrir na mesa</button><button class="btn-vazio" id="env-outra">enviar outra</button>`
      : e ? `<button class="btn-vazio" id="env-outra">enviar outra</button>` : "";
    const c = $("env-cancelar"); if (c) c.onclick = () => fetch(`cancelar?id=${env.id}`, { method: "POST" }).then(lerEnvios);
    const o = $("env-outra"); if (o) o.onclick = recomecarEnvio;
    const ab = $("env-abrir"); if (ab) ab.onclick = () => abrirEnviada(e.pasta);
  } else revelar(0, false);
  // fila: outros envios (vários arquivos de uma vez, ou enviados antes)
  const outros = env.lista.filter(x => x.estado !== "cancelada").slice(-12).reverse();
  $("env-fila").hidden = !outros.length;
  const nomes = { espera: "na fila", separando: "separando", pronta: "pronta", erro: "erro" };
  $("env-fila").innerHTML = outros.map(x => `<div class="item${x.id === env.id ? " atual" : ""}" data-id="${x.id}">
    <span class="t">${esc(x.titulo)}${x.rotulo ? ` <span class="st">(${esc(x.rotulo)})</span>` : ""}</span>
    <span class="st">→ ${esc(x.destino.toLowerCase())}</span>
    <span class="st">${x.estado === "separando" ? Math.round(x.total * 100) + "%" : nomes[x.estado] || x.estado}</span></div>`).join("");
  $("env-fila").querySelectorAll(".item").forEach(d => d.onclick = () => {   // clicar num item mostra o andamento dele
    const x = env.lista.find(y => y.id === d.dataset.id); if (!x) return;
    env.id = x.id; env.arquivo = { name: x.arquivo }; env.envio = 0;
    $("env-titulo").value = x.titulo; $("env-nome").textContent = x.arquivo; $("env-dur").textContent = "—";
    $("env-vai").textContent = x.destino.toLowerCase(); desenharEnvio();
  });
}
function recomecarEnvio() {
  env.arquivo = null; env.id = null; env.envio = 0; $("env-erro").textContent = ""; $("env-arquivo").value = "";
  desenharEnvio();
}
async function abrirEnviada(pasta) {   // abre na mesa a versão recém-separada, no disco em que ela entrou
  catTexto = ""; await lerCatalogo();
  for (const [i, a] of cat.albuns.entries()) {
    const j = a.faixas.findIndex(f => f.versoes.some(v => v.pasta === pasta));
    if (j >= 0) { est.album = i; mostrar("mesa"); est.versao = pasta; escolherFaixa(j, true); return; }
  }
}
$("env-arquivo").onchange = e => escolherArquivos(e.target.files);
$("soltar").addEventListener("dragover", e => { e.preventDefault(); $("soltar").classList.add("arrastando"); });
$("soltar").addEventListener("dragleave", () => $("soltar").classList.remove("arrastando"));
$("soltar").addEventListener("drop", e => { e.preventDefault(); $("soltar").classList.remove("arrastando"); escolherArquivos(e.dataTransfer.files); });
$("env-titulo").addEventListener("input", atualizarDestino);
$("env-separar").onclick = () => { if (env.arquivo) subir(env.arquivo, $("env-titulo").value.trim() || tituloDoArquivo(env.arquivo.name)); };
$("env-trocar").onclick = () => $("env-arquivo").click();
$("aba-enviar").onclick = () => { mostrar("enviar"); lerEnvios(); };

/* ---------- início ---------- */
montarMesa(); aplicar(); montarOnda();
(async () => {
  await lerCatalogo();
  mostrar(["mesa", "enviar"].includes(est.vista) ? est.vista : "discos");
  const f = faixaAtual();
  if (f && f.versoes.length) carregar(est.versao, false);
  document.fonts.ready.then(ajustarAltura);
  setInterval(lerCatalogo, 20000);
})();
requestAnimationFrame(quadro);
