"""Geste de l'enfant (app/tag_gesture.py), avec une horloge simulée.

    python -m pytest tests/
"""

from app.tag_gesture import PAUSE, RESTART, START, TagGesture


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(window=3.0, enabled=True):
    clock = Clock()
    return TagGesture(lambda: window, lambda: enabled, clock), clock


def test_pose_retrait_pose_lente_reprend():
    gesture, clock = make()
    assert gesture.on_present("A") == START
    clock.now += 60
    assert gesture.on_absent("A") == PAUSE
    clock.now += 3.5
    assert gesture.on_present("A") == START


def test_double_pose_rapprochee_remet_a_zero():
    gesture, clock = make()
    gesture.on_present("A")
    clock.now += 10
    gesture.on_absent("A")
    clock.now += 1.2
    assert gesture.on_present("A") == RESTART


def test_limite_de_la_fenetre_incluse():
    gesture, clock = make(window=3.0)
    gesture.on_present("A")
    gesture.on_absent("A")
    clock.now += 3.0
    assert gesture.on_present("A") == RESTART


def test_autre_tag_ne_remet_pas_a_zero():
    gesture, clock = make()
    gesture.on_present("A")
    gesture.on_absent("A")
    clock.now += 0.5
    assert gesture.on_present("B") == START


def test_double_pose_desactivee():
    gesture, clock = make(enabled=False)
    gesture.on_present("A")
    gesture.on_absent("A")
    clock.now += 0.5
    assert gesture.on_present("A") == START


def test_retrait_d_un_tag_qui_n_est_pas_pose_ignore():
    gesture, _clock = make()
    gesture.on_present("A")
    assert gesture.on_absent("B") is None
    assert gesture.present_uid == "A"


def test_triple_pose_rapide_remet_a_zero_a_chaque_fois():
    gesture, clock = make()
    gesture.on_present("A")
    for _ in range(2):
        gesture.on_absent("A")
        clock.now += 1
        assert gesture.on_present("A") == RESTART


def test_forget_annule_la_double_pose():
    gesture, clock = make()
    gesture.on_present("A")
    gesture.on_absent("A")
    gesture.forget()
    clock.now += 1
    assert gesture.on_present("A") == START
