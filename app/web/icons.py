"""
Icônes de l'interface (charte Audiolibre) : des dessins au trait en SVG,
intégrés directement dans la page — aucune police d'icônes ni fichier
externe, donc rien à télécharger depuis Internet (la boîte doit rester
utilisable sur son point d'accès de secours).

Utilisation dans un gabarit Jinja : {{ icon('book') }} ou {{ icon('book', 24) }}
Pour ajouter une icône : une entrée de plus dans ICONS (dessin sur une
grille de 24 x 24, trait de 1.8).
"""

from markupsafe import Markup

ICONS = {
    # Navigation
    "headphones": '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="4.5" height="6.5" rx="1.5"/><rect x="16.5" y="14" width="4.5" height="6.5" rx="1.5"/>',
    "library": '<path d="M5 4v16"/><path d="M10 4v16"/><path d="M14.5 6l4.5 13.5"/>',
    "tag": '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M9.5 14.5a3.5 3.5 0 0 0 0-5"/><path d="M13 16.5a7 7 0 0 0 0-9"/>',
    "import": '<path d="M12 4v10"/><path d="M8 10l4 4 4-4"/><path d="M5 16v2.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V16"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "logout": '<path d="M14 4h4a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 18 20h-4"/><path d="M10 8l-4 4 4 4"/><path d="M6 12h9"/>',
    # Contenus
    "book": '<path d="M12 7c-2-1.5-5-1.8-8-1v12c3-.8 6-.5 8 1 2-1.5 5-1.8 8-1V6c-3-.8-6-.5-8 1z"/><path d="M12 7v12"/>',
    "music": '<path d="M9 17V5l10-2v12"/><ellipse cx="6.5" cy="17" rx="2.5" ry="2"/><ellipse cx="16.5" cy="15" rx="2.5" ry="2"/>',
    "list": '<path d="M8 7h11M8 12h11M8 17h11"/><path d="M4.5 7h.01M4.5 12h.01M4.5 17h.01"/>',
    "moon": '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>',
    # Lecture
    "play": '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
    "pause": '<rect x="7" y="5.5" width="3.5" height="13" rx="1" fill="currentColor"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1" fill="currentColor"/>',
    "back": '<path d="M4.5 12a7.5 7.5 0 1 0 2.4-5.5"/><path d="M4.5 4.5v4h4"/>',
    "forward": '<path d="M19.5 12a7.5 7.5 0 1 1-2.4-5.5"/><path d="M19.5 4.5v4h-4"/>',
    "prev": '<path d="M18 6v12l-9-6z" fill="currentColor"/><path d="M6.5 6v12"/>',
    "next": '<path d="M6 6v12l9-6z" fill="currentColor"/><path d="M17.5 6v12"/>',
    "volume-low": '<path d="M4 10v4h3.5L12 18V6L7.5 10z"/><path d="M15.5 10a3 3 0 0 1 0 4"/>',
    "volume-high": '<path d="M4 10v4h3.5L12 18V6L7.5 10z"/><path d="M15.5 9.5a3.5 3.5 0 0 1 0 5"/><path d="M18 7a7 7 0 0 1 0 10"/>',
    "shuffle": '<path d="M4 7h3.5c5 0 5 10 10 10H20"/><path d="M4 17h3.5c1.4 0 2.4-.8 3.2-1.9"/><path d="M13.3 8.9C14.1 7.8 15.1 7 16.5 7H20"/><path d="M17.5 4.500L20 7l-2.5 2.5"/><path d="M17.5 14.500L20 17l-2.5 2.5"/>',
    "repeat": '<path d="M5 11V9.500A2.5 2.5 0 0 1 7.5 7H19"/><path d="M16 4l3 3-3 3"/><path d="M19 13v1.500a2.5 2.5 0 0 1-2.5 2.500H5"/><path d="M8 20l-3-3 3-3"/>',
    # Actions
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "trash": '<path d="M5 7h14"/><path d="M9 7V5h6v2"/><path d="M7 7l1 12h8l1-12"/>',
    "up": '<path d="M6 14l6-6 6 6"/>',
    "down": '<path d="M6 10l6 6 6-6"/>',
    "chevron": '<path d="M9 6l6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "refresh": '<path d="M5 9a7.5 7.5 0 0 1 13.5-2"/><path d="M19 4v4h-4"/><path d="M19 15a7.5 7.5 0 0 1-13.5 2"/><path d="M5 20v-4h4"/>',
    "undo": '<path d="M9 6L5 10l4 4"/><path d="M5 10h9a5 5 0 0 1 0 10h-3"/>',
    # Réglages
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
    "folder": '<path d="M4 7.5A1.5 1.5 0 0 1 5.5 6H10l2 2h6.500A1.5 1.5 0 0 1 20 9.500v8a1.5 1.5 0 0 1-1.5 1.500h-13A1.5 1.5 0 0 1 4 17.500z"/>',
    "lock": '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "wifi": '<path d="M4 10a12 12 0 0 1 16 0"/><path d="M7 13.5a7.5 7.5 0 0 1 10 0"/><path d="M12 18h.01"/>',
    "gamepad": '<rect x="3" y="8" width="18" height="10" rx="4"/><path d="M7.5 11.5v3M6 13h3"/><path d="M15.5 12h.01M17.5 14h.01"/>',
    "speaker": '<rect x="6" y="3.5" width="12" height="17" rx="2.5"/><circle cx="12" cy="14" r="3"/><path d="M12 7.500h.01"/>',
    "battery": '<rect x="3" y="8" width="16" height="8" rx="2"/><path d="M21 11v2"/><path d="M6.5 11v2M9.5 11v2"/>',
    "storage": '<rect x="4" y="5" width="16" height="6" rx="1.5"/><rect x="4" y="13" width="16" height="6" rx="1.5"/><path d="M7.5 8h.01M7.5 16h.01"/>',
    "power": '<path d="M12 4v8"/><path d="M7 6.500a7 7 0 1 0 10 0"/>',
    "document": '<path d="M7 3.500h7l4 4V19a1.5 1.5 0 0 1-1.5 1.500h-9.500A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.500z"/><path d="M14 3.500v4h4"/><path d="M9 12.500h6M9 16h6"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.7 9.500a2.4 2.4 0 1 1 3.5 2.100c-.800.5-1.2 1-1.2 1.9"/><path d="M12 16.500h.01"/>',
    "warning": '<path d="M12 4l9 16H3z"/><path d="M12 10v4.500M12 17.500h.01"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.500c2.5 2.3 3.8 5.2 3.8 8.500s-1.3 6.2-3.8 8.500c-2.5-2.3-3.8-5.2-3.8-8.500s1.3-6.2 3.8-8.500z"/>',
    "phone": '<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="M11 18h2"/>',
    "display": '<rect x="3.5" y="5" width="17" height="11" rx="2"/><path d="M9 20h6M12 16v4"/>',
    "usb": '<rect x="7.5" y="9.500" width="9" height="11" rx="2"/><path d="M9.500 9.500V4h5v5.500"/><path d="M11 6.500h.01M13 6.500h.01"/>',
    "swap": '<path d="M4 8h14l-3.500-3.500"/><path d="M20 16H6l3.500 3.500"/>',
}


def icon(name: str, size: int = 20) -> Markup:
    """Renvoie le SVG d'une icône, prêt à insérer dans un gabarit. Une
    icône inconnue ne casse jamais la page : on affiche un simple point."""
    body = ICONS.get(name, '<circle cx="12" cy="12" r="2" fill="currentColor"/>')
    return Markup(
        f'<svg class="icon" width="{int(size)}" height="{int(size)}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" focusable="false">{body}</svg>'
    )


def logo(size: int = 56) -> Markup:
    """Logo Audiolibre décliné pour la boîte (teinte miel) : un livre
    ouvert dont la reliure se prolonge en note de musique."""
    return Markup(
        f'<svg class="logo" width="{int(size)}" height="{int(size)}" viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false">'
        '<path d="M32 30C26 25.5 17 24.5 8 27V50C17 47.5 26 48.5 32 54Z" fill="#F2C96A"/>'
        '<path d="M32 30C38 25.5 47 24.5 56 27V50C47 47.5 38 48.5 32 54Z" fill="#8A5F0B"/>'
        '<ellipse cx="26" cy="41.5" rx="8" ry="6" transform="rotate(-22 26 41.5)" fill="#22253A"/>'
        '<path d="M32 41V8" stroke="#22253A" stroke-width="3.6" stroke-linecap="round"/>'
        '<path d="M32 8C33.5 15 44.5 15 44 26C42.5 21 37.5 19.5 32 19.5Z" fill="#22253A" stroke="#22253A" stroke-width="1.6" stroke-linejoin="round"/>'
        '</svg>'
    )
