"""
Lance le serveur web ET le contrôle par boutons GPIO — à utiliser sur le
Raspberry Pi. Sur PC pendant le développement, utilisez plutôt run.py
(contrôle clavier).
"""

from app.web import create_app
from app.controls.gpio_controller import start as start_gpio_controls
from run_common import start_box_services

app = create_app()
start_gpio_controls()
start_box_services(on_box=True)

if __name__ == "__main__":
    from app.config import web_port
    app.run(host="0.0.0.0", port=web_port(on_box=True), debug=False)
