"""
Ce que joue un tag, et où il en est (v0.11).

Un tag pointe vers une histoire, un album ou une liste de lecture (voir
app/tags.py). Quand on le pose, ce module construit la file de lecture
correspondante et la confie au lecteur (PlayerController.play_queue()),
au bon endroit :

- reprise activée (par défaut) : à l'élément et à la seconde où ce tag
  s'était arrêté, avec quelques secondes de recul pour une histoire ;
- reprise désactivée, ou après une double pose : depuis le début.

L'avancement est rangé PAR TAG (table tag_progress), pas par livre : deux
tags peuvent lancer la même histoire sans se gêner. Il est enregistré
chaque seconde pendant la lecture et au retrait du tag, et effacé quand
le contenu arrive à son terme (la pose suivante repart du début).

Ce module ne sait rien du lecteur NFC ni du geste (voir
app/tag_gesture.py et app/nfc_controller.py).
"""

import json
import random
from typing import Optional

from app.database import get_connection
from app.player import player_controller
from app.tags import TagManager

# Recul à la reprise d'une histoire, pour retrouver le fil.
RESUME_REWIND_MS = 3000

CONTEXT_PREFIX = "tag:"

_tags = TagManager()


def context_for(uid: str) -> str:
    return f"{CONTEXT_PREFIX}{uid}"


def uid_from_context(context: Optional[str]) -> Optional[str]:
    if context and context.startswith(CONTEXT_PREFIX):
        return context[len(CONTEXT_PREFIX):]
    return None


def build_queue(kind: str, item_id: int) -> list:
    """File (kind, item_id) d'un contenu, dans son ordre naturel."""
    conn = get_connection()
    try:
        if kind == "book":
            row = conn.execute("SELECT id FROM books WHERE id = ?", (item_id,)).fetchone()
            return [("book", row["id"])] if row else []
        if kind == "album":
            rows = conn.execute(
                "SELECT id FROM tracks WHERE album_id = ? ORDER BY order_index ASC, id ASC", (item_id,)
            ).fetchall()
            return [("track", row["id"]) for row in rows]
        if kind == "playlist":
            rows = conn.execute(
                "SELECT p.kind, p.item_id FROM playlist_items p "
                "LEFT JOIN books b ON p.kind = 'book' AND b.id = p.item_id "
                "LEFT JOIN tracks t ON p.kind = 'track' AND t.id = p.item_id "
                "WHERE p.playlist_id = ? AND (b.id IS NOT NULL OR t.id IS NOT NULL) "
                "ORDER BY p.order_index ASC, p.id ASC",
                (item_id,),
            ).fetchall()
            return [(row["kind"], row["item_id"]) for row in rows]
        return []
    finally:
        conn.close()


def _saved_place(progress, queue: list, shuffle: bool):
    """(file, index, position) à reprendre d'après l'avancement enregistré,
    ou None si on ne peut pas le réutiliser (contenu modifié entre-temps)."""
    try:
        saved = [(kind, int(item_id)) for kind, item_id in json.loads(progress["queue"])]
    except (ValueError, TypeError):
        return None
    index = int(progress["queue_index"])
    if not saved or not 0 <= index < len(saved):
        return None
    if sorted(saved) == sorted(queue):
        # Même contenu : on garde l'ordre enregistré (mélange compris).
        return saved, index, int(progress["position_ms"])
    if not shuffle and saved[index] in queue:
        # Contenu modifié (morceau ajouté, retiré…) : on retrouve l'élément
        # en cours dans la nouvelle file.
        return queue, queue.index(saved[index]), int(progress["position_ms"])
    return None


def start(uid: str, association, *, from_start: bool = False) -> bool:
    """Lance le contenu du tag. False si ce contenu n'existe plus (vide,
    supprimé). « from_start » : double pose, l'avancement est effacé."""
    queue = build_queue(association["kind"], association["item_id"])
    if not queue:
        return False
    resume = bool(association["resume"])
    shuffle = bool(association["shuffle"])
    loop = bool(association["loop"])
    context = context_for(uid)

    if from_start or not resume:
        _tags.clear_progress(uid)
    elif player_controller.current_context() == context:
        # Le tag revient alors que son contenu est encore chargé (en pause) :
        # reprise immédiate, sans recharger.
        snapshot = player_controller.snapshot()
        rewind = RESUME_REWIND_MS if snapshot and snapshot["kind"] == "book" else 0
        return player_controller.resume_with_rewind(rewind)

    index, position = 0, 0
    progress = None if (from_start or not resume) else _tags.get_progress(uid)
    place = _saved_place(progress, queue, shuffle) if progress is not None else None
    if place is not None:
        queue, index, position = place
        if queue[index][0] == "book":
            position = max(0, position - RESUME_REWIND_MS)
    elif shuffle:
        random.shuffle(queue)

    return player_controller.play_queue(
        queue, index, position, loop=loop, shuffle=shuffle, context=context
    )


def pause(uid: str) -> None:
    """Tag retiré : pause en douceur et avancement enregistré tout de suite."""
    if player_controller.current_context() != context_for(uid):
        return
    player_controller.fade_pause()
    save_now()


def save_now() -> None:
    _save(player_controller.snapshot())


def _save(snapshot: Optional[dict]) -> None:
    if not snapshot:
        return
    uid = uid_from_context(snapshot.get("context"))
    if uid is None or not snapshot["queue"]:
        return
    _tags.save_progress(uid, json.dumps(snapshot["queue"]), snapshot["index"], snapshot["position_ms"])


def _on_queue_end(context: Optional[str]) -> None:
    uid = uid_from_context(context)
    if uid is not None:
        _tags.clear_progress(uid)


def describe_progress(uid: str, association) -> Optional[dict]:
    """Pour l'administration : {"index": 2, "total": 6, "position_ms": …}
    ou None si le tag repartira du début."""
    progress = _tags.get_progress(uid)
    if progress is None:
        return None
    try:
        total = len(json.loads(progress["queue"]))
    except ValueError:
        return None
    return {
        "index": int(progress["queue_index"]) + 1,
        "total": total,
        "position_ms": int(progress["position_ms"]),
        "updated_at": progress["updated_at"],
    }


player_controller.progress_listeners.append(_save)
player_controller.queue_end_listeners.append(_on_queue_end)
