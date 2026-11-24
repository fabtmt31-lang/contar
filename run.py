"""
Lance le serveur web ET le contrôle clavier — à utiliser sur PC pendant
le développement. Sur le vrai Raspberry Pi, utilisez run_pi.py à la place
(contrôle par boutons GPIO plutôt que clavier).

Lecteur NFC : un lecteur USB PC/SC (Omnikey…) par défaut. Sans lecteur,
CONTAR_NFC=simu permet de « poser » un tag depuis la ligne de commande :
  curl -X POST -H 'Content-Type: application/json' -d '{"uid":"04A1B2"}' http://127.0.0.1:5000/api/dev/tag
  curl -X POST -H 'Content-Type: application/json' -d '{"uid":null}'     http://127.0.0.1:5000/api/dev/tag
(il faut être connecté : la page de connexion d'abord, ou un cookie de session).

Le rechargement automatique de Flask (use_reloader) est désactivé ici :
avec lui, ce fichier s'exécute deux fois (processus superviseur + worker),
ce qui enregistrerait les raccourcis clavier deux fois. Relancez
manuellement le script après une modification de code.
"""

from app.web import create_app
from run_common import start_box_services

app = create_app()

try:
    from app.controls.keyboard_controller import start as start_keyboard_controls
    start_keyboard_controls()
except Exception as exc:
    print(f"[i] Contrôle clavier non démarré ({exc}).")
    print("    Installez-le avec : pip install keyboard")

start_box_services(on_box=False)

if __name__ == "__main__":
    from app.config import web_port
    app.run(host="0.0.0.0", port=web_port(on_box=False), debug=True, use_reloader=False)
