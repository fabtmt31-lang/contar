#!/usr/bin/env python3
"""
Vérifie les traductions de l'administration.

À lancer depuis la racine du projet :  python3 tools/check_i18n.py

Signale :
- les textes des pages (gabarits) qui n'ont pas de traduction occitane ou
  anglaise dans app/i18n_texts.py ;
- les textes présents deux fois dans app/i18n_texts.py ;
- les traductions qui auraient perdu un repère {n}, {title}…

Ne modifie rien. Renvoie un code d'erreur s'il manque quelque chose.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.i18n_texts import TEXTS  # noqa: E402

CALL = re.compile(r"""_\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def template_texts():
    found = {}
    for path in sorted((ROOT / "app" / "web" / "templates").glob("*.html")):
        for match in CALL.finditer(path.read_text(encoding="utf-8")):
            text = match.group(1) if match.group(1) is not None else match.group(2)
            text = text.replace("\\'", "'").replace('\\"', '"')
            found.setdefault(text, path.name)
    return found


def main() -> int:
    problems = 0
    known = {}
    for french, occitan, english in TEXTS:
        if french in known:
            print(f"EN DOUBLE   : {french!r}")
            problems += 1
        known[french] = (occitan, english)
        marks = set(re.findall(r"\{\w+\}", french))
        for name, translation in (("occitan", occitan), ("anglais", english)):
            if translation and set(re.findall(r"\{\w+\}", translation)) != marks:
                print(f"REPÈRE      : {french!r} ({name})")
                problems += 1

    for text, where in template_texts().items():
        if text not in known:
            print(f"SANS TRADUCTION ({where}) : {text!r}")
            problems += 1
        else:
            occitan, english = known[text]
            if not occitan:
                print(f"OCCITAN VIDE ({where}) : {text!r}")
                problems += 1
            if not english:
                print(f"ANGLAIS VIDE ({where}) : {text!r}")
                problems += 1

    print(f"{len(known)} textes traduits, {len(template_texts())} textes dans les pages, {problems} problème(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
