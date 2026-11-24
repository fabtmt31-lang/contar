"""
Association entre un tag NFC/RFID (son UID) et un contenu de la
bibliothèque : une histoire, un album entier ou une liste de lecture
(v0.11), avec la façon de le jouer (reprise, ordre, boucle) et
l'avancement propre au tag.

Volontairement simple : une seule table, une seule association par tag —
poser un tag déjà associé sur un autre livre/album remplace l'ancienne
association plutôt que d'échouer ou d'en créer une seconde. Ce module ne
touche jamais à la lecture elle-même (ça reste le rôle de
PlayerController, voir app/player.py) ni à la détection matérielle du tag
(voir app/nfc_controller.py) — uniquement au contenu de la table
tag_associations. Même division des responsabilités que
PlaylistManager/PlayerController.play_playlist() pour les listes de
lecture.
"""

from app.database import get_connection


class TagManager:
    KINDS = ("book", "album", "playlist")

    def associate(self, uid_tag: str, kind: str, item_id: int, *,
                  resume: bool = True, shuffle: bool = False, loop: bool = False) -> None:
        """Associe (ou réassocie) un tag. Changer de contenu efface
        l'avancement du tag : il repartira du début du nouveau contenu."""
        conn = get_connection()
        previous = conn.execute(
            "SELECT kind, item_id FROM tag_associations WHERE uid_tag = ?", (uid_tag,)
        ).fetchone()
        conn.execute(
            "INSERT INTO tag_associations (uid_tag, kind, item_id, resume, shuffle, loop) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(uid_tag) DO UPDATE SET kind = excluded.kind, item_id = excluded.item_id, "
            "resume = excluded.resume, shuffle = excluded.shuffle, loop = excluded.loop",
            (uid_tag, kind, item_id, int(resume), int(shuffle), int(loop)),
        )
        if previous is None or (previous["kind"], previous["item_id"]) != (kind, item_id):
            conn.execute("DELETE FROM tag_progress WHERE uid_tag = ?", (uid_tag,))
        conn.commit()
        conn.close()

    def set_options(self, uid_tag: str, *, resume: bool, shuffle: bool, loop: bool) -> None:
        conn = get_connection()
        old = conn.execute("SELECT shuffle FROM tag_associations WHERE uid_tag = ?", (uid_tag,)).fetchone()
        conn.execute(
            "UPDATE tag_associations SET resume = ?, shuffle = ?, loop = ? WHERE uid_tag = ?",
            (int(resume), int(shuffle), int(loop), uid_tag),
        )
        if old is not None and bool(old["shuffle"]) != shuffle:
            # L'ordre enregistré ne correspond plus : on repart du début.
            conn.execute("DELETE FROM tag_progress WHERE uid_tag = ?", (uid_tag,))
        conn.commit()
        conn.close()

    def dissociate(self, uid_tag: str) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM tag_associations WHERE uid_tag = ?", (uid_tag,))
        conn.execute("DELETE FROM tag_progress WHERE uid_tag = ?", (uid_tag,))
        conn.commit()
        conn.close()

    # ---- Avancement par tag (v0.11) ----------------------------------------

    def get_progress(self, uid_tag: str):
        conn = get_connection()
        row = conn.execute("SELECT * FROM tag_progress WHERE uid_tag = ?", (uid_tag,)).fetchone()
        conn.close()
        return row

    def save_progress(self, uid_tag: str, queue_json: str, queue_index: int, position_ms: int) -> None:
        conn = get_connection()
        conn.execute(
            "INSERT INTO tag_progress (uid_tag, queue, queue_index, position_ms, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now', 'localtime')) "
            "ON CONFLICT(uid_tag) DO UPDATE SET queue = excluded.queue, "
            "queue_index = excluded.queue_index, position_ms = excluded.position_ms, "
            "updated_at = excluded.updated_at",
            (uid_tag, queue_json, int(queue_index), max(0, int(position_ms))),
        )
        conn.commit()
        conn.close()

    def clear_progress(self, uid_tag: str) -> None:
        conn = get_connection()
        conn.execute("DELETE FROM tag_progress WHERE uid_tag = ?", (uid_tag,))
        conn.commit()
        conn.close()

    def get(self, uid_tag: str):
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM tag_associations WHERE uid_tag = ?", (uid_tag,)
        ).fetchone()
        conn.close()
        return row

    def list_all(self):
        """Toutes les associations. À l'appelant (routes.py) d'aller
        chercher titre/jaquette dans la bonne table selon "kind", comme
        il le fait déjà pour les listes de lecture (voir
        PlaylistManager.get_items())."""
        conn = get_connection()
        rows = conn.execute("SELECT * FROM tag_associations ORDER BY rowid ASC").fetchall()
        conn.close()
        return rows

    def has_tag(self, kind: str, item_id: int) -> bool:
        """Utilisé par les bibliothèques (livres/albums) pour savoir si un
        élément a déjà un tag associé, sans avoir besoin de son UID —
        voir _book_to_dict()/_album_to_dict() dans app/web/routes.py."""
        conn = get_connection()
        row = conn.execute(
            "SELECT 1 FROM tag_associations WHERE kind = ? AND item_id = ? LIMIT 1",
            (kind, item_id),
        ).fetchone()
        conn.close()
        return row is not None

    def dissociate_item(self, kind: str, item_id: int) -> None:
        """Retire TOUS les tags qui pointent vers cet élément (en pratique
        il n'y en a jamais qu'un, mais rien n'empêche un parent d'avoir
        associé deux tags de secours au même livre/album)."""
        conn = get_connection()
        conn.execute(
            "DELETE FROM tag_progress WHERE uid_tag IN "
            "(SELECT uid_tag FROM tag_associations WHERE kind = ? AND item_id = ?)", (kind, item_id)
        )
        conn.execute(
            "DELETE FROM tag_associations WHERE kind = ? AND item_id = ?", (kind, item_id)
        )
        conn.commit()
        conn.close()

    # ---- Noms de tags (v0.10) ------------------------------------------------
    # Un nom facultatif par tag (« Loup bleu »), rangé dans la table tags. Il
    # suit le tag : dissocier un tag ou le réassocier ne l'efface pas.

    MAX_NAME_LENGTH = 40

    def get_name(self, uid_tag: str) -> str:
        conn = get_connection()
        row = conn.execute("SELECT name FROM tags WHERE uid_tag = ?", (uid_tag,)).fetchone()
        conn.close()
        return row["name"] if row else ""

    def set_name(self, uid_tag: str, name: str) -> None:
        """Enregistre le nom du tag ; un nom vide le retire."""
        name = " ".join((name or "").split())[: self.MAX_NAME_LENGTH]
        conn = get_connection()
        if name:
            conn.execute(
                "INSERT INTO tags (uid_tag, name) VALUES (?, ?) "
                "ON CONFLICT(uid_tag) DO UPDATE SET name = excluded.name",
                (uid_tag, name),
            )
        else:
            conn.execute("DELETE FROM tags WHERE uid_tag = ?", (uid_tag,))
        conn.commit()
        conn.close()

    def names(self) -> dict:
        conn = get_connection()
        rows = conn.execute("SELECT uid_tag, name FROM tags").fetchall()
        conn.close()
        return {row["uid_tag"]: row["name"] for row in rows}

    def item_tags(self, kind: str) -> dict:
        """{identifiant du livre ou de l'album: nom du tag associé, ou ""}
        pour tous les éléments de ce genre qui ont un tag. Une seule requête
        pour toute une page de bibliothèque."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT a.item_id, COALESCE(t.name, '') AS name FROM tag_associations a "
            "LEFT JOIN tags t ON t.uid_tag = a.uid_tag WHERE a.kind = ? ORDER BY a.rowid ASC",
            (kind,),
        ).fetchall()
        conn.close()
        result = {}
        for row in rows:
            # Deux tags sur le même élément : on garde le premier qui a un nom.
            if not result.get(row["item_id"]):
                result[row["item_id"]] = row["name"]
        return result
