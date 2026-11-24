"""
Routes de l'interface web.

Découpage volontaire de cette étape :
- PIN + session, page "lecture en cours" et son API : complets
- Bibliothèque livres/musique + upload de fichiers : complets
- Fiches détaillées (livre/morceau) avant lecture, jaquettes réelles : complets
- Réglages (PIN, minuterie, plages horaires, catégories) : page "à venir"
  pour l'instant, déjà dans la navigation et déjà protégée par le PIN.
"""

from pathlib import Path
from typing import Optional

from flask import (
    Blueprint, flash, get_flashed_messages, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from werkzeug.utils import secure_filename

from app import audio_output
from app.config import AUDIO_EXTENSIONS, BOOKS_DIR, COVERS_DIR, MUSIC_DIR
from app.controls import mapping
from app.database import get_connection
from app.factory_reset import perform_factory_reset
from app.i18n import LANGUAGE_LABELS, tr, tr_message
from app.library_scan import scan_books, scan_music
from app import network_apply
from app.network_apply import forget_wifi_network
from app.network_status import get_wifi_status, scan_wifi_networks
from app import wifi_fallback
from app import nfc_controller
from app import usb_import
from app import library_delete
from app.pin import PinManager
from app.player import player_controller
from app.playlist import PlaylistManager
from app import power_settings
from app.settings import DaySchedule, SettingsManager
from app.storage_status import get_storage_status
from app.system_control import reboot_now, shutdown_now
from app.tags import TagManager

main_bp = Blueprint("main", __name__)

# Tous les messages affichés après une action passent par la traduction
# (voir app/i18n.py) : un message connu s'affiche dans la langue choisie,
# un message inconnu (détail technique renvoyé par le système, par
# exemple) s'affiche tel quel, en français.
_flask_flash = flash


def flash(message):  # noqa: F811 — remplace volontairement flask.flash dans ce module
    _flask_flash(tr_message(message))

pin_manager = PinManager()
settings_manager = SettingsManager()
playlist_manager = PlaylistManager()
tag_manager = TagManager()

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


# ---- Authentification -------------------------------------------------------------

@main_bp.before_request
def require_login():
    if request.endpoint == "main.login":
        return None
    if not session.get("authenticated"):
        return redirect(url_for("main.login"))


# Endpoints accessibles même quand l'assistant de bienvenue est en attente
# (voir require_onboarding ci-dessous) — l'assistant lui-même, bien sûr,
# plus déconnexion (pour ne jamais enfermer quelqu'un dans l'assistant).
_ONBOARDING_EXEMPT_ENDPOINTS = {
    "main.login", "main.logout", "main.force_logout",
    "main.onboarding_pin", "main.onboarding_wifi", "main.onboarding_wifi_skip",
    "main.onboarding_tutoriel", "main.onboarding_finish",
    "main.network_trial_state",
    # Étape « Tags maîtres » de l'assistant (v0.10) et la capture d'un tag.
    "main.onboarding_tags", "main.set_master_tag", "main.clear_master_tag",
    "main.start_tag_capture", "main.cancel_tag_capture", "main.tag_capture_state",
}


@main_bp.before_request
def require_onboarding():
    """Après une réinitialisation usine (app/factory_reset.py), impossible
    d'utiliser l'appli tant que l'assistant de bienvenue (création du PIN,
    Wifi, diapos) n'a pas été mené à son terme — voir
    SettingsManager.is_onboarding_pending()."""
    if request.endpoint in _ONBOARDING_EXEMPT_ENDPOINTS:
        return None
    if not session.get("authenticated"):
        return None  # laissé à require_login ci-dessus, qui redirige déjà vers la connexion
    if settings_manager.is_onboarding_pending():
        return redirect(url_for("main.onboarding_pin"))


# Pendant un import par clé USB (app/usb_import.py), la bibliothèque est en
# train d'être recomposée : un fichier envoyé ou supprimé à ce moment-là
# pourrait se perdre dans la bascule. Ces quatre actions attendent la fin.
_BLOCKED_DURING_IMPORT = {
    "main.upload_books", "main.upload_music",
    "main.delete_book_route", "main.delete_album_route",
}


@main_bp.before_request
def wait_for_import():
    if request.endpoint in _BLOCKED_DURING_IMPORT and session.get("authenticated") and usb_import.is_busy():
        flash("Un import par clé USB est en cours : réessayez dans un instant.")
        return redirect(url_for("main.import_page"))


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin_manager.verify_pin(pin):
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("main.now_playing"))
        error = "Code incorrect, réessayez."

    return render_template(
        "login.html",
        error=error,
        pin_not_configured=not pin_manager.is_pin_configured(),
    )


@main_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ---- Assistant de bienvenue (après une réinitialisation usine) -------------
# Quatre étapes (voir require_onboarding ci-dessus, qui empêche tout accès
# au reste de l'appli tant qu'elles n'ont pas été menées à leur terme) :
# créer un vrai code PIN (l'ancien a été effacé), proposer de se connecter
# au Wifi de la maison, proposer de déclarer les deux tags maîtres de
# l'import par clé USB (v0.10) — ces deux étapes peuvent être passées —,
# puis quelques diapos expliquant le fonctionnement.

ONBOARDING_STEPS = 4

ONBOARDING_SLIDES = [
    {
        "icon": "import",
        "title": "Ajoutez des histoires et de la musique",
        "text": "Par clé USB : rangez vos fichiers audio (mp3, m4a, m4b) dans un dossier "
                "« Audiolibre », avec « Livres » et « Musiques », branchez la clé sur la boîte et "
                "posez le tag « Ajouter ». Ou ouvrez « Import » dans le menu, depuis un téléphone "
                "ou un ordinateur du même réseau, et envoyez-les.",
    },
    {
        "icon": "tag",
        "title": "Un tag pour chaque histoire",
        "text": "Dans la Bibliothèque, touchez « Sans tag » puis posez un tag sur la boîte : "
                "l'enfant n'aura plus qu'à poser ce tag pour lancer son histoire.",
    },
    {
        "icon": "list",
        "title": "Des listes de lecture",
        "text": "Mélangez livres et musiques dans une liste, avec lecture aléatoire ou en "
                "boucle si besoin : pratique pour un enchaînement du soir toujours différent.",
    },
    {
        "icon": "clock",
        "title": "Minuterie et plages horaires",
        "text": "Une minuterie de coucher met la lecture en pause après un temps donné. Des plages "
                "horaires, par jour de la semaine, peuvent aussi limiter quand la boîte accepte "
                "de jouer quoi que ce soit.",
    },
    {
        "icon": "gamepad",
        "title": "Boutons ou manette",
        "text": "Les actions (lecture ou pause, avance, recul, volume) se réassignent aux "
                "boutons de la boîte ou à une manette USB, depuis Réglages → Boutons et manette.",
    },
    {
        "icon": "lock",
        "title": "Le code PIN protège les réglages",
        "text": "Le code que vous venez de créer est demandé à chaque ouverture de la boîte : "
                "pensez à le garder pour vous, pas pour les enfants.",
    },
]


@main_bp.route("/bienvenue/pin", methods=["GET", "POST"])
def onboarding_pin():
    if not settings_manager.is_onboarding_pending():
        return redirect(url_for("main.now_playing"))
    error = None
    if request.method == "POST":
        new = request.form.get("new_pin", "")
        confirm = request.form.get("confirm_pin", "")
        if len(new) < 4:
            error = "Le code doit faire au moins 4 chiffres."
        elif new != confirm:
            error = "Les deux codes ne correspondent pas."
        else:
            pin_manager.set_pin(new)
            return redirect(url_for("main.onboarding_wifi"))
    return render_template("onboarding_pin.html", error=error)


@main_bp.route("/bienvenue/wifi", methods=["GET", "POST"])
def onboarding_wifi():
    if not settings_manager.is_onboarding_pending():
        return redirect(url_for("main.now_playing"))
    if request.method == "POST":
        wifi_ssid = (request.form.get("wifi_ssid") or "").strip()
        wifi_password = request.form.get("wifi_password") or ""
        if wifi_ssid:
            network = settings_manager.get_network_config()
            return _start_wifi_trial(
                wifi_ssid, wifi_password,
                network["ip_mode"], network["static_ip"], network["static_netmask"],
                network["static_gateway"], network["static_dns"],
                back_endpoint="main.onboarding_wifi", next_endpoint="main.onboarding_tags",
            )
        return redirect(url_for("main.onboarding_tags"))
    return render_template(
        "onboarding_wifi.html",
        wifi_networks=scan_wifi_networks(),
        network=settings_manager.get_network_config(),
        trial=_recent_trial(),
    )


@main_bp.route("/bienvenue/wifi/passer", methods=["POST"])
def onboarding_wifi_skip():
    if not settings_manager.is_onboarding_pending():
        return redirect(url_for("main.now_playing"))
    return redirect(url_for("main.onboarding_tags"))


@main_bp.route("/bienvenue/tags")
def onboarding_tags():
    """Étape 3 : déclarer les deux tags maîtres de l'import par clé USB.
    Facultative — on peut continuer sans, et le faire plus tard dans Tags."""
    if not settings_manager.is_onboarding_pending():
        return redirect(url_for("main.now_playing"))
    return render_template("onboarding_tags.html", master_tags=settings_manager.get_master_tags())


@main_bp.route("/bienvenue/tutoriel")
def onboarding_tutoriel():
    if not settings_manager.is_onboarding_pending():
        return redirect(url_for("main.now_playing"))
    diapo = request.args.get("diapo", 1, type=int)
    diapo = max(1, min(diapo, len(ONBOARDING_SLIDES)))
    return render_template(
        "onboarding_tutoriel.html",
        slide=ONBOARDING_SLIDES[diapo - 1],
        diapo=diapo,
        total=len(ONBOARDING_SLIDES),
        is_last=diapo == len(ONBOARDING_SLIDES),
    )


@main_bp.route("/bienvenue/terminer", methods=["POST"])
def onboarding_finish():
    settings_manager.set_onboarding_pending(False)
    flash("Configuration terminée, bon amusement !")
    return redirect(url_for("main.now_playing"))


# ---- Jaquettes -------------------------------------------------------------

@main_bp.route("/covers/<path:filename>")
def cover_image(filename):
    """
    Sert les vignettes extraites des fichiers audio (voir app/audio_meta.py),
    stockées dans data/covers/, en dehors du dossier static/ habituel.
    """
    return send_from_directory(COVERS_DIR, filename)


def _cover_filename(cover_path):
    return Path(cover_path).name if cover_path else None


def _cover_url(cover_path):
    filename = _cover_filename(cover_path)
    return url_for("main.cover_image", filename=filename) if filename else None


# ---- Formatage -------------------------------------------------------------

def _format_duration(ms: int) -> str:
    total_seconds = max(0, int((ms or 0) / 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


# ---- Conversion des lignes SQLite en dictionnaires enrichis (pour les templates) ----

def _book_to_dict(row, tagged: Optional[dict] = None) -> dict:
    """tagged : résultat de tag_manager.item_tags("book"), à fournir quand
    on prépare toute une liste (une seule requête au lieu d'une par livre)."""
    if tagged is None:
        tagged = tag_manager.item_tags("book")
    d = dict(row)
    d["cover_filename"] = _cover_filename(row["cover_path"])
    d["cover_url"] = _cover_url(row["cover_path"])
    d["duration_label"] = _format_duration(row["duration_ms"])
    d["progress_label"] = f"{_format_duration(row['position_ms'])} / {_format_duration(row['duration_ms'])}"
    d["has_tag"] = row["id"] in tagged
    d["tag_name"] = tagged.get(row["id"], "")
    return d


def _track_to_dict(row, album_row=None) -> dict:
    d = dict(row)
    d["cover_filename"] = _cover_filename(row["cover_path"])
    d["cover_url"] = _cover_url(row["cover_path"])
    d["duration_label"] = _format_duration(row["duration_ms"])
    d["progress_label"] = f"{_format_duration(row['position_ms'])} / {_format_duration(row['duration_ms'])}"
    if album_row is not None:
        d["album_emoji"] = album_row["emoji"]
        d["album_color_hex"] = album_row["color_hex"]
    return d


def _album_to_dict(row, tagged: Optional[dict] = None) -> dict:
    if tagged is None:
        tagged = tag_manager.item_tags("album")
    d = dict(row)
    d["cover_filename"] = _cover_filename(row["cover_path"])
    d["cover_url"] = _cover_url(row["cover_path"])
    d["has_tag"] = row["id"] in tagged
    d["tag_name"] = tagged.get(row["id"], "")
    return d


# Filtre « Sans tag » de la bibliothèque (v0.10) : /livres?filtre=sans-tag.
# Une histoire arrivée par clé USB ou par envoi n'a pas encore de tag ; ce
# filtre les regroupe pour les associer une par une.
_UNTAGGED = "sans-tag"


# ---- Pages -------------------------------------------------------------

@main_bp.route("/")
def now_playing():
    return render_template("now_playing.html", active="lecture")


@main_bp.route("/livres")
def livres():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM books ORDER BY title ASC").fetchall()
    conn.close()
    tagged = tag_manager.item_tags("book")
    books = [_book_to_dict(row, tagged) for row in rows]
    untagged = [book for book in books if not book["has_tag"]]
    only_untagged = request.args.get("filtre") == _UNTAGGED
    return render_template(
        "library_books.html", active="livres",
        books=untagged if only_untagged else books,
        total_count=len(books), untagged_count=len(untagged), only_untagged=only_untagged,
    )


@main_bp.route("/livres/upload", methods=["POST"])
def upload_books():
    saved = _save_uploaded_files(request.files.getlist("files"), BOOKS_DIR)
    if saved:
        scan_books()
    return redirect(url_for("main.livres"))


@main_bp.route("/livres/<int:book_id>")
def book_detail(book_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    categories = conn.execute("SELECT * FROM categories ORDER BY name ASC").fetchall()
    conn.close()
    if row is None:
        return redirect(url_for("main.livres"))
    return render_template(
        "book_detail.html", active="livres", book=_book_to_dict(row), categories=categories
    )


@main_bp.route("/reglages/tags/dissocier-item", methods=["POST"])
def dissociate_tag_item():
    """
    Retrait rapide du tag NFC d'un livre ou d'un album, déclenché depuis
    la bibliothèque (liste ou fiche détail) plutôt que depuis Réglages →
    Tags NFC — remplace l'ancien bouton "Visible/Masqué pour l'enfant"
    (retiré : n'avait plus lieu d'être, tout est désormais géré par tag,
    voir discussion du projet — sans tag associé, pas de lecture possible
    pour l'enfant de toute façon).
    """
    kind = request.form.get("kind")
    raw_id = request.form.get("item_id") or ""
    if kind in ("book", "album") and raw_id.isdigit():
        tag_manager.dissociate_item(kind, int(raw_id))
        flash("Tag NFC retiré.")
    # Revient à la page d'où l'action a été déclenchée (liste ou fiche détail).
    return redirect(request.referrer or url_for("main.reglages"))


@main_bp.route("/livres/<int:book_id>/play", methods=["POST"])
def play_book(book_id: int):
    player_controller.play("book", book_id)
    return redirect(url_for("main.now_playing"))


@main_bp.route("/livres/<int:book_id>/supprimer", methods=["POST"])
def delete_book_route(book_id: int):
    ok, message = library_delete.delete_book(book_id)
    flash(message)
    # Toujours vers la liste : la fiche détail, si c'est de là que vient
    # la requête, n'existe plus une fois le livre supprimé.
    return redirect(url_for("main.livres"))


@main_bp.route("/musique")
def musique():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM albums ORDER BY name ASC").fetchall()
    conn.close()
    tagged = tag_manager.item_tags("album")
    albums = [_album_to_dict(row, tagged) for row in rows]
    untagged = [album for album in albums if not album["has_tag"]]
    only_untagged = request.args.get("filtre") == _UNTAGGED
    return render_template(
        "library_albums.html", active="musique",
        albums=untagged if only_untagged else albums,
        total_count=len(albums), untagged_count=len(untagged), only_untagged=only_untagged,
    )


@main_bp.route("/musique/upload", methods=["POST"])
def upload_music():
    folder_name = (request.form.get("folder_name") or "").strip()
    target_dir = _safe_album_dir(folder_name) if folder_name else MUSIC_DIR
    saved = _save_uploaded_files(request.files.getlist("files"), target_dir)
    if saved:
        scan_music()
    return redirect(url_for("main.musique"))


@main_bp.route("/musique/<int:album_id>")
def album_detail(album_id: int):
    conn = get_connection()
    album_row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if album_row is None:
        conn.close()
        return redirect(url_for("main.musique"))
    track_rows = conn.execute(
        "SELECT * FROM tracks WHERE album_id = ? ORDER BY order_index ASC", (album_id,)
    ).fetchall()
    conn.close()
    album = _album_to_dict(album_row)
    tracks = [_track_to_dict(row) for row in track_rows]
    return render_template("album_detail.html", active="musique", album=album, tracks=tracks)


@main_bp.route("/musique/track/<int:track_id>")
def track_detail(track_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if row is None:
        conn.close()
        return redirect(url_for("main.musique"))
    album_row = conn.execute("SELECT * FROM albums WHERE id = ?", (row["album_id"],)).fetchone()
    conn.close()
    return render_template(
        "track_detail.html", active="musique", track=_track_to_dict(row, album_row), album=album_row
    )


@main_bp.route("/musique/track/<int:track_id>/play", methods=["POST"])
def play_track(track_id: int):
    player_controller.play("track", track_id)
    return redirect(url_for("main.now_playing"))


@main_bp.route("/musique/<int:album_id>/supprimer", methods=["POST"])
def delete_album_route(album_id: int):
    ok, message = library_delete.delete_album(album_id)
    flash(message)
    return redirect(url_for("main.musique"))


# ---- Listes de lecture -------------------------------------------------
#
# Une liste peut mélanger librement des livres et des morceaux (voir
# app/playlist.py). Cette section ne fait que du CRUD + lancer la
# lecture — toute la logique de file d'attente (enchaînement automatique,
# boucle, aléatoire) vit dans PlayerController (app/player.py).

def _playlist_item_to_dict(entry_row) -> dict:
    """Enrichit une ligne playlist_items (juste kind + item_id) avec le
    titre/la jaquette/etc. de l'élément réel, selon sa table d'origine."""
    kind = entry_row["kind"]
    conn = get_connection()
    table = "books" if kind == "book" else "tracks"
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entry_row["item_id"],)).fetchone()
    conn.close()

    if row is None:
        # Le livre/morceau a disparu depuis (pas de suppression possible
        # actuellement dans l'appli, mais on reste défensif).
        return {
            "entry_id": entry_row["id"],
            "kind": kind,
            "item_id": entry_row["item_id"],
            "title": tr("(élément introuvable)"),
            "subtitle": "",
            "cover_url": None,
            "emoji": "❓",
            "color_hex": "#a9afda",
        }

    d = {
        "entry_id": entry_row["id"],
        "kind": kind,
        "item_id": entry_row["item_id"],
        "title": row["title"],
        "subtitle": row["author"] if kind == "book" else (row["artist"] or ""),
    }
    d.update(_visual_fields(kind, row))
    return d


@main_bp.route("/listes", methods=["GET", "POST"])
def playlists():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if name:
            playlist_id = playlist_manager.create(name)
            return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))
        return redirect(url_for("main.playlists"))

    rows = playlist_manager.list_all()
    return render_template("playlists.html", active="listes", playlists=[dict(r) for r in rows])


@main_bp.route("/listes/<int:playlist_id>")
def playlist_detail(playlist_id: int):
    playlist_row = playlist_manager.get(playlist_id)
    if playlist_row is None:
        return redirect(url_for("main.playlists"))

    entries = playlist_manager.get_items(playlist_id)
    items = [_playlist_item_to_dict(e) for e in entries]
    already_in_playlist = {(e["kind"], e["item_id"]) for e in entries}

    conn = get_connection()
    book_rows = conn.execute("SELECT * FROM books ORDER BY title ASC").fetchall()
    track_rows = conn.execute(
        "SELECT tracks.*, albums.name AS album_name FROM tracks "
        "JOIN albums ON albums.id = tracks.album_id "
        "ORDER BY albums.name ASC, tracks.order_index ASC"
    ).fetchall()
    conn.close()

    available_books = [
        _book_to_dict(r) for r in book_rows if ("book", r["id"]) not in already_in_playlist
    ]
    available_tracks = []
    for r in track_rows:
        if ("track", r["id"]) in already_in_playlist:
            continue
        d = _track_to_dict(r)
        d["album_name"] = r["album_name"]
        available_tracks.append(d)

    return render_template(
        "playlist_detail.html",
        active="listes",
        playlist=dict(playlist_row),
        items=items,
        available_books=available_books,
        available_tracks=available_tracks,
    )


@main_bp.route("/listes/<int:playlist_id>/renommer", methods=["POST"])
def rename_playlist(playlist_id: int):
    name = (request.form.get("name") or "").strip()
    if name:
        playlist_manager.rename(playlist_id, name)
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/supprimer", methods=["POST"])
def delete_playlist(playlist_id: int):
    playlist_manager.delete(playlist_id)
    flash("Liste de lecture supprimée.")
    return redirect(url_for("main.playlists"))


@main_bp.route("/listes/<int:playlist_id>/modes", methods=["POST"])
def set_playlist_modes(playlist_id: int):
    shuffle = request.form.get("shuffle") == "on"
    loop = request.form.get("loop") == "on"
    playlist_manager.set_modes(playlist_id, shuffle, loop)
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/ajouter", methods=["POST"])
def add_to_playlist(playlist_id: int):
    kind = request.form.get("kind")
    raw_item_id = request.form.get("item_id") or ""
    if kind in ("book", "track") and raw_item_id.isdigit():
        playlist_manager.add_item(playlist_id, kind, int(raw_item_id))
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/item/<int:entry_id>/retirer", methods=["POST"])
def remove_playlist_item(playlist_id: int, entry_id: int):
    playlist_manager.remove_item(entry_id)
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/item/<int:entry_id>/monter", methods=["POST"])
def move_playlist_item_up(playlist_id: int, entry_id: int):
    playlist_manager.move_item(entry_id, "up")
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/item/<int:entry_id>/descendre", methods=["POST"])
def move_playlist_item_down(playlist_id: int, entry_id: int):
    playlist_manager.move_item(entry_id, "down")
    return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))


@main_bp.route("/listes/<int:playlist_id>/lire", methods=["POST"])
def play_playlist_route(playlist_id: int):
    playlist_row = playlist_manager.get(playlist_id)
    if playlist_row is None:
        return redirect(url_for("main.playlists"))
    ok = player_controller.play_playlist(
        playlist_id, bool(playlist_row["shuffle"]), bool(playlist_row["loop"])
    )
    if not ok:
        flash("Cette liste de lecture est vide — ajoutez d'abord des livres ou des morceaux.")
        return redirect(url_for("main.playlist_detail", playlist_id=playlist_id))
    return redirect(url_for("main.now_playing"))


# ---- Import -------------------------------------------------------------
# Deux façons d'apporter des histoires à la boîte :
# - par clé USB branchée sur la boîte (v0.9, voir app/usb_import.py) : la
#   page montre ce que contient la clé et propose Ajouter ou Remplacer —
#   les mêmes actions que les deux tags maîtres ;
# - en envoyant des fichiers depuis l'appareil qui affiche la page (routes
#   upload_books et upload_music, inchangées).

# Message affiché quand un import est refusé ou n'a pas abouti.
_IMPORT_MESSAGES = {
    "pas_de_cle": "Aucune clé USB reconnue : branchez-la sur la boîte.",
    "cle_inconnue": "Cette clé n'a pas de dossier « Audiolibre ».",
    "cle_vide": "La clé ne contient aucune histoire ni musique : rien n'a été changé.",
    "rien": "Tout est déjà sur la boîte : rien à importer.",
    "place": "Pas assez de place sur la boîte pour cet import.",
    "occupe": "Un import est déjà en cours.",
    "cle_retiree": "La clé a été retirée pendant l'import : rien n'a été changé.",
    "copie": "L'import n'a pas pu se terminer : rien n'a été changé.",
}


def _usb_context() -> dict:
    status = usb_import.get_status()
    masters = settings_manager.get_master_tags()
    status["masters_ready"] = all(masters.values())
    conn = get_connection()
    status["untagged_books"] = conn.execute(
        "SELECT COUNT(*) FROM books WHERE id NOT IN (SELECT item_id FROM tag_associations WHERE kind = 'book')"
    ).fetchone()[0]
    status["untagged_albums"] = conn.execute(
        "SELECT COUNT(*) FROM albums WHERE id NOT IN (SELECT item_id FROM tag_associations WHERE kind = 'album')"
    ).fetchone()[0]
    conn.close()
    status["messages"] = _IMPORT_MESSAGES
    status["history"] = usb_import.history(8)
    return status


@main_bp.route("/import")
def import_page():
    return render_template("import.html", active="import", usb=_usb_context())


@main_bp.route("/import/cle")
def import_usb_panel():
    """Le cadre « Clé USB » seul, relu toutes les deux secondes par la page
    (static/js/import.js) pour suivre la clé et l'avancement d'un import."""
    return render_template("_import_usb.html", usb=_usb_context())


@main_bp.route("/import/cle/lancer", methods=["POST"])
def import_usb_start():
    mode = request.form.get("mode") or ""
    code = usb_import.start_import(mode, "web") if mode in usb_import.MODES else "copie"
    if code != "ok":
        flash(_IMPORT_MESSAGES.get(code, _IMPORT_MESSAGES["copie"]))
    return redirect(url_for("main.import_page"))


@main_bp.route("/import/annuler-remplacement", methods=["POST"])
def import_undo():
    code = usb_import.undo_last_replace("web")
    flash({
        "ok": "Remplacement annulé : la boîte a retrouvé son contenu précédent.",
        "rien": "Il n'y a pas de remplacement à annuler.",
        "occupe": "Un import est déjà en cours.",
    }.get(code, "L'annulation n'a pas pu se terminer."))
    return redirect(url_for("main.import_page"))


# ---- Utilitaires d'upload -------------------------------------------------

def _save_uploaded_files(files, target_dir: Path) -> int:
    """
    Enregistre les fichiers audio valides dans target_dir. Ignore les
    fichiers vides ou dont l'extension n'est pas autorisée. En cas de nom
    déjà pris, ajoute un suffixe plutôt que d'écraser un fichier existant.
    Retourne le nombre de fichiers effectivement enregistrés.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for file in files:
        if not file or not file.filename:
            continue
        filename = secure_filename(file.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            continue

        destination = target_dir / filename
        counter = 1
        stem = Path(filename).stem
        while destination.exists():
            destination = target_dir / f"{stem} ({counter}){suffix}"
            counter += 1

        file.save(destination)
        saved += 1
    return saved


def _safe_album_dir(folder_name: str) -> Path:
    safe_name = secure_filename(folder_name) or "Musique"
    return MUSIC_DIR / safe_name


@main_bp.route("/reglages")
def reglages():
    return render_template(
        "settings_menu.html",
        active="reglages",
        language=settings_manager.get_language(),
        language_labels=LANGUAGE_LABELS,
        storage=get_storage_status(),
    )


@main_bp.route("/reglages/langue", methods=["POST"])
def set_language():
    language = request.form.get("language", "fr")
    if language in LANGUAGE_LABELS:
        settings_manager.set_language(language)
    return redirect(url_for("main.reglages"))


@main_bp.route("/reglages/deconnexion-forcee", methods=["POST"])
def force_logout():
    # Bouton dédié dans les réglages, en plus du lien "Déconnexion" déjà
    # présent en haut de chaque page — même action.
    session.clear()
    return redirect(url_for("main.login"))


@main_bp.route("/reglages/eteindre", methods=["POST"])
def shutdown_pi():
    _ok, message = shutdown_now()
    flash(message)
    return redirect(url_for("main.reglages"))


# ---- Réinitialisation usine -------------------------------------------------------
# Pour confier la boîte à quelqu'un d'autre : efface tout (livres, musique,
# tags, listes de lecture, réglages, Wifi de la maison, code PIN, mapping
# boutons — voir app/factory_reset.py pour le détail exact) puis redémarre.
# Un simple confirm() JavaScript n'a pas semblé suffisant vu l'irréversibilité
# de l'opération : une phrase à recopier est exigée, comme pour la
# suppression d'un dépôt sur GitHub par exemple.

FACTORY_RESET_CONFIRM_PHRASE = "RÉINITIALISER"


@main_bp.route("/reglages/reinitialisation-usine", methods=["GET", "POST"])
def factory_reset_confirm():
    error = None
    if request.method == "POST":
        typed = (request.form.get("confirmation") or "").strip().upper()
        if typed != tr(FACTORY_RESET_CONFIRM_PHRASE):
            error = tr("Tapez exactement « {phrase} » (en majuscules) pour confirmer.",
                       phrase=tr(FACTORY_RESET_CONFIRM_PHRASE))
        else:
            ok, message = perform_factory_reset()
            if not ok:
                flash(message)
                return redirect(url_for("main.reglages"))
            reboot_now()
            session.clear()
            return render_template("factory_reset_done.html")
    return render_template(
        "factory_reset_confirm.html",
        active="reglages",
        error=error,
        confirm_phrase=tr(FACTORY_RESET_CONFIRM_PHRASE),
    )


# ---- Configurateur de boutons / manette ----------------------------------------------------
#
# Réassignation des boutons physiques (manette USB ou boutons GPIO) aux
# actions de lecture, et des deux boutons dont l'appui simultané maintenu
# éteint la boîte. Toute la logique de mapping/capture vit dans
# app/controls/mapping.py ; ces routes ne font que l'exposer côté web.
# N'a de sens que sur le vrai Pi (ou la boîte PC x86), quand un contrôleur
# manette/GPIO tourne réellement — settings_manager.get_control_mode()
# renvoie None tant qu'aucun des deux ne s'est jamais lancé (ex: pendant
# les tests sur PC avec le clavier).

def _control_code_label(mode: str, code: str) -> str:
    """Étiquette lisible d'un control_id, pour l'affichage."""
    if not code:
        return "Non assigné"
    if mode == "gpio":
        return f"GPIO {code}"
    if code.startswith("AXIS:"):
        _, axis, direction = code.split(":")
        return f"Croix/stick ({axis}, {'−' if direction == '-1' else '+'})"
    return code


@main_bp.route("/reglages/manette")
def settings_controls():
    mode = settings_manager.get_control_mode()
    if mode is None:
        return render_template("settings_controls.html", active="reglages", mode=None)

    data = mapping.get_mapping(mode)
    actions = [
        {
            "key": action,
            "label": mapping.ACTION_LABELS[action],
            "controls": [
                {"code": code, "label": _control_code_label(mode, code)}
                for code in mapping.controls_for_action(mode, action)
            ],
        }
        for action in mapping.ASSIGNABLE_ACTIONS
    ]
    combo = data["shutdown_combo"]
    combo_labels = [_control_code_label(mode, c) for c in combo]

    return render_template(
        "settings_controls.html",
        active="reglages",
        mode=mode,
        mode_label="manette USB" if mode == "gamepad" else "boutons GPIO",
        actions=actions,
        combo=combo,
        combo_labels=combo_labels,
    )


@main_bp.route("/reglages/manette/capture/demarrer", methods=["POST"])
def start_control_capture():
    mapping.begin_capture()
    return jsonify({"ok": True})


@main_bp.route("/reglages/manette/capture/annuler", methods=["POST"])
def cancel_control_capture():
    mapping.cancel_capture()
    return jsonify({"ok": True})


@main_bp.route("/reglages/manette/capture/etat")
def control_capture_state():
    mode = settings_manager.get_control_mode()
    code = mapping.take_captured()
    if code is not None:
        return jsonify({"code": code, "label": _control_code_label(mode or "gamepad", code)})
    return jsonify({"code": None, "capturing": mapping.is_capturing()})


@main_bp.route("/reglages/manette/assigner", methods=["POST"])
def assign_control():
    mode = settings_manager.get_control_mode()
    action = request.form.get("action")
    code = request.form.get("code")
    if mode and action in mapping.ASSIGNABLE_ACTIONS and code:
        mapping.add_binding(mode, action, code)
        flash("Bouton assigné.")
    return redirect(url_for("main.settings_controls"))


@main_bp.route("/reglages/manette/retirer", methods=["POST"])
def unassign_control():
    mode = settings_manager.get_control_mode()
    action = request.form.get("action")
    code = request.form.get("code")
    if mode and action and code:
        _ok, message = mapping.remove_binding(mode, action, code)
        flash(message)
    return redirect(url_for("main.settings_controls"))


@main_bp.route("/reglages/manette/extinction/assigner", methods=["POST"])
def assign_shutdown_combo():
    mode = settings_manager.get_control_mode()
    code = request.form.get("code")
    raw_slot = request.form.get("slot") or ""
    if mode and code and raw_slot in ("0", "1"):
        _ok, message = mapping.set_shutdown_combo_slot(mode, int(raw_slot), code)
        flash(message)
    return redirect(url_for("main.settings_controls"))


@main_bp.route("/reglages/manette/reinitialiser", methods=["POST"])
def reset_controls():
    mode = settings_manager.get_control_mode()
    if mode:
        mapping.reset_to_default(mode)
        flash("Boutons réinitialisés aux réglages d'usine.")
    return redirect(url_for("main.settings_controls"))


# ---- Tags NFC/RFID (étape 30) ------------------------------------------------
# Un tag = un livre OU un album entier (jamais un morceau isolé, jamais
# une liste de lecture) — voir app/tags.py et app/nfc_controller.py. Le
# flux de capture ("posez un tag à associer") reprend exactement le même
# principe que la capture d'un bouton juste au-dessus (start/état/annuler),
# appliqué à un UID de tag plutôt qu'à un control_id.

@main_bp.route("/reglages/tags")
def settings_tags():
    associations = [_tag_association_to_dict(row) for row in tag_manager.list_all()]

    conn = get_connection()
    books = conn.execute("SELECT id, title FROM books ORDER BY title ASC").fetchall()
    albums = conn.execute("SELECT id, name FROM albums ORDER BY name ASC").fetchall()
    conn.close()

    return render_template(
        "settings_tags.html",
        active="tags",
        associations=associations,
        books=books,
        albums=albums,
        master_tags=settings_manager.get_master_tags(),
    )


@main_bp.route("/reglages/tags/capture/demarrer", methods=["POST"])
def start_tag_capture():
    nfc_controller.begin_capture()
    return jsonify({"ok": True})


@main_bp.route("/reglages/tags/capture/annuler", methods=["POST"])
def cancel_tag_capture():
    nfc_controller.cancel_capture()
    return jsonify({"ok": True})


@main_bp.route("/reglages/tags/capture/etat")
def tag_capture_state():
    uid = nfc_controller.take_captured()
    if uid is not None:
        # Le nom déjà donné à ce tag, s'il en a un, pour le proposer tel quel.
        return jsonify({"uid": uid, "name": tag_manager.get_name(uid)})
    return jsonify({"uid": None, "capturing": nfc_controller.is_capturing()})


@main_bp.route("/reglages/tags/associer", methods=["POST"])
def associate_tag():
    uid_tag = request.form.get("uid_tag")
    target = request.form.get("target") or ""  # "book:12" ou "album:5"
    kind, _sep, raw_id = target.partition(":")
    if uid_tag and settings_manager.master_tag_role(uid_tag):
        # Un tag maître (import par clé USB) ne lance jamais d'histoire.
        flash("Ce tag est un tag maître : il ne peut pas lancer une histoire.")
    elif uid_tag and kind in ("book", "album") and raw_id.isdigit():
        tag_manager.associate(uid_tag, kind, int(raw_id))
        if "tag_name" in request.form:
            tag_manager.set_name(uid_tag, request.form.get("tag_name") or "")
        flash("Tag associé.")
    else:
        flash("Choisissez un livre ou un album avant de valider.")
    return redirect(url_for("main.settings_tags"))


@main_bp.route("/reglages/tags/dissocier", methods=["POST"])
def dissociate_tag():
    uid_tag = request.form.get("uid_tag")
    if uid_tag:
        tag_manager.dissociate(uid_tag)
        flash("Tag dissocié.")
    return redirect(url_for("main.settings_tags"))


@main_bp.route("/reglages/tags/nommer", methods=["POST"])
def rename_tag():
    """Donne un nom à un tag (« Loup bleu »), ou le retire si le nom est vide."""
    uid_tag = (request.form.get("uid_tag") or "").strip()
    if uid_tag:
        name = (request.form.get("tag_name") or "").strip()
        tag_manager.set_name(uid_tag, name)
        flash("Nom du tag enregistré." if name else "Nom du tag retiré.")
    return redirect(url_for("main.settings_tags"))


# Tags maîtres (v0.9) : deux tags réservés à l'import par clé USB, l'un pour
# « Ajouter », l'autre pour « Remplacer ». Déclarés par la même capture que
# les tags d'histoire. Voir app/usb_import.py et app/nfc_controller.py.

def _master_tags_page() -> str:
    """Page où revenir après avoir déclaré ou retiré un tag maître : la
    page Tags, ou l'assistant de bienvenue si c'est de là qu'on vient."""
    if request.form.get("retour") == "bienvenue" and settings_manager.is_onboarding_pending():
        return url_for("main.onboarding_tags")
    return url_for("main.settings_tags")


@main_bp.route("/reglages/tags/maitre", methods=["POST"])
def set_master_tag():
    role = request.form.get("role") or ""
    uid_tag = (request.form.get("uid_tag") or "").strip()
    masters = settings_manager.get_master_tags()
    if role not in masters or not uid_tag:
        flash("Tag non reconnu : recommencez.")
    elif tag_manager.get(uid_tag) is not None:
        flash("Ce tag lance déjà une histoire ou un album : dissociez-le d'abord.")
    elif any(uid == uid_tag for other, uid in masters.items() if other != role):
        flash("Ce tag est déjà l'autre tag maître.")
    else:
        settings_manager.set_master_tag(role, uid_tag)
        flash("Tag maître enregistré.")
    return redirect(_master_tags_page())


@main_bp.route("/reglages/tags/maitre/retirer", methods=["POST"])
def clear_master_tag():
    role = request.form.get("role") or ""
    if role in settings_manager.get_master_tags():
        settings_manager.clear_master_tag(role)
        flash("Tag maître retiré.")
    return redirect(_master_tags_page())


# ---- Énergie (HDMI + mode éco CPU) -------------------------------------------

@main_bp.route("/reglages/energie")
def settings_energie():
    return render_template(
        "settings_energie.html",
        active="reglages",
        hdmi_enabled=settings_manager.get_power_hdmi_enabled(),
        eco_mode=settings_manager.get_power_eco_mode(),
        audio_uses_hdmi=settings_manager.get_audio_output_preference() in ("hdmi1", "hdmi2"),
        lcd_backlight_timeout=settings_manager.get_lcd_backlight_timeout(),
    )


@main_bp.route("/reglages/energie", methods=["POST"])
def set_power_settings_route():
    hdmi_enabled = request.form.get("hdmi_enabled") == "on"
    eco_mode = request.form.get("eco_mode") == "on"
    raw_timeout = request.form.get("lcd_backlight_timeout") or ""

    settings_manager.set_power_hdmi_enabled(hdmi_enabled)
    settings_manager.set_power_eco_mode(eco_mode)
    if raw_timeout.isdigit():
        settings_manager.set_lcd_backlight_timeout(int(raw_timeout))
    ok, message = power_settings.apply_power_settings(hdmi_enabled, eco_mode)
    flash(message or ("Réglages enregistrés." if ok else "Échec de l'application du réglage."))
    return redirect(url_for("main.settings_energie"))


# ---- Sortie audio (gpio / jack USB / hdmi1 / hdmi2) -----------------------------------------
# Le Bluetooth a été retiré (voir README.md "Étape 24") : dix tentatives de
# reconnexion réelles échouaient systématiquement malgré un casque allumé
# et à portée — en pause pour se concentrer sur la stabilité du reste.

_AUDIO_PREFERENCE_KINDS = ("gpio", "hdmi1", "hdmi2")


@main_bp.route("/reglages/audio")
def settings_audio():
    return render_template(
        "settings_audio.html",
        active="reglages",
        outputs=audio_output.list_outputs(),
        current=settings_manager.get_audio_output(),
        preference=settings_manager.get_audio_output_preference(),
        max_volume=settings_manager.get_max_volume(),
        tone=settings_manager.get_tone(),
        tone_limit=settings_manager.TONE_LIMIT,
    )


@main_bp.route("/reglages/audio/tonalite", methods=["POST"])
def set_tone_route():
    """Tonalité du haut-parleur : graves, médiums, aigus (de -12 à +12 dB).
    Appliquée tout de suite, y compris à la lecture en cours — la page
    l'envoie à chaque déplacement d'un curseur, pour régler à l'oreille."""
    def read(name: str) -> int:
        try:
            return int(float(request.form.get(name) or 0))
        except ValueError:
            return 0

    if request.form.get("reset"):
        settings_manager.set_tone(0, 0, 0)
    else:
        settings_manager.set_tone(read("bass"), read("mid"), read("treble"))
    player_controller.apply_tone()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(settings_manager.get_tone())
    flash("Tonalité enregistrée.")
    return redirect(url_for("main.settings_audio"))


@main_bp.route("/reglages/audio/volume-max", methods=["POST"])
def set_max_volume_route():
    raw = request.form.get("max_volume") or ""
    if raw.isdigit():
        settings_manager.set_max_volume(int(raw))
        # Reclampe tout de suite le volume en cours s'il dépassait le
        # nouveau plafond — pas la peine d'attendre un Volume +/- pour
        # que ça se voie.
        player_controller.set_volume(player_controller.get_state()["volume"])
        flash("Plafond de volume enregistré.")
    else:
        flash("Valeur de volume invalide.")
    return redirect(url_for("main.settings_audio"))


@main_bp.route("/reglages/audio/preference", methods=["POST"])
def set_audio_output_preference():
    """Sélecteur gpio/hdmi1/hdmi2 (Réglages → Sortie audio). Un jack
    (adaptateur USB) déjà branché continue de prendre le dessus quoi qu'il
    arrive (voir audio_output.resolve_effective_output) — ce réglage ne
    fait que départager gpio/hdmi1/hdmi2 pour quand aucun jack n'est
    branché. Appliqué tout de suite (pas besoin d'attendre le prochain
    passage du service de fond bin/audio_output_watchdog.py)."""
    preference = request.form.get("preference", "")
    if preference not in _AUDIO_PREFERENCE_KINDS:
        flash("Choix de sortie invalide.")
        return redirect(url_for("main.settings_audio"))

    settings_manager.set_audio_output_preference(preference)
    # Un changement ici peut faire dépendre le son de l'HDMI (ou au
    # contraire l'en libérer) — Réglages → Énergie doit en tenir compte
    # tout de suite, pas seulement au prochain changement énergie lui-même.
    power_settings.apply_saved_power_settings()
    target = audio_output.resolve_effective_output(preference)
    if not target:
        flash("Préférence enregistrée, mais aucune sortie détectée pour l'appliquer tout de suite.")
        return redirect(url_for("main.settings_audio"))

    ok, message = audio_output.set_output(target["alsa_target"])
    if ok:
        settings_manager.set_audio_output(target["kind"], target["label"], target["alsa_target"])
        if target["kind"] == "jack":
            message = f"Jack branché — reste prioritaire ({target['label']})."
    flash(message)
    return redirect(url_for("main.settings_audio"))


@main_bp.route("/reglages/audio/appliquer", methods=["POST"])
def apply_audio_output():
    kind = request.form.get("kind", "autre")
    label = request.form.get("label", "")
    alsa_target = request.form.get("alsa_target", "").strip()
    if alsa_target:
        ok, message = audio_output.set_output(alsa_target)
        flash(message)
        if ok:
            settings_manager.set_audio_output(kind, label or alsa_target, alsa_target)
    else:
        # Uniquement atteignable depuis le champ "Sortie manuelle" (l'autre
        # formulaire de cette page envoie toujours un alsa_target déjà
        # rempli via un champ caché) — laissé vide.
        flash("Indiquez une cible ALSA avant de valider.")
    return redirect(url_for("main.settings_audio"))


# ---- Minuterie et plages horaires ---------------------------------------------------------

@main_bp.route("/reglages/temps", methods=["GET", "POST"])
def settings_time():
    if request.method == "POST":
        try:
            minutes = int(request.form.get("sleep_timer_minutes") or 0)
        except ValueError:
            minutes = 0
        settings_manager.set_sleep_timer_minutes(max(0, min(180, minutes)))
        # La nouvelle durée s'applique tout de suite à la lecture en cours.
        player_controller.rearm_sleep_timer()
        for day in range(7):
            enabled = request.form.get(f"day_{day}_enabled") == "on"
            start_hour = int(request.form.get(f"day_{day}_start", 8))
            end_hour = int(request.form.get(f"day_{day}_end", 20))
            settings_manager.set_day_schedule(day, DaySchedule(enabled, start_hour, end_hour))
        flash("Réglages enregistrés.")
        return redirect(url_for("main.settings_time"))

    schedules = [(day, DAY_NAMES[day], settings_manager.get_day_schedule(day)) for day in range(7)]
    return render_template(
        "settings_time.html",
        active="reglages",
        sleep_timer_minutes=settings_manager.get_sleep_timer_minutes(),
        schedules=schedules,
    )


# ---- Catégories -------------------------------------------------------

@main_bp.route("/reglages/categories", methods=["GET", "POST"])
def settings_categories():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        icon = (request.form.get("icon") or "🏷️").strip()
        color_hex = request.form.get("color_hex") or "#8FB6FF"
        if name:
            conn = get_connection()
            conn.execute(
                "INSERT INTO categories (name, icon, color_hex) VALUES (?, ?, ?)",
                (name, icon, color_hex),
            )
            conn.commit()
            conn.close()
        return redirect(url_for("main.settings_categories"))

    conn = get_connection()
    categories = conn.execute("SELECT * FROM categories ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("settings_categories.html", active="reglages", categories=categories)


@main_bp.route("/reglages/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id: int):
    conn = get_connection()
    conn.execute("UPDATE books SET category_id = NULL WHERE category_id = ?", (category_id,))
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("main.settings_categories"))


@main_bp.route("/livres/<int:book_id>/category", methods=["POST"])
def set_book_category(book_id: int):
    raw = request.form.get("category_id") or ""
    category_id = int(raw) if raw.isdigit() else None
    conn = get_connection()
    conn.execute("UPDATE books SET category_id = ? WHERE id = ?", (category_id, book_id))
    conn.commit()
    conn.close()
    return redirect(url_for("main.book_detail", book_id=book_id))


# ---- Code PIN -------------------------------------------------------

@main_bp.route("/reglages/pin", methods=["GET", "POST"])
def settings_pin():
    error = None
    if request.method == "POST":
        current = request.form.get("current_pin", "")
        new = request.form.get("new_pin", "")
        confirm = request.form.get("confirm_pin", "")
        if not pin_manager.verify_pin(current):
            error = "Le code actuel est incorrect."
        elif len(new) < 4:
            error = "Le nouveau code doit faire au moins 4 chiffres."
        elif new != confirm:
            error = "Les deux codes ne correspondent pas."
        else:
            pin_manager.set_pin(new)
            flash("Code PIN mis à jour.")
            return redirect(url_for("main.reglages"))
    return render_template("settings_pin.html", active="reglages", error=error)


# ---- Réseau (enregistré, appliqué lors de l'installation sur le Pi) ----------------

def _start_wifi_trial(
    wifi_ssid, wifi_password, ip_mode, static_ip, static_netmask, static_gateway, static_dns,
    back_endpoint, next_endpoint,
):
    """Enregistre le Wifi saisi, lance son essai et affiche la page
    d'attente. La page est renvoyée directement (pas de redirection) :
    deux secondes plus tard, la boîte quitte le réseau par lequel elle a
    été demandée. Voir app/network_apply.py."""
    settings_manager.remember_previous_wifi()
    network = settings_manager.get_network_config()
    settings_manager.set_network_config(
        network["hostname"], wifi_ssid, wifi_password,
        ip_mode, static_ip, static_netmask, static_gateway, static_dns,
    )
    wifi_fallback.sync_fallback_conf()
    ok, message = network_apply.start_wifi_trial(
        wifi_ssid, wifi_password, ip_mode, static_ip, static_netmask, static_gateway, static_dns,
    )
    if not ok:
        settings_manager.restore_previous_wifi()
        wifi_fallback.sync_fallback_conf()
        flash(message)
        return redirect(url_for(back_endpoint))
    return render_template(
        "network_trial.html",
        ssid=wifi_ssid,
        hostname=network["hostname"],
        on_fallback=wifi_fallback.is_ap_active(max_age=0),
        state_url=url_for("main.network_trial_state"),
        back_url=url_for(back_endpoint),
        next_url=url_for(next_endpoint),
    )


@main_bp.route("/reglages/reseau/etat")
def network_trial_state():
    """Compte rendu du dernier essai de Wifi, interrogé par la page
    d'attente dès que l'appareil retrouve la boîte."""
    state = network_apply.reconcile_after_trial()
    return jsonify({"state": state["state"], "ssid": state["ssid"], "reason": state["reason"], "ip": state["ip"]})


@main_bp.route("/reglages/reseau", methods=["GET", "POST"])
def settings_network():
    if request.method == "POST":
        current = settings_manager.get_network_config()
        hostname = secure_filename(request.form.get("hostname") or "") or current["hostname"]
        wifi_ssid = (request.form.get("wifi_ssid") or "").strip()
        wifi_password = request.form.get("wifi_password") or ""
        ip_mode = "static" if request.form.get("ip_mode") == "static" else "dhcp"
        static_ip = (request.form.get("static_ip") or "").strip()
        static_netmask = (request.form.get("static_netmask") or "255.255.255.0").strip()
        static_gateway = (request.form.get("static_gateway") or "").strip()
        static_dns = (request.form.get("static_dns") or "").strip()

        fallback_enabled = request.form.get("fallback_enabled") == "on"
        fallback_ssid = (request.form.get("fallback_ssid") or "").strip() or SettingsManager.DEFAULT_WIFI_FALLBACK_SSID
        fallback_password = (request.form.get("fallback_password") or "").strip()
        current_fallback_password = settings_manager.get_wifi_fallback_config()["password"]
        if fallback_password and len(fallback_password) < 8:
            flash("Mot de passe du point d'accès de secours trop court (8 caractères minimum) — ancien mot de passe conservé.")
            fallback_password = current_fallback_password
        elif not fallback_password:
            fallback_password = current_fallback_password
        settings_manager.set_wifi_fallback_config(fallback_enabled, fallback_ssid, fallback_password)
        wifi_fallback.sync_fallback_conf()

        # Le nom de la boîte n'est appliqué que s'il a vraiment été changé.
        if hostname != current["hostname"]:
            _ok, message = network_apply.apply_hostname(hostname)
            flash(message)

        # Le Wifi n'est (ré)essayé que s'il y a quelque chose de nouveau à
        # essayer : un réglage modifié, ou une boîte qui n'est pas reliée au
        # Wifi indiqué. Avant la v0.8, chaque « Enregistrer » supprimait et
        # recréait la connexion, même pour un simple changement de nom.
        wanted = (wifi_ssid, wifi_password, ip_mode, static_ip, static_netmask, static_gateway, static_dns)
        stored = tuple(current[key] for key in (
            "wifi_ssid", "wifi_password", "ip_mode", "static_ip", "static_netmask", "static_gateway", "static_dns"))
        if wifi_ssid and (wanted != stored or get_wifi_status()["connected_ssid"] != wifi_ssid):
            return _start_wifi_trial(
                *wanted, back_endpoint="main.settings_network", next_endpoint="main.settings_network")

        if not wifi_ssid:
            settings_manager.set_network_config(
                current["hostname"], "", "", ip_mode, static_ip, static_netmask, static_gateway, static_dns)
            wifi_fallback.sync_fallback_conf()
        flash("Réglages enregistrés.")
        return redirect(url_for("main.settings_network"))

    return render_template(
        "settings_network.html",
        active="reglages",
        network=settings_manager.get_network_config(),
        wifi_status=get_wifi_status(),
        wifi_networks=scan_wifi_networks(),
        fallback=settings_manager.get_wifi_fallback_config(),
        fallback_status=wifi_fallback.get_fallback_status(),
        trial=_recent_trial(),
    )


def _recent_trial() -> dict | None:
    """Dernier essai de Wifi s'il date de moins d'un quart d'heure, pour
    l'afficher en haut de la page Réseau (et de l'étape Wifi de l'assistant)."""
    state = network_apply.reconcile_after_trial()
    if state["state"] in ("ok", "echec") and state["age"] is not None and state["age"] < 900:
        return state
    return None


@main_bp.route("/reglages/reseau/oublier", methods=["POST"])
def forget_wifi():
    """"Oublier ce réseau" : supprime la connexion NetworkManager ET le
    SSID/mot de passe enregistrés côté appli — repart de zéro, comme si
    aucun Wifi n'avait jamais été configuré."""
    current_ssid = settings_manager.get_network_config()["wifi_ssid"]
    if not current_ssid:
        flash("Aucun réseau enregistré à oublier.")
        return redirect(url_for("main.settings_network"))

    _ok, message = forget_wifi_network(current_ssid)
    flash(message)

    network = settings_manager.get_network_config()
    settings_manager.set_network_config(
        network["hostname"], "", "",
        network["ip_mode"], network["static_ip"], network["static_netmask"],
        network["static_gateway"], network["static_dns"],
    )
    wifi_fallback.sync_fallback_conf()
    return redirect(url_for("main.settings_network"))


# ---- Pages statiques -------------------------------------------------------

@main_bp.route("/reglages/mentions-legales")
def legal_notice():
    return render_template("legal_notice.html", active="reglages")


@main_bp.route("/reglages/aide")
def help_page():
    return render_template("help_page.html", active="reglages")


# ---- API du lecteur, utilisée par la page "lecture en cours" ---------------------------------

def _fetch_row(kind: str, item_id: int):
    conn = get_connection()
    table = "books" if kind == "book" else "tracks"
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return row


def _fetch_album(album_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    conn.close()
    return row


def _visual_fields(kind: str, row) -> dict:
    """
    Emoji / couleur / jaquette à afficher pour un livre ou un morceau.
    Un livre porte directement ces champs. Un morceau n'a PAS de colonnes
    emoji/color_hex (seule sa table "albums" en a) — on va donc les
    chercher sur son album, et on ne retombe sur la jaquette de l'album
    que si le morceau lui-même n'en a pas.
    """
    if kind == "book":
        return {
            "emoji": row["emoji"],
            "color_hex": row["color_hex"],
            "cover_url": _cover_url(row["cover_path"]),
        }

    album_row = _fetch_album(row["album_id"])
    cover_source = row["cover_path"] or (album_row["cover_path"] if album_row is not None else None)
    return {
        "emoji": album_row["emoji"] if album_row is not None else "🎵",
        "color_hex": album_row["color_hex"] if album_row is not None else "#8FB6FF",
        "cover_url": _cover_url(cover_source),
    }


def _playlist_name(playlist_id) -> Optional[str]:
    if not playlist_id:
        return None
    row = playlist_manager.get(playlist_id)
    return row["name"] if row is not None else None


def _tag_association_to_dict(assoc) -> dict:
    """Enrichit une ligne tag_associations avec le titre/emoji/couleur du
    livre ou de l'album visé, pour l'affichage (Réglages → Tags NFC).
    Reste affichable même si le livre/album a été supprimé depuis
    (bibliothèque modifiée sans repasser par la dissociation du tag)."""
    if assoc["kind"] == "book":
        row = _fetch_row("book", assoc["item_id"])
        title = row["title"] if row is not None else tr("(livre supprimé)")
        emoji = row["emoji"] if row is not None else "❓"
        color_hex = row["color_hex"] if row is not None else "#CCCCCC"
    else:
        row = _fetch_album(assoc["item_id"])
        title = row["name"] if row is not None else tr("(album supprimé)")
        emoji = row["emoji"] if row is not None else "❓"
        color_hex = row["color_hex"] if row is not None else "#CCCCCC"
    return {
        "uid_tag": assoc["uid_tag"],
        "tag_name": tag_manager.get_name(assoc["uid_tag"]),
        "kind": assoc["kind"],
        "item_id": assoc["item_id"],
        "title": title,
        "emoji": emoji,
        "color_hex": color_hex,
    }


def _display_state() -> dict:
    """
    État renvoyé à la page web. Deux cas :
    - un livre/morceau est activement chargé dans le lecteur -> son état réel
    - rien n'est chargé -> on propose de reprendre le dernier lu, avec
      "loaded": false pour que la page sache qu'il faut appeler /api/play
      (et pas /api/toggle) au premier clic.
    """
    state = player_controller.get_state()

    if state["kind"] is not None:
        row = _fetch_row(state["kind"], state["item_id"])
        state["loaded"] = True
        if row is not None:
            state.update(_visual_fields(state["kind"], row))
        else:
            state["emoji"], state["color_hex"], state["cover_url"] = "🌙", "#8FB6FF", None
        state["playlist_name"] = _playlist_name(state.get("playlist_id"))
        return state

    last = player_controller.get_last_played()
    if last is None:
        return {"loaded": False, "kind": None}

    row = _fetch_row(last["kind"], last["item_id"])
    if row is None:
        return {"loaded": False, "kind": None}

    result = {
        "loaded": False,
        "kind": last["kind"],
        "item_id": last["item_id"],
        "title": row["title"],
        "subtitle": row["author"] if last["kind"] == "book" else (row["artist"] or ""),
        "position_ms": row["position_ms"],
        "duration_ms": row["duration_ms"],
        "is_playing": False,
        "volume": state["volume"],
        "playlist_name": None,
    }
    result.update(_visual_fields(last["kind"], row))
    return result


@main_bp.route("/api/state")
def api_state():
    return jsonify(_display_state())


@main_bp.route("/api/play", methods=["POST"])
def api_play():
    data = request.get_json(force=True)
    ok = player_controller.play(data["kind"], int(data["item_id"]))
    return jsonify({"ok": ok, "state": _display_state()})


@main_bp.route("/api/toggle", methods=["POST"])
def api_toggle():
    player_controller.toggle_play_pause()
    return jsonify({"state": _display_state()})


@main_bp.route("/api/seek", methods=["POST"])
def api_seek():
    data = request.get_json(force=True)
    if "delta_ms" in data:
        player_controller.seek_relative(int(data["delta_ms"]))
    else:
        player_controller.seek_to(int(data["position_ms"]))
    return jsonify({"state": _display_state()})


@main_bp.route("/api/skip_forward", methods=["POST"])
def api_skip_forward():
    """Musique : morceau suivant. Livre : avance de 10s (comportement inchangé)."""
    player_controller.skip_forward()
    return jsonify({"state": _display_state()})


@main_bp.route("/api/skip_back", methods=["POST"])
def api_skip_back():
    """
    Musique : simple appui = relance le morceau, double appui rapide =
    morceau précédent. Livre : recule de 10s (comportement inchangé).
    """
    player_controller.skip_back()
    return jsonify({"state": _display_state()})


@main_bp.route("/api/volume", methods=["POST"])
def api_volume():
    data = request.get_json(force=True)
    if "level" in data:
        player_controller.set_volume(int(data["level"]))
    elif data.get("direction") == "up":
        player_controller.volume_up()
    else:
        player_controller.volume_down()
    return jsonify({"state": _display_state()})
