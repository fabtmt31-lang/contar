"""
Rangement du disque de dépôt (v0.11).

Quand la boîte est reliée à un ordinateur par le câble USB-C, elle lui
présente un petit disque « CONTAR » (voir bin/usb-gadget.sh). Le parent y
copie des fichiers, puis éjecte le disque ; la boîte le reprend et ce
module range ce qu'il contient dans la bibliothèque :

    Histoires/x.mp3          -> Bibliotheque/Livres/x.mp3     (une histoire)
    Histoires/Dossier/y.mp3  -> Bibliotheque/Livres/y.mp3     (une histoire aussi)
    Musiques/Album/z.mp3     -> Bibliotheque/Musiques/Album/z.mp3
    Musiques/z.mp3           -> Bibliotheque/Musiques/z.mp3   (album « Musique »)
    x.mp3 (à la racine)      -> une histoire

Rien n'est jamais supprimé ni remplacé dans la bibliothèque : un fichier
déjà présent à l'identique (même nom, même taille) est ignoré ; un autre
fichier du même nom est rangé avec un suffixe « (1) ». Les dossiers
« Livres » et « Musique » sont acceptés comme synonymes.

Le disque est ensuite vidé par l'appelant (app/usb_gadget.py).
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from app.config import AUDIO_EXTENSIONS, BOOKS_DIR, LIBRARY_DIR, MUSIC_DIR
from app.database import get_connection

BOOK_NAMES = ("histoires", "histoire", "livres", "livre", "istorias", "stories")
MUSIC_NAMES = ("musiques", "musique", "music", "musica")
# Place laissée libre sur la carte après le rangement (base, jaquettes, système).
FREE_MARGIN_BYTES = int(os.environ.get("CONTAR_IMPORT_MARGE", str(200 * 1024 * 1024)))
MAX_NAME_BYTES = 255

# Dossiers de travail de l'ancien import par clé USB (v0.9–v0.10).
_OLD_WORK_DIRS = (".attente", ".reserve.tmp", ".annule.tmp", ".reserve.old")


def _hidden(name: str) -> bool:
    return name.startswith(".") or name.startswith("_") or name in ("System Volume Information", "$RECYCLE.BIN")


def _is_audio(path: Path) -> bool:
    return (path.is_file() and not path.is_symlink() and not _hidden(path.name)
            and path.suffix.lower() in AUDIO_EXTENSIONS
            and len(path.name.encode("utf-8")) <= MAX_NAME_BYTES)


def _children(folder: Path) -> list:
    try:
        return sorted(folder.iterdir(), key=lambda e: e.name.lower())
    except OSError:
        return []


def _subdirs(folder: Path) -> list:
    return [e for e in _children(folder) if e.is_dir() and not e.is_symlink() and not _hidden(e.name)]


def plan(root: Path) -> list:
    """Ce qu'il y a à ranger : [(source, destination relative à Bibliotheque/)]."""
    moves = []
    books, music = None, None
    for entry in _subdirs(root):
        lowered = entry.name.lower()
        if lowered in BOOK_NAMES and books is None:
            books = entry
        elif lowered in MUSIC_NAMES and music is None:
            music = entry

    for entry in _children(root):
        if _is_audio(entry):
            moves.append((entry, Path("Livres") / entry.name))
    if books is not None:
        for dirpath, dirnames, filenames in os.walk(books):
            dirnames[:] = sorted(d for d in dirnames if not _hidden(d))
            for name in sorted(filenames, key=str.lower):
                source = Path(dirpath) / name
                if _is_audio(source):
                    moves.append((source, Path("Livres") / name))
    if music is not None:
        for entry in _children(music):
            if _is_audio(entry):
                moves.append((entry, Path("Musiques") / entry.name))
        for album in _subdirs(music):
            for dirpath, dirnames, filenames in os.walk(album):
                dirnames[:] = sorted(d for d in dirnames if not _hidden(d))
                for name in sorted(filenames, key=str.lower):
                    source = Path(dirpath) / name
                    if _is_audio(source):
                        moves.append((source, Path("Musiques") / album.name / name))
    return moves


def _free_bytes() -> int:
    try:
        return shutil.disk_usage(LIBRARY_DIR).free
    except OSError:
        return 0


def _destination(rel: Path, size: int):
    """Chemin définitif, ou None si le même fichier est déjà sur la boîte."""
    target = LIBRARY_DIR / rel
    if not target.exists():
        return target
    try:
        if target.stat().st_size == size:
            return None
    except OSError:
        pass
    counter = 1
    while True:
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _record(status: str, added: int = 0, present: int = 0, ignored: int = 0) -> None:
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO imports (started_at, mode, source, status, added, removed, present, ignored, key_label) "
            "VALUES (?, 'depot', 'usb', ?, ?, 0, ?, ?, 'CONTAR')",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), status, added, present, ignored),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[dépôt] journal non écrit : {exc}")


def import_from(root: Path) -> dict:
    """Range le contenu du dépôt monté en « root ». Renvoie le bilan :
    {"status": "ok" | "vide" | "place" | "copie", "added", "present", "ignored"}."""
    moves = plan(root)
    if not moves:
        _record("vide")
        return {"status": "vide", "added": 0, "present": 0, "ignored": 0}

    todo, present = [], 0
    for source, rel in moves:
        size = source.stat().st_size
        target = _destination(rel, size)
        if target is None:
            present += 1
        else:
            todo.append((source, target, size))

    needed = sum(size for _s, _t, size in todo)
    if needed + FREE_MARGIN_BYTES > _free_bytes():
        _record("place", present=present)
        return {"status": "place", "added": 0, "present": present, "ignored": 0, "needed": needed}

    added = 0
    try:
        for source, target, _size in todo:
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.part")
            shutil.copyfile(source, partial)
            os.replace(partial, target)
            added += 1
    except OSError as exc:
        print(f"[dépôt] copie interrompue : {exc}")
        _record("copie", added=added, present=present)
        _scan()
        return {"status": "copie", "added": added, "present": present, "ignored": 0}

    _scan()
    _record("ok", added=added, present=present)
    return {"status": "ok", "added": added, "present": present, "ignored": 0}


def _scan() -> None:
    from app.library_scan import scan_books, scan_music
    scan_books()
    scan_music()


def history(limit: int = 8) -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def clean_old_work_dirs() -> None:
    """Restes de l'import par clé USB d'avant la v0.11 (fichiers à moitié
    copiés). « .reserve », qui garde ce qu'un ancien « Remplacer » avait
    retiré, n'est pas touché : voir CHANGELOG.md."""
    for name in _OLD_WORK_DIRS:
        path = LIBRARY_DIR / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for folder in (BOOKS_DIR, MUSIC_DIR):
        if folder.is_dir():
            for partial in folder.rglob(".*.part"):
                partial.unlink(missing_ok=True)
