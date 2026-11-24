"""
Portage direct de PinManager.kt.

Le code parental n'est jamais conservé en clair : seule son empreinte
SHA-256 est enregistrée dans la table settings (clé "pin_hash"), comparée
à chaque tentative de saisie. Comportement identique à la version Android,
y compris le PIN par défaut "1234" tant qu'aucun n'a été configuré.
"""

import hashlib

from app.database import get_connection

DEFAULT_PIN = "1234"  # à changer par le parent dès le premier lancement


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PinManager:
    def is_pin_configured(self) -> bool:
        conn = get_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = 'pin_hash'").fetchone()
        conn.close()
        return row is not None

    def set_pin(self, pin: str) -> None:
        conn = get_connection()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('pin_hash', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_hash(pin),),
        )
        conn.commit()
        conn.close()

    def verify_pin(self, pin: str) -> bool:
        conn = get_connection()
        row = conn.execute("SELECT value FROM settings WHERE key = 'pin_hash'").fetchone()
        conn.close()
        stored = row["value"] if row else _hash(DEFAULT_PIN)
        return stored == _hash(pin)
