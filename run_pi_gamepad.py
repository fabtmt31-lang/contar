"""
Lance le serveur web ET le contrôle par manette USB — variante pour le
vrai Raspberry Pi, sans câblage GPIO : une manette USB filaire type
NES/Super NES branchée sur le Pi fait office de boutons physiques.

app/controls/gamepad_controller.py ne dépend d'aucun matériel spécifique (il lit la manette via /dev/input,
comme n'importe quel périphérique USB), donc le même code fonctionne à
l'identique sur un Raspberry Pi.

Utilisez ce fichier à la place de run_pi.py tant que les boutons ne sont
pas câblés sur les GPIO (ou si vous préférez rester sur une manette USB
durablement, plus simple à mettre en place qu'un câblage). Le reste de
l'application (serveur web, lecteur, base de données) est strictement
identique quel que soit le point d'entrée utilisé — voir
app/controls/actions.py.

C'est ce fichier qu'installe install_pi.sh par défaut (mode "gamepad").
"""

from app.web import create_app
from run_common import start_box_services

app = create_app()

try:
    from app.controls.gamepad_controller import start as start_gamepad_controls
    start_gamepad_controls()
except Exception as exc:
    print(f"[i] Contrôle manette non démarré ({exc}).")
    print("    Installez la dépendance avec : pip install inputs")

start_box_services(on_box=True)

if __name__ == "__main__":
    from app.config import web_port
    app.run(host="0.0.0.0", port=web_port(on_box=True), debug=False, use_reloader=False)
