"""
Interface commune à tous les lecteurs NFC/RFID supportés par le projet,
pour que app/nfc_controller.py (capture, association, déclenchement de
lecture) n'ait JAMAIS besoin de savoir quel matériel tourne en dessous.

Deux implémentations concrètes :
- PCSCReader — lecteurs PC/SC (Omnikey 5422 validé, tout lecteur USB
  compatible CCID en théorie). Utilisé sur PC (run.py) pour
  le développement/test, sans matériel Raspberry Pi spécifique.
- PN532Reader — module PN532 en I2C, lecteur définitif de la boîte
  (run_pi.py, run_pi_gamepad.py). Partage le bus I2C avec l'écran LCD
  (voir app/lcd_display.py), à une adresse différente.

Contrat commun : start(on_tag_seen) démarre l'écoute en tâche de fond et
revient IMMÉDIATEMENT (jamais bloquant) ; on_tag_seen(uid) est appelé une
seule fois par ARRIVÉE d'un tag (jamais en continu tant qu'il reste posé,
jamais au retrait) — chaque implémentation gère son propre mécanisme
(événementiel pour PC/SC via pyscard, sondage actif dans un thread dédié
pour le PN532, qui n'a pas d'équivalent événementiel).
"""

import threading
import time
from typing import Callable, Optional

OnTagSeen = Callable[[str], None]


class TagReader:
    def start(self, on_tag_seen: OnTagSeen) -> None:
        raise NotImplementedError


class PCSCReader(TagReader):
    """Lecteurs PC/SC (Omnikey 5422 et compatibles CCID) — voir
    test_step29_nfc.py pour le script de validation matérielle initial,
    dont ce qui suit reprend exactement le même principe."""

    GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]

    def __init__(self) -> None:
        self._monitor = None  # gardé en instance pour ne pas être nettoyé par le GC

    def start(self, on_tag_seen: OnTagSeen) -> None:
        from smartcard.CardMonitoring import CardMonitor, CardObserver
        from smartcard.util import toHexString

        def _read_uid(card) -> Optional[str]:
            try:
                connection = card.createConnection()
                connection.connect()
                data, sw1, sw2 = connection.transmit(self.GET_UID_APDU)
                if (sw1, sw2) != (0x90, 0x00):
                    return None
                return toHexString(data).replace(" ", "")
            except Exception as exc:
                print(f"[NFC/PC-SC] erreur de lecture d'un tag : {exc}")
                return None

        class _Observer(CardObserver):
            def update(self, observable, actions):
                added, _removed = actions
                for card in added:
                    uid = _read_uid(card)
                    if uid:
                        on_tag_seen(uid)

        self._monitor = CardMonitor()
        self._monitor.addObserver(_Observer())
        print("Lecteur NFC actif (PC/SC).")


class PN532Reader(TagReader):
    """Module PN532 en I2C. Contrairement à pyscard (événementiel), la lib
    Adafruit fonctionne par SONDAGE ACTIF : read_passive_target() renvoie
    le MÊME tag à chaque appel tant qu'il reste posé, donc c'est CE module
    qui doit suivre lui-même la présence d'un tour à l'autre pour ne
    déclencher on_tag_seen() qu'à l'arrivée (last_uid et misses
    ci-dessous) — pas de notion de "retrait" fournie par la lib, on la
    reconstruit."""

    def __init__(self, poll_interval: float = 0.3) -> None:
        self._poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None

    def start(self, on_tag_seen: OnTagSeen) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(on_tag_seen,), daemon=True
        )
        self._thread.start()
        print("Lecteur NFC actif (PN532, I2C).")

    RETRY_SECONDS = 15.0  # lecteur absent : nouvel essai à cet intervalle

    # Nombre de lectures vides de suite avant de considérer le tag comme
    # retiré (v0.9). Une seule lecture manquée — cela arrive, le lecteur
    # partage son câble avec l'écran — ne doit pas faire croire qu'un tag
    # resté posé vient d'être reposé : c'est ce geste qui confirme
    # « Remplacer » (voir app/usb_import.py). Un AUTRE tag, lui, est pris en
    # compte tout de suite.
    MISSES_BEFORE_GONE = 2

    def _connect(self):
        """Ouvre le bus et initialise le PN532. En cas d'échec, le bus est
        refermé avant de relancer l'erreur (jamais de bus laissé ouvert)."""
        import board
        import busio
        from adafruit_pn532.i2c import PN532_I2C

        i2c = busio.I2C(board.SCL, board.SDA)
        try:
            pn532 = PN532_I2C(i2c, debug=False)
            pn532.SAM_configuration()
            return pn532
        except Exception:
            try:
                i2c.deinit()
            except Exception:
                pass
            raise

    def _run(self, on_tag_seen: OnTagSeen) -> None:
        # Correction v0.7.1 — avant, un lecteur absent au démarrage arrêtait
        # définitivement le contrôle NFC : il fallait redémarrer la boîte
        # après l'avoir rebranché. Désormais on retente régulièrement, en
        # ne l'écrivant qu'une fois dans le journal.
        pn532 = None
        missing_logged = False
        while pn532 is None:
            try:
                pn532 = self._connect()
            except Exception as exc:
                if not missing_logged:
                    print(f"[NFC/PN532] lecteur introuvable : {exc}")
                    print("[NFC/PN532] vérifiez le câblage I2C (i2cdetect -y 1 doit montrer 0x24) et que le module est bien alimenté."
                          f" Nouvel essai toutes les {int(self.RETRY_SECONDS)} s.")
                    missing_logged = True
                time.sleep(self.RETRY_SECONDS)
        if missing_logged:
            print("[NFC/PN532] lecteur détecté, contrôle NFC actif.")

        last_uid = None
        misses = 0
        last_error = ""
        while True:
            try:
                uid_bytes = pn532.read_passive_target(timeout=0.5)
                last_error = ""
            except Exception as exc:
                if str(exc) != last_error:  # une seule ligne par erreur différente
                    print(f"[NFC/PN532] erreur de lecture d'un tag : {exc}")
                    last_error = str(exc)
                uid_bytes = None

            if uid_bytes is not None:
                uid = uid_bytes.hex().upper()
                if uid != last_uid:
                    on_tag_seen(uid)
                last_uid = uid
                misses = 0
            else:
                misses += 1
                if misses >= self.MISSES_BEFORE_GONE:
                    last_uid = None

            time.sleep(self._poll_interval)
