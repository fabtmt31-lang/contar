"""
Interface commune à tous les lecteurs NFC/RFID supportés par le projet,
pour que app/nfc_controller.py (capture, association, geste de l'enfant)
n'ait JAMAIS besoin de savoir quel matériel tourne en dessous.

Contrat (v0.11) : start(on_present, on_absent) démarre l'écoute en tâche
de fond et revient IMMÉDIATEMENT. on_present(uid) est appelé une fois à
l'ARRIVÉE d'un tag ; on_absent(uid) une fois à son RETRAIT. Un tag laissé
posé ne redéclenche rien. Chaque lecteur filtre lui-même ses micro-coupures
(lectures ratées) pour qu'un tag resté posé ne passe jamais pour « retiré
puis reposé » — ce qui déclencherait une remise à zéro (voir
app/tag_gesture.py).

Implémentations :
- PCSCReader — lecteurs USB PC/SC (Omnikey 5422 validé), pour le PC de
  développement (run.py).
- PN532Reader — module PN532, lecteur de la boîte. En SPI depuis la v0.11
  (libère la broche GPIO 3 pour le bouton de réveil), en I2C pour une
  boîte pas encore recâblée. Choix par la variable CONTAR_NFC_BUS
  (spi par défaut, ou i2c), voir make_reader().
- ManualReader — aucun matériel : les tags sont « posés » par programme
  (tests, et PC sans lecteur avec CONTAR_NFC=simu, voir app/web/routes.py).
"""

import os
import threading
import time
from typing import Callable, Optional

OnTag = Callable[[str], None]


class TagReader:
    def start(self, on_present: OnTag, on_absent: OnTag) -> None:
        raise NotImplementedError


class ManualReader(TagReader):
    """Lecteur sans matériel : present("04A1B2") puis absent()."""

    def __init__(self) -> None:
        self._on_present: Optional[OnTag] = None
        self._on_absent: Optional[OnTag] = None
        self.current: Optional[str] = None

    def start(self, on_present: OnTag, on_absent: OnTag) -> None:
        self._on_present, self._on_absent = on_present, on_absent
        print("Lecteur NFC simulé : posez un tag depuis /api/dev/tag.")

    def present(self, uid: str) -> None:
        if self.current == uid:
            return
        if self.current is not None:
            self.absent()
        self.current = uid
        if self._on_present:
            self._on_present(uid)

    def absent(self) -> None:
        uid, self.current = self.current, None
        if uid is not None and self._on_absent:
            self._on_absent(uid)


class PCSCReader(TagReader):
    """Lecteurs PC/SC (Omnikey 5422 et compatibles CCID) — voir
    test_step29_nfc.py pour le script de validation matérielle initial,
    dont ce qui suit reprend exactement le même principe."""

    GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]

    def __init__(self) -> None:
        self._monitor = None  # gardé en instance pour ne pas être nettoyé par le GC

    def start(self, on_present: OnTag, on_absent: OnTag) -> None:
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

        # Une carte retirée ne se lit plus : on retient l'UID lu à l'arrivée.
        uids: dict = {}

        class _Observer(CardObserver):
            def update(self, observable, actions):
                added, removed = actions
                for card in removed:
                    uid = uids.pop(card, None)
                    if uid:
                        on_absent(uid)
                for card in added:
                    uid = _read_uid(card)
                    if uid:
                        uids[card] = uid
                        on_present(uid)

        self._monitor = CardMonitor()
        self._monitor.addObserver(_Observer())
        print("Lecteur NFC actif (PC/SC).")


class PN532Reader(TagReader):
    """Module PN532, par SONDAGE ACTIF : read_passive_target() renvoie le
    MÊME tag à chaque appel tant qu'il reste posé. Ce module suit donc
    lui-même la présence d'un tour à l'autre : arrivée = premier tour où on
    le lit, retrait = ABSENT_SECONDS sans l'avoir lu (une lecture ratée de
    temps en temps ne compte pas comme un retrait).

    Câblage SPI (v0.11, par défaut) : SCK → GPIO 11 (broche 23),
    MOSI → GPIO 10 (broche 19), MISO → GPIO 9 (broche 21),
    SS/NSS → GPIO 25 (broche 22), VCC 3,3 V, GND. Interrupteurs du module
    sur « SPI ». Voir GUIDE_RASPBERRY.md."""

    RETRY_SECONDS = 15.0     # lecteur absent : nouvel essai à cet intervalle
    ABSENT_SECONDS = 0.5     # temps sans lecture avant de déclarer le tag retiré
    READ_TIMEOUT = 0.12

    def __init__(self, bus: Optional[str] = None, poll_interval: float = 0.05) -> None:
        self.bus = (bus or os.environ.get("CONTAR_NFC_BUS", "spi")).lower()
        self.poll_interval = poll_interval   # réglable à chaud (veille : plus lent)
        self._thread: Optional[threading.Thread] = None

    def start(self, on_present: OnTag, on_absent: OnTag) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(on_present, on_absent), daemon=True
        )
        self._thread.start()
        print(f"Lecteur NFC actif (PN532, {self.bus.upper()}).")

    def _connect(self):
        """Ouvre le bus et initialise le PN532. En cas d'échec, le bus est
        refermé avant de relancer l'erreur (jamais de bus laissé ouvert)."""
        import board
        import busio
        if self.bus == "i2c":
            from adafruit_pn532.i2c import PN532_I2C
            bus = busio.I2C(board.SCL, board.SDA)
            make = lambda: PN532_I2C(bus, debug=False)  # noqa: E731
        else:
            import digitalio
            from adafruit_pn532.spi import PN532_SPI
            bus = busio.SPI(board.SCK, board.MOSI, board.MISO)
            cs_pin = getattr(board, "D" + os.environ.get("CONTAR_NFC_CS", "25"))
            cs = digitalio.DigitalInOut(cs_pin)
            make = lambda: PN532_SPI(bus, cs, debug=False)  # noqa: E731
        try:
            pn532 = make()
            pn532.SAM_configuration()
            return pn532
        except Exception:
            try:
                bus.deinit()
            except Exception:
                pass
            raise

    def _wiring_hint(self) -> str:
        if self.bus == "i2c":
            return "vérifiez le câblage I2C (i2cdetect -y 1 doit montrer 0x24) et que le module est en mode I2C."
        return ("vérifiez le câblage SPI (SCK broche 23, MOSI 19, MISO 21, SS 22), que le module est "
                "en mode SPI et que le SPI est activé (dtparam=spi=on).")

    def _run(self, on_present: OnTag, on_absent: OnTag) -> None:
        pn532 = None
        missing_logged = False
        while pn532 is None:
            try:
                pn532 = self._connect()
            except Exception as exc:
                if not missing_logged:
                    print(f"[NFC/PN532] lecteur introuvable : {exc}")
                    print(f"[NFC/PN532] {self._wiring_hint()} Nouvel essai toutes les {int(self.RETRY_SECONDS)} s.")
                    missing_logged = True
                time.sleep(self.RETRY_SECONDS)
        if missing_logged:
            print("[NFC/PN532] lecteur détecté, contrôle NFC actif.")

        current: Optional[str] = None
        last_seen = 0.0
        last_error = ""
        while True:
            try:
                uid_bytes = pn532.read_passive_target(timeout=self.READ_TIMEOUT)
                last_error = ""
            except Exception as exc:
                if str(exc) != last_error:  # une seule ligne par erreur différente
                    print(f"[NFC/PN532] erreur de lecture d'un tag : {exc}")
                    last_error = str(exc)
                uid_bytes = None

            now = time.monotonic()
            if uid_bytes is not None:
                uid = uid_bytes.hex().upper()
                if uid != current:
                    if current is not None:
                        on_absent(current)
                    current = uid
                    on_present(uid)
                last_seen = now
            elif current is not None and now - last_seen >= self.ABSENT_SECONDS:
                gone, current = current, None
                on_absent(gone)

            time.sleep(self.poll_interval)


def make_reader(on_box: bool) -> TagReader:
    """Lecteur à utiliser : CONTAR_NFC=simu (aucun matériel), pcsc ou
    pn532 ; par défaut PN532 sur la boîte, PC/SC sur un PC."""
    choice = os.environ.get("CONTAR_NFC", "pn532" if on_box else "pcsc").lower()
    if choice == "simu":
        return ManualReader()
    if choice == "pcsc":
        return PCSCReader()
    return PN532Reader()
