"""
Traductions de l'interface : français (langue d'écriture), occitan, anglais.

Deux mécanismes cohabitent :

1. tr("Texte en français") — utilisé partout dans l'administration web.
   Le texte français sert lui-même de clé : on écrit la page en français,
   et les traductions occitane et anglaise sont rangées dans
   app/i18n_texts.py (une ligne par texte). Un texte sans traduction
   s'affiche simplement en français — rien ne casse.
   Dans un gabarit Jinja : {{ _('Bibliothèque') }}
   Avec une valeur à insérer : {{ _('{n} éléments', n=3) }}

2. t("lcd.idle_line1") — l'ancien système à clés, conservé pour l'écran
   LCD de la boîte (voir app/lcd_display.py), dont les messages sont
   limités à 16 caractères par ligne.

Les deux partagent le même réglage de langue (Réglages → Langue).

Note sur l'occitan : les traductions sont une base de bonne foi (graphie
classique, références languedociennes), à faire relire par un locuteur.
Pour corriger une formulation : app/i18n_texts.py pour l'administration,
TRANSLATIONS["oc"] ci-dessous pour l'écran LCD.
"""

import re

from app.settings import SettingsManager

TRANSLATIONS = {
    "fr": {
        "nav.lecture": "Lecture",
        "nav.livres": "Livres",
        "nav.musique": "Musique",
        "nav.listes": "Liste de lecture",
        "nav.reglages": "Réglages",
        "login.title": "Contar",
        "login.subtitle": "Entrez le code parent pour continuer",
        "login.submit": "Valider",
        "login.error": "Code incorrect, réessayez.",
        "login.hint": "Aucun code n'a encore été choisi : le code par défaut est 1234. Pensez à le changer dans les réglages.",
        "logout": "Déconnexion",
        "settings.title": "Réglages",
        "settings.general": "Général",
        "settings.language": "Langue de l'interface",
        "settings.shutdown": "Éteindre la boîte à histoires",
        "settings.shutdown_hint": "Il faudra débrancher puis rebrancher la boîte à histoires pour qu'elle refonctionne.",
        "settings.shutdown_confirm": "Éteindre la boîte maintenant ?",
        "settings.logout_button": "Se déconnecter",
        "settings.section_config": "Configuration",
        "settings.time": "Minuterie et plages horaires",
        "settings.categories": "Catégories",
        "settings.pin": "Code PIN",
        "settings.network": "Réseau",
        "settings.section_about": "À propos",
        "settings.legal": "Mentions légales",
        "settings.help": "Aide et utilisation",
        "settings.back": "← Réglages",
        "lcd.welcome_line1": "Bonjour !",
        "lcd.welcome_line2": "Boite prete !",
        "lcd.idle_line1": "En attente...",
        "lcd.idle_line2": "Posez un tag",
        "lcd.tag_scanned_label": "Tag reconnu :",
        "lcd.unknown_tag_line1": "Tag inconnu",
        "lcd.unknown_tag_line2": "Voir Reglages",
        "lcd.quiet_hours_line1": "Chut...",
        "lcd.quiet_hours_line2": "Pas maintenant",
        "lcd.volume_label": "Volume",
        "lcd.shutdown_line1": "A bientot !",
        "lcd.shutdown_line2": "Extinction...",
        "lcd.status_playing": "Lecture",
        "lcd.status_paused": "Pause",
        # État du réseau (v0.8) — 16 caractères au plus par ligne.
        "lcd.net_home": "Wifi maison",
        "lcd.net_fallback": "Wifi de secours",
        "lcd.net_code": "Code Wifi :",
        "lcd.net_trying": "Essai du Wifi",
        "lcd.net_ok": "Wifi OK",
        "lcd.net_failed_line1": "Echec du Wifi",
        "lcd.net_failed_line2": "Secours actif",
        "lcd.net_wired": "Reseau filaire",
        "lcd.net_none": "Pas de reseau",
        # Import par clé USB (v0.9) — 16 caractères au plus, sans accents.
        "lcd.import_reading": "Lecture cle...",
        "lcd.import_ready_line1": "Cle prete",
        "lcd.import_ready_line2": "Posez un tag",
        "lcd.import_unknown_key": "Cle non reconnue",
        "lcd.import_no_key": "Branchez une cle",
        "lcd.import_confirm_line1": "Remplacer tout ?",
        "lcd.import_confirm_line2": "Reposez le tag",
        "lcd.import_done_line1": "Import fini",
        "lcd.import_done_added": "{n} ajoutees",
        "lcd.import_done_both": "+{a} / -{r}",
        "lcd.import_remove_key": "Retirez la cle",
        "lcd.import_no_space_line1": "Pas assez",
        "lcd.import_no_space_line2": "de place",
        "lcd.import_nothing_line1": "Rien a importer",
        "lcd.import_nothing_line2": "Deja a jour",
        "lcd.import_busy_line1": "Import en cours",
        "lcd.import_busy_line2": "Patientez...",
        "lcd.import_stopped_line1": "Import arrete",
        "lcd.import_stopped_line2": "Rien de change",
        # Minuterie de coucher (v0.10)
        "lcd.sleep_line1": "Bonne nuit !",
        "lcd.sleep_line2": "Minuterie finie",
    },
    "oc": {
        "nav.lecture": "Lectura",
        "nav.livres": "Libres",
        "nav.musique": "Musica",
        "nav.listes": "Lista de lectura",
        "nav.reglages": "Reglatges",
        "login.title": "Istòrias del Ser",
        "login.subtitle": "Picatz lo còdi parent per contunhar",
        "login.submit": "Validar",
        "login.error": "Còdi incorrècte, tornatz ensajar.",
        "login.hint": "Cap de còdi es pas encara estat causit : lo còdi per defaut es 1234. Pensatz de lo cambiar dins los reglatges.",
        "logout": "Desconnexion",
        "settings.title": "Reglatges",
        "settings.general": "General",
        "settings.language": "Lenga de l'interfàcia",
        "settings.shutdown": "Atudar la bóstia d'istòrias",
        "settings.shutdown_hint": "Caldrà desbrancar puèi rebrancar la bóstia d'istòrias per que tòrne foncionar.",
        "settings.shutdown_confirm": "Atudar la bóstia ara ?",
        "settings.logout_button": "Se desconnectar",
        "settings.section_config": "Configuracion",
        "settings.time": "Minutariá e plajas horàrias",
        "settings.categories": "Categorias",
        "settings.pin": "Còdi PIN",
        "settings.network": "Ret",
        "settings.section_about": "A prepaus",
        "settings.legal": "Mencions legalas",
        "settings.help": "Ajuda e utilizacion",
        "settings.back": "← Reglatges",
        "lcd.welcome_line1": "Adiu pichon !",
        "lcd.welcome_line2": "Tot es prèst !",
        "lcd.idle_line1": "En espèra...",
        "lcd.idle_line2": "Pausatz un tag",
        "lcd.tag_scanned_label": "Tag reconegut",
        "lcd.unknown_tag_line1": "Tag desconegut",
        "lcd.unknown_tag_line2": "Vejatz Reglatges",
        "lcd.quiet_hours_line1": "Silenci...",
        "lcd.quiet_hours_line2": "Ora de dormir",
        "lcd.volume_label": "Volum",
        "lcd.shutdown_line1": "A lèu !",
        "lcd.shutdown_line2": "S'atuda...",
        "lcd.status_playing": "Lectura",
        "lcd.status_paused": "Pausa",
        # État du réseau (v0.8) — 16 caractères au plus par ligne.
        "lcd.net_home": "Wifi ostal",
        "lcd.net_fallback": "Wifi de secors",
        "lcd.net_code": "Còdi Wifi :",
        "lcd.net_trying": "Ensag del Wifi",
        "lcd.net_ok": "Wifi OK",
        "lcd.net_failed_line1": "Fracàs del Wifi",
        "lcd.net_failed_line2": "Secors actiu",
        "lcd.net_wired": "Ret filara",
        "lcd.net_none": "Cap de ret",
        # Import par clé USB (v0.9) — 16 caractères au plus, sans accents.
        "lcd.import_reading": "Lectura clau...",
        "lcd.import_ready_line1": "Clau presta",
        "lcd.import_ready_line2": "Pausatz un tag",
        "lcd.import_unknown_key": "Clau desconeguda",
        "lcd.import_no_key": "Brancatz la clau",
        "lcd.import_confirm_line1": "Remplacar tot ?",
        "lcd.import_confirm_line2": "Tornatz pausar",
        "lcd.import_done_line1": "Import acabat",
        "lcd.import_done_added": "{n} apondudas",
        "lcd.import_done_both": "+{a} / -{r}",
        "lcd.import_remove_key": "Levatz la clau",
        "lcd.import_no_space_line1": "Pas pro",
        "lcd.import_no_space_line2": "de placa",
        "lcd.import_nothing_line1": "Res a importar",
        "lcd.import_nothing_line2": "Ja a jorn",
        "lcd.import_busy_line1": "Import en cors",
        "lcd.import_busy_line2": "Esperatz...",
        "lcd.import_stopped_line1": "Import arrestat",
        "lcd.import_stopped_line2": "Res de cambiat",
        # Minuterie de coucher (v0.10)
        "lcd.sleep_line1": "Bona nueit !",
        "lcd.sleep_line2": "Minutaria finida",
    },
    "en": {
        "nav.lecture": "Now playing",
        "nav.livres": "Books",
        "nav.musique": "Music",
        "nav.listes": "Playlist",
        "nav.reglages": "Settings",
        "login.title": "Contar",
        "login.subtitle": "Enter the parent code to continue",
        "login.submit": "Confirm",
        "login.error": "Wrong code, try again.",
        "login.hint": "No code has been chosen yet: the default code is 1234. Remember to change it in the settings.",
        "logout": "Log out",
        "settings.title": "Settings",
        "settings.general": "General",
        "settings.language": "Interface language",
        "settings.shutdown": "Turn off the story box",
        "settings.shutdown_hint": "You will need to unplug the story box and plug it back in to use it again.",
        "settings.shutdown_confirm": "Turn off the box now?",
        "settings.logout_button": "Log out",
        "settings.section_config": "Configuration",
        "settings.time": "Sleep timer and allowed hours",
        "settings.categories": "Categories",
        "settings.pin": "PIN code",
        "settings.network": "Network",
        "settings.section_about": "About",
        "settings.legal": "Legal notice",
        "settings.help": "Help",
        "settings.back": "← Settings",
        "lcd.welcome_line1": "Hello!",
        "lcd.welcome_line2": "Box is ready!",
        "lcd.idle_line1": "Waiting...",
        "lcd.idle_line2": "Place a tag",
        "lcd.tag_scanned_label": "Tag found:",
        "lcd.unknown_tag_line1": "Unknown tag",
        "lcd.unknown_tag_line2": "See Settings",
        "lcd.quiet_hours_line1": "Shh...",
        "lcd.quiet_hours_line2": "Not right now",
        "lcd.volume_label": "Volume",
        "lcd.shutdown_line1": "See you soon!",
        "lcd.shutdown_line2": "Shutting down",
        "lcd.status_playing": "Playing",
        "lcd.status_paused": "Paused",
        # État du réseau (v0.8) — 16 caractères au plus par ligne.
        "lcd.net_home": "Home Wi-Fi",
        "lcd.net_fallback": "Backup Wi-Fi",
        "lcd.net_code": "Wi-Fi code:",
        "lcd.net_trying": "Trying Wi-Fi",
        "lcd.net_ok": "Wi-Fi OK",
        "lcd.net_failed_line1": "Wi-Fi failed",
        "lcd.net_failed_line2": "Backup active",
        "lcd.net_wired": "Wired network",
        "lcd.net_none": "No network",
        # Import par clé USB (v0.9) — 16 caractères au plus, sans accents.
        "lcd.import_reading": "Reading key...",
        "lcd.import_ready_line1": "Key ready",
        "lcd.import_ready_line2": "Place a tag",
        "lcd.import_unknown_key": "Unknown key",
        "lcd.import_no_key": "Plug in a key",
        "lcd.import_confirm_line1": "Replace all?",
        "lcd.import_confirm_line2": "Place tag again",
        "lcd.import_done_line1": "Import done",
        "lcd.import_done_added": "{n} added",
        "lcd.import_done_both": "+{a} / -{r}",
        "lcd.import_remove_key": "Remove the key",
        "lcd.import_no_space_line1": "Not enough",
        "lcd.import_no_space_line2": "space",
        "lcd.import_nothing_line1": "Nothing to add",
        "lcd.import_nothing_line2": "Up to date",
        "lcd.import_busy_line1": "Import running",
        "lcd.import_busy_line2": "Please wait...",
        "lcd.import_stopped_line1": "Import stopped",
        "lcd.import_stopped_line2": "Nothing changed",
        # Minuterie de coucher (v0.10)
        "lcd.sleep_line1": "Good night!",
        "lcd.sleep_line2": "Sleep timer",
    },
}

LANGUAGE_LABELS = {"fr": "Français", "oc": "Occitan", "en": "English"}


def t(key: str) -> str:
    language = SettingsManager().get_language()
    table = TRANSLATIONS.get(language, TRANSLATIONS["fr"])
    return table.get(key, TRANSLATIONS["fr"].get(key, key))


# ---- Administration web : le texte français sert de clé ----------------------

def current_language() -> str:
    """Langue choisie dans les réglages. Pendant l'affichage d'une page web,
    la valeur est lue une seule fois puis gardée le temps de la requête
    (une page contient plus d'une centaine de textes) ; ailleurs (écran
    LCD), elle est relue à chaque appel pour suivre un changement de
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
