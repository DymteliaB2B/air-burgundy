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

VERSION = '1.0.0'


class Api:
    def __init__(self):
        self.s = Session(); self.engine = None; self.window = None
        self.settings = load_settings(); self.apts = None
        threading.Thread(target=self._load_airports, daemon=True).start()

    def _load_airports(self):
        self.apts = Airports()

    def _ok(self, **kw): return {'ok': True, **kw}
    def _err(self, e): return {'ok': False, 'error': friendly(e)}

    # ---------------------------------------------------------------- session
    def init(self):
        out = {'version': VERSION, 'settings': self.settings, 'logged_in': False}
        if self.s.restore():
            try:
                out.update(logged_in=True, me=self.s.rpc('pilot_me'))
            except ApiError as e:
                self.s.logout(); out['error'] = friendly(e)
        return out

    def send_code(self, email):
        try:
            self.s.send_code(email); return self._ok()
        except Exception as e:
            return self._err(e)

    def verify(self, email, code):
        try:
            self.s.verify(email, code); return self._ok(me=self.s.rpc('pilot_me'))
        except Exception as e:
            return self._err(e)

    def logout(self):
        if self.engine and self.engine.is_alive():
            return {'ok': False, 'error': "Arrête d'abord le vol en cours."}
        self.s.logout(); return self._ok()

    def me(self):
        try: return self._ok(me=self.s.rpc('pilot_me'))
        except Exception as e: return self._err(e)

    def update_profile(self, p):
        try: return self._ok(profile=self.s.rpc('pilot_update', {'p': p}))
        except Exception as e: return self._err(e)

    def save_settings(self, st):
        self.settings.update({k: st[k] for k in ('xp', 'rate') if k in st}); save_settings(self.settings)
        return self._ok(settings=self.settings)

    # ---------------------------------------------------------------- vol
    def load_ofp(self, simbrief_id):
        try:
            if not simbrief_id:
                return {'ok': False, 'error': 'Renseigne ton ID SimBrief dans ton profil.'}
            return self._ok(ofp=simbrief.fetch(simbrief_id))
        except Exception as e:
            return self._err(e)

    def start_flight(self, plan):
        if self.engine and self.engine.is_alive():
            return {'ok': False, 'error': 'Un vol est déjà en cours.'}
        if self.apts is None:
            self._load_airports()
        self.engine = Engine(self.s, self._emit, plan, self.settings, self.apts)
        self.engine.start()
        return self._ok()

    def stop_flight(self):
        if self.engine and self.engine.is_alive():
            self.engine.stop()
        return self._ok()

    def _emit(self, st):
        if self.window:
            self.window.evaluate_js(f'window.onAcars && window.onAcars({json.dumps(st, ensure_ascii=False)})')

    def open_site(self):
        import webbrowser; webbrowser.open('https://airburgundyva.online'); return self._ok()


def main():
    api = Api()
    win = webview.create_window('AIR BURGUNDY Pilote', os.path.join(BASE, 'ui', 'index.html'), js_api=api,
                                width=1240, height=820, min_size=(980, 660), background_color='#f5f1ea')
    api.window = win

    def closing():
        if api.engine and api.engine.is_alive():
            api.engine.stop(); api.engine.join(timeout=6)
    win.events.closing += closing
    webview.start(gui='edgechromium', private_mode=False, storage_path=os.path.join(os.environ.get('APPDATA', '.'), 'AIR BURGUNDY', 'web'))


if __name__ == '__main__':
    main()
