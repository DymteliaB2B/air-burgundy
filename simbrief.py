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


def fetch(user, full=False):
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
        **({'details': details(d)} if full else {}),
    }


def _s(v):
    """SimBrief renvoie '{}' pour les champs vides."""
    return None if v in (None, '', '{}', {}, []) else v


def details(d):
    """OFP complet pour la page « Vol du jour » (jamais envoyé au site : reste dans l'application)."""
    g, t, fu, w = d.get('general') or {}, d.get('times') or {}, d.get('fuel') or {}, d.get('weights') or {}
    wx, ac, par = d.get('weather') or {}, d.get('aircraft') or {}, d.get('params') or {}
    o, de, al = d.get('origin') or {}, d.get('destination') or {}, d.get('alternate') or {}
    files = d.get('files') or {}
    pdf = files.get('pdf') or {}
    pdf_url = (files.get('directory', '').rstrip('/') + '/' + pdf['link']) if isinstance(pdf, dict) and pdf.get('link') else None
    fixes = (d.get('navlog') or {}).get('fix', [])
    if isinstance(fixes, dict): fixes = [fixes]
    nav = [{'id': fx.get('ident'), 'name': _s(fx.get('name')), 'via': _s(fx.get('via_airway')), 'stage': fx.get('stage'),
            'alt': _f(fx.get('altitude_feet')), 'dist': _f(fx.get('distance')), 'trk': _s(fx.get('track_mag')),
            'wind': f"{fx.get('wind_dir', '')}/{fx.get('wind_spd', '')}" if _s(fx.get('wind_dir')) else None,
            'oat': _f(fx.get('oat')), 'gs': _f(fx.get('groundspeed')), 'time': _f(fx.get('time_total')),
            'fuel': _f(fx.get('fuel_plan_onboard')), 'freq': _s(fx.get('frequency'))} for fx in fixes]
    apt = lambda a: {'icao': a.get('icao_code'), 'iata': _s(a.get('iata_code')), 'name': a.get('name'),
                     'rwy': _s(a.get('plan_rwy')), 'elev': _f(a.get('elevation')),
                     'trans_alt': _f(a.get('trans_alt')), 'trans_level': _f(a.get('trans_level'))} if a else None
    return {
        'units': par.get('units', 'kgs'), 'airac': _s(par.get('airac')), 'layout': _s(par.get('ofp_layout')),
        'aircraft': {'type': ac.get('icaocode'), 'name': _s(ac.get('name')), 'engines': _s(ac.get('engines')),
                     'reg': _s(ac.get('reg')), 'selcal': _s(ac.get('selcal'))},
        'general': {k: _s(g.get(k)) for k in ('cruise_profile', 'climb_profile', 'descent_profile', 'costindex', 'cont_rule',
                                              'initial_altitude', 'stepclimb_string', 'avg_wind_comp', 'avg_wind_dir',
                                              'avg_wind_spd', 'avg_temp_dev', 'gc_distance', 'route_distance', 'air_distance',
                                              'cruise_tas', 'cruise_mach', 'passengers', 'sid_ident', 'star_ident', 'route')},
        'times': {k: _f(t.get(k)) for k in ('sched_out', 'sched_off', 'sched_on', 'sched_in', 'est_out', 'est_off', 'est_on',
                                            'est_in', 'est_time_enroute', 'est_block', 'taxi_out', 'taxi_in', 'endurance',
                                            'reserve_time', 'contfuel_time')},
        'fuel': {k: _f(fu.get(k)) for k in ('taxi', 'enroute_burn', 'contingency', 'alternate_burn', 'reserve', 'extra',
                                            'min_takeoff', 'plan_takeoff', 'plan_ramp', 'plan_landing', 'avg_fuel_flow', 'max_tanks')},
        'weights': {k: _f(w.get(k)) for k in ('oew', 'pax_count', 'cargo', 'payload', 'est_zfw', 'max_zfw', 'est_tow', 'max_tow',
                                              'est_ldw', 'max_ldw', 'est_ramp')},
        'origin': apt(o), 'destination': apt(de), 'alternate': apt(al),
        'weather': {k: _s(wx.get(k)) for k in ('orig_metar', 'orig_taf', 'dest_metar', 'dest_taf', 'altn_metar', 'altn_taf')},
        'navlog': nav,
        'plan_html': _s((d.get('text') or {}).get('plan_html')),
        'pdf_url': pdf_url,
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
