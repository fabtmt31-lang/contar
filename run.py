"""
Lance le serveur web ET le contrôle clavier — à utiliser sur PC pendant
le développement. Sur le vrai Raspberry Pi, utilisez run_pi.py à la place
(contrôle par boutons GPIO plutôt que clavier).

Le rechargement automatique de Flask (use_reloader) est désactivé ici :
avec lui, ce fichier s'exécute deux fois (processus superviseur + worker),
ce qui enregistrerait les raccourcis clavier deux fois. Relancez
manuellement le script après une modification de code.
"""

from app.web import create_app

app = create_app()

try:
    from app.controls.keyboard_controller import start as start_keyboard_controls
    start_keyboard_controls()
except Exception as exc:
    print(f"[i] Contrôle clavier non démarré ({exc}).")
    print("    Installez-le avec : pip install keyboard")

# Import par clé USB (v0.9). Sur PC, il n'y a pas de clé à surveiller : pour
# essayer, désignez un dossier qui en tient lieu, par exemple
#   CONTAR_CLE_SIMULEE=/chemin/vers/ma_cle python run.py
# (ce dossier doit contenir Audiolibre/Livres et Audiolibre/Musiques).
try:
    import os
    from app import usb_import
    usb_import.recover_interrupted()
    if os.environ.get("CONTAR_CLE_SIMULEE"):
        usb_import.start_watcher()
except Exception as exc:
    print(f"[i] Import par clé USB non démarré ({exc}).")

try:
    from app import nfc_controller
    from app.tag_reader import PCSCReader
    nfc_controller.start(PCSCReader())
except Exception as exc:
    print(f"[i] Contrôle NFC non démarré ({exc}).")
    print("    Installez la dépendance avec : pip install pyscard")

if __name__ == "__main__":
    from app.config import web_port
    app.run(host="0.0.0.0", port=web_port(on_box=False), debug=True, use_reloader=False)
