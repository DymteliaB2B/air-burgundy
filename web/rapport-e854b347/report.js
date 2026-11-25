/* AIR BURGUNDY - générateur de Flight Report (image PNG dessinée dans le navigateur). */
const CFG = window.AB_CONFIG || {};
const $ = s => document.querySelector(s);
const FORMATS = {story: [1080, 1920], portrait: [1080, 1350], square: [1080, 1080], landscape: [1200, 630]};
const THEMES = {
  light: {bg: '#f5f1ea', card: '#fbf9f5', ink: '#1f1416', ink2: '#5b4d50', ink3: '#8c7f81', rule: '#d9d0c4', accent: '#4a0b1e', gold: '#b08a42', track: '#4a0b1e', plan: '#c9a055'},
  dark:  {bg: '#2a0712', card: '#3a0c1a', ink: '#f5f1ea', ink2: '#e2d3cb', ink3: '#b59f9a', rule: '#5a2232', accent: '#e4c77f', gold: '#c9a055', track: '#e4c77f', plan: '#b59f9a'},
};
let FLIGHTS = [], FLEET = {}, CUR = null, FMT = 'story', THEME = 'light';

async function rpc(fn, args = {}) {
  if (CFG.supabaseUrl && CFG.supabaseAnonKey) {
    const r = await fetch(`${CFG.supabaseUrl.replace(/\/$/, '')}/rest/v1/rpc/${fn}`, {method: 'POST',
      headers: {apikey: CFG.supabaseAnonKey, Authorization: `Bearer ${CFG.supabaseAnonKey}`, 'Content-Type': 'application/json'}, body: JSON.stringify(args)});
    if (!r.ok) throw new Error(r.status); return r.json();
  }
  const path = {api_flights: `/api/flights?limit=${args.p_limit || 50}`, api_fleet: '/api/fleet', api_flight: `/api/flights/${args.p_id}`}[fn];
  const r = await fetch(path); if (!r.ok) throw new Error(r.status); return r.json();
}

/* ---------------------------------------------------------------- utilitaires */
const fmt = n => n == null ? '–' : Number(n).toLocaleString('fr-FR');
const hm = m => m == null ? '–' : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
const fl = a => a == null ? '–' : (a >= 10000 ? 'FL' + String(Math.round(a / 100)).padStart(3, '0') : fmt(Math.round(a / 10) * 10) + ' ft');
const dateFr = t => t ? new Date(t * 1000).toLocaleDateString('fr-FR', {day: 'numeric', month: 'long', year: 'numeric'}) : '';
const shortName = a => (a?.name || '').replace(/\s*-\s*/g, ' – ').replace(/\b(\w)(\w*)/g, (m, x, y) => x.toUpperCase() + y.toLowerCase());
const imgCache = {};
function loadImg(src) {
  if (!imgCache[src]) imgCache[src] = new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = src; });
  return imgCache[src];
}
/* rognage automatique sur la partie opaque (les profils ont des marges transparentes) */
const bboxCache = new Map();
function opaqueBox(img) {
  if (bboxCache.has(img)) return bboxCache.get(img);
  const c = document.createElement('canvas'), w = c.width = img.naturalWidth, h = c.height = img.naturalHeight, x = c.getContext('2d');
  x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, w, h).data;
  let x0 = w, y0 = h, x1 = 0, y1 = 0;
  for (let y = 0; y < h; y += 2) for (let xx = 0; xx < w; xx += 2) if (d[(y * w + xx) * 4 + 3] > 20) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  const b = {x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1}; bboxCache.set(img, b); return b;
}
function fitText(ctx, text, font, size, maxW) {
  let s = size; ctx.font = font.replace('{s}', s);
  while (ctx.measureText(text).width > maxW && s > 12) { s -= 2; ctx.font = font.replace('{s}', s); }
  return s;
}
function spaced(ctx, text, x, y, track, align = 'left') {
  const w = [...text].reduce((a, c) => a + ctx.measureText(c).width, 0) + track * (text.length - 1);
  let cx = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;
  for (const c of text) { ctx.fillText(c, cx, y); cx += ctx.measureText(c).width + track; }
  return w;
}
function wordmark(ctx, x, y, s, T, align = 'left') {
  ctx.textBaseline = 'alphabetic'; ctx.fillStyle = T.ink;
  ctx.font = `400 ${s}px "IBM Plex Sans"`; const tr = s * 0.16;
  const wa = [...'AIR'].reduce((a, c) => a + ctx.measureText(c).width, 0) + tr * 2;
  ctx.font = `600 ${s}px "IBM Plex Sans"`;
  const wb = [...'BURGUNDY'].reduce((a, c) => a + ctx.measureText(c).width, 0) + tr * 7;
  const gap = s * 1.1, tot = wa + gap + wb, x0 = align === 'right' ? x - tot : x;
  ctx.font = `400 ${s}px "IBM Plex Sans"`; spaced(ctx, 'AIR', x0, y, tr);
  const dx = x0 + wa + gap / 2, dy = y - s * 0.36, r = s * 0.2;
  ctx.fillStyle = '#c9a055'; ctx.beginPath(); ctx.moveTo(dx, dy - r); ctx.lineTo(dx + r, dy); ctx.lineTo(dx, dy + r); ctx.lineTo(dx - r, dy); ctx.fill();
  ctx.fillStyle = T.ink; ctx.font = `600 ${s}px "IBM Plex Sans"`; spaced(ctx, 'BURGUNDY', x0 + wa + gap, y, tr);
}
const MENTION = "Air Burgundy est une compagnie aérienne virtuelle regroupant des passionnés d'aéronautique bourguignons.";
function wrapLines(ctx, text, maxW) {
  const out = []; let line = '';
  for (const w of text.split(' ')) { const t = line ? line + ' ' + w : w; if (ctx.measureText(t).width > maxW && line) { out.push(line); line = w; } else line = t; }
  if (line) out.push(line); return out;
}
function fpmColor(f, T) { if (f == null) return T.ink; return f >= -250 ? '#2e8a55' : f >= -450 ? '#c08a1a' : '#c0392b'; }

/* ---------------------------------------------------------------- carte de la trace */
function drawMap(ctx, f, x, y, w, h, T) {
  ctx.fillStyle = T.card; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = T.rule; ctx.lineWidth = 1; ctx.strokeRect(x + .5, y + .5, w - 1, h - 1);
  const trk = (f.track || []).map(p => [p.lat, p.lon]).filter(p => p[0] != null);
  const plan = [];
  if (f.route) { if (f.route.origin?.lat != null) plan.push([f.route.origin.lat, f.route.origin.lon]);
    (f.route.fixes || []).forEach(p => plan.push([p.lat, p.lon]));
    if (f.route.destination?.lat != null) plan.push([f.route.destination.lat, f.route.destination.lon]); }
  const dep = f.dep_airport?.lat != null ? [f.dep_airport.lat, f.dep_airport.lon] : trk[0];
  const arr = f.arr_airport?.lat != null ? [f.arr_airport.lat, f.arr_airport.lon] : trk[trk.length - 1];
  const all = [...trk, ...plan, dep, arr].filter(Boolean);
  if (all.length < 2) return;
  const lat0 = all.reduce((a, p) => a + p[0], 0) / all.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = all.map(p => p[1] * k), ys = all.map(p => p[0]);
  const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
  const pad = Math.min(w, h) * 0.14, sc = Math.min((w - 2 * pad) / ((maxx - minx) || 1e-3), (h - 2 * pad) / ((maxy - miny) || 1e-3));
  const ox = x + w / 2 - (minx + maxx) / 2 * sc, oy = y + h / 2 + (miny + maxy) / 2 * sc;
  const P = p => [ox + p[1] * k * sc, oy - p[0] * sc];
  // repère discret
  ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.strokeStyle = T.rule; ctx.lineWidth = 1; ctx.setLineDash([2, 8]);
  for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(x, y + h * i / 4); ctx.lineTo(x + w, y + h * i / 4); ctx.stroke(); }
  ctx.setLineDash([]);
  if (plan.length > 1) { ctx.strokeStyle = T.plan; ctx.lineWidth = 3; ctx.setLineDash([10, 10]); ctx.beginPath();
    plan.forEach((p, i) => { const [a, b] = P(p); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke(); ctx.setLineDash([]); }
  if (trk.length > 1) { ctx.strokeStyle = T.track; ctx.lineWidth = 6; ctx.lineJoin = ctx.lineCap = 'round'; ctx.beginPath();
    trk.forEach((p, i) => { const [a, b] = P(p); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke(); }
  const s = Math.max(22, w / 28);
  [[dep, f.dep], [arr, f.arr || f.planned_arr]].forEach(([p, code], i) => {
    if (!p) return; const [a, b] = P(p);
    ctx.fillStyle = T.bg; ctx.strokeStyle = T.track; ctx.lineWidth = 5; ctx.beginPath(); ctx.arc(a, b, s * 0.38, 0, 7); ctx.fill(); ctx.stroke();
    ctx.font = `500 ${s}px "IBM Plex Mono"`; ctx.fillStyle = T.ink; ctx.textBaseline = 'middle';
    const right = a < x + w * 0.7; ctx.textAlign = right ? 'left' : 'right';
    ctx.fillText(code || '', a + (right ? s * 0.8 : -s * 0.8), b); ctx.textAlign = 'left';
  });
  ctx.restore(); ctx.textBaseline = 'alphabetic';
}

/* ---------------------------------------------------------------- rendu */
async function render() {
  const f = CUR; if (!f) return;
  const [W, H] = FORMATS[FMT], T = THEMES[THEME], cv = $('#cv'), ctx = cv.getContext('2d');
  cv.width = W; cv.height = H;
  await Promise.all(['400 40px "Instrument Serif"', 'italic 400 40px "Instrument Serif"', '400 20px "IBM Plex Sans"', '600 20px "IBM Plex Sans"',
                     '500 20px "IBM Plex Mono"'].map(x => document.fonts.load(x)));
  let img = null; try { img = await loadImg(`../img/profile-${f.reg}.webp`); } catch (e) {}
  ctx.fillStyle = T.bg; ctx.fillRect(0, 0, W, H);
  const ac = FLEET[f.reg] || {}, cap = $('#caption').value.trim();
  const stats = [
    ['Temps de vol', hm(f.air_min)], ['Distance', f.distance_nm ? fmt(Math.round(f.distance_nm)) + ' NM' : '–'],
    ['Toucher', f.landing_fpm != null ? `${f.landing_fpm} ft/min` : '–', fpmColor(f.landing_fpm, T)],
    ['Temps bloc', hm(f.block_min)], ['Niveau max', fl(f.max_alt)], ['Carburant', f.fuel_used != null ? fmt(f.fuel_used) + ' kg' : '–']];
  if (FMT === 'landscape') return renderLandscape(ctx, f, W, H, T, img, ac, stats, cap);

  const u = W / 1080, m = 76 * u;
  const cfg = {story: {route: 190, gap: 1, map: true, cols: 2, img: 1, rh: 118, top: 76},
               portrait: {route: 150, gap: .4, map: false, cols: 3, img: .92, rh: 108, top: 70},
               square: {route: 108, gap: 0, map: false, cols: 3, img: .6, rh: 92, top: 58}}[FMT];
  let y = 96 * u;
  wordmark(ctx, m, y, 26 * u, T);
  ctx.font = `500 ${22 * u}px "IBM Plex Mono"`; ctx.fillStyle = T.ink3; spaced(ctx, 'FLIGHT REPORT', W - m, y, 4 * u, 'right');
  y += 30 * u; ctx.fillStyle = T.ink; ctx.fillRect(m, y, W - 2 * m, 2 * u);
  y += cfg.top * u;
  ctx.font = `500 ${40 * u}px "IBM Plex Mono"`; ctx.fillStyle = T.accent; ctx.fillText(f.flight_no || '', m, y);
  ctx.font = `400 ${26 * u}px "IBM Plex Sans"`; ctx.fillStyle = T.ink3; ctx.textAlign = 'right'; ctx.fillText(dateFr(f.started), W - m, y); ctx.textAlign = 'left';
  // route
  const route = `${f.dep || '····'} → ${f.arr || f.planned_arr || '····'}`;
  const rs = fitText(ctx, route, '400 {s}px "Instrument Serif"', cfg.route * u, W - 2 * m);
  y += rs * 0.95 + 20 * u; ctx.fillStyle = T.ink; ctx.fillText(route, m - 4 * u, y);
  y += 50 * u; ctx.font = `400 ${28 * u}px "IBM Plex Sans"`; ctx.fillStyle = T.ink2;
  const names = [shortName(f.dep_airport), shortName(f.arr_airport)].filter(Boolean).join('  —  ');
  fitText(ctx, names, '400 {s}px "IBM Plex Sans"', 28 * u, W - 2 * m); ctx.fillText(names, m, y);
  if (cap && FMT !== 'square') { y += 70 * u; ctx.font = `italic 400 ${50 * u}px "Instrument Serif"`; ctx.fillStyle = T.accent;
    fitText(ctx, cap, 'italic 400 {s}px "Instrument Serif"', 50 * u, W - 2 * m); ctx.fillText(cap, m, y); }
  // avion
  y += 40 * u * cfg.gap + 30 * u;
  if (img) { const b = opaqueBox(img), iw = (W - 2 * m) * cfg.img, ih = iw * b.h / b.w;
    ctx.drawImage(img, b.x, b.y, b.w, b.h, m, y, iw, ih); y += ih; }
  y += (FMT === 'square' ? 36 : 54) * u;
  ctx.font = `500 ${32 * u}px "IBM Plex Mono"`; ctx.fillStyle = T.ink; const rw = spaced(ctx, f.reg || '', m, y, 3 * u);
  ctx.font = `italic 400 ${42 * u}px "Instrument Serif"`; ctx.fillStyle = T.accent; ctx.fillText(ac.name || '', m + rw + 22 * u, y);
  ctx.font = `400 ${24 * u}px "IBM Plex Sans"`; ctx.fillStyle = T.ink3; ctx.textAlign = 'right';
  ctx.fillText([ac.type, f.sim].filter(Boolean).join(' · '), W - m, y); ctx.textAlign = 'left';
  // statistiques
  y += (FMT === 'square' ? 26 : 40) * u; ctx.fillStyle = T.rule; ctx.fillRect(m, y, W - 2 * m, 2 * u);
  const cols = cfg.cols, cw = (W - 2 * m) / cols, rh = cfg.rh * u;
  stats.forEach(([k, v, c], i) => {
    const cx = m + (i % cols) * cw, cy = y + Math.floor(i / cols) * rh;
    ctx.font = `400 ${22 * u}px "IBM Plex Sans"`; ctx.fillStyle = T.ink3; ctx.fillText(k, cx, cy + (rh / u - 76) * u);
    ctx.font = `500 ${(cols === 2 ? 46 : 40) * u}px "IBM Plex Mono"`; ctx.fillStyle = c || T.ink;
    fitText(ctx, v, `500 {s}px "IBM Plex Mono"`, (cols === 2 ? 46 : 40) * u, cw - 20 * u); ctx.fillText(v, cx, cy + (rh / u - 26) * u);
    if (i % cols === 0 && i) { ctx.fillStyle = T.rule; ctx.fillRect(m, cy, W - 2 * m, 1 * u); }
  });
  y += Math.ceil(stats.length / cols) * rh;
  if (f.landing_g) { ctx.font = `400 ${22 * u}px "IBM Plex Mono"`; ctx.fillStyle = T.ink3; }
  // carte (story)
  const footY = H - 150 * u;                       // trait du pied de page
  if (cfg.map && footY - y > 240 * u) drawMap(ctx, f, m, y + 24 * u, W - 2 * m, footY - y - 54 * u, T);
  // pied : pilote, site, mention
  ctx.fillStyle = T.rule; ctx.fillRect(m, footY, W - 2 * m, 1 * u);
  ctx.font = `400 ${24 * u}px "IBM Plex Sans"`; ctx.fillStyle = T.ink2;
  ctx.fillText(f.pilot ? `Vol effectué par : ${f.pilot}` : '', m, footY + 44 * u);
  ctx.font = `500 ${22 * u}px "IBM Plex Mono"`; ctx.fillStyle = T.ink3; ctx.textAlign = 'right'; ctx.fillText('airburgundyva.online', W - m, footY + 44 * u); ctx.textAlign = 'left';
  ctx.font = `italic 400 ${25 * u}px "Instrument Serif"`; ctx.fillStyle = T.ink3;
  wrapLines(ctx, MENTION, W - 2 * m).forEach((l, i) => ctx.fillText(l, m, footY + 86 * u + i * 28 * u));
}

function renderLandscape(ctx, f, W, H, T, img, ac, stats, cap) {
  const m = 44, colW = 520;
  wordmark(ctx, m, 62, 18, T);
  ctx.font = '500 16px "IBM Plex Mono"'; ctx.fillStyle = T.ink3; spaced(ctx, 'FLIGHT REPORT', W - m, 62, 3, 'right');
  ctx.fillStyle = T.ink; ctx.fillRect(m, 80, W - 2 * m, 2);
  ctx.font = '500 26px "IBM Plex Mono"'; ctx.fillStyle = T.accent; ctx.fillText(f.flight_no || '', m, 130);
  ctx.font = '400 18px "IBM Plex Sans"'; ctx.fillStyle = T.ink3; ctx.fillText(dateFr(f.started), m + 170, 130);
  const route = `${f.dep || '····'} → ${f.arr || f.planned_arr || '····'}`;
  const rs = fitText(ctx, route, '400 {s}px "Instrument Serif"', 104, colW); ctx.fillStyle = T.ink; ctx.fillText(route, m - 2, 130 + rs * 0.95);
  let y = 130 + rs * 0.95 + 34;
  ctx.font = '400 18px "IBM Plex Sans"'; ctx.fillStyle = T.ink2;
  const names = [shortName(f.dep_airport), shortName(f.arr_airport)].filter(Boolean).join('  —  ');
  fitText(ctx, names, '400 {s}px "IBM Plex Sans"', 18, colW); ctx.fillText(names, m, y);
  if (cap) { y += 40; ctx.font = 'italic 400 30px "Instrument Serif"'; ctx.fillStyle = T.accent; fitText(ctx, cap, 'italic 400 {s}px "Instrument Serif"', 30, colW); ctx.fillText(cap, m, y); }
  y = H - 232; ctx.fillStyle = T.rule; ctx.fillRect(m, y, colW, 1);
  const cw = colW / 3;
  stats.forEach(([k, v, c], i) => { const cx = m + (i % 3) * cw, cy = y + Math.floor(i / 3) * 78;
    ctx.font = '400 15px "IBM Plex Sans"'; ctx.fillStyle = T.ink3; ctx.fillText(k, cx, cy + 30);
    ctx.font = '500 26px "IBM Plex Mono"'; ctx.fillStyle = c || T.ink; fitText(ctx, v, '500 {s}px "IBM Plex Mono"', 26, cw - 12); ctx.fillText(v, cx, cy + 62); });
  // droite
  const rx = m + colW + 40, rw = W - rx - m;
  if (img) { const b = opaqueBox(img), ih = rw * b.h / b.w; ctx.drawImage(img, b.x, b.y, b.w, b.h, rx, 120, rw, ih);
    ctx.font = '500 22px "IBM Plex Mono"'; ctx.fillStyle = T.ink; const w = spaced(ctx, f.reg || '', rx, 120 + ih + 44, 2);
    ctx.font = 'italic 400 30px "Instrument Serif"'; ctx.fillStyle = T.accent; ctx.fillText(ac.name || '', rx + w + 16, 120 + ih + 44);
    drawMap(ctx, f, rx, 120 + ih + 70, rw, H - (120 + ih + 70) - 66, T); }
  ctx.font = '400 15px "IBM Plex Sans"'; ctx.fillStyle = T.ink2; ctx.fillText(f.pilot ? `Vol effectué par : ${f.pilot}` : '', m, H - 34);
  ctx.font = '500 14px "IBM Plex Mono"'; ctx.fillStyle = T.ink3; ctx.textAlign = 'right'; ctx.fillText('airburgundyva.online', W - m, H - 34); ctx.textAlign = 'left';
  ctx.font = 'italic 400 16px "Instrument Serif"'; ctx.fillStyle = T.ink3; ctx.fillText(MENTION, m, H - 13);
}

/* ---------------------------------------------------------------- interface */
async function pick(id) {
  $('#msg').textContent = 'Chargement du vol…'; $('#dl').disabled = true;
  try { CUR = await rpc('api_flight', {p_id: +id}); await render(); $('#msg').textContent = ''; $('#dl').disabled = false; }
  catch (e) { $('#msg').textContent = 'Vol introuvable.'; }
}
document.querySelectorAll('#formats button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#formats button').forEach(x => x.classList.toggle('on', x === b)); FMT = b.dataset.f; render(); });
document.querySelectorAll('#themes button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#themes button').forEach(x => x.classList.toggle('on', x === b)); THEME = b.dataset.t; render(); });
let capT; $('#caption').oninput = () => { clearTimeout(capT); capT = setTimeout(render, 250); };
$('#flight').onchange = e => pick(e.target.value);
$('#dl').onclick = () => {
  const a = document.createElement('a');
  a.download = `${CUR.flight_no || 'vol'}_${CUR.dep || ''}-${CUR.arr || ''}_${FMT}.png`.replace(/[^\w.-]+/g, '_');
  a.href = $('#cv').toDataURL('image/png'); a.click();
};
(async () => {
  try {
    const [flights, fleet] = await Promise.all([rpc('api_flights', {p_limit: 60}), rpc('api_fleet')]);
    fleet.forEach(a => FLEET[a.reg] = a);
    FLIGHTS = flights.filter(f => f.status === 'termine');
    if (!FLIGHTS.length) { $('#flight').innerHTML = '<option>Aucun vol terminé</option>'; return; }
    $('#flight').innerHTML = FLIGHTS.map(f => `<option value="${f.id}">${f.flight_no} · ${f.dep || '?'} → ${f.arr || '?'} · ${f.reg} · ${new Date(f.started * 1000).toLocaleDateString('fr-FR')}</option>`).join('');
    const want = new URLSearchParams(location.search).get('id');
    if (want && FLIGHTS.some(f => f.id == want)) $('#flight').value = want;
    pick($('#flight').value);
  } catch (e) { $('#msg').textContent = 'Impossible de charger les vols.'; }
})();
