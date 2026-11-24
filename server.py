"""AIR BURGUNDY - serveur de la compagnie virtuelle.

Sert le site (dossier web/) et l'API JSON (/api/...), stockage SQLite (data/airburgundy.db).
Aucune dependance externe : Python 3.8+ suffit.

    python server.py                 # http://127.0.0.1:8080
    python server.py --host 0.0.0.0  # accessible depuis le reseau local

Production (variables d'environnement, prioritaires sur config.json) :
    AIRBURGUNDY_API_KEY   cle secrete de l'ACARS (obligatoire en ligne)
    AIRBURGUNDY_DATA      dossier persistant de la base SQLite (ex. /data)
    HOST / PORT           interface et port d'ecoute (ex. 0.0.0.0 / 8080)
"""
import argparse, json, math, os, re, secrets, sqlite3, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, 'web')
DATA = os.environ.get('AIRBURGUNDY_DATA') or os.path.join(ROOT, 'data')
DB = os.path.join(DATA, 'airburgundy.db')
AIRPORTS_FILE = os.path.join(ROOT, 'data', 'airports.json')
MAX_BODY = 2 * 1024 * 1024
CONFIG = os.path.join(ROOT, 'config.json')

VA = {'name': 'AIR BURGUNDY', 'icao': 'BRG', 'callsign': 'BURGUNDY', 'base': 'LFSD',
      'slogan': 'Le ciel, en Grand Cru.'}
FLEET = [
    ('F-DIMI', 'Ville de Dijon', 'A321neo XLR', 'PW1130G-JM', 'Classique', 'img/profile-F-DIMI.webp'),
    ('F-NINO', 'Ville de Montceau', 'A321neo XLR', 'PW1130G-JM', 'Classique', 'img/profile-F-NINO.webp'),
    ('F-JERO', "Ville d’Autun", 'A321neo XLR', 'PW1130G-JM', 'Édition Mosaïque', 'img/profile-F-JERO.webp'),
    ('F-PINO', 'Ville de Beaune', 'A321neo XLR', 'PW1130G-JM', 'Classique', 'img/profile-F-PINO.webp'),
    ('F-LAUR', 'Ville de Mâcon', 'A319', 'CFM56-5B', 'Vendanges', 'img/profile-F-LAUR.webp'),
]
LIVE_TIMEOUT = 180          # s sans position -> l'avion n'apparait plus sur la carte
LOST_TIMEOUT = 6 * 3600     # s sans position -> vol actif clos en "perdu"

_lock = threading.Lock()
AIRPORTS = {}


def load_config():
    env_key = os.environ.get('AIRBURGUNDY_API_KEY')
    if env_key:
        return {'api_key': env_key}
    if not os.path.exists(CONFIG):
        cfg = {'api_key': secrets.token_urlsafe(24), 'pilots': ['Pilote']}
        json.dump(cfg, open(CONFIG, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        print('config.json cree - cle ACARS :', cfg['api_key'])
    return json.load(open(CONFIG, encoding='utf-8'))


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    os.makedirs(DATA, exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS aircraft(reg TEXT PRIMARY KEY, name TEXT, type TEXT, engines TEXT,
            livery TEXT, image TEXT, location TEXT);
        CREATE TABLE IF NOT EXISTS flights(id INTEGER PRIMARY KEY AUTOINCREMENT, flight_no TEXT, reg TEXT,
            pilot TEXT, dep TEXT, arr TEXT, planned_arr TEXT, status TEXT, phase TEXT,
            started REAL, block_off REAL, takeoff REAL, landing REAL, block_on REAL, ended REAL,
            distance_nm REAL DEFAULT 0, fuel_start REAL, fuel_end REAL, landing_fpm REAL, landing_g REAL,
            max_alt REAL DEFAULT 0, last_update REAL, sim TEXT);
        CREATE TABLE IF NOT EXISTS positions(flight_id INTEGER, t REAL, lat REAL, lon REAL, alt REAL,
            gs REAL, hdg REAL, vs REAL, ias REAL, phase TEXT);
        CREATE INDEX IF NOT EXISTS pos_f ON positions(flight_id, t);
        """)
        cols = [r[1] for r in c.execute('PRAGMA table_info(flights)')]
        if 'route' not in cols:
            c.execute('ALTER TABLE flights ADD COLUMN route TEXT')
        for reg, name, typ, eng, liv, img in FLEET:
            c.execute('INSERT INTO aircraft(reg,name,type,engines,livery,image,location) VALUES(?,?,?,?,?,?,?) '
                      'ON CONFLICT(reg) DO UPDATE SET name=excluded.name, type=excluded.type, engines=excluded.engines, '
                      'livery=excluded.livery, image=excluded.image',
                      (reg, name, typ, eng, liv, img, VA['base']))


def load_airports():
    p = AIRPORTS_FILE
    if os.path.exists(p):
        AIRPORTS.update(json.load(open(p, encoding='utf-8')))


def nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(a)))


def apt(icao):
    a = AIRPORTS.get((icao or '').upper())
    return {'icao': icao, 'name': a[0], 'lat': a[1], 'lon': a[2]} if a else ({'icao': icao} if icao else None)


def flight_json(r, c=None):
    f = dict(r)
    try: f['route'] = json.loads(f['route']) if f.get('route') else None
    except Exception: f['route'] = None
    f['dep_airport'] = apt(f['dep']); f['arr_airport'] = apt(f['arr'] or f['planned_arr'])
    if f['route'] and f['route'].get('destination') and (not f['arr_airport'] or f['arr_airport'].get('lat') is None):
        f['arr_airport'] = f['route']['destination']
    t0 = f['block_off'] or f['started']; t1 = f['block_on'] or f['ended'] or f['last_update']
    f['block_min'] = round((t1 - t0) / 60) if t0 and t1 else None
    f['air_min'] = round(((f['landing'] or f['last_update']) - f['takeoff']) / 60) if f['takeoff'] else None
    f['fuel_used'] = round(f['fuel_start'] - f['fuel_end']) if f['fuel_start'] and f['fuel_end'] else None
    if c is not None:
        p = c.execute('SELECT * FROM positions WHERE flight_id=? ORDER BY t DESC LIMIT 1', (f['id'],)).fetchone()
        f['position'] = dict(p) if p else None
    return f


def expire_lost(c):
    c.execute("UPDATE flights SET status='perdu', ended=last_update WHERE status='actif' AND last_update<?",
              (time.time() - LOST_TIMEOUT,))


# ------------------------------------------------------------------ API ----
def api_get(path, q):
    with db() as c:
        expire_lost(c)
        if path == '/api/va':
            return VA
        if path == '/api/live':
            rows = c.execute("SELECT * FROM flights WHERE status='actif' AND last_update>? ORDER BY started",
                             (time.time() - LIVE_TIMEOUT,)).fetchall()
            out = []
            for r in rows:
                f = flight_json(r, c)
                tr = c.execute('SELECT lat,lon,alt FROM positions WHERE flight_id=? ORDER BY t', (r['id'],)).fetchall()
                f['track'] = [[p['lat'], p['lon'], p['alt']] for p in tr]
                out.append(f)
            return {'server_time': time.time(), 'flights': out}
        if path == '/api/fleet':
            out = []
            for a in c.execute('SELECT * FROM aircraft ORDER BY rowid'):
                d = dict(a)
                s = c.execute("SELECT COUNT(*) n, COALESCE(SUM(landing-takeoff),0) air, COALESCE(SUM(distance_nm),0) dist "
                              "FROM flights WHERE reg=? AND status='termine'", (a['reg'],)).fetchone()
                d.update(flights=s['n'], hours=round(s['air'] / 3600, 1), distance_nm=round(s['dist']))
                live = c.execute("SELECT * FROM flights WHERE reg=? AND status='actif' AND last_update>? ORDER BY started DESC LIMIT 1",
                                 (a['reg'], time.time() - LIVE_TIMEOUT)).fetchone()
                d['live'] = flight_json(live, c) if live else None
                d['location_airport'] = apt(a['location'])
                out.append(d)
            return out
        if path == '/api/flights':
            lim = max(1, min(500, int(q.get('limit', ['50'])[0])))
            reg = q.get('reg', [None])[0]
            sql = "SELECT * FROM flights WHERE status!='actif'" + (' AND reg=?' if reg else '') + ' ORDER BY started DESC LIMIT ?'
            return [flight_json(r) for r in c.execute(sql, ((reg, lim) if reg else (lim,)))]
        m = re.fullmatch(r'/api/flights/(\d+)', path)
        if m:
            r = c.execute('SELECT * FROM flights WHERE id=?', (int(m.group(1)),)).fetchone()
            if not r:
                return None
            f = flight_json(r, c)
            f['track'] = [dict(p) for p in c.execute('SELECT t,lat,lon,alt,gs,hdg,vs,ias,phase FROM positions WHERE flight_id=? ORDER BY t', (r['id'],))]
            return f
        if path == '/api/stats':
            s = c.execute("SELECT COUNT(*) n, COALESCE(SUM(landing-takeoff),0) air, COALESCE(SUM(distance_nm),0) dist, "
                          "AVG(landing_fpm) avg_fpm, MAX(landing_fpm) best_fpm, COALESCE(SUM(fuel_start-fuel_end),0) fuel, "
                          "COUNT(DISTINCT arr) dests FROM flights WHERE status='termine'").fetchone()
            best = c.execute("SELECT id, flight_no, reg, arr, landing_fpm FROM flights WHERE status='termine' AND landing_fpm IS NOT NULL "
                             "ORDER BY landing_fpm DESC LIMIT 1").fetchone()
            live = c.execute("SELECT COUNT(*) FROM flights WHERE status='actif' AND last_update>?", (time.time() - LIVE_TIMEOUT,)).fetchone()[0]
            return {'flights': s['n'], 'hours': round(s['air'] / 3600, 1), 'distance_nm': round(s['dist']),
                    'fuel_kg': round(s['fuel']), 'destinations': s['dests'],
                    'avg_landing_fpm': round(s['avg_fpm']) if s['avg_fpm'] is not None else None,
                    'best_landing': dict(best) if best else None, 'live': live}
        m = re.fullmatch(r'/api/airports/([A-Za-z0-9]{3,4})', path)
        if m:
            return apt(m.group(1).upper()) if m.group(1).upper() in AIRPORTS else None
    return None


def api_post(path, body):
    now = time.time()
    with _lock, db() as c:
        if path == '/api/acars/start':
            reg = body.get('reg', '').upper()
            if not c.execute('SELECT 1 FROM aircraft WHERE reg=?', (reg,)).fetchone():
                return 400, {'error': f"{reg} n'est pas un avion AIR BURGUNDY"}
            # un seul vol actif par avion : on clot les precedents
            c.execute("UPDATE flights SET status='interrompu', ended=last_update WHERE reg=? AND status='actif'", (reg,))
            rt = body.get('route') or {}
            if not body.get('arr') and (rt.get('destination') or {}).get('icao'):
                body['arr'] = rt['destination']['icao']
            fno = body.get('flight_no') or rt.get('flight_no') or 'BRG' + str(100 + c.execute('SELECT COUNT(*) FROM flights').fetchone()[0] + 1)
            cur = c.execute("INSERT INTO flights(flight_no,reg,pilot,dep,planned_arr,status,phase,started,last_update,fuel_start,sim) "
                            "VALUES(?,?,?,?,?,'actif',?,?,?,?,?)",
                            (fno, reg, body.get('pilot'), (body.get('dep') or '').upper() or None,
                             (body.get('arr') or '').upper() or None, body.get('phase', 'Embarquement'),
                             now, now, body.get('fuel'), body.get('sim') or 'X-Plane'))
            if rt:
                c.execute('UPDATE flights SET route=? WHERE id=?', (json.dumps(rt, ensure_ascii=False), cur.lastrowid))
            return 200, {'flight_id': cur.lastrowid, 'flight_no': fno}
        fid = body.get('flight_id')
        f = c.execute("SELECT * FROM flights WHERE id=?", (fid,)).fetchone()
        if not f:
            return 404, {'error': 'vol inconnu'}
        if path == '/api/acars/pos':
            pts = body.get('positions', [])
            last = c.execute('SELECT lat,lon FROM positions WHERE flight_id=? ORDER BY t DESC LIMIT 1', (fid,)).fetchone()
            dist = f['distance_nm'] or 0; maxalt = f['max_alt'] or 0
            for p in pts:
                if last and p.get('gs', 0) > 30:     # distance parcourue en vol / au roulage rapide
                    dist += nm(last[0], last[1], p['lat'], p['lon'])
                last = (p['lat'], p['lon']); maxalt = max(maxalt, p.get('alt', 0))
                c.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (fid, p.get('t', now), p['lat'], p['lon'], p.get('alt'), p.get('gs'), p.get('hdg'),
                           p.get('vs'), p.get('ias'), p.get('phase')))
            ev = body.get('events', {})
            sets = {'distance_nm': dist, 'max_alt': maxalt, 'last_update': now}
            if pts: sets['phase'] = pts[-1].get('phase', f['phase'])
            for k in ('block_off', 'takeoff', 'landing', 'landing_fpm', 'landing_g', 'dep'):
                if ev.get(k) is not None and f[k] is None:
                    sets[k] = ev[k]
            c.execute('UPDATE flights SET ' + ','.join(f'{k}=?' for k in sets) + ' WHERE id=?', (*sets.values(), fid))
            return 200, {'ok': True, 'stored': len(pts)}
        if path == '/api/acars/route':
            rt = body.get('route') or {}
            dest = (rt.get('destination') or {}).get('icao')
            c.execute('UPDATE flights SET route=?, planned_arr=COALESCE(?, planned_arr), flight_no=COALESCE(?, flight_no) WHERE id=?',
                      (json.dumps(rt, ensure_ascii=False), dest, rt.get('flight_no'), fid))
            return 200, {'ok': True, 'fixes': len(rt.get('fixes', []))}
        if path == '/api/acars/end':
            status = body.get('status', 'termine')
            arr = (body.get('arr') or f['planned_arr'] or '').upper() or None
            c.execute('UPDATE flights SET status=?, phase=?, arr=?, block_on=?, ended=?, fuel_end=?, last_update=?, '
                      'landing=COALESCE(landing,?), landing_fpm=COALESCE(landing_fpm,?), landing_g=COALESCE(landing_g,?) WHERE id=?',
                      (status, 'Arrivé' if status == 'termine' else status.capitalize(), arr, body.get('block_on', now), now,
                       body.get('fuel'), now, body.get('landing'), body.get('landing_fpm'), body.get('landing_g'), fid))
            if status == 'termine' and arr:
                c.execute('UPDATE aircraft SET location=? WHERE reg=?', (arr, f['reg']))
            return 200, {'ok': True}
    return 404, {'error': 'route inconnue'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def log_message(self, fmt, *args):
        try:
            err = len(args) > 1 and str(args[1])[:1] in ('4', '5')
        except Exception:
            err = True
        if err or '/api/acars' in (getattr(self, 'path', '') or ''):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        super().end_headers()

    def list_directory(self, path):          # pas de listing de dossiers en ligne
        self.send_error(404)
        return None

    def send_json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith('/api/'):
            try:
                r = api_get(u.path.rstrip('/'), parse_qs(u.query))
            except Exception as e:
                return self.send_json(500, {'error': str(e)})
            return self.send_json(200, r) if r is not None else self.send_json(404, {'error': 'introuvable'})
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        if not u.path.startswith('/api/acars/'):
            return self.send_json(404, {'error': 'route inconnue'})
        if not secrets.compare_digest(self.headers.get('X-API-Key', ''), CFG['api_key']):
            return self.send_json(401, {'error': 'cle ACARS invalide'})
        try:
            n = int(self.headers.get('Content-Length', 0) or 0)
            if n > MAX_BODY:
                return self.send_json(413, {'error': 'requete trop grosse'})
            body = json.loads(self.rfile.read(n) or b'{}')
            code, r = api_post(u.path.rstrip('/'), body)
        except Exception as e:
            code, r = 500, {'error': str(e)}
        self.send_json(code, r)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default=os.environ.get('HOST', '127.0.0.1'))
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8080)))
    a = ap.parse_args()
    CFG = load_config(); init_db(); load_airports()
    print(f"AIR BURGUNDY - site et API sur http://{a.host if a.host != '0.0.0.0' else '127.0.0.1'}:{a.port}  "
          f"({len(AIRPORTS)} aeroports)")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
else:
    CFG = None
