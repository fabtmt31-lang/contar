#!/usr/bin/env python3
"""
Essai de l'écran LCD de la boîte, sans le reste du programme.

À lancer sur le Raspberry Pi, boîte arrêtée (sinon les deux écrivent sur
l'écran en même temps) :

    sudo systemctl stop contar
    sudo -u contar /opt/contar/venv/bin/python /opt/contar/tools/test_ecran.py
    sudo systemctl start contar

L'essai dure une vingtaine de secondes et affiche trois écrans de suite.
Il suffit de regarder l'écran et de noter lesquels s'affichent en entier.
"""

import sys
import time

BUS = 1
ADDRESSES = (0x27, 0x3F)    # les deux adresses courantes de ces écrans


def answers(address: int) -> bool:
    try:
        from smbus2 import SMBus
        with SMBus(BUS) as bus:
            bus.read_byte(address)
        return True
    except Exception:
        return False


def link_trouble(exc: OSError) -> int:
    print()
    print(f"L'écran répond, puis décroche pendant l'écriture ({exc}).")
    print("Ce n'est pas le programme : la liaison est perturbée. À vérifier, dans l'ordre :")
    print("  1. débrancher les autres modules (lecteur NFC, ampli) et relancer cet essai ;")
    print("     s'il passe, c'est le câblage commun qui gêne (masse, 5 V, fils SDA/SCL partagés) ;")
    print("  2. VCC de l'écran sur le 5 V (broche 2 ou 4), GND sur une masse, fils courts et bien enfoncés ;")
    print("  3. l'alimentation du Pi : la commande  vcgencmd get_throttled  doit répondre throttled=0x0.")
    return 2


def main() -> int:
    found = [address for address in ADDRESSES if answers(address)]
    if not found:
        print("Aucun écran ne répond (adresses 0x27 et 0x3f).")
        print("Vérifiez les quatre fils : VCC sur le 5 V (broche 2 ou 4), GND sur une masse")
        print("(broche 6), SDA sur la broche 3, SCL sur la broche 5. Puis : i2cdetect -y 1")
        return 1
    address = found[0]
    print(f"Écran trouvé à l'adresse {hex(address)}.")
    if address != 0x27:
        print("Attention : la boîte attend l'adresse 0x27. Dites-le moi, c'est un réglage à changer.")

    from RPLCD.i2c import CharLCD

    try:
        lcd = CharLCD(i2c_expander="PCF8574", address=address, port=BUS, cols=16, rows=2)
    except OSError as exc:
        return link_trouble(exc)
    try:
        print("Écran 1/3 (6 s) — on doit lire :   Contar ligne 1   /   0123456789ABCDEF")
        lcd.clear()
        lcd.write_string("Contar ligne 1")
        lcd.cursor_pos = (1, 0)
        lcd.write_string("0123456789ABCDEF")
        time.sleep(6)

        print("Écran 2/3 (8 s) — écrit lentement : Lettre a lettre  /   ABCDEFGHIJKLMNOP")
        lcd.clear()
        time.sleep(0.2)
        for row, text in enumerate(("Lettre a lettre", "ABCDEFGHIJKLMNOP")):
            for col, char in enumerate(text):
                lcd.cursor_pos = (row, col)
                lcd.write_string(char)
                time.sleep(0.05)
        time.sleep(6)

        print("Écran 3/3 (6 s) — la lumière de l'écran clignote trois fois, texte : Fin de l'essai")
        lcd.clear()
        lcd.write_string("Fin de l'essai")
        for _ in range(3):
            lcd.backlight_enabled = False
            time.sleep(0.5)
            lcd.backlight_enabled = True
            time.sleep(0.5)
        time.sleep(2)
    except OSError as exc:
        return link_trouble(exc)
    finally:
        try:
            lcd.close(clear=True)
        except Exception:
            pass
    print()
    print("Essai terminé. Ce qu'il m'est utile de savoir :")
    print("  - l'écran 1 s'est-il affiché en entier, sur les deux lignes ?")
    print("  - et l'écran 2 (écrit lentement) ?")
    print("  - sinon, qu'avez-vous vu exactement (une lettre, des carrés, rien) ?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
