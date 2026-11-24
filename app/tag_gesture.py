"""
Le geste de l'enfant (v0.11), sans aucun matériel ni lecture : ce module
reçoit seulement « tel tag vient d'arriver » et « tel tag vient de
partir », et décide quoi faire. Il est ainsi testable seul
(tests/test_tag_gesture.py), avec une horloge simulée.

    poser                       -> START   (reprise où le tag en était)
    retirer                     -> PAUSE   (avancement enregistré)
    reposer dans la fenêtre     -> RESTART (avancement remis à zéro)
    reposer après la fenêtre    -> START

La fenêtre (3 s par défaut) part du retrait. Les micro-coupures du lecteur
(un tag qui glisse, une lecture ratée) sont filtrées en amont par le
lecteur lui-même (app/tag_reader.py) : ici, un retrait est un vrai retrait.
"""

import time
from typing import Callable, Optional

START = "start"
RESTART = "restart"
PAUSE = "pause"


class TagGesture:
    def __init__(
        self,
        window_seconds: Callable[[], float] = lambda: 3.0,
        double_enabled: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._double_enabled = double_enabled
        self._clock = clock
        self.present_uid: Optional[str] = None
        self._removed_uid: Optional[str] = None
        self._removed_at: Optional[float] = None

    def on_present(self, uid: str) -> str:
        now = self._clock()
        quick = (
            self._removed_uid == uid
            and self._removed_at is not None
            and now - self._removed_at <= self._window()
            and self._double_enabled()
        )
        self.present_uid = uid
        self._removed_uid = None
        self._removed_at = None
        return RESTART if quick else START

    def on_absent(self, uid: str) -> Optional[str]:
        """PAUSE si c'est bien le tag posé qui part, None sinon."""
        if uid != self.present_uid:
            return None
        self.present_uid = None
        self._removed_uid = uid
        self._removed_at = self._clock()
        return PAUSE

    def forget(self) -> None:
        """Oublie le dernier retrait (ex. tag inconnu, mode transfert)."""
        self._removed_uid = None
        self._removed_at = None
