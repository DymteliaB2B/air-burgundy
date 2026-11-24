/* AIR BURGUNDY Pilote - interface. Parle à Python via window.pywebview.api */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => n == null ? '–' : Number(n).toLocaleString('fr-FR');
const fl = a => a == null ? '–' : (a >= 10000 ? 'FL' + String(Math.round(a / 100)).padStart(3, '0') : fmt(Math.round(a / 10) * 10) + ' ft');
const hm = m => m == null ? '–' : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
const dt = t => t ? new Date(t * 1000).toLocaleString('fr-FR', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'}) : '–';
const fpmClass = f => f == null ? '' : (f >= -250 ? 'g' : f >= -450 ? 'm' : 'b');
let api, ME = null, OFP = null, ROUTE = null, RUNNING = false, email = '';

window.addEventListener('pywebviewready', boot);
async function boot() {
  api = window.pywebview.api;
  const r = await api.init();
  $('#versionLine').textContent = `AIR BURGUNDY Pilote ${r.version}`;
  $('#aboutLine').textContent = `Version ${r.version}`;
  fillSettings(r.settings);
  if (r.logged_in) enter(r.me); else showLogin(r.error);
}

/* ================= connexion ================= */
function showLogin(err) {
  $('#app').hidden = true; $('#login').hidden = false;
  $('#emailForm').hidden = false; $('#codeForm').hidden = true;
  setErr(err);
}
function setErr(e) { $('#loginErr').hidden = !e; $('#loginErr').textContent = e || ''; }
$('#emailForm').onsubmit = async ev => {
  ev.preventDefault(); setErr(); email = $('#email').value.trim();
  $('#sendBtn').disabled = true; $('#sendBtn').textContent = 'Envoi…';
  const r = await api.send_code(email);
  $('#sendBtn').disabled = false; $('#sendBtn').textContent = 'Recevoir mon code';
  if (!r.ok) return setErr(r.error);
  $('#emailForm').hidden = true; $('#codeForm').hidden = false;
  $('#loginHint').textContent = `Code envoyé à ${email}. Il est valable quelques minutes.`;
  $('#code').value = ''; $('#code').focus();
};
$('#codeForm').onsubmit = async ev => {
  ev.preventDefault(); setErr();
  $('#verifyBtn').disabled = true;
  const r = await api.verify(email, $('#code').value);
  $('#verifyBtn').disabled = false;
  if (!r.ok) return setErr(r.error);
  enter(r.me);
};
$('#backBtn').onclick = () => { $('#codeForm').hidden = true; $('#emailForm').hidden = false; setErr();
  $('#loginHint').textContent = "Saisis l'e-mail avec lequel la compagnie t'a invité. Tu recevras un code à 6 chiffres."; };
$('#logoutBtn').onclick = async () => { const r = await api.logout(); if (!r.ok) return alert(r.error); ME = null; showLogin(); };

/* ================= shell ================= */
function enter(me) {
  ME = me; $('#login').hidden = true; $('#app').hidden = false;
  renderMe(); initMap();
}
function renderMe() {
  const p = ME.profile;
  $('#whoName').textContent = p.name; $('#whoCall').textContent = p.callsign || '';
  $('#pName').value = p.name || ''; $('#pCall').value = p.callsign || ''; $('#pSb').value = p.simbrief_id || '';
  $('#pBase').value = p.home_base || ''; $('#pMail').value = p.email;
  const sel = $('#fReg'), cur = sel.value;
  sel.innerHTML = '<option value="">Auto (d\'après la livrée)</option>' +
    ME.fleet.map(a => `<option value="${esc(a.reg)}">${esc(a.reg)} · ${esc(a.name)} (${esc(a.type)})</option>`).join('');
  sel.value = cur;
  renderLog();
}
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.tab').forEach(t => t.hidden = t.id !== 'tab-' + b.dataset.tab);
  if (b.dataset.tab === 'vol' && map) setTimeout(() => map.invalidateSize(), 50);
  if (b.dataset.tab === 'carnet') refreshMe();
});
async function refreshMe() { const r = await api.me(); if (r.ok) { ME = r.me; renderMe(); } }
$('#refreshBtn').onclick = refreshMe;

/* ================= carnet ================= */
function renderLog() {
  const s = ME.stats || {};
  $('#myStats').innerHTML = `<div><b>${fmt(s.flights)}</b> vols</div><div><b>${fmt(s.hours)}</b> heures</div>
    <div><b>${fmt(s.distance_nm)}</b> NM</div><div>toucher moyen <b>${s.avg_landing_fpm == null ? '–' : s.avg_landing_fpm}</b> ft/min</div>
    <div>meilleur <b>${s.best_landing_fpm == null ? '–' : s.best_landing_fpm}</b> ft/min</div>`;
  const fs = ME.flights || [];
  $('#myFlights').innerHTML = fs.length ? fs.map(f => `<tr>
    <td>${dt(f.started)}</td><td><span class="fno">${esc(f.flight_no)}</span></td><td class="mono">${esc(f.reg)}</td>
    <td class="mono">${esc(f.dep || '····')} – ${esc(f.arr || f.planned_arr || '····')}</td><td class="mono r">${hm(f.block_min)}</td>
    <td class="mono r">${f.distance_nm ? fmt(Math.round(f.distance_nm)) + ' NM' : '–'}</td>
    <td class="mono r fpm ${fpmClass(f.landing_fpm)}">${f.landing_fpm != null ? f.landing_fpm + ' ft/min' : '–'}</td>
    <td>${esc({termine: 'Terminé', actif: 'En vol', interrompu: 'Interrompu', perdu: 'Perdu'}[f.status] || f.status)}</td></tr>`).join('')
    : '<tr class="empty"><td colspan="8">Aucun vol pour l\'instant.</td></tr>';
}

/* ================= profil & réglages ================= */
$('#profileForm').onsubmit = async ev => {
  ev.preventDefault(); $('#pMsg').textContent = 'Enregistrement…';
  const r = await api.update_profile({name: $('#pName').value, callsign: $('#pCall').value, simbrief_id: $('#pSb').value, home_base: $('#pBase').value});
  if (!r.ok) { $('#pMsg').textContent = r.error; return; }
  ME.profile = {...ME.profile, ...r.profile}; renderMe(); $('#pMsg').textContent = 'Enregistré.';
};
function fillSettings(s) { $('#sXp').value = s.xp || '127.0.0.1:49000'; $('#sRate').value = s.rate || 5; }
$('#settingsForm').onsubmit = async ev => {
  ev.preventDefault();
  const r = await api.save_settings({xp: $('#sXp').value.trim() || '127.0.0.1:49000', rate: +$('#sRate').value || 5});
  $('#sMsg').textContent = r.ok ? 'Enregistré.' : r.error;
};
$('#siteBtn').onclick = () => api.open_site();

/* ================= préparation & ACARS ================= */
$('#ofpBtn').onclick = async () => {
  $('#ofpBtn').disabled = true; $('#ofpBox').innerHTML = '<p class="muted">Chargement de l\'OFP…</p>';
  const r = await api.load_ofp(ME.profile.simbrief_id);
  $('#ofpBtn').disabled = false;
  if (!r.ok) { $('#ofpBox').innerHTML = `<p class="error">${esc(r.error)}</p>`; return; }
  OFP = r.ofp; const o = OFP;
  $('#ofpBox').innerHTML = `<div class="fno">${esc(o.flight_no || '—')}</div>
    <div class="rt">${esc(o.origin?.icao)} → ${esc(o.destination?.icao)}${o.alternate?.icao ? ` <span class="muted">(dég. ${esc(o.alternate.icao)})</span>` : ''}</div>
    <div class="muted small">${fl(o.cruise_alt)} · ${fmt(Math.round(o.distance_nm || 0))} NM · ${esc(o.aircraft || '')}</div>
    <div class="route">${esc(o.route || '')}</div>`;
  if (o.flight_no) $('#fNo').value = o.flight_no;
  if (o.destination?.icao) $('#fArr').value = o.destination.icao;
  drawPlan();
};
$('#startBtn').onclick = async () => {
  const plan = {flight_no: $('#fNo').value.trim().toUpperCase(), arr: $('#fArr').value.trim().toUpperCase(),
                reg: $('#fReg').value, route: OFP};
  track = []; followed = false; lastNext = -1; ROUTE = null; clearLive();
  const r = await api.start_flight(plan);
  if (!r.ok) { $('#acarsMsg').textContent = r.error; return; }
  setRunning(true);
};
$('#stopBtn').onclick = async () => {
  if (!confirm('Arrêter le suivi du vol ? Il sera enregistré comme terminé si tu as déjà atterri, sinon comme interrompu.')) return;
  await api.stop_flight(); $('#stopBtn').disabled = true; $('#acarsMsg').textContent = 'Clôture du vol…';
};
function setRunning(on) {
  RUNNING = on; $('#startBtn').hidden = on; $('#stopBtn').hidden = !on; $('#stopBtn').disabled = false;
  ['#fNo', '#fArr', '#fReg', '#ofpBtn'].forEach(s => $(s).disabled = on);
}
function clearLive() {
  ['#gPhase', '#gAlt', '#gGs', '#gVs', '#gHdg', '#gFuel', '#gNext', '#gRem'].forEach(s => $(s).textContent = '—');
  $('#landingBox').hidden = true; $('#acarsWarn').hidden = true; $('#linkLine').textContent = '';
}

window.onAcars = st => {
  const badge = $('#acarsState');
  const labels = {connexion: 'Connexion', attente: 'En attente de X-Plane', vol: 'En vol', termine: 'Terminé', interrompu: 'Interrompu', erreur: 'Erreur'};
  badge.textContent = labels[st.state] || st.state;
  badge.className = 'status' + (st.state === 'vol' ? ' on' : st.state === 'erreur' ? ' err' : '');
  if (st.msg) $('#acarsMsg').textContent = st.msg;
  if (st.warn) { $('#acarsWarn').hidden = false; $('#acarsWarn').textContent = st.warn; }
  if ('route' in st) ROUTE = st.route;
  if (st.flight_no) $('#liveTitle').textContent = `${st.flight_no}${st.reg ? ' · ' + st.reg : ''}`;
  if (st.dep || st.arr) $('#liveRoute').textContent = `${st.dep || '····'} → ${st.arr || '····'}${st.sim ? '  ·  ' + st.sim : ''}`;
  if (st.state === 'vol' && st.lat != null) {
    $('#acarsMsg').textContent = st.on_ground ? 'Au sol' : 'En vol';
    $('#gPhase').textContent = st.phase; $('#gAlt').textContent = fl(st.alt); $('#gGs').textContent = `${fmt(st.gs)} kt`;
    $('#gVs').textContent = `${st.vs > 0 ? '+' : ''}${fmt(st.vs)} ft/min`; $('#gHdg').textContent = `${String(st.hdg).padStart(3, '0')}°`;
    $('#gFuel').textContent = `${fmt(st.fuel)} kg`;
    const pos = {lat: st.lat, lon: st.lon};
    track.push([st.lat, st.lon]);
    const rt = ROUTE || OFP, pr = rt ? progress(rt, pos) : null;
    $('#gNext').textContent = pr ? `${pr.next.id} ${Math.round(pr.toNext)} NM` : '—';
    $('#gRem').textContent = pr ? `${fmt(Math.round(pr.remaining))} NM` : '—';
    drawLive(pos, st.hdg, pr?.idx);
    $('#linkLine').textContent = st.link === 'ok' || !st.link ? 'Liaison airburgundyva.online : OK' :
      st.link === 'pause' ? 'Simulateur en pause' : st.link === 'silence' ? 'X-Plane silencieux (chargement ?)' : st.link;
  }
  if (st.landing) {
    $('#landingBox').hidden = false; $('#landingBox').className = 'landing ' + fpmClass(st.landing.fpm);
    $('#lFpm').textContent = `${st.landing.fpm} ft/min`; $('#lG').textContent = `${Number(st.landing.g).toFixed(2)} g`;
  }
  if (['termine', 'interrompu', 'erreur'].includes(st.state)) { setRunning(false); refreshMe(); }
};

/* ================= carte ================= */
let map, layer, planLayer, track = [];
function initMap() {
  if (map) return;
  map = L.map('map', {attributionControl: true}).setView([47.26, 5.09], 6);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap'}).addTo(map);
  planLayer = L.layerGroup().addTo(map); layer = L.layerGroup().addTo(map);
  map.on('zoomend', () => map.getContainer().classList.toggle('hide-fix', map.getZoom() < 8));
  map.getContainer().classList.add('hide-fix');
}
function gc(a, b) {
  const r = Math.PI / 180, p1 = a[0] * r, p2 = b[0] * r, dl = (b[1] - a[1]) * r;
  const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(h)));
}
function routePoints(rt) {
  const pts = [];
  if (rt.origin?.lat != null) pts.push({id: rt.origin.icao, lat: rt.origin.lat, lon: rt.origin.lon, apt: true});
  for (const f of rt.fixes || []) pts.push(f);
  const last = pts[pts.length - 1];
  if (rt.destination?.lat != null && !(last && last.id === rt.destination.icao))
    pts.push({id: rt.destination.icao, lat: rt.destination.lat, lon: rt.destination.lon, apt: true});
  return pts;
}
function progress(rt, p) {
  const pts = routePoints(rt); if (pts.length < 2) return null;
  const k = Math.cos(p.lat * Math.PI / 180); let best = null;
  for (let i = 0; i < pts.length - 1; i++) {
    const ax = pts[i].lon * k, ay = pts[i].lat, bx = pts[i + 1].lon * k, by = pts[i + 1].lat, px = p.lon * k, py = p.lat;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-12;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2));
    const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    if (!best || d < best.d) best = {i, d};
  }
  const nxt = pts[Math.min(best.i + 1, pts.length - 1)];
  let rem = gc([p.lat, p.lon], [nxt.lat, nxt.lon]);
  for (let j = best.i + 1; j < pts.length - 1; j++) rem += gc([pts[j].lat, pts[j].lon], [pts[j + 1].lat, pts[j + 1].lon]);
  return {next: nxt, toNext: gc([p.lat, p.lon], [nxt.lat, nxt.lon]), remaining: rem, idx: best.i + 1};
}
function drawPlan(nextIdx) {
  if (!map) return; planLayer.clearLayers(); if (!OFP) return;
  const pts = routePoints(OFP);
  if (pts.length > 1) {
    const pl = L.polyline(pts.map(x => [x.lat, x.lon]), {color: '#4a0b1e', weight: 1.5, dashArray: '5 5'}).addTo(planLayer);
    if (!RUNNING) map.fitBounds(pl.getBounds(), {padding: [30, 30]});
  }
  pts.forEach((x, i) => {
    const isNext = i === nextIdx;
    L.circleMarker([x.lat, x.lon], {radius: x.apt ? 4 : isNext ? 4.5 : 2.5, color: '#4a0b1e', weight: x.apt || isNext ? 2 : 1,
      fillColor: isNext ? '#4a0b1e' : '#fff', fillOpacity: 1})
      .bindTooltip(esc(x.id), {permanent: true, direction: 'right', offset: [5, 0], className: 'fix' + (isNext ? ' next' : '') + (x.apt ? ' next' : '')})
      .addTo(planLayer);
  });
}
let lastNext = -1, followed = false;
function drawLive(p, hdg, nextIdx) {
  if (!map) return;
  if (nextIdx !== lastNext) { drawPlan(nextIdx); lastNext = nextIdx; }
  layer.clearLayers();
  if (track.length > 1) L.polyline(track, {color: '#4a0b1e', weight: 3}).addTo(layer);
  const svg = `<svg width="28" height="28" viewBox="0 0 64 64" style="transform:rotate(${hdg}deg)"><path d="M32 3c2.4 0 3.6 3 3.6 6.4V24l21 12.6v5.2L35.6 35v13.4l6.4 5v4.4L32 55l-10 2.8v-4.4l6.4-5V35L7.4 41.8v-5.2l21-12.6V9.4C28.4 6 29.6 3 32 3z" fill="#4a0b1e" stroke="#fff" stroke-width="2.6"/></svg>`;
  L.marker([p.lat, p.lon], {icon: L.divIcon({html: svg, className: '', iconSize: [28, 28], iconAnchor: [14, 14]})}).addTo(layer);
  if (!followed) { map.setView([p.lat, p.lon], 9); followed = true; }
}

/* ================= mode démo (aperçu dans un navigateur : index.html?demo) ================= */
if (location.search.includes('demo')) setTimeout(() => {
  if (window.pywebview) return;
  const me = {profile: {email: 'pilote@exemple.fr', name: 'Pilote Démo', callsign: 'BRG12', simbrief_id: 'demo', home_base: 'LFSD', role: 'pilote'},
    stats: {flights: 3, hours: 4.2, distance_nm: 1180, avg_landing_fpm: -168, best_landing_fpm: -92},
    flights: [{started: Date.now() / 1000 - 86400, flight_no: 'BRG204', reg: 'F-LAUR', dep: 'LFSD', arr: 'EDDF', block_min: 72, distance_nm: 381, landing_fpm: -142, status: 'termine'}],
    fleet: [{reg: 'F-DIMI', name: 'Ville de Dijon', type: 'A321neo XLR'}, {reg: 'F-LAUR', name: 'Ville de Mâcon', type: 'A319'}]};
  const ofp = {flight_no: 'BRG204', origin: {icao: 'LFSD', lat: 47.2658, lon: 5.095}, destination: {icao: 'EDDF', lat: 50.0333, lon: 8.5705},
    alternate: {icao: 'EDDL'}, cruise_alt: 38000, distance_nm: 382, aircraft: 'A319', route: 'DCT JOCUZ DCT SUTAL N852 LIMGO UN858 BETEX Z140 AGBUL DCT TUTOV TUTO1C',
    fixes: [{id: 'JOCUZ', lat: 47.6655, lon: 5.4547, alt: 17300}, {id: 'TOC', lat: 49.398, lon: 6.3546, alt: 38000}, {id: 'SUTAL', lat: 49.4667, lon: 6.3917, alt: 38000},
            {id: 'BETEX', lat: 49.8158, lon: 6.4253, alt: 39000}, {id: 'TUTOV', lat: 50.31, lon: 7.2531, alt: 39000}]};
  let timer;
  window.pywebview = {api: {
    init: async () => ({version: 'démo', settings: {xp: '127.0.0.1:49000', rate: 5}, logged_in: location.search.includes('in'), me}),
    send_code: async () => ({ok: true}), verify: async () => ({ok: true, me}), me: async () => ({ok: true, me}),
    logout: async () => ({ok: true}), update_profile: async p => ({ok: true, profile: p}), save_settings: async s => ({ok: true, settings: s}),
    load_ofp: async () => ({ok: true, ofp}), open_site: async () => ({ok: true}),
    start_flight: async () => { let i = 0;
      onAcars({state: 'vol', msg: 'Vol ouvert', flight_no: 'BRG204', reg: 'F-LAUR', dep: 'LFSD', arr: 'EDDF', sim: 'X-Plane 12', route: ofp});
      timer = setInterval(() => { i++; const t = i / 40;
        onAcars({state: 'vol', phase: i < 25 ? 'Montée' : 'Croisière', lat: 47.27 + t * 2.2, lon: 5.09 + t * 1.1, alt: Math.min(38000, 1200 * i), gs: 280 + i * 4,
                 vs: i < 25 ? 2400 : 0, hdg: 25, fuel: 7000 - i * 12, on_ground: false, link: 'ok', landing: i > 30 ? {fpm: -138, g: 1.11} : null});
        if (i > 34) clearInterval(timer); }, 300);
      return {ok: true}; },
    stop_flight: async () => { clearInterval(timer); onAcars({state: 'termine', msg: 'Vol terminé à EDDF.'}); return {ok: true}; },
  }};
  boot();
}, 300);
