"""Affiche l'empreinte SHA-256 de la clé ACARS de config.json (à insérer dans va.acars_keys).
La clé elle-même n'est jamais affichée.

    python supabase/key_hash.py            # empreinte de la clé actuelle
    python supabase/key_hash.py --new      # génère une nouvelle clé dans config.json et affiche son empreinte
"""
import hashlib, json, os, secrets, sys
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
cfg = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
if '--new' in sys.argv or not cfg.get('api_key'):
    cfg['api_key'] = secrets.token_urlsafe(32)
    json.dump(cfg, open(p, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print('Nouvelle clé enregistrée dans config.json')
h = hashlib.sha256(cfg['api_key'].encode('utf-8')).hexdigest()
print(f"insert into va.acars_keys(key, label) values ('{h}', 'Pilote');")
