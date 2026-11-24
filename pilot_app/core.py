"""Moteur ACARS (thread) pour l'application pilote. Réutilise la lecture X-Plane et la machine à phases d'acars.py."""
import threading, time
import acars
from acars import XPlane, Flight, Airports, PHASE_FR, FT, KT, detect_reg, sim_name


class Engine(threading.Thread):
    """emit(dict) est appelé ~1 fois/s avec l'état du vol ; api expose post(path, body)."""

    def __init__(self, api, emit, plan, settings, airports):
        super().__init__(daemon=True)
        self.api, self.emit, self.plan, self.settings, self.apts = api, emit, plan, settings, airports
        self.stop_evt = threading.Event()
        self.state = {'state': 'connexion', 'msg': 'Connexion à X-Plane…'}

    def stop(self):
        self.stop_evt.set()

    def _send(self, **kw):
        self.state.update(kw)
        try: self.emit(dict(self.state))
        except Exception: pass

    def run(self):
        try:
            self._run()
        except Exception as e:
            self._send(state='erreur', msg=str(e))

    def _run(self):
        host, port = (self.settings.get('xp') or '127.0.0.1:49000').split(':')
        rate = float(self.settings.get('rate') or 5)
        xp = XPlane(host, int(port))
        self._send(state='connexion', msg=f'Connexion à X-Plane ({host}:{port})…')
        while not self.stop_evt.is_set():
            xp.subscribe(); xp.poll(2)
            if 'lat' in xp.v: break
            self._send(state='attente', msg='X-Plane ne répond pas : lance-le avec un vol chargé.')
        if self.stop_evt.is_set():
            return
        xp.poll(1.5)
        v = dict(xp.v)
        reg = (self.plan.get('reg') or detect_reg(xp.livery()) or '').upper()
        if not reg:
            self._send(state='erreur', msg="Livrée non reconnue : choisis l'avion dans la préparation du vol.")
            xp.unsubscribe(); return
        sim = sim_name(v.get('xpver'))
        dep = self.apts.nearest(v['lat'], v['lon'])
        route = self.plan.get('route')
        if route and dep and (route.get('origin') or {}).get('icao') not in (None, dep):
            route = None
            self._send(warn=f"OFP SimBrief ignoré : il part de {self.plan['route']['origin']['icao']}, tu es à {dep}.")
        body = {'reg': reg, 'dep': dep, 'dep_airport': self.apts.obj(dep), 'arr': self.plan.get('arr') or None,
                'flight_no': self.plan.get('flight_no') or None, 'fuel': v.get('fuel'),
                'phase': PHASE_FR['boarding'], 'route': route, 'sim': sim}
        r = self.api.post('/api/acars/start', body)
        fid = r['flight_id']
        self._send(state='vol', msg='Vol ouvert', flight_id=fid, flight_no=r['flight_no'], reg=reg, sim=sim, dep=dep,
                   arr=body['arr'] or (route or {}).get('destination', {}).get('icao'), route=route, landing=None)

        fl = Flight(); buf = []; last_pos = 0; last_send = 0; queued = 0
        while not self.stop_evt.is_set():
            xp.poll(1.0)
            now = time.time()
            if now - xp.last_rx > 15:
                self._send(link='silence'); continue
            v = dict(xp.v)
            if v.get('paused', 0) > 0.5:
                self._send(link='pause'); continue
            ph = fl.update(v, now, xp)
            on_ground = v.get('ground', 1) > 0.5
            every = rate if not on_ground else rate * 3
            if now - last_pos >= every or ph != (buf[-1]['phase_k'] if buf else None):
                buf.append({'t': now, 'lat': round(v['lat'], 6), 'lon': round(v['lon'], 6),
                            'alt': round(v.get('elev', 0) * FT), 'gs': round(v.get('gs', 0) * KT),
                            'hdg': round(v.get('hdg', 0)), 'vs': round(v.get('vs', 0)), 'ias': round(v.get('ias', 0)),
                            'phase': PHASE_FR[ph], 'phase_k': ph})
                last_pos = now
            if buf and now - last_send >= rate:
                ev = fl.new_events()
                if 'block_off' in ev and fl.ev.get('takeoff') is None:
                    ev['dep'] = self.apts.nearest(v['lat'], v['lon'], 8) or dep
                    ev['dep_airport'] = self.apts.obj(ev['dep'])
                try:
                    self.api.post('/api/acars/pos', {'flight_id': fid, 'events': ev,
                                                     'positions': [{k: x for k, x in b.items() if k != 'phase_k'} for b in buf]})
                    buf = []; queued = 0; fl.mark_sent({k: x for k, x in ev.items() if k not in ('dep', 'dep_airport')})
                    link = 'ok'
                except Exception as e:
                    queued = len(buf); link = f'envoi différé ({queued} points) : {e}'
                last_send = now
                self.state['link'] = link
            land = {'fpm': fl.ev['landing_fpm'], 'g': fl.ev['landing_g']} if 'landing' in fl.ev else None
            self._send(state='vol', phase=PHASE_FR[ph], phase_k=ph, lat=v['lat'], lon=v['lon'],
                       alt=round(v.get('elev', 0) * FT), gs=round(v.get('gs', 0) * KT), vs=round(v.get('vs', 0)),
                       ias=round(v.get('ias', 0)), hdg=round(v.get('hdg', 0)), fuel=round(v.get('fuel', 0)),
                       on_ground=on_ground, landing=land, queued=queued)
            if ph == 'arrived':
                break

        # clôture
        try:
            st = 'termine' if fl.phase in ('landed', 'taxi_in', 'arrived') else 'interrompu'
            arr = self.apts.nearest(v['lat'], v['lon'], 8) if st == 'termine' else None
            arr = arr or (self.plan.get('arr') if st == 'termine' else None)
            if buf:
                self.api.post('/api/acars/pos', {'flight_id': fid, 'events': fl.new_events(),
                                                 'positions': [{k: x for k, x in b.items() if k != 'phase_k'} for b in buf]})
            self.api.post('/api/acars/end', {'flight_id': fid, 'status': st, 'arr': arr, 'arr_airport': self.apts.obj(arr),
                                             'fuel': v.get('fuel'), 'block_on': time.time(),
                                             **{k: fl.ev.get(k) for k in ('landing', 'landing_fpm', 'landing_g')}})
            self._send(state='termine' if st == 'termine' else 'interrompu',
                       msg=f"Vol {'terminé' if st == 'termine' else 'interrompu'}{' à ' + arr if arr else ''}.", arr=arr)
        except Exception as e:
            self._send(state='erreur', msg=f'Clôture impossible : {e}')
        finally:
            try: xp.unsubscribe()
            except Exception: pass
