"""Parcours complet, avec le vrai lecteur VLC (sortie son factice) et un
lecteur NFC simulé : poser, retirer, reposer vite, album qui enchaîne,
mode transfert, et les pages de l'administration.

Nécessite VLC (libvlc) et ffmpeg pour fabriquer de courts fichiers audio.
Dure une quarantaine de secondes (la lecture est réelle).

    python -m pytest tests/
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

BASE = Path(os.environ["CONTAR_BASE_DIR"])   # voir conftest.py

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


def _tone(path: Path, seconds: float, freq: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
         "-metadata", f"title={path.stem}", "-c:a", "libmp3lame", "-b:a", "32k", str(path)],
        check=True,
    )


@pytest.fixture(scope="module")
def box():
    _tone(BASE / "Bibliotheque/Livres/Le loup.mp3", 40, 440)
    _tone(BASE / "Bibliotheque/Musiques/Comptines/01 Une.mp3", 4, 523)
    _tone(BASE / "Bibliotheque/Musiques/Comptines/02 Deux.mp3", 4, 659)

    from app.web import create_app
    app = create_app()
    from app.library_scan import scan_books, scan_music
    scan_books()
    scan_music()

    from app import nfc_controller
    from app.tag_reader import make_reader
    reader = make_reader(on_box=False)
    nfc_controller.start(reader)

    from app.database import get_connection
    conn = get_connection()
    book_id = conn.execute("SELECT id FROM books").fetchone()["id"]
    album_id = conn.execute("SELECT id FROM albums WHERE name = 'Comptines'").fetchone()["id"]
    conn.close()

    from app.tags import TagManager
    tags = TagManager()
    tags.associate("AAAA", "book", book_id)
    tags.associate("BBBB", "album", album_id)

    from app.settings import SettingsManager
    SettingsManager().set_tag_gesture(True, 2.0)

    yield {"app": app, "reader": reader, "tags": tags, "book_id": book_id, "album_id": album_id}

    from app.player import player_controller
    player_controller.stop()


def _state():
    from app.player import player_controller
    return player_controller.get_state()


def _wait(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_poser_lance_retirer_met_en_pause(box):
    reader, tags = box["reader"], box["tags"]
    reader.present("AAAA")
    assert _wait(lambda: _state()["is_playing"])
    assert _state()["context"] == "tag:AAAA"
    time.sleep(5)
    reader.absent()
    assert _wait(lambda: not _state()["is_playing"])
    progress = tags.get_progress("AAAA")
    assert progress is not None
    assert 3500 <= progress["position_ms"] <= 7000


def test_reposer_apres_la_fenetre_reprend_avec_recul(box):
    reader, tags = box["reader"], box["tags"]
    saved = tags.get_progress("AAAA")["position_ms"]
    time.sleep(2.5)                     # fenêtre réglée à 2 s
    reader.present("AAAA")
    assert _wait(lambda: _state()["is_playing"])
    time.sleep(0.3)
    position = _state()["position_ms"]
    assert saved - 3000 - 500 <= position <= saved, (saved, position)


def test_reposer_vite_repart_du_debut(box):
    reader, tags = box["reader"], box["tags"]
    time.sleep(2)
    reader.absent()
    assert _wait(lambda: not _state()["is_playing"])
    time.sleep(0.5)
    reader.present("AAAA")
    assert _wait(lambda: _state()["is_playing"])
    time.sleep(0.3)
    assert _state()["position_ms"] < 2000
    reader.absent()
    assert _wait(lambda: not _state()["is_playing"])


def test_album_enchaine_et_garde_sa_place(box):
    reader, tags = box["reader"], box["tags"]
    time.sleep(2.5)
    reader.present("BBBB")
    assert _wait(lambda: _state()["is_playing"])
    assert _state()["queue_length"] == 2
    assert _wait(lambda: _state()["queue_index"] == 1, timeout=10)
    reader.absent()
    assert _wait(lambda: not _state()["is_playing"])
    assert tags.get_progress("BBBB")["queue_index"] == 1
    # L'histoire du tag A a gardé son propre avancement.
    assert tags.get_progress("AAAA") is not None


def test_fin_du_contenu_efface_l_avancement(box):
    reader, tags = box["reader"], box["tags"]
    time.sleep(2.5)
    reader.present("BBBB")
    assert _wait(lambda: _state()["is_playing"])
    assert _wait(lambda: _state()["kind"] is None, timeout=10)
    assert tags.get_progress("BBBB") is None
    reader.absent()


def test_tag_inconnu_ne_lance_rien(box):
    reader = box["reader"]
    reader.present("CCCC")
    time.sleep(0.5)
    assert not _state()["is_playing"]
    reader.absent()


def test_mode_transfert_ignore_les_tags(box, monkeypatch):
    from app import usb_gadget
    monkeypatch.setattr(usb_gadget, "_transfer", True)
    reader = box["reader"]
    time.sleep(2.5)
    reader.present("AAAA")
    time.sleep(0.5)
    assert not _state()["is_playing"]
    reader.absent()


def test_pages_de_l_administration(box):
    client = box["app"].test_client()
    response = client.post("/login", data={"pin": "1234"})
    assert response.status_code in (200, 302)
    for url in ("/", "/reglages/tags", "/import", "/reglages/energie", "/reglages",
                "/reglages/mise-a-jour", "/reglages/aide", "/livres", "/musique", "/listes"):
        page = client.get(url)
        assert page.status_code == 200, url
    assert b"Loup" in client.get("/reglages/tags").data or "Le loup" in client.get("/reglages/tags").get_data(as_text=True)
    assert client.get("/import/usb").get_json()["connected"] is False

    # Associer un tag à une liste de lecture, avec ses options.
    from app.playlist import PlaylistManager
    playlists = PlaylistManager()
    playlist_id = playlists.create("Soir") if hasattr(playlists, "create") else None
    if playlist_id:
        client.post("/reglages/tags/associer", data={
            "uid_tag": "DDDD", "target": f"playlist:{playlist_id}", "options": "1", "shuffle": "on", "loop": "on"})
        association = box["tags"].get("DDDD")
        assert association["kind"] == "playlist"
        assert association["shuffle"] == 1 and association["loop"] == 1 and association["resume"] == 0

    client.post("/reglages/energie", data={"standby_minutes": "2", "shutdown_minutes": "30", "eco_mode": "on"})
    from app.settings import SettingsManager
    assert SettingsManager().get_idle_shutdown_minutes() == 30

    client.post("/reglages/tags/zero", data={"uid_tag": "AAAA"})
    assert box["tags"].get_progress("AAAA") is None

    response = client.post("/api/dev/tag", json={"uid": "AAAA"})
    assert response.get_json()["present"] == "AAAA"
    client.post("/api/dev/tag", json={"uid": None})


def test_depot_range_les_fichiers(box, tmp_path):
    from app import depot_import
    _tone(tmp_path / "Histoires/Nouvelle.mp3", 2, 300)
    _tone(tmp_path / "Musiques/Rondes/Ronde.mp3", 2, 350)
    _tone(tmp_path / "Racine.mp3", 2, 380)
    (tmp_path / "Histoires/_LISEZ-MOI.txt").write_text("x")
    result = depot_import.import_from(tmp_path)
    assert result["status"] == "ok" and result["added"] == 3
    assert (BASE / "Bibliotheque/Livres/Nouvelle.mp3").exists()
    assert (BASE / "Bibliotheque/Musiques/Rondes/Ronde.mp3").exists()
    again = depot_import.import_from(tmp_path)
    assert again["added"] == 0 and again["present"] == 3
    from app.database import get_connection
    conn = get_connection()
    assert conn.execute("SELECT COUNT(*) FROM albums WHERE name = 'Rondes'").fetchone()[0] == 1
    conn.close()
