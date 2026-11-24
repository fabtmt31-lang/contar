"""
Import par clé USB (v0.9).

On branche une clé sur la boîte ; elle doit contenir un dossier
« Audiolibre » rangé comme la bibliothèque de la boîte :

    Audiolibre/Livres/        un fichier = une histoire
    Audiolibre/Musiques/      un sous-dossier = un album

Deux actions, lancées par un tag maître posé sur la boîte (voir
app/nfc_controller.py) ou par un bouton de l'écran Import :

- AJOUTER   copie ce qui n'est pas encore sur la boîte. Ne supprime et ne
            modifie rien.
- REMPLACER après l'import, la boîte contient exactement ce qu'il y a sur
            la clé. Ce qui est identique n'est pas recopié et garde son
            tag et sa position de lecture. Ce qui n'est plus sur la clé
            part en RÉSERVE jusqu'au prochain import réussi : l'écran
            Import propose « Annuler le dernier remplacement ».

Garde-fous :
- la clé n'est jamais modifiée (elle est reliée en lecture seule) ;
- copie d'abord, mise en place ensuite : les fichiers arrivent dans un
  dossier d'attente et ne remplacent rien avant la fin. Clé retirée ou
  coupure de courant pendant la copie : la boîte repart comme avant
  (voir recover_interrupted(), appelé au démarrage) ;
- la place est vérifiée avant de copier ;
- pendant l'import, la lecture s'arrête et les tags d'histoire sont ignorés.

Dossiers de travail, tous dans Bibliotheque/ (même carte mémoire, donc
déplacements instantanés) et tous cachés (nom commençant par un point) :

    .attente/       fichiers en cours de copie
    .reserve/       ce que le dernier « Remplacer » a retiré + copie de la base
    .reserve.tmp/   réserve en cours de constitution (bascule en cours)
    .annule.tmp/    annulation en cours
    .reserve.old/   ancienne réserve en cours d'effacement

Pour essayer sans Raspberry Pi : la variable CONTAR_CLE_SIMULEE désigne un
dossier de l'ordinateur qui tient lieu de clé (il est vu comme une clé
branchée tant qu'il existe).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import AUDIO_EXTENSIONS, BOOKS_DIR, COVERS_DIR, DB_PATH, LIBRARY_DIR, MUSIC_DIR
from app.database import get_connection

STAGING_DIR = LIBRARY_DIR / ".attente"
RESERVE_DIR = LIBRARY_DIR / ".reserve"
RESERVE_TMP_DIR = LIBRARY_DIR / ".reserve.tmp"
UNDO_TMP_DIR = LIBRARY_DIR / ".annule.tmp"
RESERVE_OLD_DIR = LIBRARY_DIR / ".reserve.old"     # réserve abandonnée, en cours d'effacement
RESERVE_DB = "base.db"
RESERVE_INFO = "info.json"
RESERVE_TODO = "a_ranger"      # présent tant que la base n'a pas été mise à jour

# Les deux dossiers de la bibliothèque, tels qu'ils s'appellent sur la boîte.
SECTIONS = ("Livres", "Musiques")
# Noms acceptés sur la clé (sans tenir compte des majuscules).
KEY_ROOT_NAMES = ("audiolibre",)
KEY_SECTION_NAMES = {"Livres": ("livres", "livre"), "Musiques": ("musiques", "musique")}

USB_HELPER = os.environ.get(
    "CONTAR_USB_HELPER", str(Path(__file__).resolve().parent.parent / "bin" / "usb-key.sh")
)
MOUNT_DIR = Path(os.environ.get("CONTAR_USB_MOUNT_DIR", "/run/contar/cle"))
SIMULATED_KEY = os.environ.get("CONTAR_CLE_SIMULEE", "")

POLL_SECONDS = float(os.environ.get("CONTAR_USB_POLL", "2"))
CONFIRM_SECONDS = 10.0          # délai pour reposer le tag « Remplacer »
CONFIRM_MIN_GAP = 1.0           # … mais pas avant ce délai : un tag resté posé ne confirme pas
MAX_NAME_BYTES = 255            # nom de fichier le plus long accepté par la carte de la boîte
# Place laissée libre sur la carte après un import (base, jaquettes, système).
FREE_MARGIN_BYTES = int(os.environ.get("CONTAR_IMPORT_MARGE", str(200 * 1024 * 1024)))
COPY_CHUNK = 1024 * 1024
PREVIEW_MAX_AGE = 4.0           # l'aperçu est recalculé au plus à ce rythme
PREVIEW_LIST_LIMIT = 60         # noms listés dans l'aperçu (le compte reste exact)
LAST_RESULT_SECONDS = 15 * 60   # durée d'affichage du bilan dans l'administration

MODES = ("ajouter", "remplacer")


class ImportRefused(Exception):
    """Import impossible ; .code dit pourquoi (voir _REFUSALS)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


# code du refus -> (ligne 1, ligne 2) de l'écran LCD
_REFUSALS = {
    "pas_de_cle": ("lcd.import_no_key", ""),
    "cle_inconnue": ("lcd.import_unknown_key", ""),
    "cle_vide": ("lcd.import_nothing_line1", "lcd.import_nothing_line2"),
    "rien": ("lcd.import_nothing_line1", "lcd.import_nothing_line2"),
    "place": ("lcd.import_no_space_line1", "lcd.import_no_space_line2"),
    "occupe": ("lcd.import_busy_line1", "lcd.import_busy_line2"),
    "cle_retiree": ("lcd.import_stopped_line1", "lcd.import_stopped_line2"),
    "copie": ("lcd.import_stopped_line1", "lcd.import_stopped_line2"),
}

_lock = threading.RLock()

# Clé branchée : state vaut "aucune", "lecture" (en cours d'examen), "prete"
# ou "inconnue" (pas de dossier Audiolibre, ou clé illisible).
_key = {"state": "aucune", "signature": None, "root": None, "label": "", "size": 0, "mounted": False}
_preview: Optional[dict] = None
_preview_at = 0.0

_job = {"running": False, "mode": "", "source": "", "phase": "", "done": 0, "total": 0, "title": ""}
_last_result: Optional[dict] = None     # bilan du dernier import, tant que la clé reste branchée
_confirm_until = 0.0                    # « Remplacer » : reposer le tag avant cet instant
_watcher_started = False
_watch_error = ""


# ---- Petits outils -----------------------------------------------------------

def _lcd():
    from app import lcd_display
    return lcd_display


def _sound():
    from app import sound_feedback
    return sound_feedback


def _is_audio_name(name: str) -> bool:
    return not name.startswith(".") and Path(name).suffix.lower() in AUDIO_EXTENSIONS


def _is_hidden(name: str) -> bool:
    return name.startswith(".") or name.lower() in ("system volume information", "thumbs.db", "desktop.ini")


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _find_child(folder: Path, names: tuple, strict: bool = False) -> Optional[Path]:
    """Sous-dossier de « folder » portant l'un de ces noms, sans tenir compte
    des majuscules (une clé peut contenir AUDIOLIBRE ou audiolibre). Un
    raccourci (lien) n'est jamais suivi. Avec strict, une clé devenue
    illisible lève une erreur au lieu de passer pour un dossier absent :
    indispensable avant un remplacement, où « absent de la clé » veut dire
    « à retirer de la boîte »."""
    try:
        for entry in sorted(folder.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.lower() in names and entry.is_dir() and not entry.is_symlink():
                return entry
    except OSError:
        if strict:
            raise
    return None


def _display_name(rel: str) -> str:
    """« Livres/Le loup.mp3 » -> « Le loup » ; « Musiques/Comptines/a.mp3 »
    -> « Comptines / a »."""
    parts = rel.split("/")
    stem = Path(parts[-1]).stem
    if parts[0] == "Musiques" and len(parts) == 3:
        return f"{parts[1]} / {stem}"
    return stem


def _free_bytes() -> int:
    try:
        return shutil.disk_usage(LIBRARY_DIR).free
    except OSError:
        return 0


# ---- Détection de la clé -----------------------------------------------------

def _usb_partitions() -> list:
    """Partitions lisibles des clés et disques branchés en USB, d'après
    lsblk. Le disque sur lequel tourne la boîte est toujours écarté."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,PATH,TRAN,TYPE,FSTYPE,LABEL,SIZE,MOUNTPOINT"],
            capture_output=True, text=True, timeout=8,
        )
        devices = json.loads(result.stdout or "{}").get("blockdevices", [])
    except Exception:
        return []

    def system_disk(device: dict) -> bool:
        nodes = [device] + list(device.get("children") or [])
        for node in nodes:
            mount = node.get("mountpoint") or ""
            if mount == "/" or mount.startswith("/boot"):
                return True
        return False

    found = []
    for device in devices:
        if device.get("tran") != "usb" or device.get("type") != "disk" or system_disk(device):
            continue
        parts = [c for c in (device.get("children") or []) if c.get("type") == "part" and c.get("fstype")]
        if not parts and device.get("fstype"):
            parts = [device]            # clé formatée sans table de partitions
        for part in parts:
            found.append({
                "path": part.get("path") or f"/dev/{part.get('name')}",
                "label": part.get("label") or "",
                "size": int(part.get("size") or 0),
            })
    return found


def _helper(*args) -> bool:
    try:
        result = subprocess.run(["sudo", "-n", USB_HELPER, *args], capture_output=True, text=True, timeout=40)
        if result.returncode != 0 and result.stderr.strip():
            print(f"[clé USB] {result.stderr.strip()}")
        return result.returncode == 0
    except Exception as exc:
        print(f"[clé USB] commande impossible : {exc}")
        return False


def _unmount() -> None:
    with _lock:
        was_mounted = _key["mounted"]
        _key["mounted"] = False
    if was_mounted:
        _helper("umount")


def _locate_root(base: Path) -> Optional[Path]:
    return _find_child(base, KEY_ROOT_NAMES)


_parts_seen: list = []      # détail des partitions de la clé branchée


def _current_signature():
    """Ce qui est branché en ce moment : None, ou de quoi reconnaître la clé
    (les chemins de ses partitions — pas son nom, parfois connu un instant
    plus tard seulement)."""
    global _parts_seen
    if SIMULATED_KEY:
        return ("simulee", SIMULATED_KEY) if Path(SIMULATED_KEY).is_dir() else None
    parts = _usb_partitions()
    if not parts:
        return None
    _parts_seen = parts
    return tuple(p["path"] for p in parts)


def _open_key(signature) -> None:
    """Une clé vient d'être branchée : on la relie, on cherche son dossier
    Audiolibre, on prévient (écran + son)."""
    global _preview, _last_result
    parts = {p["path"]: p for p in _parts_seen}
    with _lock:
        _key.update(state="lecture", signature=signature, root=None, label="", size=0)
        _preview = None
        _last_result = None
    _lcd().show_message("lcd.import_reading", seconds=4)

    root, label, size = None, "", 0
    if signature[0] == "simulee":
        base = Path(signature[1])
        root, label = _locate_root(base), base.name
    else:
        for path in signature:
            if not _helper("mount", path):
                continue
            with _lock:
                _key["mounted"] = True
            root = _locate_root(MOUNT_DIR)
            if root is not None:
                label = parts.get(path, {}).get("label", "")
                size = parts.get(path, {}).get("size", 0)
                break
            _unmount()

    with _lock:
        if _key["signature"] != signature:
            return                      # retirée entre-temps
        if root is None:
            _key.update(state="inconnue", root=None)
        else:
            _key.update(state="prete", root=root, label=label, size=size)

    if root is None:
        print("[clé USB] clé sans dossier « Audiolibre » (ou illisible).")
        _lcd().show_message("lcd.import_unknown_key", seconds=6)
        _lcd().set_idle_hint(None)
        _sound().play_error()
    else:
        print(f"[clé USB] clé prête ({label or 'sans nom'}).")
        _lcd().show_message("lcd.import_ready_line1", "lcd.import_ready_line2", seconds=6)
        _lcd().set_idle_hint("lcd.import_ready_line1", "lcd.import_ready_line2")
        _sound().play_beep()


def _close_key() -> None:
    """La clé a été retirée. Le bilan du dernier import reste affiché un
    moment dans l'administration (voir get_status())."""
    global _preview, _confirm_until
    with _lock:
        had_key = _key["state"] != "aucune"
        _key.update(state="aucune", signature=None, root=None, label="", size=0)
        _preview = None
        _confirm_until = 0.0
    _unmount()
    _lcd().set_idle_hint(None)
    if had_key:
        print("[clé USB] clé retirée.")


def _tick() -> None:
    with _lock:
        if _job["running"]:
            return
        known = _key["signature"]
    signature = _current_signature()
    if signature == known:
        return
    if signature is None:
        _close_key()
    else:
        if known is not None:
            _close_key()
        _open_key(signature)


def _watch() -> None:
    global _watch_error
    while True:
        try:
            _tick()
            _watch_error = ""
        except Exception as exc:
            if str(exc) != _watch_error:        # une seule ligne par erreur différente
                print(f"[clé USB] surveillance : {exc}")
                _watch_error = str(exc)
        time.sleep(POLL_SECONDS)


def start_watcher() -> None:
    """Démarre la surveillance du port USB (non bloquant). À appeler une
    fois, après recover_interrupted()."""
    global _watcher_started
    with _lock:
        if _watcher_started:
            return
        _watcher_started = True
    threading.Thread(target=_watch, daemon=True).start()
    print("Import par clé USB actif : branchez une clé contenant un dossier « Audiolibre ».")


# ---- Contenu de la clé, comparé à celui de la boîte ---------------------------

def _scan_key(root: Path) -> tuple:
    """(fichiers audio de la clé, nombre de fichiers ignorés). Chaque
    fichier : {"rel": "Livres/x.mp3", "src": Path, "size": octets}."""
    items, ignored = [], 0

    def audio_files(folder: Path):
        nonlocal ignored
        out = []
        for entry in sorted(folder.iterdir(), key=lambda e: e.name.lower()):
            if _is_hidden(entry.name):
                continue
            if entry.is_symlink():
                ignored += 1            # raccourci : jamais suivi
            elif entry.is_file():
                if _is_audio_name(entry.name) and len(entry.name.encode("utf-8")) <= MAX_NAME_BYTES:
                    out.append(entry)
                else:
                    ignored += 1
        return out

    def subfolders(folder: Path) -> list:
        return [e for e in sorted(folder.iterdir(), key=lambda e: e.name.lower())
                if e.is_dir() and not e.is_symlink() and not _is_hidden(e.name)]

    def count_deeper(folder: Path) -> None:
        """Fichiers rangés trop profond pour la boîte : comptés, non importés."""
        nonlocal ignored
        for _dirpath, _dirnames, filenames in os.walk(folder):
            ignored += sum(1 for name in filenames if not _is_hidden(name))

    books = _find_child(root, KEY_SECTION_NAMES["Livres"], strict=True)
    if books is not None:
        for entry in audio_files(books):
            items.append({"rel": f"Livres/{entry.name}", "src": entry, "size": entry.stat().st_size})
        for sub in subfolders(books):
            count_deeper(sub)

    music = _find_child(root, KEY_SECTION_NAMES["Musiques"], strict=True)
    if music is not None:
        for entry in audio_files(music):
            items.append({"rel": f"Musiques/{entry.name}", "src": entry, "size": entry.stat().st_size})
        for album in subfolders(music):
            if len(album.name.encode("utf-8")) > MAX_NAME_BYTES:
                count_deeper(album)
                continue
            for entry in audio_files(album):
                items.append({
                    "rel": f"Musiques/{album.name}/{entry.name}",
                    "src": entry, "size": entry.stat().st_size,
                })
            for sub in subfolders(album):
                count_deeper(sub)
    return items, ignored


def _box_files() -> set:
    """Fichiers audio de la boîte, en chemins relatifs à Bibliotheque/."""
    found = set()
    if BOOKS_DIR.is_dir():
        for entry in BOOKS_DIR.iterdir():
            if entry.is_file() and _is_audio_name(entry.name):
                found.add(f"Livres/{entry.name}")
    if MUSIC_DIR.is_dir():
        for entry in MUSIC_DIR.iterdir():
            if entry.is_file() and _is_audio_name(entry.name):
                found.add(f"Musiques/{entry.name}")
            elif entry.is_dir() and not _is_hidden(entry.name):
                for track in entry.iterdir():
                    if track.is_file() and _is_audio_name(track.name):
                        found.add(f"Musiques/{entry.name}/{track.name}")
    return found


def _reserve_reclaimable() -> int:
    """Place rendue si on vide la réserve. Un fichier identique gardé par le
    remplacement existe à la fois dans la bibliothèque et dans la réserve
    sans occuper deux fois la place : il ne compte pas."""
    total = 0
    if RESERVE_DIR.is_dir():
        for dirpath, _dirnames, filenames in os.walk(RESERVE_DIR):
            for name in filenames:
                try:
                    info = os.stat(os.path.join(dirpath, name))
                    if info.st_nlink == 1:
                        total += info.st_size
                except OSError:
                    pass
    return total


def _analyse(root: Path) -> dict:
    """Compare la clé à la boîte. Sert à l'aperçu de l'écran Import et, juste
    avant de copier, à l'import lui-même."""
    items, ignored = _scan_key(root)
    key_rels = set()
    new, different, present = [], [], []
    for item in items:
        key_rels.add(item["rel"])
        destination = LIBRARY_DIR / item["rel"]
        if destination.is_file():
            try:
                same = destination.stat().st_size == item["size"]
            except OSError:
                same = False
            (present if same else different).append(item)
        else:
            new.append(item)
    remove = sorted(_box_files() - key_rels)

    new_bytes = sum(i["size"] for i in new)
    different_bytes = sum(i["size"] for i in different)
    free = _free_bytes()
    reclaimable = _reserve_reclaimable()

    def fits(needed: int) -> bool:
        return needed + FREE_MARGIN_BYTES <= free + reclaimable

    albums = {i["rel"].split("/")[1] for i in items if i["rel"].count("/") == 2}
    return {
        "items": items, "new": new, "different": different, "present": present, "remove": remove,
        "ignored": ignored,
        "books": sum(1 for i in items if i["rel"].startswith("Livres/")),
        "tracks": sum(1 for i in items if i["rel"].startswith("Musiques/")),
        "albums": len(albums),
        "new_bytes": new_bytes, "different_bytes": different_bytes,
        "free_bytes": free, "reclaimable_bytes": reclaimable,
        "empty": not items,
        "add_fits": fits(new_bytes),
        "replace_fits": fits(new_bytes + different_bytes),
    }


def _public_preview(analysis: dict) -> dict:
    def names(entries) -> list:
        rels = [e["rel"] if isinstance(e, dict) else e for e in entries]
        return [_display_name(rel) for rel in rels[:PREVIEW_LIST_LIMIT]]

    return {
        "books": analysis["books"], "tracks": analysis["tracks"], "albums": analysis["albums"],
        "ignored": analysis["ignored"], "empty": analysis["empty"],
        "new_count": len(analysis["new"]), "new_names": names(analysis["new"]),
        "new_bytes": analysis["new_bytes"],
        "different_count": len(analysis["different"]), "different_names": names(analysis["different"]),
        "different_bytes": analysis["different_bytes"],
        "present_count": len(analysis["present"]),
        "remove_count": len(analysis["remove"]), "remove_names": names(analysis["remove"]),
        "free_bytes": analysis["free_bytes"],
        "add_fits": analysis["add_fits"], "replace_fits": analysis["replace_fits"],
        "list_limit": PREVIEW_LIST_LIMIT,
    }


def _refresh_preview(force: bool = False) -> Optional[dict]:
    global _preview, _preview_at
    with _lock:
        root = _key["root"] if _key["state"] == "prete" else None
        fresh = _preview is not None and (time.monotonic() - _preview_at) < PREVIEW_MAX_AGE
        if root is None:
            return None
        if fresh and not force:
            return _preview
    try:
        preview = _public_preview(_analyse(root))
    except OSError as exc:
        print(f"[clé USB] lecture de la clé impossible : {exc}")
        return None
    with _lock:
        _preview, _preview_at = preview, time.monotonic()
    return preview


# ---- État pour l'administration ----------------------------------------------

def is_busy() -> bool:
    with _lock:
        return _job["running"]


def reserve_info() -> Optional[dict]:
    """Ce que le dernier remplacement a mis de côté, ou None."""
    info_path = RESERVE_DIR / RESERVE_INFO
    if not info_path.is_file():
        return None
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    return {
        "date": info.get("date", ""),
        "removed_count": int(info.get("removed_count", 0)),
        "removed_names": list(info.get("removed_names", [])),
        "added_count": int(info.get("added_count", 0)),
        "bytes": _reserve_reclaimable(),
    }


def get_status() -> dict:
    with _lock:
        key = {"state": _key["state"], "label": _key["label"], "size": _key["size"]}
        job = dict(_job)
        last = dict(_last_result) if _last_result else None
        if last and time.monotonic() - last.get("at", 0.0) > LAST_RESULT_SECONDS:
            last = None
        confirm = time.monotonic() < _confirm_until
    preview = _refresh_preview() if (key["state"] == "prete" and not job["running"]) else None
    return {
        "key": key, "preview": preview, "job": job, "last": last,
        "confirm_pending": confirm, "reserve": None if job["running"] else reserve_info(),
    }


def history(limit: int = 10) -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _record(mode: str, source: str, status: str, added: int = 0, removed: int = 0,
            present: int = 0, ignored: int = 0, key_label: str = "") -> None:
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO imports (started_at, mode, source, status, added, removed, present, ignored, key_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), mode, source, status,
             added, removed, present, ignored, key_label),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        print(f"[import] historique non enregistré : {exc}")


# ---- Lancement ---------------------------------------------------------------

def cancel_confirmation() -> None:
    global _confirm_until
    with _lock:
        _confirm_until = 0.0


def on_master_tag(mode: str) -> str:
    """Un tag maître vient d'être posé sur la boîte. « Ajouter » part tout de
    suite ; « Remplacer » demande de reposer le tag dans les 10 secondes."""
    global _confirm_until
    if mode != "remplacer":
        cancel_confirmation()
        return start_import("ajouter", "tag")

    with _lock:
        now = time.monotonic()
        pending = now < _confirm_until
        # Un tag resté posé que le lecteur perd un instant « revient » aussitôt :
        # ce n'est pas une confirmation. Il faut l'avoir levé puis reposé.
        too_soon = pending and now < _confirm_until - CONFIRM_SECONDS + CONFIRM_MIN_GAP
        if too_soon:
            return "confirmer"
        _confirm_until = 0.0
    if pending:
        return start_import("remplacer", "tag")

    # Première pose : on vérifie d'abord que l'import est possible, pour ne
    # pas demander une confirmation qui mènerait à un refus.
    try:
        _check_possible("remplacer")
    except ImportRefused as refusal:
        _announce_refusal(refusal.code)
        return refusal.code
    with _lock:
        _confirm_until = time.monotonic() + CONFIRM_SECONDS
    _lcd().show_message("lcd.import_confirm_line1", "lcd.import_confirm_line2", seconds=CONFIRM_SECONDS)
    _sound().play_beep()
    return "confirmer"


def _announce_refusal(code: str) -> None:
    line1, line2 = _REFUSALS.get(code, ("lcd.import_stopped_line1", "lcd.import_stopped_line2"))
    _lcd().show_message(line1, line2, seconds=6)
    _sound().play_error()


def _check_possible(mode: str) -> dict:
    """Vérifie qu'un import peut partir et renvoie l'analyse de la clé.
    Lève ImportRefused sinon."""
    with _lock:
        if _job["running"]:
            raise ImportRefused("occupe")
        state, root = _key["state"], _key["root"]
    if state == "inconnue":
        raise ImportRefused("cle_inconnue")
    if state != "prete" or root is None:
        raise ImportRefused("pas_de_cle")
    try:
        analysis = _analyse(root)
    except OSError as exc:
        raise ImportRefused("cle_retiree", str(exc))
    if analysis["empty"]:
        raise ImportRefused("cle_vide")
    if mode == "ajouter":
        if not analysis["new"]:
            raise ImportRefused("rien")
        if not analysis["add_fits"]:
            raise ImportRefused("place")
    else:
        if not analysis["new"] and not analysis["different"] and not analysis["remove"]:
            raise ImportRefused("rien")
        if not analysis["replace_fits"]:
            raise ImportRefused("place")
    return analysis


def start_import(mode: str, source: str) -> str:
    """Lance un import. Renvoie "ok" s'il est parti (il se poursuit en tâche
    de fond, voir get_status()), sinon le code du refus."""
    if mode not in MODES:
        return "copie"
    try:
        analysis = _check_possible(mode)
        with _lock:
            if _job["running"]:
                raise ImportRefused("occupe")
            to_copy = len(analysis["new"]) + (len(analysis["different"]) if mode == "remplacer" else 0)
            _job.update(running=True, mode=mode, source=source, phase="copie",
                        done=0, total=to_copy, title="")
    except ImportRefused as refusal:
        _announce_refusal(refusal.code)
        if refusal.code not in ("occupe", "pas_de_cle", "cle_inconnue"):
            with _lock:
                label = _key["label"]
            _record(mode, source, refusal.code, key_label=label)
        return refusal.code

    threading.Thread(target=_run_job, args=(mode, source, analysis), daemon=True).start()
    return "ok"


# ---- L'import lui-même -------------------------------------------------------

def _progress(done: int, total: int, title: str) -> None:
    with _lock:
        _job.update(done=done, total=total, title=title)
    _lcd().set_sticky(f"Import {done}/{total}", title)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as src, open(destination, "wb") as dst:
        while True:
            chunk = src.read(COPY_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    if destination.stat().st_size != source.stat().st_size:
        raise OSError(f"copie incomplète : {source.name}")


def _keep_file(existing: Path, destination: Path) -> None:
    """Fichier identique déjà sur la boîte : repris tel quel dans le dossier
    d'attente, sans recopie (même fichier sous deux noms : aucune place
    prise). Si le système refuse (fichier déposé par un autre utilisateur),
    il est recopié, à condition qu'il reste assez de place."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(existing, destination)
    except OSError:
        if existing.stat().st_size + FREE_MARGIN_BYTES > _free_bytes():
            raise ImportRefused("place")
        shutil.copy2(existing, destination)


def _make_room(needed: int) -> None:
    """S'il manque de la place, vide l'ancienne réserve. Refuse si cela ne
    suffit pas."""
    if needed + FREE_MARGIN_BYTES <= _free_bytes():
        return
    if RESERVE_DIR.exists():
        print("[import] place insuffisante : l'ancienne réserve est vidée.")
        _drop_reserve()
    if needed + FREE_MARGIN_BYTES > _free_bytes():
        raise ImportRefused("place")


def _discard_reserve() -> None:
    """Abandonne la réserve. Elle est d'abord renommée (instantané), puis
    effacée : après une coupure pendant l'effacement, il ne reste jamais de
    réserve à moitié vide que l'on proposerait d'annuler."""
    _rmtree(RESERVE_OLD_DIR)
    if RESERVE_DIR.exists():
        os.replace(RESERVE_DIR, RESERVE_OLD_DIR)
    _rmtree(RESERVE_OLD_DIR)
    if RESERVE_OLD_DIR.exists():
        raise OSError("ancienne réserve impossible à effacer")


def _drop_reserve() -> None:
    _discard_reserve()
    _clean_orphan_covers()


def _stop_playback() -> None:
    try:
        from app.player import player_controller
        player_controller.stop()
    except Exception as exc:
        print(f"[import] arrêt de la lecture impossible : {exc}")


def _run_job(mode: str, source: str, analysis: dict) -> None:
    global _last_result, _preview
    with _lock:
        label, root = _key["label"], _key["root"]
    result = {"mode": mode, "source": source, "status": "ok", "added": 0, "removed": 0,
              "present": len(analysis["present"]), "ignored": analysis["ignored"],
              "different": len(analysis["different"]), "updated": 0}
    try:
        _stop_playback()
        cancel_confirmation()
        _lcd().set_idle_hint(None)
        if mode == "ajouter":
            _do_add(analysis, result)
        else:
            _do_replace(analysis, result, root)
        print(f"[import] {mode} terminé : {result['added']} ajouté(s), {result['removed']} retiré(s).")
    except ImportRefused as refusal:
        result["status"] = refusal.code
    except OSError as exc:
        key_gone = root is None or not Path(root).exists()
        result["status"] = "cle_retiree" if key_gone else "copie"
        print(f"[import] interrompu : {exc}")
    except Exception as exc:        # ne jamais laisser la boîte bloquée « en cours »
        result["status"] = "copie"
        print(f"[import] erreur inattendue : {exc}")
    finally:
        _rmtree(STAGING_DIR)

    _record(mode, source, result["status"], result["added"], result["removed"],
            result["present"], result["ignored"], label)
    with _lock:
        _job.update(running=False, phase="", title="")
        result["at"] = time.monotonic()
        _last_result = result
        _preview = None
    _lcd().clear_sticky()

    if result["status"] == "ok":
        if result["removed"]:
            _lcd().show_message("lcd.import_done_line1", "lcd.import_done_both", seconds=8,
                                a=result["added"], r=result["removed"])
        else:
            _lcd().show_message("lcd.import_done_line1", "lcd.import_done_added", seconds=8,
                                n=result["added"])
        _lcd().set_idle_hint("lcd.import_remove_key")
        _sound().play_done()
    else:
        _announce_refusal(result["status"])
        with _lock:
            still_there = _key["state"] == "prete"
        _lcd().set_idle_hint("lcd.import_ready_line1" if still_there else None,
                             "lcd.import_ready_line2")


def _stage(entries: list, start: int, total: int) -> int:
    """Copie ces fichiers de la clé vers le dossier d'attente."""
    done = start
    for item in entries:
        _progress(done + 1, total, _display_name(item["rel"]))
        _copy_file(item["src"], STAGING_DIR / item["rel"])
        done += 1
    return done


def _do_add(analysis: dict, result: dict) -> None:
    new = analysis["new"]
    _make_room(analysis["new_bytes"])
    _rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True)
    _stage(new, 0, len(new))
    os.sync()

    with _lock:
        _job["phase"] = "mise_en_place"
    for item in new:
        destination = LIBRARY_DIR / item["rel"]
        if destination.exists():
            continue                    # arrivé entre-temps par l'administration
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(STAGING_DIR / item["rel"], destination)
        result["added"] += 1
    os.sync()

    # Un import réussi clôt le remplacement précédent : sa réserve est vidée.
    if RESERVE_DIR.exists():
        _drop_reserve()
    _scan_library()


def _rollback_switch() -> None:
    """Défait une bascule commencée : l'ancien contenu, déjà parti dans
    .reserve.tmp, reprend sa place. Sert après une coupure de courant
    (recover_interrupted) comme après une erreur pendant la bascule."""
    for section in SECTIONS:
        saved = RESERVE_TMP_DIR / section
        if saved.exists():
            _rmtree(LIBRARY_DIR / section)
            os.replace(saved, LIBRARY_DIR / section)
    _rmtree(RESERVE_TMP_DIR)


def _do_replace(analysis: dict, result: dict, root: Optional[Path] = None) -> None:
    to_copy = analysis["new"] + analysis["different"]
    if RESERVE_TMP_DIR.exists():
        _rollback_switch()              # reste d'une bascule précédente : jamais effacé tel quel
    _rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True)
    for section in SECTIONS:
        (STAGING_DIR / section).mkdir()

    # 1. Tout le futur contenu de la boîte est d'abord réuni dans le dossier
    #    d'attente : ce qui est identique est repris sur place, les
    #    nouveautés sont copiées depuis la clé. Rien n'a encore changé pour
    #    la boîte.
    for item in analysis["present"]:
        _keep_file(LIBRARY_DIR / item["rel"], STAGING_DIR / item["rel"])
    _make_room(analysis["new_bytes"] + analysis["different_bytes"])
    _stage(to_copy, 0, len(to_copy))
    os.sync()
    # La clé doit encore être là et lisible : si elle a été retirée pendant
    # l'analyse, « absent de la clé » ne voudrait plus rien dire.
    if root is not None:
        os.listdir(root)

    # 2. Bascule : l'ancien contenu part en réserve, le nouveau prend sa
    #    place. Ce ne sont que des renommages, instantanés. Une coupure de
    #    courant à cet endroit est rattrapée par recover_interrupted() ; une
    #    erreur, par le retour en arrière ci-dessous.
    with _lock:
        _job["phase"] = "mise_en_place"
    _discard_reserve()
    RESERVE_TMP_DIR.mkdir(parents=True)
    _backup_database(RESERVE_TMP_DIR / RESERVE_DB)
    after = sorted(item["rel"] for item in analysis["items"])
    changed = [item["rel"] for item in analysis["different"]]
    (RESERVE_TMP_DIR / RESERVE_INFO).write_text(json.dumps({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "removed_count": len(analysis["remove"]),
        "removed_names": [_display_name(rel) for rel in analysis["remove"][:PREVIEW_LIST_LIMIT]],
        "added_count": len(analysis["new"]),
        "after": after,                 # contenu de la boîte juste après le remplacement
    }, ensure_ascii=False), encoding="utf-8")
    (RESERVE_TMP_DIR / RESERVE_TODO).write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    try:
        for section in SECTIONS:
            current = LIBRARY_DIR / section
            if current.exists():
                os.replace(current, RESERVE_TMP_DIR / section)
        for section in SECTIONS:
            os.replace(STAGING_DIR / section, LIBRARY_DIR / section)
        os.replace(RESERVE_TMP_DIR, RESERVE_DIR)
    except Exception:
        _rollback_switch()
        raise
    os.sync()

    # 3. La base suit : fiches des histoires retirées, nouvelles histoires.
    result["added"] = len(analysis["new"])
    result["removed"] = len(analysis["remove"])
    result["updated"] = len(analysis["different"])
    try:
        _sync_database(changed)
        (RESERVE_DIR / RESERVE_TODO).unlink(missing_ok=True)
    except Exception as exc:
        # Les fichiers sont en place : l'import est réussi. La base sera
        # remise en accord au prochain démarrage (voir recover_interrupted()).
        print(f"[import] mise à jour de la base reportée au prochain démarrage : {exc}")


# ---- Base de données ---------------------------------------------------------

def _backup_database(destination: Path) -> None:
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _scan_library() -> None:
    from app.library_scan import scan_books, scan_music
    scan_books()
    scan_music()


def _under(path: str, folder: Path) -> bool:
    prefix = str(folder.resolve()) + os.sep
    return path.startswith(prefix)


def _sync_database(changed_rels: list) -> None:
    """Met la base en accord avec les fichiers après un remplacement : retire
    les fiches des histoires et morceaux qui ne sont plus là (avec leurs tags
    et leurs places dans les listes), rafraîchit celles dont le fichier a
    changé, puis ajoute les nouveautés. Une fiche dont le fichier est resté
    garde tout : tag, position de lecture, catégorie."""
    from app.audio_meta import read_audio_metadata

    conn = get_connection()
    for row in conn.execute("SELECT id, file_path FROM books").fetchall():
        if _under(row["file_path"], BOOKS_DIR) and not os.path.isfile(row["file_path"]):
            conn.execute("DELETE FROM tag_associations WHERE kind = 'book' AND item_id = ?", (row["id"],))
            conn.execute("DELETE FROM playlist_items WHERE kind = 'book' AND item_id = ?", (row["id"],))
            conn.execute("DELETE FROM books WHERE id = ?", (row["id"],))

    for row in conn.execute("SELECT id, file_path FROM tracks").fetchall():
        if _under(row["file_path"], MUSIC_DIR) and not os.path.isfile(row["file_path"]):
            conn.execute("DELETE FROM playlist_items WHERE kind = 'track' AND item_id = ?", (row["id"],))
            conn.execute("DELETE FROM tracks WHERE id = ?", (row["id"],))

    music_root = str(MUSIC_DIR.resolve())
    for row in conn.execute("SELECT id, folder_path FROM albums").fetchall():
        inside = row["folder_path"] == music_root or _under(row["folder_path"], MUSIC_DIR)
        remaining = conn.execute("SELECT 1 FROM tracks WHERE album_id = ? LIMIT 1", (row["id"],)).fetchone()
        # Un album dont tous les morceaux ont changé de nom reste le même
        # album (même dossier) : sa fiche et son tag sont gardés, la relecture
        # de la bibliothèque y rattachera les nouveaux morceaux.
        folder = Path(row["folder_path"])
        try:
            still_has_audio = folder.is_dir() and any(
                e.is_file() and _is_audio_name(e.name) for e in folder.iterdir())
        except OSError:
            still_has_audio = False
        if inside and remaining is None and not still_has_audio:
            conn.execute("DELETE FROM tag_associations WHERE kind = 'album' AND item_id = ?", (row["id"],))
            conn.execute("DELETE FROM albums WHERE id = ?", (row["id"],))

    for rel in changed_rels:
        path = (LIBRARY_DIR / rel).resolve()
        try:
            meta = read_audio_metadata(path)
        except Exception:
            continue
        if rel.startswith("Livres/"):
            conn.execute(
                "UPDATE books SET title = ?, duration_ms = ?, position_ms = 0, finished = 0 WHERE file_path = ?",
                (meta.title, meta.duration_ms, str(path)),
            )
        else:
            conn.execute(
                "UPDATE tracks SET title = ?, duration_ms = ?, position_ms = 0, finished = 0, "
                "artist = ?, album = ?, year = ? WHERE file_path = ?",
                (meta.title, meta.duration_ms, meta.artist, meta.album, meta.year, str(path)),
            )
    conn.commit()
    conn.close()
    _scan_library()


_RESTORED_TABLES = ("tracks", "albums", "books", "tag_associations", "playlist_items")


def _restore_database(backup: Path) -> None:
    """Remet les fiches (histoires, albums, morceaux, tags, contenu des
    listes) telles qu'elles étaient avant le remplacement. Les réglages ne
    sont pas touchés."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ATTACH DATABASE ? AS reserve", (str(backup),))
        for table in _RESTORED_TABLES:
            conn.execute(f"DELETE FROM main.{table}")
            conn.execute(f"INSERT INTO main.{table} SELECT * FROM reserve.{table}")
        conn.execute("UPDATE books SET category_id = NULL WHERE category_id IS NOT NULL "
                     "AND category_id NOT IN (SELECT id FROM categories)")
        conn.execute("DELETE FROM playlist_items WHERE playlist_id NOT IN (SELECT id FROM playlists)")
        conn.commit()
        conn.execute("DETACH DATABASE reserve")
    finally:
        conn.close()


def _clean_orphan_covers() -> None:
    """Supprime les jaquettes qui ne servent plus à aucune fiche. Fait
    seulement quand la réserve disparaît : tant qu'elle existe, une
    annulation doit retrouver ses jaquettes."""
    try:
        conn = get_connection()
        used = set()
        for table in ("books", "albums", "tracks"):
            for row in conn.execute(f"SELECT cover_path FROM {table} WHERE cover_path IS NOT NULL"):
                used.add(os.path.basename(row["cover_path"]))
        conn.close()
        for entry in COVERS_DIR.iterdir():
            if entry.is_file() and entry.name not in used:
                entry.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[import] nettoyage des jaquettes : {exc}")


# ---- Annuler le dernier remplacement -----------------------------------------

def can_undo() -> bool:
    return (RESERVE_DIR / RESERVE_INFO).is_file() and not is_busy()


def undo_last_replace(source: str = "web") -> str:
    """Remet la boîte dans l'état d'avant le dernier « Remplacer ». Renvoie
    "ok", "occupe" ou "rien"."""
    global _preview
    with _lock:
        if _job["running"]:
            return "occupe"
        if not (RESERVE_DIR / RESERVE_INFO).is_file():
            return "rien"
        _job.update(running=True, mode="annulation", source=source, phase="mise_en_place",
                    done=0, total=0, title="")
    info = reserve_info() or {}
    status = "ok"
    try:
        _stop_playback()
        _finish_undo()
    except Exception as exc:
        status = "copie"
        print(f"[import] annulation impossible : {exc}")
    finally:
        with _lock:
            _job.update(running=False, phase="", mode="", title="")
            _preview = None
    # Sens inversé : ce que le remplacement avait retiré revient, ce qu'il
    # avait ajouté repart.
    _record("annulation", source, status,
            added=int(info.get("removed_count", 0)), removed=int(info.get("added_count", 0)))
    return status


def _finish_undo() -> None:
    """Annulation proprement dite. Écrite pour pouvoir être reprise là où
    elle s'est arrêtée (voir recover_interrupted())."""
    UNDO_TMP_DIR.mkdir(parents=True, exist_ok=True)
    for section in SECTIONS:
        saved = RESERVE_DIR / section
        if not saved.exists():
            continue                    # déjà remis en place
        current = LIBRARY_DIR / section
        if current.exists():
            if (UNDO_TMP_DIR / section).exists():
                _rmtree(current)        # dossier vide recréé au démarrage
            else:
                os.replace(current, UNDO_TMP_DIR / section)
        os.replace(saved, current)
    backup = RESERVE_DIR / RESERVE_DB
    if backup.is_file():
        _restore_database(backup)
    _keep_later_additions()
    os.sync()
    # À partir d'ici l'annulation est acquise : la réserve change de nom
    # (instantané), puis tout ce qui ne sert plus est effacé.
    _rmtree(RESERVE_OLD_DIR)
    os.replace(RESERVE_DIR, RESERVE_OLD_DIR)
    _rmtree(UNDO_TMP_DIR)
    _rmtree(RESERVE_OLD_DIR)
    for section in SECTIONS:
        (LIBRARY_DIR / section).mkdir(parents=True, exist_ok=True)
    _scan_library()
    _clean_orphan_covers()


def _keep_later_additions() -> None:
    """Ce qui a été envoyé à la boîte APRÈS le remplacement (par l'écran
    Import, depuis un téléphone) ne vient pas de la clé : l'annulation ne
    doit pas l'emporter. Ces fichiers rejoignent le contenu rétabli."""
    try:
        info = json.loads((RESERVE_DIR / RESERVE_INFO).read_text(encoding="utf-8"))
        after = info.get("after")
    except (OSError, ValueError):
        return
    if not isinstance(after, list):
        return
    known = set(after)
    for section in SECTIONS:
        base = UNDO_TMP_DIR / section
        if not base.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                source = Path(dirpath) / name
                rel = f"{section}/{source.relative_to(base).as_posix()}"
                destination = LIBRARY_DIR / rel
                if rel in known or not _is_audio_name(name) or destination.exists():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)


# ---- Reprise après une coupure -----------------------------------------------

def recover_interrupted() -> None:
    """À appeler une fois au démarrage, avant tout le reste. Si la boîte a
    été coupée pendant un import, la remet dans un état propre :
    - coupée pendant la copie : le dossier d'attente est jeté, rien n'a changé ;
    - coupée pendant la bascule : l'ancien contenu est remis en place ;
    - coupée juste après la bascule : la base est mise en accord ;
    - coupée pendant une annulation : l'annulation est terminée."""
    try:
        if RESERVE_OLD_DIR.exists():
            _rmtree(RESERVE_OLD_DIR)    # effacement d'une ancienne réserve, à finir
        if RESERVE_TMP_DIR.exists():
            print("[import] reprise : remplacement interrompu, l'ancien contenu est remis en place.")
            _rollback_switch()
        if UNDO_TMP_DIR.exists():
            print("[import] reprise : annulation interrompue, elle est terminée.")
            if RESERVE_DIR.exists():
                _finish_undo()
            else:
                # L'annulation était acquise : il ne restait qu'à faire le ménage.
                _rmtree(UNDO_TMP_DIR)
                _scan_library()
        if STAGING_DIR.exists():
            print("[import] reprise : copie interrompue, dossier d'attente vidé.")
            _rmtree(STAGING_DIR)
        if (RESERVE_DIR / RESERVE_TODO).exists():
            print("[import] reprise : mise à jour de la base après le dernier remplacement.")
            try:
                changed = json.loads((RESERVE_DIR / RESERVE_TODO).read_text(encoding="utf-8") or "[]")
            except (OSError, ValueError):
                changed = []
            _sync_database([rel for rel in changed if isinstance(rel, str)])
            (RESERVE_DIR / RESERVE_TODO).unlink(missing_ok=True)
        for section in SECTIONS:
            (LIBRARY_DIR / section).mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[import] reprise après coupure impossible : {exc}")


def wipe_work_dirs() -> None:
    """Réinitialisation usine : plus rien en attente ni en réserve."""
    for folder in (STAGING_DIR, RESERVE_DIR, RESERVE_TMP_DIR, UNDO_TMP_DIR, RESERVE_OLD_DIR):
        _rmtree(folder)
