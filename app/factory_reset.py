"""
Réinitialisation usine : remet la boîte à l'état "jamais configurée",
pour pouvoir la confier à quelqu'un d'autre sans lui laisser les
histoires/musiques/réglages de la famille précédente.

Efface, dans cet ordre précis :
1. TOUS les réseaux Wifi enregistrés par NetworkManager (nmcli, via
   bin/forget-wifi.sh --toutes) — pas seulement celui que l'appli
   connaît (settings.net_wifi_ssid) : une boîte a pu être connectée à
   d'AUTRES réseaux au fil du temps sans repasser par "Oublier ce
   réseau" (Wifi configuré à la main via nmtui/raspi-config pendant
   l'installation, ancien propriétaire, déménagement...). Seul le point
   d'accès de secours ("Contar-Secours") est épargné, pour qu'il reste
   disponible juste après le redémarrage qui suit ce reset — c'est du
   reste tout ce qui doit survivre en Wifi (retour de test réel :
   effacer uniquement le SSID connu de l'appli laissait d'autres réseaux
   enregistrés derrière, contrairement à ce qui était attendu).
2. Toute la base SQLite (livres, tags/catégories, albums, morceaux,
   listes de lecture, plages horaires, ET tous les réglages génériques —
   code PIN compris : c'est délibéré, le nouveau propriétaire doit en
   créer un à lui). Le fichier est supprimé puis la base est recréée
   vide plutôt que vidée table par table : plus simple, et ça repart
   aussi de zéro sur les compteurs AUTOINCREMENT.
3. Les fichiers eux-mêmes : histoires (Bibliotheque/Livres), musique
   (Bibliotheque/Musiques), jaquettes extraites (data/covers) — le CONTENU de ces
   dossiers est effacé, mais pas les dossiers eux-mêmes (évite de devoir
   les recréer avec les bonnes permissions ensuite).
4. Régénère le fichier miroir du point d'accès Wifi de secours
   (data/wifi_fallback.conf, voir app/wifi_fallback.py) à partir des
   réglages désormais vides — le mot de passe de ce point d'accès retombe
   alors sur la valeur fixe par défaut (SettingsManager.
   DEFAULT_WIFI_FALLBACK_PASSWORD, get_wifi_fallback_config() la réécrit
   toute seule dès qu'aucun mot de passe n'est enregistré), volontairement
   PAS un mot de passe aléatoire : une personne qui vient de faire un reset
   usine doit pouvoir se reconnecter au point d'accès de secours sans déjà
   connaître un secret qui vient d'être régénéré (retour de test réel, voir
   README.md « Étape 27 »).
5. Marque l'assistant de première configuration comme "en attente"
   (voir SettingsManager.set_onboarding_pending) — TOUJOURS en dernier,
   puisque l'étape 2 vient de tout effacer, y compris cette clé si elle
   avait été posée avant.

Ce que ça NE touche PAS, volontairement :
- Le point d'accès de secours lui-même côté NetworkManager (connexion
  "Contar-Secours") : géré entièrement par bin/wifi-fallback-watchdog.sh,
  recréé automatiquement au besoin avec le nouveau mot de passe.

N'effectue AUCUN redémarrage — c'est à l'appelant (voir la route
Réglages → Réinitialisation usine dans app/web/routes.py) d'enchaîner
avec app.system_control.reboot_now() une fois ce module revenu avec
succès.
"""

import platform
import shutil

from app.config import BOOKS_DIR, COVERS_DIR, DB_PATH, LIBRARY_DIR, MUSIC_DIR
from app.database import init_database
from app.network_apply import forget_all_wifi_networks
from app.settings import SettingsManager
from app import wifi_fallback


def _wipe_dir_contents(path) -> None:
    """Vide un dossier de tout son contenu, sans supprimer le dossier
    lui-même (évite d'avoir à le recréer avec les bonnes permissions)."""
    if not path.exists():
        return
    for entry in path.iterdir():
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except Exception:
            pass  # un fichier récalcitrant ne doit jamais bloquer tout le reste


def perform_factory_reset() -> tuple[bool, str]:
    try:
        # 1. TOUS les réseaux Wifi enregistrés (sauf le point d'accès de
        # secours) — best-effort : un échec ici ne doit pas bloquer le reste.
        if platform.system() == "Linux":
            forget_all_wifi_networks()

        # 2. Base de données : supprimée puis recréée vide.
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = DB_PATH.parent / (DB_PATH.name + suffix)
            candidate.unlink(missing_ok=True)
        init_database()

        # 3. Fichiers : histoires, musique, jaquettes.
        _wipe_dir_contents(BOOKS_DIR)
        _wipe_dir_contents(MUSIC_DIR)
        _wipe_dir_contents(COVERS_DIR)
        # Restes de l'ancien import par clé USB (avant la v0.11), s'il y en a.
        from app import depot_import
        depot_import.clean_old_work_dirs()
        shutil.rmtree(LIBRARY_DIR / ".reserve", ignore_errors=True)

        # Wi-Fi : revient à « activé », le réglage par défaut (v0.11).
        if platform.system() == "Linux":
            from app.power_settings import apply_wifi
            apply_wifi(True)

        # 4. Point d'accès de secours : régénéré à partir des réglages
        # désormais vides (nouveau mot de passe aléatoire).
        wifi_fallback.sync_fallback_conf()

        # 5. TOUJOURS en dernier (l'étape 2 a effacé cette clé si elle existait).
        SettingsManager().set_onboarding_pending(True)

        return True, "Boîte réinitialisée aux réglages d'usine."
    except Exception as exc:
        return False, f"Échec de la réinitialisation usine : {exc}"
