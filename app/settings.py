"""
Portage direct de SettingsManager.kt.

Une différence volontaire par rapport à la version Android : le réglage
"child_security_enabled" (qui désactivait à la fois le PIN et le mode
kiosque) n'a plus lieu d'être ici, puisqu'il n'y a plus ni écran tactile
ni mode kiosque à désactiver - seul le PIN d'accès à l'interface web
subsiste, et il reste toujours actif.
"""

import socket
import json
from dataclasses import dataclass

from app.database import get_connection


def _get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def _set_setting(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


@dataclass
class DaySchedule:
    """Une plage horaire pour un jour de la semaine (0 = lundi ... 6 = dimanche)."""
    enabled: bool = False  # False = pas de restriction ce jour-là
    start_hour: int = 8
    end_hour: int = 20


class SettingsManager:
    # ---- Minuterie de coucher ------------------------------------------------

    def get_sleep_timer_minutes(self) -> int:
        return int(_get_setting("sleep_timer_minutes", "0"))

    def set_sleep_timer_minutes(self, minutes: int) -> None:
        _set_setting("sleep_timer_minutes", str(minutes))

    # ---- Plages horaires d'autorisation, par jour -----------------------------

    def get_day_schedule(self, day: int) -> DaySchedule:
        conn = get_connection()
        row = conn.execute("SELECT * FROM day_schedules WHERE day = ?", (day,)).fetchone()
        conn.close()
        if row is None:
            return DaySchedule()
        return DaySchedule(
            enabled=bool(row["enabled"]),
            start_hour=row["start_hour"],
            end_hour=row["end_hour"],
        )

    def set_day_schedule(self, day: int, schedule: DaySchedule) -> None:
        conn = get_connection()
        conn.execute(
            "INSERT INTO day_schedules (day, enabled, start_hour, end_hour) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET enabled = excluded.enabled, "
            "start_hour = excluded.start_hour, end_hour = excluded.end_hour",
            (day, int(schedule.enabled), schedule.start_hour, schedule.end_hour),
        )
        conn.commit()
        conn.close()

    def is_allowed_now(self) -> bool:
        """
        True si l'application peut être utilisée maintenant, d'après la plage
        horaire du jour actuel (toujours True si aucune restriction n'est
        activée pour ce jour). Ne gère pas les plages traversant minuit,
        comme la version Android.
        """
        from datetime import datetime

        now = datetime.now()
        day = now.weekday()  # lundi=0 ... dimanche=6, déjà dans cette convention en Python
        schedule = self.get_day_schedule(day)
        if not schedule.enabled:
            return True
        return schedule.start_hour <= now.hour < schedule.end_hour

    # ---- Langue de l'interface -------------------------------------------------

    def get_language(self) -> str:
        return _get_setting("language", "fr")

    def set_language(self, language: str) -> None:
        _set_setting("language", language)

    # ---- Configuration réseau ---------------------------------------------
    # Enregistrée dès maintenant pour être prête, mais appliquée pour de vrai
    # uniquement au moment de l'installation sur le Raspberry Pi (étape 5).
    # Le mot de passe Wifi est stocké en clair : c'est nécessaire pour pouvoir
    # configurer NetworkManager plus tard, et il ne quitte jamais cette base
    # locale (rien n'est envoyé sur le réseau).

    def get_network_config(self) -> dict:
        return {
            # Le nom de la boîte est celui du système (choisi à la préparation
            # de la carte SD ou depuis Réglages → Réseau), jamais une valeur
            # par défaut : avant la v0.8, enregistrer la page Réseau
            # renommait la boîte en « histoiresdusoir » sans le dire.
            "hostname": socket.gethostname(),
            "wifi_ssid": _get_setting("net_wifi_ssid", ""),
            "wifi_password": _get_setting("net_wifi_password", ""),
            "ip_mode": _get_setting("net_ip_mode", "dhcp"),
            "static_ip": _get_setting("net_static_ip", ""),
            "static_netmask": _get_setting("net_static_netmask", "255.255.255.0"),
            "static_gateway": _get_setting("net_static_gateway", ""),
            "static_dns": _get_setting("net_static_dns", ""),
        }

    def set_network_config(
        self, hostname: str, wifi_ssid: str, wifi_password: str,
        ip_mode: str = "dhcp", static_ip: str = "", static_netmask: str = "255.255.255.0",
        static_gateway: str = "", static_dns: str = "",
    ) -> None:
        _set_setting("net_wifi_ssid", wifi_ssid)
        _set_setting("net_wifi_password", wifi_password)
        _set_setting("net_ip_mode", ip_mode)
        _set_setting("net_static_ip", static_ip)
        _set_setting("net_static_netmask", static_netmask)
        _set_setting("net_static_gateway", static_gateway)
        _set_setting("net_static_dns", static_dns)

    # ---- Configurateur boutons / manette -----------------------------------
    # "mode" vaut "gamepad" ou "gpio" : chacun a son propre plan de boutons
    # (codes bruts de la manette, ou numéros de broche GPIO), donc son propre
    # mapping enregistré séparément. Le mode actif est renseigné tout seul,
    # au démarrage, par le contrôleur qui se lance réellement (voir
    # app/controls/gamepad_controller.py et gpio_controller.py) — pas besoin
    # de le régler à la main.

    def get_control_mode(self) -> str | None:
        return _get_setting("control_mode")

    def set_control_mode(self, mode: str) -> None:
        _set_setting("control_mode", mode)

    def get_control_mapping(self, mode: str) -> dict | None:
        """None si rien n'a encore été enregistré pour ce mode (première
        utilisation) — l'appelant retombe alors sur les réglages d'usine."""
        raw = _get_setting(f"control_mapping_{mode}")
        return json.loads(raw) if raw else None

    def set_control_mapping(self, mode: str, mapping_data: dict) -> None:
        _set_setting(f"control_mapping_{mode}", json.dumps(mapping_data))

    # ---- Sortie audio active (informatif : la config réelle vit dans
    # /etc/asound.conf, voir app/audio_output.py — ceci sert juste à
    # afficher "sortie actuelle" sans reparser ce fichier) ----------------

    def get_audio_output(self) -> dict | None:
        raw = _get_setting("audio_output")
        return json.loads(raw) if raw else None

    def set_audio_output(self, kind: str, label: str, alsa_target: str) -> None:
        _set_setting("audio_output", json.dumps({"kind": kind, "label": label, "alsa_target": alsa_target}))

    # ---- Préférence de sortie audio (gpio / hdmi1 / hdmi2) ------------------
    # Choisie via le sélecteur de Réglages → Sortie audio. Distincte de
    # get_audio_output() ci-dessus, qui reflète la sortie RÉELLEMENT
    # appliquée à cet instant : un jack (adaptateur USB) branché prend
    # toujours le dessus sur cette préférence (voir
    # app/audio_output.py::resolve_effective_output(), appliqué en continu
    # par bin/audio_output_watchdog.py) — la préférence n'est utilisée que
    # pour départager gpio/hdmi1/hdmi2 quand AUCUN jack n'est branché.
    # "gpio" par défaut (haut-parleurs intégrés de la boîte).

    def get_audio_output_preference(self) -> str:
        return _get_setting("audio_output_preference", "gpio")

    def set_audio_output_preference(self, kind: str) -> None:
        _set_setting("audio_output_preference", kind)

    # ---- Réglage Énergie (Réglages → Énergie) -------------------------------
    # Stockage du choix du parent ici, même découpage que la sortie audio
    # ci-dessus : l'application réelle au système (vcgencmd, gouverneur
    # CPU) vit dans app/power_settings.py, pas ici. Par défaut : HDMI
    # éteint (économie d'énergie/chaleur — y compris sur une boîte qui
    # utiliserait déjà HDMI pour le son : voir
    # power_settings.resolve_effective_hdmi(), qui rallume automatiquement
    # l'HDMI dans ce cas précis, jamais coupé pour de vrai sans que le
    # parent l'ait choisi explicitement) ; mode éco CPU activé par défaut.

    def get_power_hdmi_enabled(self) -> bool:
        return _get_setting("power_hdmi_enabled", "0") == "1"

    def set_power_hdmi_enabled(self, enabled: bool) -> None:
        _set_setting("power_hdmi_enabled", "1" if enabled else "0")

    def get_power_eco_mode(self) -> bool:
        return _get_setting("power_eco_mode", "1") == "1"

    def set_power_eco_mode(self, enabled: bool) -> None:
        _set_setting("power_eco_mode", "1" if enabled else "0")

    # ---- Plafond de volume (Réglages → Général) -----------------------------
    # Lu par PlayerController.set_volume() (app/player.py) à chaque
    # ajustement — un changement ici s'applique donc immédiatement, sans
    # redémarrage, y compris pendant une lecture déjà en cours (le volume
    # en place redescend au plafond dès le prochain Volume +/-, pas
    # forcément tout de suite si le volume actuel était déjà en dessous).

    def get_max_volume(self) -> int:
        return int(_get_setting("max_volume", "100"))

    def set_max_volume(self, level: int) -> None:
        _set_setting("max_volume", str(max(0, min(100, level))))

    # ---- Point d'accès Wifi de secours ("Wifi Direct") ---------------------
    # Se déclenche tout seul (via un service système à part, voir
    # app/wifi_fallback.py) quand la boîte n'arrive pas à rejoindre le Wifi
    # de la maison — c'est le SEUL moyen d'atteindre l'interface web d'une
    # boîte qui n'a encore jamais été configurée, ou qui vient de sortir
    # d'une réinitialisation usine.
    #
    # Retour de test réel : un mot de passe généré au hasard (comme avant)
    # rend ce point d'accès inutilisable la toute première fois — il
    # faudrait déjà être connecté à l'interface web (Réglages → Réseau)
    # pour le lire, ce qui suppose justement d'être DÉJÀ connecté au Wifi.
    # Pour une personne lambda qui déballe la boîte ou vient de faire un
    # reset usine, ce mot de passe doit donc être connu D'AVANCE et rester
    # le même à chaque fois — d'où une valeur fixe, identique sur toutes
    # les installations, documentée dans le guide fourni avec la boîte
    # (voir DEFAULT_WIFI_FALLBACK_PASSWORD ci-dessous). Elle reste ensuite
    # modifiable par un parent depuis Réglages → Réseau, comme avant — ce
    # n'est qu'une valeur de départ, pas une contrainte permanente.

    DEFAULT_WIFI_FALLBACK_SSID = "Contar-Secours"
    DEFAULT_WIFI_FALLBACK_PASSWORD = "audiolibre"  # 10 caractères, 8 au moins requis en WPA2
    # Valeurs par défaut d'avant la v0.8 : remplacées par les nouvelles à
    # la lecture, pour qu'une boîte mise à jour annonce bien « Contar-Secours ».
    _OLD_FALLBACK_SSID = "HistoiresDuSoir-Secours"
    _OLD_FALLBACK_PASSWORD = "histoiresdusoir"

    def get_wifi_fallback_config(self) -> dict:
        password = _get_setting("wifi_fallback_password")
        if not password or password == self._OLD_FALLBACK_PASSWORD:
            password = self.DEFAULT_WIFI_FALLBACK_PASSWORD
            _set_setting("wifi_fallback_password", password)
        ssid = _get_setting("wifi_fallback_ssid", self.DEFAULT_WIFI_FALLBACK_SSID)
        if ssid == self._OLD_FALLBACK_SSID:
            ssid = self.DEFAULT_WIFI_FALLBACK_SSID
            _set_setting("wifi_fallback_ssid", ssid)
        return {
            "enabled": _get_setting("wifi_fallback_enabled", "1") == "1",
            "ssid": ssid,
            "password": password,
        }

    # ---- Essai d'un nouveau Wifi (voir app/network_apply.py) ---------------
    # Le Wifi saisi n'est adopté qu'après un essai réussi. En attendant, on
    # garde de côté le réglage précédent pour pouvoir y revenir.

    def remember_previous_wifi(self) -> None:
        _set_setting("net_wifi_prev_ssid", _get_setting("net_wifi_ssid", ""))
        _set_setting("net_wifi_prev_password", _get_setting("net_wifi_password", ""))

    def restore_previous_wifi(self) -> None:
        _set_setting("net_wifi_ssid", _get_setting("net_wifi_prev_ssid", ""))
        _set_setting("net_wifi_password", _get_setting("net_wifi_prev_password", ""))

    def get_last_handled_trial(self) -> str:
        return _get_setting("net_wifi_trial_handled", "")

    def set_last_handled_trial(self, stamp: str) -> None:
        _set_setting("net_wifi_trial_handled", stamp)

    def set_wifi_fallback_config(self, enabled: bool, ssid: str, password: str) -> None:
        _set_setting("wifi_fallback_enabled", "1" if enabled else "0")
        _set_setting("wifi_fallback_ssid", ssid)
        _set_setting("wifi_fallback_password", password)

    # ---- Tonalité du haut-parleur (v0.10.3) ---------------------------------
    # Trois curseurs, de -12 à +12 dB : graves, médiums, aigus. Appliqués
    # par le lecteur (app/player.py::apply_tone) quand le son sort par le
    # haut-parleur de la boîte — pas au casque ni en HDMI.

    TONE_BANDS = ("bass", "mid", "treble")
    TONE_LIMIT = 12

    def get_tone(self) -> dict:
        tone = {}
        for band in self.TONE_BANDS:
            try:
                value = int(_get_setting(f"tone_{band}", "0") or 0)
            except ValueError:
                value = 0
            tone[band] = max(-self.TONE_LIMIT, min(self.TONE_LIMIT, value))
        return tone

    def set_tone(self, bass: int, mid: int, treble: int) -> None:
        for band, value in zip(self.TONE_BANDS, (bass, mid, treble)):
            value = max(-self.TONE_LIMIT, min(self.TONE_LIMIT, int(value)))
            _set_setting(f"tone_{band}", str(value))

    # ---- Geste du tag (v0.11) ----------------------------------------------
    # Poser un tag lance la lecture, le retirer la met en pause. Le reposer
    # dans les « tag_double_window » secondes qui suivent le retrait remet
    # l'avancement de ce tag à zéro (voir app/tag_gesture.py).

    def get_tag_double_enabled(self) -> bool:
        return _get_setting("tag_double_enabled", "1") == "1"

    def get_tag_double_window(self) -> float:
        try:
            return max(1.0, min(10.0, float(_get_setting("tag_double_window", "3"))))
        except ValueError:
            return 3.0

    def set_tag_gesture(self, double_enabled: bool, window_seconds: float) -> None:
        _set_setting("tag_double_enabled", "1" if double_enabled else "0")
        _set_setting("tag_double_window", str(max(1.0, min(10.0, float(window_seconds)))))

    # ---- Veille et extinction automatiques (v0.11) ---------------------------
    # Comptées à partir du moment où plus rien ne joue et où aucun tag n'est
    # posé (voir app/power_manager.py). 0 = jamais.

    def get_idle_standby_minutes(self) -> int:
        return int(_get_setting("idle_standby_minutes", "1"))

    def get_idle_shutdown_minutes(self) -> int:
        return int(_get_setting("idle_shutdown_minutes", "15"))

    def set_idle_delays(self, standby_minutes: int, shutdown_minutes: int) -> None:
        _set_setting("idle_standby_minutes", str(max(0, min(240, int(standby_minutes)))))
        _set_setting("idle_shutdown_minutes", str(max(0, min(720, int(shutdown_minutes)))))

    # ---- Wi-Fi activé ou coupé (v0.11) ---------------------------------------
    # Le câble USB-C suffit à régler la boîte : le Wi-Fi devient un choix.

    def get_wifi_enabled(self) -> bool:
        return _get_setting("wifi_enabled", "1") == "1"

    def set_wifi_enabled(self, enabled: bool) -> None:
        _set_setting("wifi_enabled", "1" if enabled else "0")

    # ---- Mise à jour depuis GitHub (v0.11) -----------------------------------

    DEFAULT_UPDATE_REPO = "fabtmt31-lang/contar"

    def get_update_repo(self) -> str:
        return _get_setting("update_repo", self.DEFAULT_UPDATE_REPO) or self.DEFAULT_UPDATE_REPO

    def get_update_token(self) -> str:
        return _get_setting("update_token", "") or ""

    def set_update_source(self, repo: str, token: str | None) -> None:
        _set_setting("update_repo", repo.strip() or self.DEFAULT_UPDATE_REPO)
        if token is not None:
            _set_setting("update_token", token.strip())

    # ---- Assistant de première configuration ("bienvenue") -----------------
    # Se déclenche après une réinitialisation usine (voir app/factory_reset.py)
    # pour forcer la création d'un vrai code PIN + proposer le Wifi + montrer
    # quelques diapos d'explication, avant de rendre la main sur l'appli.
    #
    # Par défaut (clé absente = "0" = PAS en attente) : une boîte déjà en
    # service AVANT l'introduction de cette fonctionnalité ne doit JAMAIS se
    # voir imposer cet assistant après une simple mise à jour du code — seule
    # une réinitialisation usine explicite pose cette clé à "1".

    def is_onboarding_pending(self) -> bool:
        return _get_setting("onboarding_pending", "0") == "1"

    def set_onboarding_pending(self, pending: bool) -> None:
        _set_setting("onboarding_pending", "1" if pending else "0")
