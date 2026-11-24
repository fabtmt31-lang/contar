"""
Script de vérification de l'étape 1 (base de données + PIN + réglages +
scan de bibliothèque). Ne dépend d'aucun matériel Raspberry Pi : se lance
tel quel sur Windows/Mac/Linux.

Utilisation :
    1. Déposez quelques fichiers .mp3 dans Bibliotheque/Livres et/ou dans des
       sous-dossiers de Bibliotheque/Musiques (voir le message affiché si les
       dossiers sont vides).
    2. Lancez : python test_step1.py
"""

from app.database import init_database
from app.library_scan import scan_books, scan_music
from app.pin import DEFAULT_PIN, PinManager
from app.settings import DaySchedule, SettingsManager
from app.config import BOOKS_DIR, MUSIC_DIR
from app.database import get_connection


def main() -> None:
    print("=== Étape 1 : base de données, PIN, réglages, scan ===\n")

    # 1. Création des tables
    init_database()
    print("[OK] Tables créées (ou déjà existantes).")

    # 2. PIN
    pin_manager = PinManager()
    print(f"[OK] PIN configuré : {pin_manager.is_pin_configured()}")
    print(f"[OK] Vérification du PIN par défaut ({DEFAULT_PIN}) : "
          f"{pin_manager.verify_pin(DEFAULT_PIN)}")

    # 3. Réglages : minuterie + une plage horaire d'exemple
    settings = SettingsManager()
    settings.set_sleep_timer_minutes(30)
    print(f"[OK] Minuterie de coucher : {settings.get_sleep_timer_minutes()} min")

    settings.set_day_schedule(0, DaySchedule(enabled=True, start_hour=8, end_hour=20))
    print(f"[OK] Plage horaire du lundi : {settings.get_day_schedule(0)}")
    print(f"[OK] Utilisation autorisée maintenant : {settings.is_allowed_now()}")

    # 4. Scan de la bibliothèque
    if not any(BOOKS_DIR.iterdir()):
        print(f"\n[i] Aucun fichier dans {BOOKS_DIR} — déposez-y quelques .mp3 pour tester le scan.")
    if not any(MUSIC_DIR.iterdir()):
        print(f"[i] Aucun dossier dans {MUSIC_DIR} — créez-y un sous-dossier avec des .mp3 pour tester le scan.")

    added_books = scan_books()
    added_tracks = scan_music()
    print(f"\n[OK] {added_books} nouveau(x) livre(s) ajouté(s).")
    print(f"[OK] {added_tracks} nouveau(x) morceau(x) ajouté(s).")

    # 5. Affichage du contenu actuel de la base
    conn = get_connection()
    print("\n--- Livres en base ---")
    for row in conn.execute("SELECT id, title, author, duration_ms FROM books ORDER BY title"):
        print(f"  #{row['id']:>3} {row['emoji'] if 'emoji' in row.keys() else ''} "
              f"{row['title']} — {row['author']} ({row['duration_ms']} ms)")

    print("\n--- Albums / morceaux en base ---")
    for album in conn.execute("SELECT * FROM albums ORDER BY name"):
        print(f"  Album: {album['name']} ({album['folder_path']})")
        for track in conn.execute(
            "SELECT * FROM tracks WHERE album_id = ? ORDER BY order_index", (album["id"],)
        ):
            print(f"    - {track['title']} ({track['duration_ms']} ms)")
    conn.close()

    print("\n=== Terminé ===")


if __name__ == "__main__":
    main()
