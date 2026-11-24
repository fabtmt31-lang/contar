"""
Démarrage commun aux trois points d'entrée (run.py sur PC, run_pi.py avec
boutons câblés, run_pi_gamepad.py avec manette) depuis la v0.11 :
lecteur NFC, câble USB-C, veille et extinction, voyants, son de démarrage.
"""


def start_box_services(on_box: bool) -> None:
    try:
        from app import nfc_controller
        from app.tag_reader import make_reader
        nfc_controller.start(make_reader(on_box))
    except Exception as exc:
        print(f"[i] Contrôle NFC non démarré ({exc}).")
        if on_box:
            print("    Vérifiez le câblage du PN532 (SPI par défaut, voir GUIDE_RASPBERRY.md).")
        else:
            print("    Installez pyscard (pip install pyscard), ou lancez avec CONTAR_NFC=simu.")

    try:
        from app import depot_import
        depot_import.clean_old_work_dirs()
    except Exception as exc:
        print(f"[i] {exc}")

    try:
        from app import usb_gadget
        usb_gadget.start()
    except Exception as exc:
        print(f"[i] Câble USB-C non surveillé ({exc}).")

    try:
        from app import power_manager
        power_manager.start(with_button=on_box)
    except Exception as exc:
        print(f"[i] Veille automatique non démarrée ({exc}).")

    if on_box:
        try:
            from app import leds
            leds.start()
        except Exception as exc:
            print(f"[i] Voyants non démarrés ({exc}).")
        try:
            from app.sound_feedback import play_startup
            play_startup()
        except Exception as exc:
            print(f"[i] Son de démarrage non joué ({exc}).")
