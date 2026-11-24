"""
Lance le serveur web ET le contrôle par boutons GPIO — à utiliser sur le
Raspberry Pi. Sur PC pendant le développement, utilisez plutôt run.py
(contrôle clavier).
"""

from app.web import create_app
from app.controls.gpio_controller import start as start_gpio_controls

app = create_app()
start_gpio_controls()

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
    app.run(host="0.0.0.0", port=web_port(on_box=True), debug=False)
