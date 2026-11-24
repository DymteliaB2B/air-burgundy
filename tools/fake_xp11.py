"""Simulateur de test : se fait passer pour X-Plane 11 (RREF UDP) et joue un vol accelere LFSD -> LFPG.

    python tools/fake_xp11.py --port 49000 --speed 30 --reg F-PINO
Ne pas lancer en meme temps que le vrai X-Plane (meme port).
"""
import argparse, math, socket, struct, time

ap = argparse.ArgumentParser()
ap.add_argument('--port', type=int, default=49000)
ap.add_argument('--speed', type=float, default=30)
ap.add_argument('--reg', default='F-PINO')
ap.add_argument('--dep', default='47.2672,5.0870,222')    # LFSD parking approx
ap.add_argument('--arr', default='49.0098,2.5478,119')    # LFPG
a = ap.parse_args()
dlat, dlon, delev = map(float, a.dep.split(',')); alat, alon, aelev = map(float, a.arr.split(','))
LIVERY = f'Aircraft/Laminar Research/ToLissA321_V1p9p1/liveries/AIR BURGUNDY {a.reg}/'

def nm(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(x))

def brg(la1, lo1, la2, lo2):
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360

S = dict(lat=dlat, lon=dlon, alt=delev * 3.28084, gs=0.0, vs=0.0, ground=1, fuel=9500.0, eng=1, pbrake=1.0, hdg=brg(dlat, dlon, alat, alon), gn=1.0)
phase = 'parked'; ph_t = 0.0

def step(dt):
    global phase, ph_t
    ph_t += dt
    s = S; togo = nm(s['lat'], s['lon'], alat, alon)
    if phase == 'parked':
        if ph_t > 90: phase, ph_t = 'taxi', 0; s['pbrake'] = 0
    elif phase == 'taxi':
        s['gs'] = 15
        if ph_t > 240: phase, ph_t = 'roll', 0
    elif phase == 'roll':
        s['gs'] = min(165, s['gs'] + 4 * dt)
        if s['gs'] >= 155: phase, ph_t = 'climb', 0; s['ground'] = 0
    elif phase == 'climb':
        s['vs'] = 2500 if s['alt'] < 30000 else 1200; s['gs'] = min(450, s['gs'] + 1.2 * dt)
        if s['alt'] >= 33000: s['alt'] = 33000; phase, ph_t = 'cruise', 0
        if togo < (s['alt'] - aelev * 3.28) / 1000 * 3.2: phase = 'descent'
    elif phase == 'cruise':
        s['vs'] = 0
        if togo < (s['alt'] - aelev * 3.28) / 1000 * 3.2: phase, ph_t = 'descent', 0
    elif phase == 'descent':
        need = max(togo, 0.3)
        s['gs'] = max(140, min(s['gs'], 140 + togo * 2.2))
        s['vs'] = -max(650, min(3000, (s['alt'] - aelev * 3.28) / (need / s['gs'] * 60)))
        if s['alt'] - aelev * 3.28 < 60: s['vs'] = -175     # arrondi
        if s['alt'] + s['vs'] * dt / 60 <= aelev * 3.28 + 1:
            s['alt'] = aelev * 3.28; s['vs'] = -180; s['ground'] = 1; s['gn'] = 1.21; phase, ph_t = 'rollout', 0
    elif phase == 'rollout':
        s['vs'] = 0; s['gn'] = 1.0 if ph_t > 1.5 else s['gn']
        s['gs'] = max(15, s['gs'] - 5 * dt)
        if s['gs'] <= 15: phase, ph_t = 'taxi_in', 0
    elif phase == 'taxi_in':
        s['gs'] = 12
        if ph_t > 180: phase, ph_t = 'park', 0
    elif phase == 'park':
        s['gs'] = 0; s['pbrake'] = 1.0
        if ph_t > 60: s['eng'] = 0
    if phase not in ('parked', 'park'):
        b = brg(s['lat'], s['lon'], alat, alon) if togo > 0.05 else s['hdg']; s['hdg'] = b
        d = s['gs'] * dt / 3600 if togo > 0.05 else 0
        s['lat'] += d / 60 * math.cos(math.radians(b)); s['lon'] += d / 60 * math.sin(math.radians(b)) / math.cos(math.radians(s['lat']))
    s['alt'] += s['vs'] * dt / 60
    if s['eng']: s['fuel'] -= (0.75 if not s['ground'] else 0.15) * dt

def value(name):
    s = S; ft = 3.28084
    if name.startswith('sim/aircraft/view/acf_livery_path['):
        k = int(name.split('[')[1][:-1]); return float(ord(LIVERY[k])) if k < len(LIVERY) else 0.0
    return {
        'sim/flightmodel/position/latitude': s['lat'], 'sim/flightmodel/position/longitude': s['lon'],
        'sim/flightmodel/position/elevation': s['alt'] / ft,
        'sim/flightmodel/position/y_agl': max(0, s['alt'] / ft - (aelev if phase in ('descent', 'rollout', 'taxi_in', 'park') else delev)),
        'sim/flightmodel/position/groundspeed': s['gs'] / 1.943844, 'sim/flightmodel/position/true_psi': s['hdg'],
        'sim/flightmodel/position/vh_ind_fpm': s['vs'], 'sim/flightmodel/position/indicated_airspeed': s['gs'] * (0.62 if s['alt'] > 20000 else 0.95),
        'sim/flightmodel/failures/onground_any': float(s['ground']), 'sim/flightmodel/weight/m_fuel_total': s['fuel'],
        'sim/time/paused': 0.0, 'sim/flightmodel/forces/g_nrml': s['gn'],
        'sim/cockpit2/controls/parking_brake_ratio': s['pbrake'],
        'sim/flightmodel/engine/ENGN_running[0]': float(s['eng']), 'sim/flightmodel/engine/ENGN_running[1]': float(s['eng']),
    }.get(name, 0.0)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sock.bind(('127.0.0.1', a.port)); sock.settimeout(0.05)
subs = {}   # addr -> {idx: (freq, name)}
print(f'Faux X-Plane 11 sur UDP {a.port}, vitesse x{a.speed}, livree {LIVERY}')
last = time.time(); last_send = 0; last_print = None
while True:
    try:
        data, addr = sock.recvfrom(1024)
        if data[:4] == b'RREF':
            freq, idx = struct.unpack('<ii', data[5:13]); name = data[13:413].split(b'\0')[0].decode()
            d = subs.setdefault(addr, {})
            if freq: d[idx] = name
            else: d.pop(idx, None)
    except socket.timeout:
        pass
    except ConnectionResetError:
        pass
    now = time.time()
    step((now - last) * a.speed); last = now
    if phase != last_print: print('phase', phase); last_print = phase
    if now - last_send >= 0.2:
        last_send = now
        for addr, d in list(subs.items()):
            items = list(d.items())
            for i in range(0, len(items), 100):
                pkt = b'RREF,' + b''.join(struct.pack('<if', k, value(n)) for k, n in items[i:i + 100])
                try: sock.sendto(pkt, addr)
                except OSError: pass
