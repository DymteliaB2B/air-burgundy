"""AIR BURGUNDY Pilote : application de bureau (ACARS X-Plane + espace pilote)."""
import json, os, sys, threading

if getattr(sys, 'frozen', False):
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(BASE))          # acars.py / simbrief.py à la racine du dépôt

import webview
import simbrief
from acars import Airports
from backend import Session, ApiError, friendly, load_settings, save_settings
from core import Engine

VERSION = '1.2.0'


class Api:
    # NB : pywebview expose récursivement tous les attributs publics de cet objet à l'interface.
    # Tout l'état interne est donc préfixé par « _ » (fenêtre, session, aéroports…), sinon la fenêtre gèle.
    def __init__(self):
        self._s = Session(); self._engine = None; self._window = None
        self._settings = load_settings(); self._apts = None
        threading.Thread(target=self._load_airports, daemon=True).start()

    def _load_airports(self):
        self._apts = Airports()

    def _ok(self, **kw): return {'ok': True, **kw}
    def _err(self, e): return {'ok': False, 'error': friendly(e)}

    # ---------------------------------------------------------------- session
    def init(self):
        out = {'version': VERSION, 'settings': self._settings, 'logged_in': False}
        if self._s.restore():
            try:
                out.update(logged_in=True, me=self._s.rpc('pilot_me'))
            except ApiError as e:
                self._s.logout(); out['error'] = friendly(e)
        return out

    def send_code(self, email):
        try:
            self._s.send_code(email); return self._ok()
        except Exception as e:
            return self._err(e)

    def verify(self, email, code):
        try:
            self._s.verify(email, code); return self._ok(me=self._s.rpc('pilot_me'))
        except Exception as e:
            return self._err(e)

    def logout(self):
        if self._engine and self._engine.is_alive():
            return {'ok': False, 'error': "Arrête d'abord le vol en cours."}
        self._s.logout(); return self._ok()

    def me(self):
        try: return self._ok(me=self._s.rpc('pilot_me'))
        except Exception as e: return self._err(e)

    def update_profile(self, p):
        try: return self._ok(profile=self._s.rpc('pilot_update', {'p': p}))
        except Exception as e: return self._err(e)

    def save_settings(self, st):
        self._settings.update({k: st[k] for k in ('xp', 'rate') if k in st}); save_settings(self._settings)
        return self._ok(settings=self._settings)

    # ---------------------------------------------------------------- vol
    def load_ofp(self, simbrief_id):
        try:
            if not simbrief_id:
                return {'ok': False, 'error': 'Renseigne ton ID SimBrief dans ton profil.'}
            return self._ok(ofp=simbrief.fetch(simbrief_id, full=True))
        except Exception as e:
            return self._err(e)

    def start_flight(self, plan):
        if self._engine and self._engine.is_alive():
            return {'ok': False, 'error': 'Un vol est déjà en cours.'}
        if self._apts is None:
            self._load_airports()
        self._engine = Engine(self._s, self._emit, plan, self._settings, self._apts)
        self._engine.start()
        return self._ok()

    def stop_flight(self):
        if self._engine and self._engine.is_alive():
            self._engine.stop()
        return self._ok()

    def _emit(self, st):
        if self._window:
            self._window.evaluate_js(f'window.onAcars && window.onAcars({json.dumps(st, ensure_ascii=False)})')

    def open_pdf(self, url):
        import webbrowser
        if isinstance(url, str) and url.startswith('https://www.simbrief.com/'):
            webbrowser.open(url); return self._ok()
        return {'ok': False, 'error': 'lien PDF invalide'}

    def open_site(self):
        import webbrowser; webbrowser.open('https://airburgundyva.online'); return self._ok()


def main():
    api = Api()
    win = webview.create_window('AIR BURGUNDY Pilote', os.path.join(BASE, 'ui', 'index.html'), js_api=api,
                                width=1240, height=820, min_size=(980, 660), background_color='#f5f1ea')
    api._window = win

    def closing():
        if api._engine and api._engine.is_alive():
            api._engine.stop(); api._engine.join(timeout=6)
    win.events.closing += closing
    webview.start(gui='edgechromium', private_mode=False, storage_path=os.path.join(os.environ.get('APPDATA', '.'), 'AIR BURGUNDY', 'web'))


if __name__ == '__main__':
    main()
