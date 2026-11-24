"""
Gestion des listes de lecture (playlists) : créer/renommer/supprimer une
liste, y ajouter ou retirer des livres/morceaux, réordonner, et régler la
lecture en boucle et/ou aléatoire.

Une liste de lecture peut mélanger librement des livres et des morceaux
de musique — chaque élément (playlist_items) porte son propre "kind"
("book" ou "track"), exactement la même convention que le lecteur central
utilise déjà pour un élément unique (voir app/player.py).

Ce module ne touche jamais à la lecture elle-même (ça reste le rôle de
PlayerController, seul à parler à VLC) — uniquement au contenu des listes
stockées en base. Voir PlayerController.play_playlist() pour le
démarrage effectif d'une liste.
"""

from app.database import get_connection


class PlaylistManager:
    def create(self, name: str, emoji: str = "📻", color_hex: str = "#8FB6FF") -> int:
        conn = get_connection()
        cur = conn.execute(
            "INSERT INTO playlists (name, emoji, color_hex) VALUES (?, ?, ?)",
            (name, emoji, color_hex),
        )
        conn.commit()
        playlist_id = cur.lastrowid
        conn.close()
        return playlist_id

    def rename(self, playlist_id: int, name: str) -> None:
        conn = get_connection()
        conn.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id))
        conn.commit()
        conn.close()

    def delete(self, playlist_id: int) -> None:
        conn = get_connection()
        # ON DELETE CASCADE (PRAGMA foreign_keys activé dans get_connection)
        # supprime automatiquement les playlist_items associés.
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        conn.commit()
        conn.close()

    def set_modes(self, playlist_id: int, shuffle: bool, loop: bool) -> None:
        conn = get_connection()
        conn.execute(
            "UPDATE playlists SET shuffle = ?, loop = ? WHERE id = ?",
            (int(shuffle), int(loop), playlist_id),
        )
        conn.commit()
        conn.close()

    def list_all(self):
        conn = get_connection()
        rows = conn.execute(
            "SELECT *, "
            "(SELECT COUNT(*) FROM playlist_items WHERE playlist_id = playlists.id) AS item_count "
            "FROM playlists ORDER BY name ASC"
        ).fetchall()
        conn.close()
        return rows

    def get(self, playlist_id: int):
        conn = get_connection()
        row = conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        conn.close()
        return row

    def get_items(self, playlist_id: int):
        """Éléments de la liste, dans l'ordre. Chaque ligne garde juste
        (kind, item_id) — c'est à l'appelant (routes.py) d'aller chercher
        le titre/la jaquette/etc. dans la bonne table selon kind."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY order_index ASC",
            (playlist_id,),
        ).fetchall()
        conn.close()
        return rows

    def add_item(self, playlist_id: int, kind: str, item_id: int) -> None:
        conn = get_connection()
        next_index = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) + 1 FROM playlist_items WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO playlist_items (playlist_id, kind, item_id, order_index) VALUES (?, ?, ?, ?)",
            (playlist_id, kind, item_id, next_index),
        )
        conn.commit()
        conn.close()

    def remove_item(self, entry_id: int) -> None:
        """entry_id = playlist_items.id (pas l'id du livre/morceau lui-même)."""
        conn = get_connection()
        conn.execute("DELETE FROM playlist_items WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()

    def move_item(self, entry_id: int, direction: str) -> None:
        """Échange la position de cet élément avec son voisin immédiat.
        direction : "up" (monte dans la liste) ou "down" (descend)."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM playlist_items WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            conn.close()
            return

        if direction == "up":
            neighbor = conn.execute(
                "SELECT * FROM playlist_items WHERE playlist_id = ? AND order_index < ? "
                "ORDER BY order_index DESC LIMIT 1",
                (row["playlist_id"], row["order_index"]),
            ).fetchone()
        else:
            neighbor = conn.execute(
                "SELECT * FROM playlist_items WHERE playlist_id = ? AND order_index > ? "
                "ORDER BY order_index ASC LIMIT 1",
                (row["playlist_id"], row["order_index"]),
            ).fetchone()

        if neighbor is not None:
            conn.execute(
                "UPDATE playlist_items SET order_index = ? WHERE id = ?",
                (neighbor["order_index"], row["id"]),
            )
            conn.execute(
                "UPDATE playlist_items SET order_index = ? WHERE id = ?",
                (row["order_index"], neighbor["id"]),
            )
            conn.commit()
        conn.close()
