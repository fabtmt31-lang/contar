#!/usr/bin/env python3
"""
Fabrique les deux sons de l'import par clé USB (v0.9) : un bip court et un
carillon de fin. Sons de synthèse (sinusoïdes), comme ceux du démarrage et
du tag inconnu : rien à télécharger.

À relancer seulement pour changer ces sons :  python3 tools/make_sounds.py
"""

import math
import struct
import wave
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "sounds"


def tone(freq: float, seconds: float, volume: float = 0.5) -> list:
    count = int(RATE * seconds)
    fade = int(RATE * 0.012)
    samples = []
    for i in range(count):
        envelope = min(1.0, i / fade, (count - i) / fade)
        # Une touche d'harmonique pour un timbre moins sec qu'une sinusoïde pure.
        value = math.sin(2 * math.pi * freq * i / RATE) + 0.25 * math.sin(4 * math.pi * freq * i / RATE)
        samples.append(volume * envelope * value / 1.25)
    return samples


def bell(freq: float, seconds: float, volume: float = 0.5) -> list:
    count = int(RATE * seconds)
    attack = int(RATE * 0.006)
    samples = []
    for i in range(count):
        envelope = min(1.0, i / attack) * math.exp(-4.0 * i / count)
        samples.append(volume * envelope * math.sin(2 * math.pi * freq * i / RATE))
    return samples


def silence(seconds: float) -> list:
    return [0.0] * int(RATE * seconds)


def mix(base: list, extra: list, offset_seconds: float) -> list:
    start = int(RATE * offset_seconds)
    out = base + [0.0] * max(0, start + len(extra) - len(base))
    for i, value in enumerate(extra):
        out[start + i] += value
    return out


def save(name: str, samples: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        ))
    print(f"{name} : {len(samples) / RATE:.2f} s")


if __name__ == "__main__":
    save("beep.wav", silence(0.02) + tone(880.0, 0.13) + silence(0.05))
    chime = []
    for index, freq in enumerate((783.99, 987.77, 1174.66, 1567.98)):  # sol, si, ré, sol
        chime = mix(chime, bell(freq, 0.55, 0.42), 0.02 + index * 0.13)
    save("done.wav", chime + silence(0.05))
