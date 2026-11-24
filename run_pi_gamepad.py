"""
Lance le serveur web ET le contrôle par manette USB — variante pour le
vrai Raspberry Pi, sans câblage GPIO : une manette USB filaire type
NES/Super NES branchée sur le Pi fait office de boutons physiques.

app/controls/gamepad_controller.py ne dépend d'aucun matériel spécifique (il lit la manette via /dev/input,
comme n'importe quel périphérique USB), donc le même code fonctionne à
l'identique sur un Raspberry Pi.

Utilisez ce fichier à la place de run_pi.py tant que les boutons ne sont
pas câblés sur les GPIO (ou si vous préférez rester sur une manette USB
durablement, plus simple à mettre en place qu'un câblage). Le reste de
l'application (serveur web, lecteur, base de données) est strictement
identique quel que soit le point d'entrée utilisé — voir
app/controls/actions.py.

C'est ce fichier qu'installe install_pi.sh par défaut (mode "gamepad").
"""

from app.web import create_app

app = create_app()

try:
    from app.controls.gamepad_controller import start as start_gamepad_controls
    start_gamepad_controls()
except Exception as exc:
    print(f"[i] Contrôle manette non démarré ({exc}).")
    print("    Installez la dépendance avec : pip install inputs")

# Import par clé USB (v0.9) : d'abord remettre la bibliothèque d'aplomb si
# la boîte a été coupée pendant un import, puis surveiller le port USB.
try:
    from app import usb_import
    usb_import.recover_interrupted()
    usb_import.start_watcher()
except Exception as exc:
    print(f"[i] Import par clé USB non démarré ({exc}).")

try:
    from app import nfc_controller
    from app.tag_reader import PN532Reader
    nfc_controller.start(PN532Reader())
except Exception as exc:
    print(f"[i] Contrôle NFC non démarré ({exc}).")
    print("    Vérifiez le câblage I2C du PN532 (i2cdetect -y 1) et que l'I2C est activé.")

try:
    from app import lcd_display
    lcd_display.start()
    lcd_display.show_welcome()
except Exception as exc:
    print(f"[i] Écran LCD non démarré ({exc}).")
    print("    Vérifiez le câblage I2C de l'écran (i2cdetect -y 1) et que l'I2C est activé.")

try:
    from app.sound_feedback import play_startup
    play_startup()
except Exception as exc:
    print(f"[i] Son de démarrage non joué ({exc}).")

if __name__ == "__main__":
    from app.config import web_port
    app.run(host="0.0.0.0", port=web_port(on_box=True), debug=False, use_reloader=False)
