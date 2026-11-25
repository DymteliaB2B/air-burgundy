"""AIR BURGUNDY ACARS - tracker X-Plane 11 et 12 (aucun plugin requis).

Lit X-Plane 11 / 12 en UDP (protocole RREF natif, port 49000) et envoie le vol a l'API AIR BURGUNDY.
L'immatriculation est detectee depuis la livree chargee (dossier "AIR BURGUNDY F-XXXX").
Le terrain de depart / d'arrivee est detecte automatiquement (aeroport le plus proche).
Le vol se termine tout seul au parking (au sol, arrete, moteurs coupes ou frein de parc 20 s).

    python acars.py                         # tout automatique
    python acars.py --arr LFPG --flight BRG102
    python acars.py --reg F-PINO --server http://monsite:8080
"""
import argparse, json, math, os, re, socket, struct, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
FT = 3.28084; KT = 1.943844

DREFS = [
    ('lat', 'sim/flightmodel/position/latitude'),
    ('lon', 'sim/flightmodel/position/longitude'),
    ('elev', 'sim/flightmodel/position/elevation'),          # m MSL
    ('agl', 'sim/flightmodel/position/y_agl'),               # m
    ('gs', 'sim/flightmodel/position/groundspeed'),          # m/s
    ('hdg', 'sim/flightmodel/position/true_psi'),
    ('vs', 'sim/flightmodel/position/vh_ind_fpm'),
    ('ias', 'sim/flightmodel/position/indicated_airspeed'),
    ('ground', 'sim/flightmodel/failures/onground_any'),
    ('fuel', 'sim/flightmodel/weight/m_fuel_total'),         # kg
    ('paused', 'sim/time/paused'),
    ('gn', 'sim/flightmodel/forces/g_nrml'),
    ('pbrake', 'sim/cockpit2/controls/parking_brake_ratio'),
    ('eng1', 'sim/flightmodel/engine/ENGN_running[0]'),
    ('eng2', 'sim/flightmodel/engine/ENGN_running[1]'),
    ('xpver', 'sim/version/xplane_internal_version'),
    ('vy', 'sim/flightmodel/position/local_vy'),             # m/s, vitesse verticale vraie (sans le retard du vario)
]
LIVERY_LEN = 160
LIVERY0 = len(DREFS)   # index des caracteres de sim/aircraft/view/acf_livery_path


class XPlane:
    def __init__(self, host, port):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0)); self.sock.settimeout(0.5)
        self.v = {}; self.chars = {}; self.last_rx = 0
        # toucher mesure au paquet pres (20 Hz) avec la vitesse verticale vraie (local_vy) :
        # descente la plus forte dans la demi-seconde avant le contact + g max apres contact
        self.air_vs = None; self.td_vs = None; self.td_t = None; self.td_g = 1.0; self._was_ground = None
        self._air_hist = []

    def sub(self, idx, dref, freq):
        self.sock.sendto(b'RREF\x00' + struct.pack('<ii400s', freq, idx, dref.encode()), self.addr)

    def subscribe(self, freq=5):
        for i, (n, d) in enumerate(DREFS):
            self.sub(i, d, 20 if n in ('vs', 'vy', 'ground', 'gn', 'agl') else freq)
        for k in range(LIVERY_LEN):
            self.sub(LIVERY0 + k, f'sim/aircraft/view/acf_livery_path[{k}]', 1)

    def unsubscribe(self):
        for i, (_, d) in enumerate(DREFS):
            self.sub(i, d, 0)
        for k in range(LIVERY_LEN):
            self.sub(LIVERY0 + k, f'sim/aircraft/view/acf_livery_path[{k}]', 0)

    def poll(self, dur):
        end = time.time() + dur
        while time.time() < end:
            try:
                data, _ = self.sock.recvfrom(8192)
            except socket.timeout:
                continue
            except ConnectionResetError:      # Windows : X-Plane pas encore lance
                time.sleep(0.5); continue
            if data[:4] != b'RREF':
                continue
            self.last_rx = time.time()
            for o in range(5, len(data) - 7, 8):
                i, val = struct.unpack('<if', data[o:o + 8])
                if i < LIVERY0:
                    self.v[DREFS[i][0]] = val
                else:
                    self.chars[i - LIVERY0] = int(val)
            self._touchdown_watch()

    def _touchdown_watch(self):
        if 'ground' not in self.v or 'vs' not in self.v:
            return
        g = self.v['ground'] > 0.5; now = time.time()
        fpm = self.v['vy'] * 196.850394 if 'vy' in self.v else self.v['vs']
        if not g:
            self.air_vs = fpm
            self._air_hist = [(t, x) for t, x in self._air_hist if now - t < 1.0] + [(now, fpm)]
        elif self._was_ground is False and self.air_vs is not None and (self.td_t is None or now - self.td_t > 15):
            win = [x for t, x in self._air_hist if now - t <= 0.6] or [self.air_vs]
            self.td_vs = min(win); self.td_t = now; self.td_g = self.v.get('gn', 1.0)   # rebonds ignores 15 s
        if g and self.td_t and now - self.td_t < 2.5:
            self.td_g = max(self.td_g, self.v.get('gn', 1.0))
        self._was_ground = g

    def livery(self):
        s = ''
        for k in range(LIVERY_LEN):
            c = self.chars.get(k, 0)
            if not c: break
            s += chr(c)
        return s


def nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(a)))


class Airports:
    def __init__(self):
        p = os.path.join(ROOT, 'data', 'airports.json')
        self.d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
        if not self.d:
            print('! data/airports.json absent : lance build_airports.py pour la detection auto des terrains')

    def nearest(self, lat, lon, max_nm=5):
        best = None
        for k, (_, la, lo) in self.d.items():
            if abs(la - lat) > 0.2 or abs(lo - lon) > 0.3:
                continue
            dd = nm(lat, lon, la, lo)
            if dd <= max_nm and (best is None or dd < best[1]):
                best = (k, dd)
        return best[0] if best else None

    def obj(self, icao):
        """{icao, name, lat, lon} pour le site (Supabase n'a pas de base d'aéroports)."""
        a = self.d.get((icao or '').upper())
        return {'icao': icao.upper(), 'name': a[0], 'lat': a[1], 'lon': a[2]} if a else ({'icao': icao.upper()} if icao else None)




PHASE_FR = {'boarding': 'Embarquement', 'taxi_out': 'Roulage', 'takeoff': 'Décollage', 'climb': 'Montée',
            'cruise': 'Croisière', 'descent': 'Descente', 'approach': 'Approche', 'landed': 'Atterri',
            'taxi_in': 'Roulage arrivée', 'arrived': 'Arrivé'}


class Flight:
    """Machine a etats des phases + evenements (block off, decollage, atterrissage)."""
    def __init__(self):
        self.phase = 'boarding'; self.ev = {}; self.sent_ev = set()
        self.airborne_once = False; self.prev_ground = None; self.park_since = None
        self.vs_hist = []; self.g_max = 1.0; self.td = None; self.last_air_vs = None

    def update(self, v, now, xp):
        ground = v.get('ground', 1) > 0.5
        gs = v.get('gs', 0) * KT; agl = v.get('agl', 0) * FT; vs = v.get('vs', 0); ias = v.get('ias', 0)
        eng = v.get('eng1', 0) > 0.5 or v.get('eng2', 0) > 0.5
        # toucher : mesure par XPlane au paquet pres ; on publie 3 s apres (g max stabilise)
        if self.airborne_once and 'landing' not in self.ev and xp.td_t and xp.td_t > self.ev.get('takeoff', 0) \
                and now - xp.td_t > 3:
            self.ev['landing'] = xp.td_t
            self.ev['landing_fpm'] = round(xp.td_vs)
            self.ev['landing_g'] = round(xp.td_g, 2)
        self.prev_ground = ground
        p = self.phase
        if ground:
            if not self.airborne_once:
                if gs > 3 and 'block_off' not in self.ev:
                    self.ev['block_off'] = now
                if ias > 40: p = 'takeoff'
                elif gs > 3: p = 'taxi_out'
            else:
                if gs > 40: p = 'landed'
                elif gs > 3: p = 'taxi_in'
                else:
                    parked = (not eng) or v.get('pbrake', 0) > 0.9
                    self.park_since = (self.park_since or now) if parked else None
                    p = 'arrived' if self.park_since and now - self.park_since > 20 else 'taxi_in'
        else:
            if not self.airborne_once:
                self.airborne_once = True; self.ev['takeoff'] = now
            if p in ('boarding', 'taxi_out', 'takeoff') and agl < 1500: p = 'takeoff'
            elif vs > 400: p = 'climb'
            elif vs < -400: p = 'approach' if agl < 4000 else 'descent'
            elif agl > 8000: p = 'cruise'
            elif p not in ('approach',): p = 'climb' if p == 'takeoff' else p
        self.phase = p
        return p

    def new_events(self):
        out = {k: v for k, v in self.ev.items() if (k, v) not in self.sent_ev}
        return out

    def mark_sent(self, ev):
        self.sent_ev |= set(ev.items())


def sim_name(v):
    """sim/version/xplane_internal_version : 11xxx = X-Plane 11, 12xxxx = X-Plane 12."""
    v = int(v or 0)
    if v >= 120000 or 12000 <= v < 13000: return 'X-Plane 12'
    if 11000 <= v < 12000 or 110000 <= v < 120000: return 'X-Plane 11'
    return 'X-Plane'


def detect_reg(livery):
    m = re.search(r'F-[A-Z]{4}', livery.upper())
    return m.group(0) if m else None


def main():
    ap = argparse.ArgumentParser(description='AIR BURGUNDY ACARS pour X-Plane 11 et 12')
    ap.add_argument('--server', help='URL de l\'API (defaut : config.json ou http://127.0.0.1:8080)')
    ap.add_argument('--key', help='cle ACARS (defaut : config.json)')
    ap.add_argument('--xp', default='127.0.0.1:49000', help='adresse X-Plane hote:port')
    ap.add_argument('--reg', help='forcer l\'immatriculation (sinon detectee via la livree)')
    ap.add_argument('--arr', help='terrain d\'arrivee prevu (OACI)')
    ap.add_argument('--flight', help='numero de vol, ex. BRG102')
    ap.add_argument('--pilot', help='nom du pilote')
    ap.add_argument('--rate', type=float, default=5, help='secondes entre deux positions')
    ap.add_argument('--simbrief', help='pseudo SimBrief (defaut : "simbrief_user" de config.json)')
    ap.add_argument('--no-simbrief', action='store_true', help='ne pas charger le plan SimBrief')
    a = ap.parse_args()
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

    cfg = {}
    cp = os.path.join(ROOT, 'config.json')
    if os.path.exists(cp):
        cfg = json.load(open(cp, encoding='utf-8'))
    from vaclient import Client, ApiError
    api = Client(cfg, server=a.server, key=a.key)
    print('  Serveur :', 'Supabase' if api.supabase else api.url)
    pilot = a.pilot or (cfg.get('pilots') or ['Pilote'])[0]
    h, p = a.xp.split(':')
    xp = XPlane(h, int(p)); apts = Airports()

    print('AIR ◆ BURGUNDY  ACARS  -  connexion a X-Plane', a.xp, '...')
    while True:
        xp.subscribe(); xp.poll(2)
        if 'lat' in xp.v: break
        print('  X-Plane ne repond pas (lance-le, vol charge). Nouvel essai...')
    xp.poll(1.5)
    reg = (a.reg or detect_reg(xp.livery()) or '').upper()
    if not reg:
        print('! Livree non reconnue :', repr(xp.livery()) or '(vide)')
        reg = input('  Immatriculation AIR BURGUNDY (ex. F-PINO) : ').strip().upper()
    v = xp.v
    sim = sim_name(v.get('xpver'))
    dep = apts.nearest(v['lat'], v['lon'])
    print(f'  {sim}  -  avion {reg}  -  au sol a {dep or "?"}  -  carburant {v.get("fuel", 0):.0f} kg')

    route = None
    sb_user = a.simbrief or cfg.get('simbrief_user')
    if sb_user and not a.no_simbrief:
        try:
            import simbrief
            route = simbrief.fetch(sb_user)
            o = (route.get('origin') or {}).get('icao')
            if dep and o and o != dep:
                print(f'  ! OFP SimBrief au depart de {o}, tu es a {dep} : plan ignore (regenere-le sur SimBrief)')
                route = None
            else:
                print('  SimBrief :', simbrief.summary(route).replace('\n', '\n            '))
        except Exception as e:
            print('  ! SimBrief indisponible :', e)

    try:
        r = api.post('/api/acars/start', {'reg': reg, 'pilot': pilot, 'dep': dep, 'dep_airport': apts.obj(dep),
                                          'arr': a.arr, 'flight_no': a.flight,
                                          'fuel': v.get('fuel'), 'phase': PHASE_FR['boarding'], 'route': route, 'sim': sim})
    except ApiError as e:
        sys.exit(f'! Le serveur refuse le vol : {e}')
    except Exception as e:
        sys.exit(f'! Serveur injoignable ({api.url}) : {e}')
    fid = r['flight_id']
    print(f'  Vol {r["flight_no"]} ouvert (id {fid}). Bon vol ! (Ctrl+C pour interrompre)\n')

    fl = Flight(); buf = []; last_pos = 0; last_phase = None; last_send = 0; shown_td = False
    try:
        while True:
            xp.poll(1.0)
            now = time.time()
            if now - xp.last_rx > 15:
                print('\r  ... X-Plane silencieux (pause / chargement ?)        ', end=''); continue
            v = dict(xp.v)
            if v.get('paused', 0) > 0.5:
                continue
            ph = fl.update(v, now, xp)
            if ph != last_phase:
                print(f'\n  [{time.strftime("%H:%M:%S")}] {PHASE_FR[ph]}', end='')
                last_phase = ph
            if 'landing' in fl.ev and not shown_td:
                shown_td = True
                print(f'\n  >>> Toucher : {fl.ev["landing_fpm"]} ft/min, {fl.ev["landing_g"]:.2f} g', end='')
            on_ground = v.get('ground', 1) > 0.5
            every = a.rate if not on_ground else a.rate * 3
            if now - last_pos >= every or ph != (buf[-1]['phase_k'] if buf else None):
                buf.append({'t': now, 'lat': round(v['lat'], 6), 'lon': round(v['lon'], 6),
                            'alt': round(v.get('elev', 0) * FT), 'gs': round(v.get('gs', 0) * KT),
                            'hdg': round(v.get('hdg', 0)), 'vs': round(v.get('vs', 0)), 'ias': round(v.get('ias', 0)),
                            'phase': PHASE_FR[ph], 'phase_k': ph})
                last_pos = now
                print(f'\r  {PHASE_FR[ph]:<18} FL{round(v.get("elev",0)*FT/100):03d}  GS {v.get("gs",0)*KT:4.0f} kt  '
                      f'VS {v.get("vs",0):+5.0f}  ', end='')
            if buf and now - last_send >= a.rate:
                ev = fl.new_events()
                if 'block_off' in ev and fl.ev.get('takeoff') is None:
                    ev['dep'] = apts.nearest(v['lat'], v['lon'], 8) or dep
                    ev['dep_airport'] = apts.obj(ev['dep'])
                try:
                    api.post('/api/acars/pos', {'flight_id': fid, 'positions': [{k: x for k, x in b.items() if k != 'phase_k'} for b in buf],
                                                'events': ev})
                    buf = []; fl.mark_sent({k: x for k, x in ev.items() if k not in ('dep', 'dep_airport')})
                except Exception as e:
                    print(f'\n  ! envoi differe ({len(buf)} pts en attente) : {e}', end='')
                last_send = now
            if ph == 'arrived':
                break
        arr = apts.nearest(v['lat'], v['lon'], 8) or a.arr
        api.post('/api/acars/pos', {'flight_id': fid, 'positions': [{k: x for k, x in b.items() if k != 'phase_k'} for b in buf],
                                    'events': fl.new_events()})
        api.post('/api/acars/end', {'flight_id': fid, 'status': 'termine', 'arr': arr, 'arr_airport': apts.obj(arr), 'fuel': v.get('fuel'),
                                    'block_on': time.time(), **{k: fl.ev.get(k) for k in ('landing', 'landing_fpm', 'landing_g')}})
        print(f'\n\n  Vol termine a {arr or "?"}  -  toucher {fl.ev.get("landing_fpm", "?")} ft/min. Merci d\'avoir vole AIR BURGUNDY !')
    except KeyboardInterrupt:
        try:
            st = 'termine' if fl.phase in ('landed', 'taxi_in') else 'interrompu'
            arr = apts.nearest(v['lat'], v['lon'], 8) if st == 'termine' else None
            if buf:
                api.post('/api/acars/pos', {'flight_id': fid, 'positions': [{k: x for k, x in b.items() if k != 'phase_k'} for b in buf],
                                            'events': fl.new_events()})
            api.post('/api/acars/end', {'flight_id': fid, 'status': st, 'arr': arr, 'arr_airport': apts.obj(arr), 'fuel': v.get('fuel'),
                                        **{k: fl.ev.get(k) for k in ('landing', 'landing_fpm', 'landing_g')}})
            print(f'\n  Vol {st}.')
        except Exception as e:
            print('\n  ! cloture impossible :', e)
    finally:
        try: xp.unsubscribe()
        except Exception: pass


if __name__ == '__main__':
    main()
