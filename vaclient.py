"""Client de l'API AIR BURGUNDY, commun à l'ACARS et à simbrief.py.

Deux modes, choisis d'après config.json :
  - Supabase : "supabase_url" + "supabase_anon" présents -> appels RPC /rest/v1/rpc/<fonction>
  - serveur Python : sinon -> "server" (défaut http://127.0.0.1:8080), routes /api/...
La clé ACARS ("api_key") est envoyée dans les deux cas.
"""
import json, urllib.error, urllib.request

RPC = {'/api/acars/start': 'acars_start', '/api/acars/pos': 'acars_pos',
       '/api/acars/route': 'acars_route', '/api/acars/end': 'acars_end'}
RPC_GET = {'/api/live': 'api_live', '/api/fleet': 'api_fleet', '/api/stats': 'api_stats'}


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, cfg, server=None, key=None):
        self.key = key or cfg.get('api_key', '')
        self.sb_url = (cfg.get('supabase_url') or '').rstrip('/')
        self.sb_anon = cfg.get('supabase_anon') or ''
        self.supabase = bool(self.sb_url and self.sb_anon) and not server
        self.url = self.sb_url if self.supabase else (server or cfg.get('server') or 'http://127.0.0.1:8080').rstrip('/')

    def _send(self, url, body, headers, method='POST'):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data, method=method, headers={'Content-Type': 'application/json', **headers})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b'null')
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors='replace')
            try:
                j = json.loads(raw); msg = j.get('message') or j.get('error') or raw
            except Exception:
                msg = raw
            raise ApiError(f'{e.code} {msg}')

    def _rpc(self, fn, args):
        return self._send(f'{self.sb_url}/rest/v1/rpc/{fn}', args,
                          {'apikey': self.sb_anon, 'Authorization': f'Bearer {self.sb_anon}'})

    def post(self, path, body):
        if self.supabase:
            return self._rpc(RPC[path], {'p_key': self.key, 'p': body})
        return self._send(self.url + path, body, {'X-API-Key': self.key})

    def get(self, path):
        if self.supabase:
            return self._rpc(RPC_GET[path], {})
        return self._send(self.url + path, None, {}, method='GET')
