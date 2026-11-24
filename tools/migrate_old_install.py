#!/usr/bin/env python3
"""
Reprise d'une installation d'avant la v0.8 (« Histoires du Soir »).

Lancé par install_pi.sh APRÈS que les dossiers ont été déplacés :
    /opt/histoiresdusoir/HDP    ->  /opt/contar/Bibliotheque
    /opt/histoiresdusoir/data   ->  /opt/contar/data
    data/histoiresdusoir.db     ->  data/contar.db

La base de données garde le chemin complet de chaque fichier audio et de
chaque pochette : ce script les réécrit vers les nouveaux emplacements,
et retire deux réglages devenus inutiles ou trompeurs.

    python3 tools/migrate_old_install.py <ancien_dossier> <nouveau_dossier>

Sans risque à relancer : une base déjà à jour n'est pas modifiée.
"""

import sqlite3
import sys
from pathlib import Path


def migrate(old_dir: str, new_dir: str) -> int:
    old_dir, new_dir = old_dir.rstrip("/"), new_dir.rstrip("/")
    db_path = Path(new_dir) / "data" / "contar.db"
    if not db_path.exists():
        print(f"Aucune base à reprendre ({db_path} absent) : rien à faire.")
        return 0

    # Du plus précis au plus général : le dossier des fichiers audio change
    # aussi de nom, le reste ne change que de racine.
    replacements = [
        (f"{old_dir}/HDP/", f"{new_dir}/Bibliotheque/"),
        (f"{old_dir}/", f"{new_dir}/"),
    ]

    conn = sqlite3.connect(db_path)
    changed = 0
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')
                       if (row[2] or "").upper() in ("TEXT", "")]
            for column in columns:
                for old, new in replacements:
                    cursor = conn.execute(
                        f'UPDATE "{table}" SET "{column}" = ? || substr("{column}", ?) '
                        f'WHERE substr("{column}", 1, ?) = ?',
                        (new, len(old) + 1, len(old), old),
                    )
                    changed += cursor.rowcount

        # Le nom de la boîte est désormais lu sur le système ; l'ancienne
        # valeur enregistrée (« histoiresdusoir » par défaut) renommait la
        # boîte à chaque enregistrement de la page Réseau.
        conn.execute("DELETE FROM settings WHERE key = 'net_hostname'")
        conn.commit()
    finally:
        conn.close()

    print(f"Base reprise : {changed} chemin(s) mis à jour.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(migrate(sys.argv[1], sys.argv[2]))
