/* AIR BURGUNDY - site public. Lit uniquement l'API de la compagnie. */
const API = '';            // même origine que le site
const REFRESH = 8000;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => n == null ? '–' : Number(n).toLocaleString('fr-FR');
const hm = m => m == null ? '–' : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
const dt = t => t ? new Date(t * 1000).toLocaleString('fr-FR', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'}) : '–';
const fpmClass = f => f == null ? '' : (f >= -250 ? 'g' : f >= -450 ? 'm' : 'b');
const fl = a => a == null ? '–' : (a >= 10000 ? 'FL' + String(Math.round(a / 100)).padStart(3, '0') : fmt(Math.round(a / 10) * 10) + ' ft');
const CFG = window.AB_CONFIG || {};
const SB = CFG.supabaseUrl && CFG.supabaseAnonKey;
/* même interface que l'API locale : '/api/live', '/api/flights?limit=25', '/api/flights/12'… */
function getJSON(p) {
  if (!SB) return fetch(API + p, {cache: 'no-store'}).then(r => r.ok ? r.json() : Promise.reject(r.status));
  const u = new URL(p, location.origin), q = Object.fromEntries(u.searchParams);
  let fn, args = {};
  const m = u.pathname.match(/^\/api\/flights\/(\d+)$/);
  if (m) { fn = 'api_flight'; args = {p_id: +m[1]}; }
  else if (u.pathname === '/api/flights') { fn = 'api_flights'; args = {p_limit: +(q.limit || 50), p_reg: q.reg || null}; }
  else fn = {'/api/live': 'api_live', '/api/fleet': 'api_fleet', '/api/stats': 'api_stats'}[u.pathname];
  return fetch(`${CFG.supabaseUrl.replace(/\/$/, '')}/rest/v1/rpc/${fn}`, {
    method: 'POST', cache: 'no-store',
    headers: {'apikey': CFG.supabaseAnonKey, 'Authorization': `Bearer ${CFG.supabaseAnonKey}`, 'Content-Type': 'application/json'},
    body: JSON.stringify(args)
  }).then(r => r.ok ? r.json() : Promise.reject(r.status));
}
const C = {burg: '#4a0b1e', gold: '#b08a42', ink: '#1f1416', grey: '#8c7f81'};

/* ---------- map ---------- */
const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const map = L.map('map', {worldCopyJump: true, scrollWheelZoom: false}).setView([47.0, 4.5], 6);
L.tileLayer(OSM, {maxZoom: 18, attribution: OSM_ATTR}).addTo(map);
map.on('click', () => map.scrollWheelZoom.enable());
const layer = L.layerGroup().addTo(map);
let firstFit = true, focus = null;

const planeSVG = hdg => `<svg class="plane-icon" width="30" height="30" viewBox="0 0 64 64" style="transform:rotate(${hdg}deg)">
  <path d="M32 3c2.4 0 3.6 3 3.6 6.4V24l21 12.6v5.2L35.6 35v13.4l6.4 5v4.4L32 55l-10 2.8v-4.4l6.4-5V35L7.4 41.8v-5.2l21-12.6V9.4C28.4 6 29.6 3 32 3z"
   fill="${C.burg}" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/></svg>`;

function aptMarker(a, grp) {
  if (!a || a.lat == null) return;
  L.circleMarker([a.lat, a.lon], {radius: 4, color: C.burg, weight: 2, fillColor: '#fff', fillOpacity: 1})
    .bindTooltip(a.icao, {permanent: true, direction: 'top', className: 'apt-label', offset: [0, -5]}).addTo(grp);
}

/* ---------- SimBrief route ---------- */
function gc(a, b) {
  const r = Math.PI / 180, p1 = a[0] * r, p2 = b[0] * r, dl = (b[1] - a[1]) * r;
  const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(h)));
}
function routePoints(rt) {
  const pts = [];
  if (rt.origin?.lat != null) pts.push({id: rt.origin.icao, lat: rt.origin.lat, lon: rt.origin.lon, apt: true});
  for (const fx of rt.fixes || []) pts.push(fx);
  const last = pts[pts.length - 1];
  if (rt.destination?.lat != null && !(last && last.id === rt.destination.icao))
    pts.push({id: rt.destination.icao, lat: rt.destination.lat, lon: rt.destination.lon, apt: true});
  return pts;
}
function progress(rt, p) {
  const pts = routePoints(rt); if (pts.length < 2 || !p) return null;
  const k = Math.cos(p.lat * Math.PI / 180);
  let best = null;
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
function drawRoute(rt, grp, nextIdx) {
  if (!rt) return [];
  const pts = routePoints(rt);
  if (pts.length > 1) L.polyline(pts.map(x => [x.lat, x.lon]), {color: C.burg, weight: 1.5, opacity: .9, dashArray: '5 5'}).addTo(grp);
  pts.forEach((x, i) => {
    if (x.apt) return;
    const isNext = i === nextIdx;
    L.circleMarker([x.lat, x.lon], {radius: isNext ? 4.5 : 2.5, color: C.burg, weight: isNext ? 2 : 1, fillColor: isNext ? C.burg : '#fff', fillOpacity: 1})
      .bindTooltip(`${esc(x.id)}${x.alt ? ' ' + fl(x.alt) : ''}`,
        {permanent: true, direction: 'right', className: 'fix-label' + (isNext ? ' next' : '') + (x.sidstar ? ' ss' : ''), offset: [5, 0]}).addTo(grp);
  });
  const alt = rt.alternate;
  if (alt?.lat != null && rt.destination?.lat != null) {
    L.polyline([[rt.destination.lat, rt.destination.lon], [alt.lat, alt.lon]], {color: C.grey, weight: 1, dashArray: '2 5'}).addTo(grp);
    L.circleMarker([alt.lat, alt.lon], {radius: 3.5, color: C.grey, weight: 1.5, fillColor: '#fff', fillOpacity: 1})
      .bindTooltip(`${esc(alt.icao)} dégagement`, {permanent: true, direction: 'top', className: 'apt-label alt', offset: [0, -5]}).addTo(grp);
  }
  return pts.map(x => [x.lat, x.lon]);
}
function zoomLabels(m) { const z = m.getZoom(), c = m.getContainer().classList; c.toggle('hide-fix', z < 8); c.toggle('hide-ss', z < 10); }
map.on('zoomend', () => zoomLabels(map)); zoomLabels(map);

function drawLive(flights) {
  layer.clearLayers();
  const bounds = [];
  for (const f of flights) {
    const p = f.position; if (!p) continue;
    if (f.track && f.track.length > 1)
      L.polyline(f.track.map(t => [t[0], t[1]]), {color: C.burg, weight: 3, opacity: .9}).addTo(layer);
    const arr = f.arr_airport;
    const rpts = drawRoute(f.route, layer, f.prog?.idx);
    if (!f.route && arr && arr.lat != null) L.polyline([[p.lat, p.lon], [arr.lat, arr.lon]], {color: C.burg, weight: 1.5, dashArray: '5 5'}).addTo(layer);
    aptMarker(f.dep_airport, layer); aptMarker(arr, layer);
    const icon = L.divIcon({html: planeSVG(p.hdg || 0), className: '', iconSize: [30, 30], iconAnchor: [15, 15]});
    L.marker([p.lat, p.lon], {icon, zIndexOffset: 1000}).addTo(layer)
      .bindPopup(`<b>${esc(f.flight_no)}</b> ${esc(f.reg)}<br>${esc(f.dep || '?')} – ${esc(f.arr || f.planned_arr || '?')}<br>${esc(f.phase)}, ${fl(p.alt)}, ${p.gs} kt`);
    bounds.push([p.lat, p.lon]);
    if (firstFit) rpts.forEach(x => bounds.push(x));
    if (f.dep_airport?.lat != null) bounds.push([f.dep_airport.lat, f.dep_airport.lon]);
    if (arr?.lat != null) bounds.push([arr.lat, arr.lon]);
  }
  if (firstFit && bounds.length) { map.fitBounds(bounds, {padding: [40, 40], maxZoom: 9}); firstFit = false; }
}

/* ---------- ops board ---------- */
function liveBoard(flights) {
  const tb = $('#liveBody');
  if (!flights.length) { tb.innerHTML = `<tr class="empty"><td colspan="9">Aucun avion en vol pour le moment.</td></tr>`; return; }
  tb.innerHTML = flights.map(f => {
    const p = f.position || {}, pr = f.prog;
    return `<tr data-live="${f.id}">
      <td><span class="fno">${esc(f.flight_no)}</span><span class="sub">${esc(f.pilot || '')}</span></td>
      <td class="m">${esc(f.reg)}${f.sim ? `<span class="sub">${esc(f.sim)}</span>` : ''}</td>
      <td class="m">${esc(f.dep || '····')}</td>
      <td class="m">${esc(f.arr || f.planned_arr || '····')}${f.route?.alternate?.icao ? `<span class="sub">dég. ${esc(f.route.alternate.icao)}</span>` : ''}</td>
      <td>${esc(f.phase)}</td>
      <td class="m r">${fl(p.alt)}</td>
      <td class="m r">${fmt(p.gs)} kt</td>
      <td class="m">${pr ? `${esc(pr.next.id)} <span class="sub">${fmt(Math.round(pr.toNext))} NM</span>` : '–'}</td>
      <td class="m r">${pr ? fmt(Math.round(pr.remaining)) + ' NM' : '–'}</td></tr>`;
  }).join('');
  tb.querySelectorAll('tr[data-live]').forEach(tr => tr.onclick = () => {
    const f = flights.find(x => x.id == tr.dataset.live);
    if (f?.position) { map.setView([f.position.lat, f.position.lon], 8); map.getContainer().scrollIntoView({behavior: 'smooth', block: 'center'}); }
  });
}

/* ---------- stats / fleet / logbook ---------- */
function renderStats(s) {
  document.querySelectorAll('#stats [data-k]').forEach(el => { const v = s[el.dataset.k]; el.textContent = v == null ? '–' : fmt(v); });
}

// profils rendus à la même échelle (64 px/m) : chaque image garde sa largeur relative, les avions restent à l'échelle
const PROFILE = {'A340-600': [4917, 1133]}, PROFILE_STD = [2950, 834];
const profileSize = a => PROFILE[a.type] || PROFILE_STD;

function renderFleet(list) {
  $('#factFleet').textContent = list.length + ' Airbus';
  const wmax = Math.max(PROFILE_STD[0], ...list.map(a => profileSize(a)[0]));
  $('#fleet').innerHTML = list.map(a => {
    const [pw, ph] = profileSize(a);
    const L_ = a.live;
    const where = L_ ? `<div class="where live">En vol, ${esc(L_.flight_no)} ${esc(L_.dep || '')} – ${esc(L_.arr || L_.planned_arr || '…')}</div>`
                     : `<div class="where">Au sol à ${esc(a.location_airport?.name || a.location)} (${esc(a.location)})</div>`;
    return `<article class="ac">
      <div class="cap">
        <span class="reg">${esc(a.reg)}</span>
        <span class="city">${esc(a.name)}</span>
        <span class="type">${esc(a.type)} · ${esc(a.engines)}</span>
        ${where}
        <div class="nums"><span>${esc(a.livery)}</span><span>${fmt(a.flights)} vols</span><span>${fmt(a.hours)} h</span><span>${fmt(a.distance_nm)} NM</span></div>
      </div>
      <img class="pic" src="img/profile-${esc(a.reg)}.webp" alt="Profil de ${esc(a.reg)} ${esc(a.name)}" width="${pw}" height="${ph}" style="width:${(100 * pw / wmax).toFixed(2)}%" loading="lazy">
    </article>`;
  }).join('');
}

function renderFlights(list) {
  if (!list.length) return;
  $('#flightsBody').innerHTML = list.map(f => `<tr data-id="${f.id}">
    <td>${dt(f.started)}</td><td><span class="fno">${esc(f.flight_no)}</span></td><td class="m">${esc(f.reg)}${f.sim ? `<span class="sub">${esc(f.sim)}</span>` : ''}</td>
    <td class="m">${esc(f.dep || '····')} – ${esc(f.arr || '····')}</td><td class="m r">${hm(f.block_min)}</td>
    <td class="m r">${f.distance_nm ? fmt(Math.round(f.distance_nm)) + ' NM' : '–'}</td>
    <td class="m r fpm ${fpmClass(f.landing_fpm)}">${f.landing_fpm != null ? f.landing_fpm + ' ft/min' : '–'}</td>
    <td><span class="st ${esc(f.status)}">${esc(f.status === 'termine' ? 'Terminé' : f.status.charAt(0).toUpperCase() + f.status.slice(1))}</span></td></tr>`).join('');
  document.querySelectorAll('#flightsBody tr[data-id]').forEach(tr => tr.onclick = () => openFlight(tr.dataset.id));
}

/* ---------- flight sheet ---------- */
let fmap = null;
async function openFlight(id) {
  const f = await getJSON(`/api/flights/${id}`);
  const ap = a => a ? (a.name ? `${a.name} (${a.icao})` : a.icao) : '?';
  $('#modalBody').innerHTML = `
    <h3>${esc(f.flight_no)}, ${esc(ap(f.dep_airport))} – ${esc(ap(f.arr_airport))}</h3>
    <p class="meta">${esc(f.reg)} · ${dt(f.started)} · ${esc(f.pilot || '')}${f.sim ? ' · ' + esc(f.sim) : ''}</p>
    ${f.route?.route ? `<p class="rt">${esc(f.route.route)}</p>` : ''}
    <div id="fmap"></div>
    <dl class="kv">
      <div><dt>Temps bloc</dt><dd>${hm(f.block_min)}</dd></div>
      <div><dt>Temps de vol</dt><dd>${hm(f.air_min)}</dd></div>
      <div><dt>Distance</dt><dd>${f.distance_nm ? fmt(Math.round(f.distance_nm)) + ' NM' : '–'}</dd></div>
      <div><dt>Altitude max</dt><dd>${f.max_alt ? fl(f.max_alt) : '–'}</dd></div>
      <div><dt>Carburant</dt><dd>${f.fuel_used != null ? fmt(f.fuel_used) + ' kg' : '–'}</dd></div>
      <div><dt>Toucher</dt><dd class="fpm ${fpmClass(f.landing_fpm)}">${f.landing_fpm != null ? f.landing_fpm + ' ft/min' : '–'}</dd></div>
      <div><dt>Facteur de charge</dt><dd>${f.landing_g ? f.landing_g.toFixed(2) + ' g' : '–'}</dd></div>
      <div><dt>Statut</dt><dd>${esc(f.status === 'termine' ? 'Terminé' : f.status)}</dd></div>
    </dl>
    <svg class="profile" id="prof" preserveAspectRatio="none"></svg>`;
  $('#modal').showModal();
  if (fmap) fmap.remove();
  fmap = L.map('fmap', {attributionControl: false, scrollWheelZoom: false});
  L.tileLayer(OSM, {maxZoom: 18}).addTo(fmap);
  const g = L.layerGroup().addTo(fmap);
  const pts = f.track.map(p => [p.lat, p.lon]);
  drawRoute(f.route, g, -1);
  if (pts.length > 1) {
    const pl = L.polyline(pts, {color: C.burg, weight: 3}).addTo(g);
    fmap.fitBounds(pl.getBounds(), {padding: [30, 30]});
  } else if (f.dep_airport?.lat != null) fmap.setView([f.dep_airport.lat, f.dep_airport.lon], 9);
  aptMarker(f.dep_airport, g); aptMarker(f.arr_airport, g);
  fmap.on('zoomend', () => zoomLabels(fmap)); zoomLabels(fmap);
  const svg = $('#prof'); const W = svg.clientWidth || 800, H = 110;
  if (f.track.length > 1) {
    const t0 = f.track[0].t, t1 = f.track.at(-1).t, amax = Math.max(1000, ...f.track.map(p => p.alt || 0));
    const xy = f.track.map(p => `${((p.t - t0) / (t1 - t0 || 1) * W).toFixed(1)},${(H - 2 - (p.alt || 0) / amax * (H - 22)).toFixed(1)}`);
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = `<line x1="0" y1="${H - 1}" x2="${W}" y2="${H - 1}" stroke="currentColor" stroke-width="1" opacity=".5"/>
      <polyline points="${xy.join(' ')}" fill="none" stroke="${C.burg}" stroke-width="1.6"/>
      <text x="0" y="12" font-size="11" font-family="IBM Plex Mono, monospace" fill="currentColor">Profil vertical, max ${fl(amax)}</text>`;
  }
}
$('#modalClose').onclick = () => $('#modal').close();
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') $('#modal').close(); });

/* ---------- refresh loop ---------- */
async function tick() {
  try {
    const [live, stats, fleet, flights] = await Promise.all([
      getJSON('/api/live'), getJSON('/api/stats'), getJSON('/api/fleet'), getJSON('/api/flights?limit=25')]);
    const fls = live.flights;
    fls.forEach(f => { f.prog = f.route ? progress(f.route, f.position) : null; });
    drawLive(fls); liveBoard(fls); renderStats(stats); renderFleet(fleet); renderFlights(flights);
    const t = new Date().toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    $('#liveSub').textContent = fls.length ? `${fls.length} en vol · ${t}` : `aucun vol · ${t}`;
    $('#liveDot').classList.toggle('on', fls.length > 0);
  } catch (e) {
    $('#liveSub').textContent = 'serveur injoignable';
    $('#liveDot').classList.remove('on');
  }
}
tick(); setInterval(tick, REFRESH);
