"""
Suppression d'un livre ou d'un album entier : retire la ligne en base, le
ou les fichiers audio et la jaquette du disque, toute association de tag
qui pointait dessus (voir app/tags.py) et toute entrée de liste de
lecture qui le référençait (voir app/playlist.py).

Ces deux dernières tables utilisent kind+item_id plutôt qu'une vraie clé
étrangère (une association ou un élément de liste peut viser un livre OU
un morceau) : SQLite ne les nettoie donc jamais tout seul quand la ligne
visée disparaît — il faut le faire ici, à la main, avant la suppression
elle-même.

Arrête aussi la lecture en cours si c'est justement l'élément qu'on est
en train de supprimer, pour ne pas continuer à faire tourner un fichier
qu'on vient d'effacer du disque.
"""

from pathlib import Path
from typing import Optional

from app.database import get_connection
from app.player import player_controller


def _delete_file_if_exists(path: Optional[str]) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as exc:
        print(f"[bibliothèque] impossible de supprimer le fichier {path} : {exc}")


def delete_book(book_id: int) -> tuple[bool, str]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        conn.close()
        return False, "Ce livre n'existe déjà plus."

    state = player_controller.get_state()
    if state["kind"] == "book" and state["item_id"] == book_id:
        player_controller.stop()

    conn.execute("DELETE FROM tag_associations WHERE kind = 'book' AND item_id = ?", (book_id,))
    conn.execute("DELETE FROM playlist_items WHERE kind = 'book' AND item_id = ?", (book_id,))
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()

    _delete_file_if_exists(row["file_path"])
    _delete_file_if_exists(row["cover_path"])

    return True, f"« {row['title']} » supprimé."


def delete_album(album_id: int) -> tuple[bool, str]:
    conn = get_connection()
    album_row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if album_row is None:
        conn.close()
        return False, "Cet album n'existe déjà plus."

    tracks = conn.execute("SELECT * FROM tracks WHERE album_id = ?", (album_id,)).fetchall()

    state = player_controller.get_state()
    if state["kind"] == "track" and any(t["id"] == state["item_id"] for t in tracks):
        player_controller.stop()

    for track in tracks:
        conn.execute(
            "DELETE FROM playlist_items WHERE kind = 'track' AND item_id = ?", (track["id"],)
        )
    # Les morceaux doivent disparaître AVANT l'album : tracks.album_id
    # référence albums(id) sans ON DELETE CASCADE (voir app/database.py),
    # PRAGMA foreign_keys = ON refuserait sinon la suppression de l'album
    # tant que des morceaux le référencent encore.
    conn.execute("DELETE FROM tracks WHERE album_id = ?", (album_id,))
    conn.execute("DELETE FROM tag_associations WHERE kind = 'album' AND item_id = ?", (album_id,))
    conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
    conn.commit()
    conn.close()

    for track in tracks:
        _delete_file_if_exists(track["cover_path"])
        _delete_file_if_exists(track["file_path"])
    _delete_file_if_exists(album_row["cover_path"])

    return True, f"« {album_row['name']} » supprimé (avec {len(tracks)} morceau(x))."
