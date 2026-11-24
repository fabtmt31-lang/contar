"""
Emplacement de tous les fichiers utilisés par l'application.

Pensé pour fonctionner à l'identique que ce soit lancé sur un PC Windows
pendant le développement, ou plus tard sur le Raspberry Pi : tout est
relatif à la racine du projet par défaut, et peut être redirigé ailleurs
via la variable d'environnement CONTAR_BASE_DIR si besoin (utile plus tard
si on veut par exemple stocker Bibliotheque/ sur une clé USB branchée au Pi).
"""

import os
from pathlib import Path

# Racine du projet = dossier qui contient "app/", "Bibliotheque/", "data/"
BASE_DIR = Path(os.environ.get("CONTAR_BASE_DIR", Path(__file__).resolve().parent.parent))

# Convention reprise telle quelle de la version Android :
#   Bibliotheque/Livres    -> histoires audio
#   Bibliotheque/Musiques  -> bibliothèque musicale (organisée en sous-dossiers = albums)
LIBRARY_DIR = BASE_DIR / "Bibliotheque"
BOOKS_DIR = LIBRARY_DIR / "Livres"
MUSIC_DIR = LIBRARY_DIR / "Musiques"

# Données internes de l'application (base SQLite + vignettes extraites des fichiers audio)
DATA_DIR = BASE_DIR / "data"
COVERS_DIR = DATA_DIR / "covers"
DB_PATH = DATA_DIR / "contar.db"

# Extensions audio acceptées (identique à la version Android)
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".m4b"}

# Création des dossiers nécessaires au premier lancement
for _folder in (BOOKS_DIR, MUSIC_DIR, COVERS_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

# Nom de la boîte dans la suite Audiolibre. Depuis la v0.8, tout porte ce
# nom : dossier d'installation (/opt/contar), service (contar), base de
# données (data/contar.db), réseau de secours (Contar-Secours). Les anciens
# noms (histoiresdusoir, HDP, hds) ne subsistent que dans install_pi.sh et
# tools/migrate_old_install.py, pour reprendre une ancienne installation.
APP_NAME = "Contar"

# Port du serveur web. 80 sur la boîte (adresse sans numéro de port :
# http://contar.local), 5000 pour les essais sur PC où le port 80 est
# réservé à l'administrateur. Réglable par la variable CONTAR_PORT.
DEFAULT_PORT_ON_BOX = 80
DEFAULT_PORT_ON_PC = 5000


def web_port(on_box: bool) -> int:
    try:
        return int(os.environ["CONTAR_PORT"])
    except (KeyError, ValueError):
        return DEFAULT_PORT_ON_BOX if on_box else DEFAULT_PORT_ON_PC


def _read_version() -> str:
    try:
        # Toujours à côté du code, même si CONTAR_BASE_DIR déplace les données.
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip() or "?"
    except OSError:
        return "?"


# Numéro de version (fichier VERSION à la racine). Ajouté à l'adresse des
# fichiers de style et de script pour que le navigateur recharge la bonne
# version après une mise à jour, au lieu de garder l'ancienne en mémoire.
APP_VERSION = _read_version()
