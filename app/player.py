"""
Contrôleur central de lecture audio.

Portage de la logique de PlaybackService.kt + PlayerViewModel.kt, mais sans
l'aspect service/notification Android (pas nécessaire ici). Utilise VLC
(via python-vlc) plutôt qu'ExoPlayer, disponible aussi bien sur Windows
pour les tests que sur le Raspberry Pi en production.

Point clé d'architecture : ce module ne connaît ni l'interface web, ni le
clavier, ni les boutons GPIO. C'est volontaire — toutes ces entrées
appelleront les mêmes méthodes ci-dessous, ce qui garantit un état toujours
cohérent, quelle que soit l'origine de l'action (exactement le principe
évoqué dès le départ pour le "module contrôleur de lecture central").

Un seul média actif à la fois (un livre OU un morceau), comme sur la
version Android : lancer une nouvelle lecture remplace toujours la précédente.
"""

import math
import os
import platform
import random
import threading
import time
from typing import Literal, Optional

import vlc

from app.database import get_connection
from app.settings import SettingsManager

Kind = Literal["book", "track"]

SAVE_INTERVAL_SECONDS = 1.0
FINISHED_MARGIN_MS = 500          # identique au seuil utilisé côté Android
DEFAULT_VOLUME = 70
VOLUME_STEP = 10
SEEK_STEP_MS = 10_000              # 10 secondes, comme les boutons ⟲10/⟳10 d'origine
DOUBLE_TAP_WINDOW_SECONDS = 1.2    # fenêtre pour détecter un double appui rapide sur "précédent"
SLEEP_FADE_SECONDS = 15            # minuterie de coucher : le son baisse sur cette durée avant la pause

LAST_KIND_SETTING = "last_played_kind"
LAST_ITEM_SETTING = "last_played_item_id"


class PlayerController:
    def __init__(self) -> None:
        self._lock = threading.RLock()

        # Sur Linux (Raspberry Pi), on force explicitement la sortie audio
        # sur ALSA plutôt que de laisser VLC deviner (par défaut, il essaie
        # PulseAudio/PipeWire en premier). Le service tourne comme service
        # systemd sans session graphique/utilisateur ouverte, or PipeWire
        # (utilisé par défaut depuis Raspberry Pi OS Bookworm) ne démarre
        # que dans une vraie session utilisateur : sans lui, VLC "joue" en
        # silence (la position avance normalement, mais aucun son ne sort)
        # au lieu d'échouer franchement. --aout=alsa évite ce piège en
        # parlant directement au pilote de la carte son. Sans effet sur
        # Windows/Mac (mode PC de développement), où ce module n'existe
        # pas — VLC y garde son choix de sortie audio habituel.
        vlc_args = ["--no-video"]
        if os.environ.get("CONTAR_VLC_AOUT"):
            vlc_args.append(f"--aout={os.environ['CONTAR_VLC_AOUT']}")   # ex. « dummy » pour les tests
        elif platform.system() == "Linux":
            vlc_args.append("--aout=alsa")

        # ---- Minuterie de coucher (v0.10) ---------------------------------
        # Réglée dans Réglages → Minuterie (en minutes, 0 = désactivée). Elle
        # part à chaque lancement voulu — tag posé, bouton lecture, lecture
        # demandée depuis l'administration — et PAS quand un album ou une
        # liste enchaîne tout seul sur l'élément suivant (_sleep_auto). À
        # l'échéance, le son baisse sur SLEEP_FADE_SECONDS puis la lecture se
        # met en pause : l'histoire reprendra au même endroit.
        self._sleep_deadline: Optional[float] = None
        self._sleep_auto = False
        self._sleep_fade_from: Optional[int] = None   # volume d'avant la baisse, à rétablir
        # Fonctions appelées quand la minuterie arrête la lecture.
        self.sleep_listeners: list = []

        self._instance = vlc.Instance(*vlc_args)
        self._player: vlc.MediaPlayer = self._instance.media_player_new()
        self.set_volume(DEFAULT_VOLUME)
        self._equalizer = None      # gardé en mémoire tant qu'il est en service
        self.apply_tone()

        self._kind: Optional[Kind] = None
        self._item_id: Optional[int] = None
        self._title: str = ""
        self._subtitle: str = ""   # auteur (livre) ou artiste (morceau)
        self._duration_ms: int = 0
        self._last_back_press_at: float = 0.0

        # ---- Liste de lecture (playlist) en cours, le cas échéant --------
        # None tant qu'on lit un livre/morceau isolé depuis la bibliothèque.
        # Rempli par play_playlist() ; la file (_queue) contient des couples
        # (kind, item_id) dans l'ordre de lecture (mélangé si shuffle=True).
        self._playlist_id: Optional[int] = None
        self._queue: list[tuple[Kind, int]] = []
        self._queue_position: int = -1
        self._loop: bool = False
        self._shuffle: bool = False
        # Contexte de la file (v0.11) : "tag:<UID>" quand c'est un tag qui
        # l'a lancée (voir app/tag_playback.py), None sinon. Le lecteur ne
        # sait rien des tags : il transmet seulement ce repère à ceux qui
        # suivent l'avancement.
        self._context: Optional[str] = None
        # Appelées chaque seconde pendant la lecture avec snapshot(), et une
        # fois quand une file arrive à son terme (avec son contexte).
        self.progress_listeners: list = []
        self.queue_end_listeners: list = []

        self._stop_event = threading.Event()
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

    # ---- Chargement / lecture -------------------------------------------------

    def play(self, kind: Kind, item_id: int, *, from_playlist_id: Optional[int] = None) -> bool:
        """
        Charge et lance un livre ou un morceau, en reprenant sa position
        sauvegardée — sauf quand appelé depuis une liste de lecture
        (from_playlist_id renseigné), auquel cas l'appelant a déjà remis
        la position à zéro (voir play_playlist()/_advance_queue()) : une
        liste de lecture démarre toujours chaque élément depuis le début.
        """
        with self._lock:
            row = self._fetch_item(kind, item_id)
            if row is None:
                return False

            if from_playlist_id is None:
                # Lecture manuelle d'un livre/morceau isolé : on sort d'une
                # éventuelle file en cours (liste de lecture ou tag), sinon
                # elle reprendrait la main au prochain élément "terminé".
                already_loaded = self._kind == kind and self._item_id == item_id and not self._queue
                self._clear_queue()
                if already_loaded:
                    # Déjà chargé : on se contente de relancer la lecture, comme
                    # togglePlayPause côté Android quand isActive est déjà vrai.
                    self._persist_last_played(kind, item_id)
                    self._player.play()
                    self._arm_sleep_timer()
                    return True
            else:
                self._playlist_id = from_playlist_id
                self._context = None

            return self._load(row, kind, item_id, row["position_ms"] or 0)

    def _load(self, row, kind: Kind, item_id: int, start_ms: int) -> bool:
        """Remplace le média en cours par celui-ci et le lance à start_ms."""
        self._persist_last_played(kind, item_id)
        # On sauvegarde la progression de ce qui était en cours avant de le remplacer.
        self._save_progress()

        self._player.stop()
        media = self._instance.media_new(row["file_path"])
        self._player.set_media(media)
        self._kind = kind
        self._item_id = item_id
        self._title = row["title"]
        self._subtitle = row["author"] if kind == "book" else (row["artist"] or "")
        self._duration_ms = row["duration_ms"] or 0

        self._player.play()

        if start_ms > 0:
            # VLC a besoin d'un court instant après play() pour que set_time
            # soit pris en compte de façon fiable.
            time.sleep(0.1)
            self._player.set_time(start_ms)

        self._last_back_press_at = 0.0  # nouveau média : on oublie un éventuel double-appui en attente
        self._arm_sleep_timer()
        return True

    def _clear_queue(self) -> None:
        self._playlist_id = None
        self._queue = []
        self._queue_position = -1
        self._context = None

    def play_queue(self, queue: list, index: int = 0, position_ms: int = 0, *,
                   loop: bool = False, shuffle: bool = False, context: Optional[str] = None) -> bool:
        """
        Lance une file (v0.11) : une suite de (kind, item_id) déjà dans
        l'ordre voulu, à partir de l'élément « index », à « position_ms ».
        Utilisé par les tags (app/tag_playback.py), qui gardent eux-mêmes
        leur avancement : la position enregistrée dans le livre n'est pas
        utilisée ici. À la fin de la file : boucle (remélangée si
        « shuffle ») ou arrêt, puis queue_end_listeners.
        """
        with self._lock:
            if not queue:
                return False
            index = max(0, min(int(index), len(queue) - 1))
            kind, item_id = queue[index]
            row = self._fetch_item(kind, item_id)
            if row is None:
                return False
            self._queue = [(k, int(i)) for k, i in queue]
            self._queue_position = index
            self._loop = loop
            self._shuffle = shuffle
            self._playlist_id = None
            self._context = context
            return self._load(row, kind, item_id, max(0, int(position_ms)))

    def snapshot(self) -> Optional[dict]:
        """Où en est la file en cours (pour l'enregistrer), ou None si
        rien n'est chargé."""
        with self._lock:
            if self._kind is None:
                return None
            return {
                "context": self._context,
                "queue": list(self._queue),
                "index": self._queue_position,
                "kind": self._kind,
                "item_id": self._item_id,
                "position_ms": max(self._player.get_time(), 0),
                "is_playing": bool(self._player.is_playing()),
            }

    def current_context(self) -> Optional[str]:
        with self._lock:
            return self._context if self._kind is not None else None

    def fade_pause(self, seconds: float = 0.4) -> None:
        """Pause en douceur (tag retiré) : le son baisse en « seconds »,
        puis la lecture s'arrête et le volume est rétabli pour la reprise."""
        with self._lock:
            if self._kind is None or not self._player.is_playing():
                return
            start = self._player.audio_get_volume()
            steps = 8
            if start > 0:
                for step in range(steps, 0, -1):
                    self._player.audio_set_volume(int(start * (step - 1) / steps))
                    time.sleep(seconds / steps)
            self._player.pause()
            if start >= 0:
                self._player.audio_set_volume(start)
            self._disarm_sleep_timer()
            self._save_progress()

    def resume_with_rewind(self, rewind_ms: int = 0) -> bool:
        """Reprend ce qui est chargé, en reculant un peu pour retrouver le
        fil. False si rien n'est chargé."""
        with self._lock:
            if self._kind is None:
                return False
            if rewind_ms > 0:
                self._player.set_time(max(0, self._player.get_time() - rewind_ms))
            if not self._player.is_playing():
                self._player.play()
            self._arm_sleep_timer()
            return True

    def toggle_play_pause(self) -> None:
        """
        Bouton ▶️⏸️. Cas normal : bascule lecture/pause de ce qui est
        chargé. Cas particulier, après un redémarrage de la boîte (rien
        n'est encore chargé en mémoire, self._kind vaut None) : plutôt que
        de ne rien faire — ce qui obligeait auparavant à assigner un
        second bouton "Reprendre" (voir actions.py) rien que pour ce cas —
        ce même bouton relance directement la dernière lecture, à
        l'endroit exact où elle s'était arrêtée. Une seule pression
        suffit, quel que soit l'état au démarrage.
        """
        with self._lock:
            if self._kind is None:
                last = self.get_last_played()
                if last is not None:
                    self.play(last["kind"], last["item_id"])
                return
            if self._player.is_playing():
                self._player.pause()
                self._disarm_sleep_timer()
            else:
                self._player.play()
                self._arm_sleep_timer()

    def pause(self) -> None:
        with self._lock:
            if self._player.is_playing():
                self._player.pause()
                self._disarm_sleep_timer()

    def resume(self) -> None:
        with self._lock:
            if self._kind is not None and not self._player.is_playing():
                self._player.play()
                self._arm_sleep_timer()

    def stop(self) -> None:
        with self._lock:
            self._save_progress()
            self._player.stop()
            self._disarm_sleep_timer()
            self._kind = None
            self._item_id = None
            self._title = ""
            self._subtitle = ""
            self._duration_ms = 0
            self._clear_queue()

    # ---- Navigation -------------------------------------------------------

    def seek_relative(self, delta_ms: int) -> None:
        """Avance ou recule de delta_ms (négatif pour reculer)."""
        with self._lock:
            if self._kind is None:
                return
            current = max(self._player.get_time(), 0)
            target = max(current + delta_ms, 0)
            duration = self._current_duration_ms()
            if duration > 0:
                target = min(target, duration)
            self._player.set_time(target)

    def seek_to(self, position_ms: int) -> None:
        """Se positionne directement (utilisé quand on clique/glisse sur la barre d'avancement)."""
        with self._lock:
            if self._kind is None:
                return
            duration = self._current_duration_ms()
            target = max(0, min(position_ms, duration)) if duration > 0 else max(0, position_ms)
            self._player.set_time(target)

    def restart_current(self) -> None:
        """Relance le média actuel depuis le début, sans changer d'élément."""
        with self._lock:
            if self._kind is None:
                return
            self._player.set_time(0)

    def next_track(self) -> bool:
        """
        Passe au morceau suivant du même album (même ordre que le dossier
        d'origine). Sans effet pour un livre, ou si c'est déjà le dernier
        morceau de l'album.
        """
        with self._lock:
            if self._queue:
                return self._queue_step(+1)
            if self._kind != "track" or self._item_id is None:
                return False
            conn = get_connection()
            current = conn.execute(
                "SELECT album_id, order_index FROM tracks WHERE id = ?", (self._item_id,)
            ).fetchone()
            if current is None:
                conn.close()
                return False
            nxt = conn.execute(
                "SELECT id FROM tracks WHERE album_id = ? AND order_index > ? "
                "ORDER BY order_index ASC LIMIT 1",
                (current["album_id"], current["order_index"]),
            ).fetchone()
            conn.close()
            if nxt is None:
                return False
            return self.play("track", nxt["id"])

    def previous_track(self) -> bool:
        """Revient au morceau précédent du même album. Sans effet pour un livre."""
        with self._lock:
            if self._queue:
                return self._queue_step(-1)
            if self._kind != "track" or self._item_id is None:
                return False
            conn = get_connection()
            current = conn.execute(
                "SELECT album_id, order_index FROM tracks WHERE id = ?", (self._item_id,)
            ).fetchone()
            if current is None:
                conn.close()
                return False
            prev = conn.execute(
                "SELECT id FROM tracks WHERE album_id = ? AND order_index < ? "
                "ORDER BY order_index DESC LIMIT 1",
                (current["album_id"], current["order_index"]),
            ).fetchone()
            conn.close()
            if prev is None:
                return False
            return self.play("track", prev["id"])

    def _queue_step(self, delta: int) -> bool:
        """Élément suivant (+1) ou précédent (-1) de la file en cours."""
        target = self._queue_position + delta
        if target >= len(self._queue):
            if not self._loop:
                return False
            target = 0
        if target < 0:
            return False
        kind, item_id = self._queue[target]
        row = self._fetch_item(kind, item_id)
        if row is None:
            return False
        self._queue_position = target
        self._reset_position(kind, item_id)
        return self._load(row, kind, item_id, 0)

    def skip_forward(self) -> None:
        """Bouton ⟳ : morceau suivant pour une musique, avance de 10s pour un livre (inchangé)."""
        with self._lock:
            if self._kind == "track":
                self.next_track()
            elif self._kind == "book":
                self.seek_relative(SEEK_STEP_MS)

    def skip_back(self) -> None:
        """
        Bouton ⟲ : pour un livre, recule de 10s (comportement inchangé).
        Pour une musique, convention classique des lecteurs audio : un
        appui simple relance le morceau depuis le début, un double appui
        rapproché (moins de DOUBLE_TAP_WINDOW_SECONDS) revient au morceau
        précédent de l'album.
        """
        with self._lock:
            if self._kind == "book":
                self.seek_relative(-SEEK_STEP_MS)
                return
            if self._kind != "track":
                return

            now = time.monotonic()
            is_double_tap = (now - self._last_back_press_at) <= DOUBLE_TAP_WINDOW_SECONDS
            self._last_back_press_at = now

            if is_double_tap:
                self.previous_track()
            else:
                self.restart_current()

    # ---- Volume -------------------------------------------------------

    def set_volume(self, level: int) -> None:
        with self._lock:
            max_volume = SettingsManager().get_max_volume()
            level = max(0, min(max_volume, level))
            if self._sleep_fade_from is not None:
                # Pendant la baisse de fin de minuterie, on retient le volume
                # voulu : il sera rétabli après la pause.
                self._sleep_fade_from = level
                return
            self._player.audio_set_volume(level)

    def _user_volume(self) -> int:
        """Volume réglé par l'utilisateur — pas le volume momentanément
        baissé par la fin de la minuterie de coucher."""
        if self._sleep_fade_from is not None:
            return self._sleep_fade_from
        return self._player.audio_get_volume()

    def volume_up(self, step: int = VOLUME_STEP) -> None:
        with self._lock:
            self.set_volume(self._user_volume() + step)

    def volume_down(self, step: int = VOLUME_STEP) -> None:
        with self._lock:
            self.set_volume(self._user_volume() - step)

    # ---- Tonalité du haut-parleur (v0.10.3) ------------------------------------

    @staticmethod
    def tone_gain(frequency: float, bass: float, mid: float, treble: float) -> float:
        """Correction (en dB) à appliquer à cette fréquence pour ces trois
        réglages. Les graves agissent en plein sous 100 Hz et plus du tout
        au-dessus de 500 Hz ; les aigus, en plein au-dessus de 8 kHz et plus
        du tout sous 2 kHz ; les médiums, autour de 1 kHz (de 250 Hz à 4 kHz)."""
        def ramp(low: float, high: float) -> float:
            # 0 à « low », 1 à « high », progressif entre les deux (échelle des octaves)
            position = (math.log(frequency) - math.log(low)) / (math.log(high) - math.log(low))
            return max(0.0, min(1.0, position))

        bass_weight = 1.0 - ramp(100.0, 500.0)
        treble_weight = ramp(2000.0, 8000.0)
        mid_weight = min(ramp(250.0, 1000.0), 1.0 - ramp(1000.0, 4000.0))
        gain = bass * bass_weight + mid * mid_weight + treble * treble_weight
        return max(-15.0, min(15.0, gain))

    def apply_tone(self) -> None:
        """Applique le réglage de tonalité (Réglages → Volume et sortie audio)
        au lecteur, tout de suite, y compris sur une lecture en cours. Le
        réglage corrige le haut-parleur de la boîte : au casque ou en HDMI,
        le son reste tel quel. Best-effort : un souci avec l'égaliseur ne
        doit jamais empêcher la lecture."""
        with self._lock:
            try:
                settings = SettingsManager()
                tone = settings.get_tone()
                output = settings.get_audio_output() or {}
                on_speaker = output.get("kind", "gpio") in ("gpio", None, "")
                flat = not any(tone.values())
                if flat or not on_speaker:
                    self._player.set_equalizer(None)
                    self._equalizer = None
                    return
                equalizer = vlc.AudioEqualizer()
                loudest = 0.0
                for band in range(vlc.libvlc_audio_equalizer_get_band_count()):
                    frequency = vlc.libvlc_audio_equalizer_get_band_frequency(band)
                    gain = self.tone_gain(frequency, tone["bass"], tone["mid"], tone["treble"])
                    equalizer.set_amp_at_index(gain, band)
                    loudest = max(loudest, gain)
                # Une bande renforcée peut faire saturer le son : on baisse un
                # peu l'ensemble en proportion.
                equalizer.set_preamp(-0.6 * loudest)
                self._player.set_equalizer(equalizer)
                self._equalizer = equalizer
            except Exception as exc:
                print(f"[tonalité] réglage non appliqué : {exc}")

    # ---- Minuterie de coucher -------------------------------------------------

    def _arm_sleep_timer(self) -> None:
        """(Re)lance la minuterie. Sans effet pendant un enchaînement
        automatique : seul un lancement voulu remet le compteur à zéro."""
        if self._sleep_auto:
            return
        self._end_sleep_fade()
        try:
            minutes = SettingsManager().get_sleep_timer_minutes()
        except Exception:
            minutes = 0
        self._sleep_deadline = time.monotonic() + minutes * 60 if minutes > 0 else None

    def _disarm_sleep_timer(self) -> None:
        self._end_sleep_fade()
        self._sleep_deadline = None

    def _end_sleep_fade(self) -> None:
        if self._sleep_fade_from is not None:
            self._player.audio_set_volume(self._sleep_fade_from)
            self._sleep_fade_from = None

    def rearm_sleep_timer(self) -> None:
        """Après un changement du réglage : la nouvelle durée s'applique tout
        de suite à la lecture en cours."""
        with self._lock:
            if self._kind is not None and self._player.is_playing():
                self._arm_sleep_timer()
            else:
                self._disarm_sleep_timer()

    def sleep_remaining_seconds(self) -> Optional[int]:
        with self._lock:
            if self._sleep_deadline is None or self._kind is None or not self._player.is_playing():
                return None
            return max(0, int(self._sleep_deadline - time.monotonic() + 0.999))

    def _check_sleep_timer(self) -> None:
        """Appelée chaque seconde par _save_loop() pendant la lecture."""
        if self._sleep_deadline is None:
            return
        remaining = self._sleep_deadline - time.monotonic()
        if remaining > SLEEP_FADE_SECONDS:
            return
        if remaining > 0:
            if self._sleep_fade_from is None:
                current = self._player.audio_get_volume()
                if current < 0:
                    return      # volume inconnu de VLC à cet instant : pas de baisse, juste la pause
                self._sleep_fade_from = current
            self._player.audio_set_volume(max(0, int(self._sleep_fade_from * remaining / SLEEP_FADE_SECONDS)))
            return
        self._save_progress()
        self._player.pause()
        self._disarm_sleep_timer()
        print("[minuterie] délai écoulé : lecture mise en pause.")
        for listener in list(self.sleep_listeners):
            try:
                listener()
            except Exception as exc:
                print(f"[minuterie] {exc}")

    # ---- Listes de lecture -------------------------------------------------

    def play_playlist(self, playlist_id: int, shuffle: bool, loop: bool) -> bool:
        """
        Charge une liste de lecture et démarre son premier élément.
        Contrairement à play(), chaque élément d'une liste démarre
        toujours depuis le début (pas de reprise de position) — c'est le
        comportement attendu d'une playlist plutôt que d'une reprise
        individuelle de lecture.
        """
        conn = get_connection()
        rows = conn.execute(
            "SELECT kind, item_id FROM playlist_items WHERE playlist_id = ? ORDER BY order_index ASC",
            (playlist_id,),
        ).fetchall()
        conn.close()

        if not rows:
            return False

        queue: list[tuple[Kind, int]] = [(row["kind"], row["item_id"]) for row in rows]
        if shuffle:
            random.shuffle(queue)

        with self._lock:
            self._queue = queue
            self._queue_position = 0
            self._loop = loop
            self._shuffle = shuffle
            kind, item_id = queue[0]

        self._reset_position(kind, item_id)
        return self.play(kind, item_id, from_playlist_id=playlist_id)

    def play_album(self, album_id: int) -> bool:
        """
        Lance un album entier (utilisé par un tag NFC associé à un album,
        voir app/nfc_controller.py) en reprenant au premier morceau NON
        terminé dans l'ordre du dossier — ou depuis le tout début si
        l'album entier est déjà marqué terminé. Contrairement à
        play_playlist(), aucune notion de liste de lecture n'est créée
        ici : une fois lancé, l'enchaînement automatique au morceau
        suivant se fait exactement comme pour n'importe quelle musique
        isolée (voir next_track() et _save_loop() plus bas), l'album
        n'étant qu'un simple regroupement de morceaux par album_id.
        """
        conn = get_connection()
        row = conn.execute(
            "SELECT id FROM tracks WHERE album_id = ? AND finished = 0 "
            "ORDER BY order_index ASC LIMIT 1",
            (album_id,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM tracks WHERE album_id = ? ORDER BY order_index ASC LIMIT 1",
                (album_id,),
            ).fetchone()
        conn.close()

        if row is None:
            return False
        return self.play("track", row["id"])

    def _advance_queue(self) -> None:
        """
        Appelée quand l'élément en cours d'une file (liste de lecture ou
        tag) vient de se terminer naturellement : passe automatiquement au
        suivant. Respecte le mode aléatoire (déjà mélangé au lancement,
        remélangé à chaque tour en mode boucle, pour ne pas rejouer le même
        ordre en boucle) et le mode boucle (sinon, s'arrête proprement à la
        fin). Un élément supprimé entre-temps est sauté.
        """
        if not self._queue:
            return

        for _attempt in range(len(self._queue) + 1):
            self._queue_position += 1
            if self._queue_position >= len(self._queue):
                if not self._loop:
                    context = self._context
                    self.stop()
                    self._notify_queue_end(context)
                    return
                self._queue_position = 0
                if self._shuffle:
                    random.shuffle(self._queue)

            kind, item_id = self._queue[self._queue_position]
            row = self._fetch_item(kind, item_id)
            if row is None:
                continue
            self._reset_position(kind, item_id)
            if self._playlist_id is not None:
                self.play(kind, item_id, from_playlist_id=self._playlist_id)
            else:
                self._load(row, kind, item_id, 0)
            return
        context = self._context
        self.stop()
        self._notify_queue_end(context)

    def _notify_queue_end(self, context: Optional[str]) -> None:
        for listener in list(self.queue_end_listeners):
            try:
                listener(context)
            except Exception as exc:
                print(f"[lecteur] {exc}")

    def _reset_position(self, kind: Kind, item_id: int) -> None:
        """Remet un livre/morceau à zéro avant de le lancer depuis une
        liste de lecture (voir play_playlist()/_advance_queue())."""
        conn = get_connection()
        table = "books" if kind == "book" else "tracks"
        conn.execute(f"UPDATE {table} SET position_ms = 0, finished = 0 WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()

    # ---- État -------------------------------------------------------

    def get_state(self) -> dict:
        """
        État complet, pensé pour être directement renvoyé tel quel par
        l'interface web (étape 3) en JSON.
        """
        with self._lock:
            return {
                "kind": self._kind,
                "item_id": self._item_id,
                "title": self._title,
                "subtitle": self._subtitle,
                "is_playing": bool(self._player.is_playing()) if self._kind else False,
                "position_ms": max(self._player.get_time(), 0) if self._kind else 0,
                "duration_ms": self._current_duration_ms(),
                "volume": self._user_volume(),
                "playlist_id": self._playlist_id,
                "context": self._context,
                "queue_index": self._queue_position if self._queue else None,
                "queue_length": len(self._queue),
                "sleep_remaining_s": self.sleep_remaining_seconds(),
            }

    # ---- Sauvegarde automatique -------------------------------------------------

    def _current_duration_ms(self) -> int:
        # VLC ne connaît la durée réelle qu'une fois le média "parsé" ; en
        # attendant, on retombe sur la durée déjà stockée en base (issue des
        # tags lus à l'étape 1).
        length = self._player.get_length()
        return length if length > 0 else self._duration_ms

    def _fetch_item(self, kind: Kind, item_id: int):
        conn = get_connection()
        table = "books" if kind == "book" else "tracks"
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        return row

    def _persist_last_played(self, kind: Kind, item_id: int) -> None:
        conn = get_connection()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LAST_KIND_SETTING, kind),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (LAST_ITEM_SETTING, str(item_id)),
        )
        conn.commit()
        conn.close()

    def get_last_played(self) -> Optional[dict]:
        """
        Dernier livre/morceau joué, mémorisé même après redémarrage du
        serveur — utilisé par l'interface web pour afficher "reprendre la
        dernière lecture" tant que rien n'est activement en cours.
        """
        conn = get_connection()
        kind_row = conn.execute("SELECT value FROM settings WHERE key = ?", (LAST_KIND_SETTING,)).fetchone()
        item_row = conn.execute("SELECT value FROM settings WHERE key = ?", (LAST_ITEM_SETTING,)).fetchone()
        conn.close()
        if kind_row is None or item_row is None:
            return None
        return {"kind": kind_row["value"], "item_id": int(item_row["value"])}

    def _save_progress(self) -> bool:
        """Sauvegarde la position courante en base. Retourne True si
        l'élément est arrivé à sa fin (utilisé par _save_loop() pour
        déclencher l'avance automatique dans une liste de lecture)."""
        if self._kind is None or self._item_id is None:
            return False
        position_ms = max(self._player.get_time(), 0)
        duration_ms = self._current_duration_ms()
        if self._player.get_state() == vlc.State.Ended:
            position_ms = duration_ms
            finished = True
        else:
            finished = duration_ms > 0 and position_ms >= duration_ms - FINISHED_MARGIN_MS

        conn = get_connection()
        table = "books" if self._kind == "book" else "tracks"
        conn.execute(
            f"UPDATE {table} SET position_ms = ?, finished = ? WHERE id = ?",
            (position_ms, int(finished), self._item_id),
        )
        conn.commit()
        conn.close()
        return finished

    def _save_loop(self) -> None:
        """
        Sauvegarde la position toutes les secondes tant qu'une lecture est
        active, comme startProgressLoop côté Android : si la boîte est
        débranchée brutalement, l'histoire reprendra quasiment où elle
        s'était arrêtée. C'est aussi ici qu'on détecte la fin naturelle
        d'un élément pour enchaîner automatiquement sur le suivant d'une
        liste de lecture, le cas échéant.
        """
        while not self._stop_event.is_set():
            with self._lock:
                # « Ended » : VLC a atteint la fin du fichier et ne joue plus.
                # Avant la v0.11, seul « en lecture » était surveillé : la fin
                # n'était vue que si ce tour tombait dans la dernière
                # demi-seconde, et un album s'arrêtait une fois sur deux.
                ended = self._kind is not None and self._player.get_state() == vlc.State.Ended
                if self._kind is not None and (self._player.is_playing() or ended):
                    finished = self._save_progress()
                    if finished:
                        # Enchaînement automatique : il ne relance pas la
                        # minuterie de coucher (voir _arm_sleep_timer()).
                        self._sleep_auto = True
                        try:
                            if self._queue:
                                self._advance_queue()
                            elif self._kind == "track":
                                # Comportement par défaut pour la musique (hors
                                # liste de lecture) : enchaîner sur la piste
                                # suivante du même dossier/album, comme un
                                # lecteur audio classique. Sans effet si c'est
                                # déjà la dernière piste de l'album.
                                self.next_track()
                        finally:
                            self._sleep_auto = False
                    if self._kind is not None and self._player.is_playing():
                        self._check_sleep_timer()
                    snapshot = self.snapshot() if self.progress_listeners else None
                else:
                    snapshot = None
            if snapshot is not None:
                for listener in list(self.progress_listeners):
                    try:
                        listener(snapshot)
                    except Exception as exc:
                        print(f"[lecteur] {exc}")
            time.sleep(SAVE_INTERVAL_SECONDS)

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._save_progress()
            self._end_sleep_fade()
            self._player.stop()


# Instance unique partagée par toute l'application (web, clavier, GPIO...).
player_controller = PlayerController()
