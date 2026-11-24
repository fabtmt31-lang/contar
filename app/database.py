"""
Base de données SQLite : équivalent direct de la base Room de la version
Android (books, categories, albums, tracks), plus deux tables qui
remplacent le DataStore (settings, day_schedules).
"""

import sqlite3

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT NOT NULL,
    author              TEXT NOT NULL,
    file_path           TEXT NOT NULL UNIQUE,
    emoji               TEXT NOT NULL,
    color_hex           TEXT NOT NULL,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    position_ms         INTEGER NOT NULL DEFAULT 0,
    finished            INTEGER NOT NULL DEFAULT 0,
    -- Vestige de l'ancien bouton "Visible/Masqué pour l'enfant", retiré :
    -- plus lu ni écrit nulle part (voir app/web/routes.py, remplacé par
    -- le badge NFC). Colonne conservée telle quelle pour ne pas casser
    -- les bases existantes (SQLite migre mal la suppression de colonne),
    -- mais n'a plus aucun effet.
    visible_to_child    INTEGER NOT NULL DEFAULT 1,
    cover_path          TEXT,
    category_id         INTEGER REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    icon        TEXT NOT NULL,
    color_hex   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS albums (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    folder_path  TEXT NOT NULL UNIQUE,
    emoji        TEXT NOT NULL,
    color_hex    TEXT NOT NULL,
    cover_path   TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id      INTEGER NOT NULL REFERENCES albums(id),
    title         TEXT NOT NULL,
    file_path     TEXT NOT NULL UNIQUE,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    order_index   INTEGER NOT NULL DEFAULT 0,
    position_ms   INTEGER NOT NULL DEFAULT 0,
    finished      INTEGER NOT NULL DEFAULT 0,
    cover_path    TEXT,
    artist        TEXT,
    album         TEXT,
    year          TEXT
);

-- Remplace le DataStore Android : stockage clé/valeur générique
-- (pin_hash, sleep_timer_minutes, langue, réseau, tags maîtres...)
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- Plages horaires d'autorisation, une ligne par jour (0 = lundi ... 6 = dimanche)
CREATE TABLE IF NOT EXISTS day_schedules (
    day         INTEGER PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 0,
    start_hour  INTEGER NOT NULL DEFAULT 8,
    end_hour    INTEGER NOT NULL DEFAULT 20
);

-- Listes de lecture : peuvent librement mélanger livres et morceaux de
-- musique (voir playlist_items.kind, même convention que le lecteur
-- central dans app/player.py). shuffle/loop pilotent la lecture en
-- aléatoire et/ou en boucle quand la liste est lancée.
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    shuffle     INTEGER NOT NULL DEFAULT 0,
    loop        INTEGER NOT NULL DEFAULT 0,
    emoji       TEXT NOT NULL DEFAULT '📻',
    color_hex   TEXT NOT NULL DEFAULT '#8FB6FF'
);

-- Éléments d'une liste de lecture, dans l'ordre (order_index). "item_id"
-- pointe vers books.id ou tracks.id selon "kind" — pas de clé étrangère
-- directe possible ici (la cible dépend de kind), donc vérifié à la main
-- côté application plutôt qu'en base, comme le fait déjà app/player.py
-- pour la lecture d'un élément unique.
CREATE TABLE IF NOT EXISTS playlist_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id   INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('book', 'track')),
    item_id       INTEGER NOT NULL,
    order_index   INTEGER NOT NULL DEFAULT 0
);

-- Association entre un tag NFC/RFID (son UID, tel que lu par
-- app/nfc_controller.py) et un contenu de la bibliothèque (v0.11) : une
-- histoire ('book'), un album entier ('album') ou une liste de lecture
-- ('playlist', histoires et musiques mélangées). Un tag ne pointe que vers
-- un seul contenu à la fois. Chaque tag porte aussi sa façon de jouer :
--   resume   1 = reprendre où on en était, 0 = toujours depuis le début
--   shuffle  1 = ordre mélangé
--   loop     1 = recommencer à la fin, 0 = s'arrêter
CREATE TABLE IF NOT EXISTS tag_associations (
    uid_tag     TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('book', 'album', 'playlist')),
    item_id     INTEGER NOT NULL,
    resume      INTEGER NOT NULL DEFAULT 1,
    shuffle     INTEGER NOT NULL DEFAULT 0,
    loop        INTEGER NOT NULL DEFAULT 0
);

-- Avancement propre à chaque tag (v0.11) : la file de lecture telle que le
-- tag l'a lancée (ordre mélangé compris, en JSON : [["book", 3], ...]), la
-- place dans cette file et la position dans l'élément en cours. Retirer le
-- tag l'enregistre ; la double pose l'efface. Voir app/tag_playback.py.
CREATE TABLE IF NOT EXISTS tag_progress (
    uid_tag      TEXT PRIMARY KEY,
    queue        TEXT NOT NULL,
    queue_index  INTEGER NOT NULL DEFAULT 0,
    position_ms  INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT ''
);

-- Nom donné à un tag (v0.10) : « Loup bleu », « Carte rouge »… pour le
-- reconnaître dans l'administration autrement que par son numéro. Le nom
-- suit le tag lui-même : il est gardé si le tag change d'histoire, ou s'il
-- n'est associé à rien pour l'instant. Voir app/tags.py.
CREATE TABLE IF NOT EXISTS tags (
    uid_tag     TEXT PRIMARY KEY,
    name        TEXT NOT NULL
);

-- Journal des imports. Jusqu'à la v0.10 : imports par clé USB. Depuis la
-- v0.11 : rangement du disque de dépôt USB-C (mode 'depot', source 'usb',
-- voir app/depot_import.py). "status" vaut 'ok' ou le code du refus.
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    mode        TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,
    added       INTEGER NOT NULL DEFAULT 0,
    removed     INTEGER NOT NULL DEFAULT 0,
    present     INTEGER NOT NULL DEFAULT 0,
    ignored     INTEGER NOT NULL DEFAULT 0,
    key_label   TEXT NOT NULL DEFAULT ''
);
"""


def get_connection() -> sqlite3.Connection:
    """
    Ouvre une connexion à la base. row_factory permet d'accéder aux colonnes
    par leur nom (row["title"]) plutôt que par index, comme des objets Room.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database() -> None:
    """À appeler une fois au démarrage de l'application : crée les tables si absentes."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Dossiers supplémentaires (retirés en v0.10) : la boîte ne lit plus que
    # sa propre bibliothèque, Bibliotheque/Livres et Bibliotheque/Musiques.
    conn.execute("DELETE FROM settings WHERE key IN ('extra_book_folders', 'extra_music_folders')")
    _migrate_tag_associations(conn)
    # Réglages devenus sans objet en v0.11 (écran LCD, tags maîtres).
    conn.execute(
        "DELETE FROM settings WHERE key IN "
        "('lcd_backlight_timeout_seconds', 'master_tag_ajouter', 'master_tag_remplacer')"
    )
    conn.commit()
    conn.close()


def _migrate_tag_associations(conn: sqlite3.Connection) -> None:
    """Base d'avant la v0.11 : la table n'acceptait que 'book' et 'album' et
    n'avait pas les options de lecture. SQLite ne sait pas modifier une
    contrainte : on recrée la table et on recopie les associations."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tag_associations)")}
    if "resume" in columns:
        return
    conn.executescript("""
        ALTER TABLE tag_associations RENAME TO tag_associations_v010;
        CREATE TABLE tag_associations (
            uid_tag     TEXT PRIMARY KEY,
            kind        TEXT NOT NULL CHECK (kind IN ('book', 'album', 'playlist')),
            item_id     INTEGER NOT NULL,
            resume      INTEGER NOT NULL DEFAULT 1,
            shuffle     INTEGER NOT NULL DEFAULT 0,
            loop        INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO tag_associations (uid_tag, kind, item_id)
            SELECT uid_tag, kind, item_id FROM tag_associations_v010;
        DROP TABLE tag_associations_v010;
    """)
