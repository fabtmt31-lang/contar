"""
Mise à jour depuis GitHub (v0.11) — Réglages → Mise à jour.

1. « Vérifier » : demande à GitHub la dernière version publiée du dépôt
   (par défaut fabtmt31-lang/contar) : la dernière « release » si le dépôt
   en publie, sinon le fichier VERSION de sa branche principale.
2. « Installer » : télécharge l'archive dans data/maj/, puis la confie à
   bin/update-contar.sh (root, via sudo), qui relance install_pi.sh dessus
   en gardant le mode de contrôle (manette ou boutons). Bibliothèque, base
   et réglages sont conservés, comme pour toute réinstallation.

Il faut un accès Internet : le Wi-Fi de la maison (le câble USB-C ne
donne accès qu'à l'ordinateur). Un dépôt privé demande un jeton d'accès
GitHub en lecture seule (« fine-grained token », droit Contents: read),
saisi dans la même page et gardé sur la boîte.
"""

import json
import os
import platform
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app.config import APP_VERSION, DATA_DIR
from app.settings import SettingsManager

API = "https://api.github.com"
HELPER = os.environ.get(
    "CONTAR_UPDATE_HELPER", str(Path(__file__).resolve().parent.parent / "bin" / "update-contar.sh")
)
DOWNLOAD_DIR = DATA_DIR / "maj"
ARCHIVE = DOWNLOAD_DIR / "contar.tar.gz"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_settings = SettingsManager()
_lock = threading.Lock()
_state = {"step": "idle", "message": "", "latest": None}


def _version_tuple(text: str) -> tuple:
    numbers = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def _request(url: str, accept: str = "application/vnd.github+json", timeout: float = 20):
    headers = {"Accept": accept, "User-Agent": "Contar-box", "X-GitHub-Api-Version": "2022-11-28"}
    token = _settings.get_update_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def _json(url: str) -> dict:
    with _request(url) as response:
        return json.loads(response.read().decode("utf-8"))


def check() -> dict:
    """{"ok", "version", "notes", "archive_url", "current", "newer"} ou
    {"ok": False, "error": message}."""
    repo = _settings.get_update_repo()
    if not REPO_PATTERN.match(repo):
        return {"ok": False, "error": "Nom de dépôt invalide (attendu : propriétaire/dépôt)."}
    try:
        try:
            release = _json(f"{API}/repos/{repo}/releases/latest")
            version = release.get("tag_name") or release.get("name") or ""
            result = {
                "version": version.lstrip("vV"),
                "notes": (release.get("body") or "")[:2000],
                "archive_url": release.get("tarball_url"),
            }
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            # Pas de « release » publiée : on lit la branche principale.
            info = _json(f"{API}/repos/{repo}")
            branch = info.get("default_branch") or "main"
            with _request(f"{API}/repos/{repo}/contents/VERSION?ref={branch}",
                          accept="application/vnd.github.raw") as response:
                version = response.read().decode("utf-8").strip()
            result = {
                "version": version,
                "notes": "",
                "archive_url": f"{API}/repos/{repo}/tarball/{branch}",
            }
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return {"ok": False, "error": "Dépôt introuvable ou privé : vérifiez son nom et le jeton d'accès."}
        return {"ok": False, "error": f"GitHub a répondu {exc.code}."}
    except (urllib.error.URLError, OSError, ValueError):
        return {"ok": False, "error": "Pas d'accès à Internet : la mise à jour passe par le Wi-Fi de la maison."}
    result.update(ok=True, current=APP_VERSION, newer=is_newer(result["version"]))
    with _lock:
        _state["latest"] = result
    return result


def state() -> dict:
    with _lock:
        return dict(_state)


def _set(step: str, message: str = "") -> None:
    with _lock:
        _state["step"], _state["message"] = step, message


def install() -> tuple[bool, str]:
    """Lance le téléchargement puis l'installation, en tâche de fond."""
    with _lock:
        latest = _state.get("latest")
        busy = _state["step"] in ("download", "install")
    if busy:
        return False, "Une mise à jour est déjà en cours."
    if not latest or not latest.get("archive_url"):
        return False, "Vérifiez d'abord la version disponible."
    if platform.system() != "Linux":
        return False, "La mise à jour n'est disponible que sur la boîte."
    threading.Thread(target=_run, args=(latest["archive_url"],), daemon=True).start()
    return True, "Mise à jour lancée : la boîte redémarre son service à la fin (quelques minutes)."


def _run(url: str) -> None:
    _set("download", "Téléchargement…")
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        partial = ARCHIVE.with_suffix(".part")
        with _request(url, accept="application/vnd.github+json", timeout=60) as response, open(partial, "wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
        partial.replace(ARCHIVE)
    except Exception as exc:
        _set("error", f"Téléchargement impossible : {exc}")
        return
    _set("install", "Installation…")
    try:
        result = subprocess.run(["sudo", HELPER, str(ARCHIVE)], capture_output=True, text=True, timeout=60)
    except Exception as exc:
        _set("error", f"Installation impossible : {exc}")
        return
    if result.returncode != 0:
        _set("error", result.stderr.strip() or result.stdout.strip() or "Installation impossible.")
        return
    # Le script continue seul (hors du service) et redémarre la boîte applicative.
    _set("install", "Installation en cours : la page reviendra d'elle-même dans quelques minutes.")


def last_log() -> Optional[str]:
    log = DOWNLOAD_DIR / "derniere-maj.log"
    try:
        return log.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return None
