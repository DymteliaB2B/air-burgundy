"""Construit data/airports.json (ICAO -> [nom, lat, lon]) depuis l'apt.dat de X-Plane 11. A lancer une fois.

    python build_airports.py "D:/SteamLibrary/steamapps/common/X-Plane 11"
"""
import json, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
xp = sys.argv[1] if len(sys.argv) > 1 else r"D:/SteamLibrary/steamapps/common/X-Plane 11"
src = [os.path.join(xp, 'Custom Scenery', 'Global Airports', 'Earth nav data', 'apt.dat'),
       os.path.join(xp, 'Resources', 'default scenery', 'default apt dat', 'Earth nav data', 'apt.dat')]
src = next(p for p in src if os.path.exists(p))
out = {}
cur = None; lat = lon = None

def flush():
    if cur and lat is not None and cur[0] not in out:
        out[cur[0]] = [cur[1], round(lat, 5), round(lon, 5)]

with open(src, encoding='utf-8', errors='replace') as f:
    for line in f:
        code = line[:5].split(' ', 1)[0]
        if code == '1':                                   # aeroport terrestre
            flush(); p = line.split(None, 5)
            cur = (p[4].upper(), p[5].strip() if len(p) > 5 else p[4]); lat = lon = None
        elif code in ('16', '17'):                        # hydrobase / heliport : ignores
            flush(); cur = None
        elif cur and code == '1302' and ('datum_lat' in line or 'datum_lon' in line):
            p = line.split()
            if len(p) > 2 and p[2]:
                try:
                    if p[1] == 'datum_lat': lat = float(p[2])
                    else: lon = float(p[2])
                except ValueError: pass
        elif cur and code == '100' and lat is None:      # piste : milieu de la piste
            p = line.split()
            try:
                lat = (float(p[9]) + float(p[18])) / 2; lon = (float(p[10]) + float(p[19])) / 2
            except (IndexError, ValueError): pass
flush()
os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'airports.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(out), 'aeroports depuis', src)
