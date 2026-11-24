"""
Écran LCD 16x2 I2C (module générique type Freenove/HD44780 + dos
PCF8574), piloté via RPLCD.

Rôle : donner un retour visuel directement sur la boîte, sans avoir à
ouvrir l'interface web — message d'accueil au démarrage, confirmation au
passage d'un tag (connu ou inconnu, voir app/nfc_controller.py), puis
pendant la lecture : titre en défilement sur la ligne du haut, statut
▶️/⏸️ et temps restant sur la ligne du bas.

Tourne sur son propre thread, à son PROPRE rythme : lit l'état du
lecteur via player_controller.get_state() (voir app/player.py) au lieu
d'attendre que player.py lui pousse quoi que ce soit — l'écran est un
simple spectateur de l'état de lecture, jamais un acteur qui le modifie,
et player.py n'a besoin de rien savoir de son existence.

Partage le même bus I2C que le lecteur PN532 (voir app/tag_reader.py), à
une adresse différente (LCD_I2C_ADDRESS ci-dessous) — deux périphériques
I2C sur un seul bus, chacun à sa propre adresse, aucun conflit.

Best-effort partout : un souci quelconque (pas d'écran branché, bus I2C
absent, adresse erronée...) ne doit JAMAIS faire planter le reste de
l'appli — juste rester silencieux, avec un message en console.
"""

import threading
import time
from typing import Optional

from app.i18n import t
from app.player import player_controller
from app.settings import SettingsManager

_settings_manager = SettingsManager()

LCD_I2C_ADDRESS = 0x27  # adresse la plus courante pour ce type de dos
                         # PCF8574 — à ajuster ici si le vôtre diffère
                         # (voir "i2cdetect -y 1" sur le Pi pour vérifier)
LCD_I2C_BUS = 1          # bus I2C des broches 3 (SDA) et 5 (SCL) du Pi
LCD_COLS = 16
LCD_ROWS = 2

# Écran absent ou débranché : on ne retente pas à chaque cycle d'affichage
# (toutes les 0,4 s) mais seulement à cet intervalle. Voir _get_lcd().
LCD_RETRY_SECONDS = 15.0
# Un écran qui vient d'être branché (ou de recevoir son courant) met un
# instant à être prêt, et les fils ne font pas tous contact au même moment.
# On attend donc un peu entre « il répond » et sa mise en route, puis on
# vérifie qu'il répond toujours (v0.10.1) : une mise en route envoyée trop
# tôt laisse l'écran dans un état bancal — quelques lettres, puis plus rien.
LCD_SETTLE_SECONDS = 1.0
# Après une erreur d'écriture (liaison perturbée un instant), l'écran est
# repris au bout de ce délai, et non plus des 15 secondes réservées à un
# écran absent (v0.10.2) : une erreur passagère ne laisse plus l'écran figé
# sur une lettre. Au-delà de quelques erreurs de suite, on repasse au
# rythme lent pour ne pas s'acharner sur un écran débranché.
LCD_ERROR_RETRY_SECONDS = 2.0
LCD_FAST_RETRIES = 5

REFRESH_INTERVAL = 0.4          # rythme de rafraîchissement/défilement
MESSAGE_DISPLAY_SECONDS = 2.5   # durée par défaut d'un message ponctuel

_lcd = None

_lock = threading.Lock()
# Message temporaire (bienvenue, tag scanné...), prioritaire sur
# l'affichage normal tant que sa date d'expiration n'est pas dépassée —
# _run() y repasse automatiquement ensuite.
_override_lines: Optional[tuple] = None
_override_until = 0.0

_scroll_offset = 0
_last_scrolled_title: Optional[str] = None

_last_activity = time.monotonic()
_backlight_on = True

# Import par clé USB (v0.9, voir app/usb_import.py) :
# - _sticky_lines : message tenu à l'écran tant qu'il n'est pas retiré
#   (avancement de la copie), à la place du titre en cours ou de l'attente ;
# - _idle_hint : ce que l'écran d'attente affiche tant qu'une clé est
#   branchée (« Clé prête / Posez un tag », puis « Retirez la clé »).
_sticky_lines: Optional[tuple] = None
_idle_hint: Optional[tuple] = None

_lcd_errors = 0              # erreurs d'écriture de suite (voir _drop_lcd)
_lcd_retry_at = 0.0          # pas de nouvelle tentative avant cet instant
_lcd_missing_logged = False  # pour n'écrire « écran absent » qu'une fois
_last_error_text = ""        # pour ne pas répéter la même erreur en boucle


# État du réseau, relu régulièrement pour l'afficher (v0.8) : l'adresse de la
# boîte au démarrage et à chaque changement, le résultat d'un essai de Wifi,
# et, sur le réseau de secours, son nom et son mot de passe en alternance
# avec l'écran d'attente. Voir app/network_status.py::lcd_summary().
NETWORK_POLL_SECONDS = 6.0
NETWORK_MESSAGE_SECONDS = 10.0
_network = {"mode": None, "ssid": "", "ip": "", "password": ""}
_network_shown = None                        # dernier état déjà affiché
_next_network_poll = time.monotonic() + 5.0  # après le message de bienvenue


class _LcdUnavailable(Exception):
    """Écran absent pour l'instant : rien à afficher, rien à signaler."""


def mark_activity() -> None:
    """Réinitialise le délai avant extinction du rétroéclairage — appelé à
    chaque bouton pressé (voir app/controls/actions.py::trigger()) et à
    chaque tag posé, connu ou non (voir app/nfc_controller.py)."""
    global _last_activity
    _last_activity = time.monotonic()


def _lcd_answers() -> bool:
    """Vrai si un module répond à l'adresse de l'écran. Le bus est ouvert
    puis REFERMÉ à chaque fois (bloc « with ») : c'est tout l'intérêt de ce
    test préalable, voir _get_lcd()."""
    try:
        from smbus2 import SMBus
        with SMBus(LCD_I2C_BUS) as bus:
            bus.read_byte(LCD_I2C_ADDRESS)
        return True
    except Exception:
        return False


def _get_lcd():
    """Renvoie l'écran prêt à l'emploi, ou lève _LcdUnavailable s'il ne
    répond pas.

    Correction v0.7.1 — avant, un écran absent faisait créer un nouvel
    objet CharLCD à CHAQUE cycle (toutes les 0,4 s). Or sa création ouvre
    le bus I2C avant d'échouer, sans jamais le refermer : au bout de
    quelques minutes le programme avait épuisé son quota de fichiers
    ouverts, ne pouvait plus ouvrir sa base de données (« unable to open
    database file ») et l'administration ne répondait plus. Désormais :
    on vérifie d'abord que l'écran répond (test qui referme le bus), et
    on ne retente que toutes les LCD_RETRY_SECONDS. Effet secondaire
    utile : un écran rebranché est repris tout seul, sans redémarrage."""
    global _lcd, _lcd_retry_at, _lcd_missing_logged, _backlight_on
    if _lcd is not None:
        return _lcd

    now = time.monotonic()
    if now < _lcd_retry_at:
        raise _LcdUnavailable()
    _lcd_retry_at = now + LCD_RETRY_SECONDS

    if not _lcd_answers():
        if not _lcd_missing_logged:
            print(f"[écran] aucun écran à l'adresse {hex(LCD_I2C_ADDRESS)} : la boîte continue sans "
                  f"(nouvel essai toutes les {int(LCD_RETRY_SECONDS)} s).")
            _lcd_missing_logged = True
        raise _LcdUnavailable()

    time.sleep(LCD_SETTLE_SECONDS)
    if not _lcd_answers():
        raise _LcdUnavailable()     # faux contact : nouvel essai dans 15 s

    from RPLCD.i2c import CharLCD
    _lcd = CharLCD(
        i2c_expander="PCF8574",
        address=LCD_I2C_ADDRESS,
        port=LCD_I2C_BUS,
        cols=LCD_COLS,
        rows=LCD_ROWS,
    )
    _backlight_on = True  # un écran tout juste initialisé est allumé
    if _lcd_missing_logged:
        print("[écran] écran détecté, affichage repris.")
        _lcd_missing_logged = False
    return _lcd


def _drop_lcd() -> None:
    """L'écran ne répond plus (débranché en marche, faux contact) : on
    referme proprement le bus et on repassera par _get_lcd() plus tard."""
    global _lcd, _lcd_retry_at, _lcd_errors
    lcd, _lcd = _lcd, None
    _lcd_errors += 1
    delay = LCD_ERROR_RETRY_SECONDS if _lcd_errors <= LCD_FAST_RETRIES else LCD_RETRY_SECONDS
    _lcd_retry_at = time.monotonic() + delay
    if lcd is None:
        return
    # Les deux appels sont nécessaires : selon la version de RPLCD,
    # close() ne referme pas le bus I2C lui-même.
    for closer in (lambda: lcd.close(clear=False), lambda: lcd.bus.close()):
        try:
            closer()
        except Exception:
            pass


def _write(line1: str, line2: str) -> None:
    lcd = _get_lcd()
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1.ljust(LCD_COLS)[:LCD_COLS])
    lcd.cursor_pos = (1, 0)
    lcd.write_string(line2.ljust(LCD_COLS)[:LCD_COLS])


def _show_temporary(line1: str, line2: str, seconds: float = MESSAGE_DISPLAY_SECONDS) -> None:
    global _override_lines, _override_until
    with _lock:
        _override_lines = (line1, line2)
        _override_until = time.monotonic() + seconds


def show_welcome() -> None:
    """Appelé une fois au tout début du démarrage réel de la boîte (voir
    run_pi.py / run_pi_gamepad.py)."""
    _show_temporary(t("lcd.welcome_line1"), t("lcd.welcome_line2"), seconds=4)


def show_tag_scanned(title: str) -> None:
    """Appelé depuis app/nfc_controller.py après le déclenchement d'une
    lecture par tag connu."""
    _show_temporary(t("lcd.tag_scanned_label"), (title or "")[:LCD_COLS])


def show_unknown_tag() -> None:
    """Appelé depuis app/nfc_controller.py quand le tag posé n'est associé
    à rien — complète le bip sonore (voir app/sound_feedback.py)."""
    _show_temporary(t("lcd.unknown_tag_line1"), t("lcd.unknown_tag_line2"))


def show_quiet_hours() -> None:
    """Appelé depuis app/nfc_controller.py quand un tag reconnu est posé
    en dehors de la plage horaire autorisée (Réglages → Horaires,
    app/settings.py::is_allowed_now() — existait déjà, jamais appelé
    nulle part avant ce jour). Ne bloque QUE le lancement d'une nouvelle
    histoire par tag ; une lecture déjà en cours n'est jamais interrompue
    par ce mécanisme."""
    _show_temporary(t("lcd.quiet_hours_line1"), t("lcd.quiet_hours_line2"))


def show_volume(level: int) -> None:
    """Appelé à chaque Volume +/- (voir app/controls/actions.py) — un
    petit bandeau de niveau, retour immédiat sans avoir à deviner en
    écoutant."""
    filled = round(LCD_COLS * max(0, min(100, level)) / 100)
    bar = "█" * filled + "░" * (LCD_COLS - filled)
    _show_temporary(f"{t('lcd.volume_label')} : {level}%", bar, seconds=1.5)


def show_shutdown_message() -> None:
    """Appelé juste avant l'extinction (voir app/system_control.py) — un
    dernier mot avant que l'écran ne s'éteigne avec le reste de la boîte.
    Délai volontairement long (30s) : la boîte sera de toute façon
    éteinte pour de vrai bien avant, inutile de calculer un délai précis
    ici."""
    _show_temporary(t("lcd.shutdown_line1"), t("lcd.shutdown_line2"), seconds=30)


def plain(text: str) -> str:
    """Retire les accents : l'écran ne connaît que les lettres simples, un
    « é » y deviendrait un signe sans rapport."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("œ", "oe").replace("Œ", "OE").replace("’", "'").replace("«", '"').replace("»", '"')


def show_message(key1: str, key2: str = "", seconds: float = MESSAGE_DISPLAY_SECONDS, **values) -> None:
    """Affiche quelques secondes un message désigné par ses clés de
    traduction (voir app/i18n.py, « lcd.… »). Les valeurs nommées
    remplacent les repères {n} du texte. Rallume l'écran s'il était éteint."""
    def line(key: str) -> str:
        if not key:
            return ""
        text = t(key)
        if values:
            try:
                text = text.format(**values)
            except (KeyError, IndexError, ValueError):
                pass
        return text
    mark_activity()
    _show_temporary(line(key1), line(key2), seconds=seconds)


def set_sticky(line1: str, line2: str = "") -> None:
    """Tient ce message à l'écran jusqu'à clear_sticky() — avancement d'un
    import. Un message temporaire (volume, réseau) passe quand même devant."""
    global _sticky_lines
    mark_activity()
    with _lock:
        _sticky_lines = (plain(line1), plain(line2))


def clear_sticky() -> None:
    global _sticky_lines
    with _lock:
        _sticky_lines = None


def set_idle_hint(key1: Optional[str], key2: str = "") -> None:
    """Remplace l'écran d'attente tant qu'une clé USB est branchée. Passer
    None pour revenir à l'attente habituelle."""
    global _idle_hint
    with _lock:
        _idle_hint = (key1, key2) if key1 else None


def _network_lines(summary: dict) -> tuple:
    mode = summary["mode"]
    if mode == "essai":
        return t("lcd.net_trying"), summary["ssid"]
    if mode == "ok":
        return t("lcd.net_ok"), summary["ip"]
    if mode == "echec":
        return t("lcd.net_failed_line1"), t("lcd.net_failed_line2")
    if mode == "secours":
        return t("lcd.net_fallback"), summary["ssid"]
    if mode == "wifi":
        return t("lcd.net_home"), summary["ip"]
    if mode == "filaire":
        return t("lcd.net_wired"), summary["ip"]
    return t("lcd.net_none"), ""


def _poll_network() -> None:
    """Relit l'état du réseau toutes les NETWORK_POLL_SECONDS et l'affiche
    quelques secondes quand il change. Tourne même sans écran branché : il
    range aussi les réglages après un essai de Wifi refusé (voir
    app/network_apply.py::reconcile_after_trial)."""
    global _network, _network_shown, _next_network_poll
    now = time.monotonic()
    if now < _next_network_poll:
        return
    _next_network_poll = now + NETWORK_POLL_SECONDS

    from app.network_apply import reconcile_after_trial
    from app.network_status import lcd_summary

    reconcile_after_trial()
    summary = lcd_summary()
    _network = summary
    signature = (summary["mode"], summary["ssid"], summary["ip"])
    if signature != _network_shown:
        _network_shown = signature
        mark_activity()  # rallume le rétroéclairage : l'information doit se voir
        _show_temporary(*_network_lines(summary), seconds=NETWORK_MESSAGE_SECONDS)


def _idle_lines() -> tuple:
    """Écran d'attente. Sur le réseau de secours, il alterne toutes les 4
    secondes avec le nom du réseau puis son mot de passe : sans cela, une
    personne qui reçoit la boîte n'a aucun moyen de savoir comment s'y relier."""
    if _network.get("mode") in ("secours", "echec"):
        phase = int(time.monotonic() / 4) % 3
        if phase == 1:
            return t("lcd.net_fallback"), _network["ssid"]
        if phase == 2:
            return t("lcd.net_code"), _network["password"]
    hint = _idle_hint
    if hint:
        return t(hint[0]), (t(hint[1]) if hint[1] else "")
    return t("lcd.idle_line1"), t("lcd.idle_line2")


def _format_remaining(position_ms: int, duration_ms: int) -> str:
    remaining_s = max(0, (duration_ms - position_ms) // 1000)
    minutes, seconds = divmod(remaining_s, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _scrolled_title(title: str) -> str:
    """Fait défiler "title" dans une fenêtre de LCD_COLS caractères,
    comme un bandeau — un espace de séparation avant de reboucler au
    début. Reprend le défilement à zéro dès que le titre change (sinon
    l'offset d'un ancien titre, potentiellement plus long, resterait
    incohérent sur le nouveau)."""
    global _scroll_offset, _last_scrolled_title

    if title != _last_scrolled_title:
        _last_scrolled_title = title
        _scroll_offset = 0

    if len(title) <= LCD_COLS:
        return title

    padded = title + "   "
    window = (padded * 2)[_scroll_offset:_scroll_offset + LCD_COLS]
    _scroll_offset = (_scroll_offset + 1) % len(padded)
    return window


def _run() -> None:
    global _backlight_on, _last_error_text, _lcd_errors
    while True:
        try:
            _poll_network()
        except Exception as exc:
            print(f"[écran] état du réseau illisible : {exc}")

        try:
            backlight_timeout = _settings_manager.get_lcd_backlight_timeout()
            should_backlight_on = (time.monotonic() - _last_activity) < backlight_timeout

            if should_backlight_on != _backlight_on:
                _get_lcd().backlight_enabled = should_backlight_on
                _backlight_on = should_backlight_on

            if should_backlight_on:
                with _lock:
                    show_override = _override_lines if time.monotonic() < _override_until else None
                    sticky = _sticky_lines

                if show_override:
                    _write(*show_override)
                elif sticky:
                    _write(*sticky)
                else:
                    state = player_controller.get_state()
                    if state["kind"] is None:
                        _write(*_idle_lines())
                    else:
                        line1 = _scrolled_title(state["title"] or "")
                        status = t("lcd.status_playing") if state["is_playing"] else t("lcd.status_paused")
                        remaining = _format_remaining(state["position_ms"], state["duration_ms"])
                        _write(line1, f"{status} -{remaining}")
            # Rétroéclairage éteint : pas la peine de continuer à écrire du
            # texte invisible, juste attendre le prochain mark_activity().
            _last_error_text = ""
            _lcd_errors = 0
        except _LcdUnavailable:
            pass  # écran absent : déjà signalé une fois par _get_lcd()
        except Exception as exc:
            if isinstance(exc, OSError) and _lcd is not None:
                # Erreur d'entrée/sortie alors que l'écran était en service :
                # il a été débranché ou le contact est mauvais.
                _drop_lcd()
            text = str(exc)
            if text != _last_error_text:  # une seule ligne par erreur différente
                print(f"[écran] erreur d'affichage : {text}")
                _last_error_text = text

        time.sleep(REFRESH_INTERVAL)


def show_sleep_timer_end() -> None:
    """La minuterie de coucher vient de mettre la lecture en pause (voir
    app/player.py::_check_sleep_timer)."""
    show_message("lcd.sleep_line1", "lcd.sleep_line2", seconds=8)


def start() -> None:
    """Démarre l'affichage en tâche de fond (non bloquant)."""
    if show_sleep_timer_end not in player_controller.sleep_listeners:
        player_controller.sleep_listeners.append(show_sleep_timer_end)
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    print("Écran LCD actif.")
