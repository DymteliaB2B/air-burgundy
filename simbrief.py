"""SimBrief : récupère le dernier plan de vol (OFP) d'un pilote et le résume pour AIR BURGUNDY.

    python simbrief.py                 # affiche ton dernier OFP (pseudo SimBrief lu dans config.json)
    python simbrief.py --attach        # rattache ton dernier OFP au vol AIR BURGUNDY en cours
    python simbrief.py --user MonPseudo
"""
import argparse, json, os, sys, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = 'https://www.simbrief.com/api/xml.fetcher.php'


def _f(x, default=None):
    try: return float(x)
    except (TypeError, ValueError): return default


def _apt(a):
    if not isinstance(a, dict): return None
    return {'icao': a.get('icao_code'), 'name': a.get('name'), 'lat': _f(a.get('pos_lat')), 'lon': _f(a.get('pos_long')),
            'rwy': a.get('plan_rwy') or None}


def fetch(user):
    """user : pseudo SimBrief ou identifiant numérique (Pilot ID)."""
    key = 'userid' if str(user).isdigit() else 'username'
    q = urllib.parse.urlencode({key: user, 'json': 1})
    req = urllib.request.Request(f'{URL}?{q}', headers={'User-Agent': 'AirBurgundy-ACARS/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read()).get('fetch', {}).get('status')
        except Exception: msg = None
        raise RuntimeError(msg or f'SimBrief HTTP {e.code}')
    st = d.get('fetch', {}).get('status', '')
    if st and st.lower() != 'success':
        raise RuntimeError(st)
    g = d.get('general', {})
    fixes = d.get('navlog', {}).get('fix', [])
    if isinstance(fixes, dict): fixes = [fixes]
    out = []
    for fx in fixes:
        lat, lon = _f(fx.get('pos_lat')), _f(fx.get('pos_long'))
        if lat is None or lon is None: continue
        out.append({'id': fx.get('ident'), 'name': fx.get('name'), 'type': fx.get('type'), 'lat': lat, 'lon': lon,
                    'alt': _f(fx.get('altitude_feet')), 'stage': fx.get('stage'), 'sidstar': fx.get('is_sid_star') == '1'})
    fno = (g.get('icao_airline') or '') + (g.get('flight_number') or '')
    return {
        'flight_no': fno or None,
        'origin': _apt(d.get('origin')), 'destination': _apt(d.get('destination')), 'alternate': _apt(d.get('alternate')),
        'route': g.get('route'), 'cruise_alt': _f(g.get('initial_altitude')),
        'distance_nm': _f(g.get('route_distance')) or _f(g.get('air_distance')),
        'aircraft': (d.get('aircraft') or {}).get('icaocode'), 'reg': (d.get('aircraft') or {}).get('reg'),
        'generated': _f((d.get('params') or {}).get('time_generated')),
        'fixes': out,
    }


def summary(r):
    o, de, al = r['origin'] or {}, r['destination'] or {}, r['alternate'] or {}
    s = f"{r['flight_no'] or '?'}  {o.get('icao')} -> {de.get('icao')}"
    if al.get('icao'): s += f"  (dégagement {al['icao']})"
    s += f"  FL{int((r['cruise_alt'] or 0) / 100):03d}  {len(r['fixes'])} points"
    if r.get('reg'): s += f"  avion {r['reg']}"
    return s + '\n  ' + (r['route'] or '')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--user'); ap.add_argument('--attach', action='store_true'); ap.add_argument('--server')
    a = ap.parse_args()
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
    cfg = {}
    if os.path.exists(os.path.join(ROOT, 'config.json')):
        cfg = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
    user = a.user or cfg.get('simbrief_user')
    if not user:
        sys.exit('Ajoute "simbrief_user": "TonPseudo" dans config.json (ou --user TonPseudo)')
    r = fetch(user)
    print(summary(r))
    if a.attach:
        from vaclient import Client
        api = Client(cfg, server=a.server)
        live = api.get('/api/live')['flights']
        if not live:
            sys.exit('Aucun vol AIR BURGUNDY en cours.')
        f = live[-1]
        print(api.post('/api/acars/route', {'flight_id': f['id'], 'route': r}), '->', f['flight_no'], f['reg'])
