"""
Équivalent Python de MediaMetadataRetriever (utilisé côté Android dans
BookRepository et MusicRepository) : lecture des tags (titre, artiste,
album, année, durée) et extraction de la vignette embarquée, si présente.

Nécessite la librairie "mutagen" (pip install mutagen), qui gère aussi
bien les tags ID3 des .mp3 que les tags MP4 des .m4a/.m4b.
"""

from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4


@dataclass
class AudioMeta:
    title: str
    artist: str | None
    album: str | None
    year: str | None
    duration_ms: int
    cover_bytes: bytes | None


def _first(value) -> str | None:
    """Les tags "easy" de mutagen renvoient des listes ; on prend le premier élément non vide."""
    if not value:
        return None
    text = str(value[0]).strip()
    return text or None


def _extract_cover(path: Path) -> bytes | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".mp3":
            id3 = ID3(path)
            for tag in id3.values():
                if isinstance(tag, APIC):
                    return tag.data
            return None
        if suffix in (".m4a", ".m4b"):
            mp4 = MP4(path)
            covers = mp4.tags.get("covr") if mp4.tags else None
            if covers:
                return bytes(covers[0])
            return None
    except Exception:
        return None
    return None


def read_audio_metadata(path: Path) -> AudioMeta:
    """
    Lit les métadonnées d'un fichier audio. Ne lève jamais d'exception :
    en cas de fichier illisible ou sans tags, on retombe sur des valeurs
    par défaut basées sur le nom de fichier, comme le fait la version Android.
    """
    title = path.stem
    artist = None
    album = None
    year = None
    duration_ms = 0

    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            if audio.info is not None and getattr(audio.info, "length", None):
                duration_ms = int(audio.info.length * 1000)
            tags = audio.tags or {}
            title = _first(tags.get("title")) or title
            artist = _first(tags.get("artist"))
            album = _first(tags.get("album"))
            year = _first(tags.get("date")) or _first(tags.get("year"))
    except Exception:
        pass

    cover_bytes = _extract_cover(path)

    return AudioMeta(
        title=title,
        artist=artist,
        album=album,
        year=year,
        duration_ms=duration_ms,
        cover_bytes=cover_bytes,
    )
