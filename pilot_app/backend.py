"""Supabase côté pilote : connexion par code e-mail, session chiffrée (DPAPI Windows), appels RPC authentifiés."""
import base64, ctypes, ctypes.wintypes as wt, json, os, time, urllib.error, urllib.request

SUPABASE_URL = 'https://rtiqpvhjdkuqwzrntarm.supabase.co'
SUPABASE_ANON = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ0aXFwdmhqZGt1cXd6cm50YXJtIiwicm9sZSI6'
                 'ImFub24iLCJpYXQiOjE3OTU1MzU4NTIsImV4cCI6MjExMTExMTg1Mn0.EhVdS7URGZN9EK9yeGi8XDGkkAUH7TcaVU3L_ba2zUY')
APPDIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'AIR BURGUNDY')
SESSION = os.path.join(APPDIR, 'session.bin')
SETTINGS = os.path.join(APPDIR, 'settings.json')


class ApiError(RuntimeError):
    pass


# ------------------------------------------------------------------ DPAPI (session illisible hors de ce compte Windows)
class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _protect(data: bytes, unprotect=False) -> bytes:
    src = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    dst = _Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if unprotect else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
        raise OSError('DPAPI')
    out = ctypes.string_at(dst.pbData, dst.cbData)
    ctypes.windll.kernel32.LocalFree(dst.pbData)
    return out


def _http(method, path, body=None, token=None, timeout=12):
    headers = {'apikey': SUPABASE_ANON, 'Content-Type': 'application/json',
               'Authorization': f'Bearer {token or SUPABASE_ANON}'}
    req = urllib.request.Request(SUPABASE_URL + path, None if body is None else json.dumps(body).encode(),
                                 method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors='replace')
        try:
            j = json.loads(raw)
            msg = j.get('msg') or j.get('message') or j.get('error_description') or j.get('error') or raw
        except Exception:
            msg = raw
        err = ApiError(msg); err.status = e.code
        raise err
    except urllib.error.URLError as e:
        raise ApiError(f'réseau indisponible ({e.reason})')


def friendly(e):
    m = str(e)
    low = m.lower()
    if 'invit' in low or 'database error saving new user' in low or 'signups not allowed' in low:
        return "Cet e-mail n'est pas invité chez AIR BURGUNDY. Demande une invitation à la compagnie."
    if 'token has expired' in low or 'otp' in low and 'invalid' in low or 'expired' in low:
        return 'Code invalide ou expiré. Redemande un code.'
    if 'rate limit' in low or 'security purposes' in low:
        return 'Trop de demandes. Patiente une minute avant de redemander un code.'
    return m


class Session:
    def __init__(self):
        self.access = None; self.refresh_token = None; self.expires = 0; self.email = None
        os.makedirs(APPDIR, exist_ok=True)

    # ---- connexion
    def send_code(self, email):
        _http('POST', '/auth/v1/otp', {'email': email.strip().lower(), 'create_user': True})

    def verify(self, email, code):
        d = _http('POST', '/auth/v1/verify', {'type': 'email', 'email': email.strip().lower(), 'token': code.strip()})
        self._set(d)

    def _set(self, d):
        self.access = d['access_token']; self.refresh_token = d['refresh_token']
        self.expires = time.time() + int(d.get('expires_in', 3600)) - 60
        self.email = (d.get('user') or {}).get('email', self.email)
        try:
            blob = _protect(json.dumps({'r': self.refresh_token, 'e': self.email}).encode())
            open(SESSION, 'wb').write(base64.b64encode(blob))
        except Exception:
            pass

    def restore(self):
        try:
            d = json.loads(_protect(base64.b64decode(open(SESSION, 'rb').read()), unprotect=True))
        except Exception:
            return False
        self.refresh_token, self.email = d['r'], d.get('e')
        try:
            self._refresh(); return True
        except ApiError:
            self.logout(); return False

    def _refresh(self):
        self._set(_http('POST', '/auth/v1/token?grant_type=refresh_token', {'refresh_token': self.refresh_token}))

    def logout(self):
        if self.access:
            try: _http('POST', '/auth/v1/logout', {}, token=self.access)
            except Exception: pass
        self.access = self.refresh_token = None
        try: os.remove(SESSION)
        except OSError: pass

    @property
    def logged_in(self):
        return bool(self.refresh_token)

    # ---- appels authentifiés
    def rpc(self, fn, args=None):
        if not self.refresh_token:
            raise ApiError('non connecté')
        if time.time() > self.expires:
            self._refresh()
        try:
            return _http('POST', f'/rest/v1/rpc/{fn}', args or {}, token=self.access)
        except ApiError as e:
            if getattr(e, 'status', 0) == 401:
                self._refresh()
                return _http('POST', f'/rest/v1/rpc/{fn}', args or {}, token=self.access)
            raise

    # client compatible avec l'ACARS (post('/api/acars/...'))
    def post(self, path, body):
        fn = {'/api/acars/start': 'acars_start', '/api/acars/pos': 'acars_pos',
              '/api/acars/route': 'acars_route', '/api/acars/end': 'acars_end'}[path]
        return self.rpc(fn, {'p_key': None, 'p': body})


def load_settings():
    try:
        return json.load(open(SETTINGS, encoding='utf-8'))
    except Exception:
        return {'xp': '127.0.0.1:49000', 'rate': 5}


def save_settings(s):
    os.makedirs(APPDIR, exist_ok=True)
    json.dump(s, open(SETTINGS, 'w', encoding='utf-8'), indent=2)
