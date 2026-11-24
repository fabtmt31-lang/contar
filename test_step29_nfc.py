"""
Étape 29 — test du lecteur NFC/RFID (Omnikey 5422 pour l'instant, puis
plus tard n'importe quel lecteur PC/SC compatible CCID, par exemple sur
le Pi le jour où vous ajoutez un module RC522 via une petite carte
adaptatrice USB-CCID, ou un autre lecteur USB).

Ce script ne touche à rien du reste de l'application (pas de base, pas
de player) : il sert uniquement à valider que le lecteur est vu par le
système et qu'on sait lire l'UID d'un tag posé dessus, avant d'écrire la
logique de déclenchement de lecture (étape 30).

Fonctionne à l'identique sur PC (Windows, service Smart Card natif, rien
à installer normalement) et sur le Raspberry Pi, à condition d'avoir
installé les paquets système une seule fois sur le Pi :
    sudo apt install pcscd libccid
    sudo systemctl enable --now pcscd

Dépendance Python (les deux environnements) :
    pip install pyscard

Lancez ce script, posez un tag sur le lecteur : son UID s'affiche.
Retirez-le puis reposez-le (même tag ou un autre) : ça s'affiche à
nouveau, une seule fois par pose (pas en boucle tant qu'il reste dessus)
— exactement le comportement dont on aura besoin à l'étape 30 pour éviter
qu'un tag oublié sur le lecteur ne relance sans arrêt la même histoire.

Ctrl+C pour arrêter.
"""

import sys
import time

try:
    from smartcard.CardMonitoring import CardMonitor, CardObserver
    from smartcard.System import readers
    from smartcard.util import toHexString
except ImportError:
    print("Le paquet 'pyscard' n'est pas installé.")
    print("Installez-le avec : pip install pyscard")
    sys.exit(1)

# Commande APDU standard "Get Data" (UID) : reconnue par la quasi-totalité
# des lecteurs PC/SC en mode contactless (Omnikey, ACR122u, adaptateurs
# CCID pour RC522...), quelle que soit la marque du tag (Mifare, NTAG...).
GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]


class UidPrinter(CardObserver):
    """Affiche l'UID de chaque tag qui apparaît sur le lecteur, et signale
    son retrait. C'est exactement le même type d'événement ("arrivée" vs
    "présence continue") que celui qu'on branchera sur le déclenchement de
    lecture à l'étape 30."""

    def update(self, observable, actions):
        added, removed = actions
        for card in added:
            try:
                connection = card.createConnection()
                connection.connect()
                data, sw1, sw2 = connection.transmit(GET_UID_APDU)
                if (sw1, sw2) == (0x90, 0x00):
                    uid = toHexString(data).replace(" ", "")
                    print(f"[tag posé]   UID = {uid}")
                else:
                    print(f"[tag posé]   lecture UID échouée (SW={sw1:02X}{sw2:02X})")
            except Exception as exc:
                print(f"[tag posé]   erreur de lecture : {exc}")
        for _card in removed:
            print("[tag retiré]")


def main() -> None:
    available = readers()
    if not available:
        print("Aucun lecteur PC/SC détecté.")
        print("- Sous Windows : vérifiez que le lecteur est bien branché en USB "
              "(l'Omnikey 5422 ne nécessite normalement aucun pilote à installer).")
        print("- Sous Raspberry Pi OS : sudo apt install pcscd libccid "
              "&& sudo systemctl enable --now pcscd, puis rebranchez le lecteur.")
        sys.exit(1)

    print("Lecteur(s) PC/SC détecté(s) :")
    for reader in available:
        print(f"  - {reader}")
    print("\nPosez un tag sur le lecteur (Ctrl+C pour arrêter)...\n")

    printer = UidPrinter()
    monitor = CardMonitor()
    monitor.addObserver(printer)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        monitor.deleteObserver(printer)


if __name__ == "__main__":
    main()
