# AIR ◆ BURGUNDY : site + ACARS

Tout tourne en local sur ton PC avec Python 3. Il n'y a rien à installer.

| Fichier | Rôle |
|---|---|
| `Lancer le site.bat` | Démarre le site et l'API : http://127.0.0.1:8080 |
| `Lancer ACARS.bat` | Démarre le tracker. Lance-le une fois l'avion chargé dans X-Plane. |
| `server.py` | Serveur du site et de l'API, base `data/airburgundy.db` |
| `acars.py` | Tracker X-Plane 11 et 12 (version détectée automatiquement) |
| `build_airports.py` | Reconstruit `data/airports.json` depuis l'apt.dat de X-Plane (déjà fait) |
| `config.json` | Clé ACARS secrète, liste des pilotes et adresse du serveur (`"server"`, facultatif) |
| `tools/fake_xp11.py` | Faux X-Plane qui joue un vol accéléré, pour tester sans le simulateur |

## Faire un vol

1. Double-clique sur **Lancer le site.bat** et laisse la fenêtre ouverte.
2. Dans X-Plane (11 ou 12), charge l'Airbus ToLiss avec une livrée **AIR BURGUNDY F-XXXX**.
3. Double-clique sur **Lancer ACARS.bat**. Il fait le reste :
   - il reconnaît l'immatriculation d'après le nom du dossier de la livrée ;
   - il détecte le terrain de départ (aéroport le plus proche) ;
   - il suit les phases : roulage, décollage, montée, croisière, descente, approche, atterrissage ;
   - il mesure le toucher en ft/min et en g, au paquet près (20 Hz) ;
   - il clôt le vol au parking, une fois l'avion arrêté avec les moteurs coupés ou le frein de parc serré pendant 20 s.
4. Pour indiquer la destination ou le numéro de vol à l'avance :
   `python acars.py --arr LFPG --flight BRG204`
5. Ctrl+C interrompt le vol. Il est enregistré comme « terminé » si l'avion avait déjà atterri, sinon comme « interrompu ».

L'ACARS lit X-Plane par le protocole UDP natif (RREF, port 49000) : pas de plugin, et Volanta peut tourner en même temps.
Si le serveur ne répond plus, les positions restent en attente et repartent dès qu'il revient.

## API interne (utilisée par le site, non affichée publiquement)

- `GET /api/live` : vols en cours, avec position et trace
- `GET /api/fleet` : flotte, emplacement, heures et vols par avion
- `GET /api/flights?limit=50&reg=F-DIMI` : historique
- `GET /api/flights/{id}` : détail d'un vol et trace complète
- `GET /api/stats` : statistiques de la compagnie
- `GET /api/va` : identité de la compagnie

L'écriture (`POST /api/acars/*`) exige l'en-tête `X-API-Key`, qui doit correspondre à la clé de `config.json`. Ne la partage pas.

## Mise en ligne : Supabase + GitHub Pages

- **Site** : le dossier `web/` est publié sur GitHub Pages à chaque push sur `main`, par le workflow `.github/workflows/pages.yml`.
- **Base et API** : Supabase. Lance `supabase/schema.sql` une fois dans l'éditeur SQL.
  - Les tables sont dans le schéma privé `va`, jamais exposé.
  - Le site lit les données par les fonctions `api_*`.
  - L'ACARS écrit par les fonctions `acars_*`, qui exigent la clé ACARS.
- **Clé ACARS** : Supabase n'en garde que l'empreinte SHA-256. `python supabase/key_hash.py` affiche la ligne SQL à exécuter dans Supabase, sans jamais montrer la clé. Avec `--new`, il génère aussi une nouvelle clé dans `config.json`, par exemple pour un nouveau pilote. Ne mets jamais `config.json` dans git.
- **Site → Supabase** : renseigne l'URL du projet et la clé `anon` dans `web/config.js`. Elles sont publiques par conception : elles ne donnent accès qu'aux fonctions de lecture.
- **Pilote → Supabase** : dans `config.json`, ajoute `"supabase_url"`, `"supabase_anon"`, `"api_key"` et `"simbrief_user"`. Voir `config.example.json`.
- **En local** : si `web/config.js` est vide, le site et l'ACARS utilisent le serveur Python (`Lancer le site.bat`), comme avant.

## Application pilote (AIR BURGUNDY Pilote.exe)

- **Sources :** `pilot_app/` (pywebview). Construction de l'exe :
  ```
  .venv-app\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name "AIR BURGUNDY Pilote" --icon pilot_app/icon.ico --paths . --paths pilot_app --add-data "pilot_app/ui;ui" --add-data "data/airports.json;data" pilot_app/app.py
  ```
- **Connexion :** e-mail et code à 6 chiffres (Supabase Auth). Seuls les e-mails présents dans `va.pilots` peuvent se connecter :
  `insert into va.pilots(email, name) values ('pilote@exemple.fr', 'Prénom Nom');`
- **Session :** elle est enregistrée chiffrée (DPAPI Windows) dans `%APPDATA%\AIR BURGUNDY`.
- **E-mails :** envoyés par Resend via le SMTP de Supabase, avec le modèle `supabase/email_code.html`.
- **Aperçu de l'interface sans X-Plane :** servir `pilot_app/ui` et ouvrir `index.html?demo&in`.
