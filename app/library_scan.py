"""
Portage direct de la logique de scan de BookRepository.kt et
MusicRepository.kt : parcourt les dossiers Bibliotheque/Livres et
Bibliotheque/Musiques et ajoute en base tout nouveau fichier audio trouvé.

Convention conservée à l'identique de la version Android :
- Bibliotheque/Livres : tous les fichiers audio à la racine deviennent des "books"
- Bibliotheque/Musiques : chaque sous-dossier direct devient un "album" ; les
  fichiers posés directement à la racine sont regroupés dans un album
  "Musique". Un seul niveau de profondeur, comme sur Android.
"""

from pathlib import Path

from app.audio_meta import read_audio_metadata
from app.config import AUDIO_EXTENSIONS, BOOKS_DIR, COVERS_DIR, MUSIC_DIR
from app.database import get_connection

BOOK_PALETTE = [
    ("🦊", "#FFB25E"), ("🐢", "#7FE0C4"), ("🐻", "#C9A6FF"),
    ("🐰", "#FF9AA8"), ("🦉", "#8FB6FF"), ("🐨", "#B7E37B"),
]

MUSIC_PALETTE = [
    ("🎵", "#8FB6FF"), ("🎶", "#FFB25E"), ("🎧", "#7FE0C4"),
    ("🎹", "#C9A6FF"), ("🥁", "#FF9AA8"),
]


def _is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS


def _save_cover(data: bytes | None, base_name: str) -> str | None:
    if not data:
        return None
    try:
        out_path = COVERS_DIR / f"{base_name}.jpg"
        out_path.write_bytes(data)
        return str(out_path)
    except Exception:
        return None


def scan_books() -> int:
    """Retourne le nombre de nouveaux livres ajoutés en base."""
    conn = get_connection()
    existing = {row["file_path"] for row in conn.execute("SELECT file_path FROM books")}

    # Depuis la v0.10, la boîte ne lit plus que sa propre bibliothèque (les
    # « dossiers supplémentaires » hérités de la version Android sont retirés).
    folders = [BOOKS_DIR]

    files: list[Path] = []
    for folder in folders:
        if folder.exists() and folder.is_dir():
            files.extend(sorted(f for f in folder.iterdir() if _is_audio(f)))

    new_files = [f for f in files if str(f.resolve()) not in existing]

    added = 0
    for index, file in enumerate(new_files):
        meta = read_audio_metadata(file)
        emoji, color = BOOK_PALETTE[index % len(BOOK_PALETTE)]
        cover_path = _save_cover(meta.cover_bytes, f"book_{abs(hash(str(file.resolve())))}")

        conn.execute(
            """INSERT OR IGNORE INTO books
               (title, author, file_path, emoji, color_hex, duration_ms, cover_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                meta.title,
                meta.artist or "Histoire du soir",
                str(file.resolve()),
                emoji,
                color,
                meta.duration_ms,
                cover_path,
            ),
        )
        added += 1

    conn.commit()
    conn.close()
    return added


def scan_music() -> int:
    """Retourne le nombre de nouveaux morceaux ajoutés en base."""
    conn = get_connection()
    existing_tracks = {row["file_path"] for row in conn.execute("SELECT file_path FROM tracks")}

    roots = [MUSIC_DIR]

    # (dossier, fichiers audio qu'il contient), un niveau de profondeur
    groups: list[tuple[Path, list[Path]]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        subfolders = [f for f in root.iterdir() if f.is_dir()]
        root_files = sorted(f for f in root.iterdir() if _is_audio(f))

        for folder in subfolders:
            files_in_folder = sorted(f for f in folder.iterdir() if _is_audio(f))
            groups.append((folder, files_in_folder))

        if root_files:
            groups.append((root, root_files))

    added = 0
    for i, (folder, files) in enumerate(groups):
        if not files:
            continue
        emoji, color = MUSIC_PALETTE[i % len(MUSIC_PALETTE)]
        folder_path = str(folder.resolve())

        conn.execute(
            "INSERT OR IGNORE INTO albums (name, folder_path, emoji, color_hex) VALUES (?, ?, ?, ?)",
            (folder.name or "Musique", folder_path, emoji, color),
        )
        conn.commit()

        album_row = conn.execute(
            "SELECT id, cover_path FROM albums WHERE folder_path = ?", (folder_path,)
        ).fetchone()
        if album_row is None:
            continue
        album_id = album_row["id"]

        new_tracks = [f for f in files if str(f.resolve()) not in existing_tracks]
        for index, file in enumerate(new_tracks):
            meta = read_audio_metadata(file)
            cover_path = _save_cover(meta.cover_bytes, f"track_{abs(hash(str(file.resolve())))}")

            conn.execute(
                """INSERT OR IGNORE INTO tracks
                   (album_id, title, file_path, duration_ms, order_index, cover_path, artist, album, year)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    album_id,
                    meta.title,
                    str(file.resolve()),
                    meta.duration_ms,
                    index,
                    cover_path,
                    meta.artist,
                    meta.album,
                    meta.year,
                ),
            )
            added += 1
        conn.commit()

        # Vignette de l'album = vignette du premier morceau du dossier qui en
        # possède une, recalculée seulement si absente ou si le fichier
        # pointé n'existe plus (auto-réparation, comme sur Android).
        needs_cover = album_row["cover_path"] is None or not Path(album_row["cover_path"]).exists()
        if needs_cover:
            for f in files:
                meta = read_audio_metadata(f)
                if meta.cover_bytes:
                    resolved_cover = _save_cover(meta.cover_bytes, f"album_{album_id}")
                    if resolved_cover:
                        conn.execute(
                            "UPDATE albums SET cover_path = ? WHERE id = ?", (resolved_cover, album_id)
                        )
                        conn.commit()
                    break

    conn.close()
    return added
