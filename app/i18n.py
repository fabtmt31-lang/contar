"""
Traductions de l'interface : français (langue d'écriture), occitan, anglais.

tr("Texte en français") — utilisé partout dans l'administration web.
   Le texte français sert lui-même de clé : on écrit la page en français,
   et les traductions occitane et anglaise sont rangées dans
   app/i18n_texts.py (une ligne par texte). Un texte sans traduction
   s'affiche simplement en français — rien ne casse.
   Dans un gabarit Jinja : {{ _('Bibliothèque') }}
   Avec une valeur à insérer : {{ _('{n} éléments', n=3) }}

Note sur l'occitan : les traductions sont une base de bonne foi (graphie
classique, références languedociennes), à faire relire par un locuteur.
Pour corriger une formulation : app/i18n_texts.py.
"""

import re

from app.settings import SettingsManager

LANGUAGE_LABELS = {"fr": "Français", "oc": "Occitan", "en": "English"}


# ---- Administration web : le texte français sert de clé ----------------------

def current_language() -> str:
    """Langue choisie dans les réglages. Pendant l'affichage d'une page web,
    la valeur est lue une seule fois puis gardée le temps de la requête
    (une page contient plus d'une centaine de textes) ; ailleurs, elle est relue à chaque appel pour suivre un changement de
    réglage sans redémarrage."""
    try:
        from flask import g, has_request_context
        if has_request_context():
            if not hasattr(g, "contar_language"):
                g.contar_language = SettingsManager().get_language()
            return g.contar_language
    except ImportError:
        pass
    return SettingsManager().get_language()


def _build_tables():
    from app.i18n_texts import TEXTS
    oc, en = {}, {}
    for french, occitan, english in TEXTS:
        if occitan:
            oc[french] = occitan
        if english:
            en[french] = english
    return {"oc": oc, "en": en}


_TABLES = None


def tr(text: str, **values) -> str:
    """Traduit un texte écrit en français vers la langue choisie. Sans
    traduction connue, renvoie le texte français. Les valeurs nommées
    remplacent les repères {nom} du texte."""
    global _TABLES
    if _TABLES is None:
        _TABLES = _build_tables()
    language = current_language()
    if language != "fr":
        text = _TABLES.get(language, {}).get(text, text)
    if values:
        try:
            text = text.format(**values)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def tr_message(message: str) -> str:
    """Traduit un message produit ailleurs dans l'application (suppression,
    réseau, extinction…). Les messages fixes passent par tr() ; ceux qui
    contiennent un titre ou un nombre sont reconnus par les modèles de
    app/i18n_texts.py. Un message inconnu est renvoyé tel quel."""
    if not message or current_language() == "fr":
        return message
    translated = tr(message)
    if translated != message:
        return translated
    from app.i18n_texts import MESSAGE_PATTERNS
    for pattern, template in MESSAGE_PATTERNS:
        match = re.fullmatch(pattern, message)
        if match:
            return tr(template, **match.groupdict())
    return message
