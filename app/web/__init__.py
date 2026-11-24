"""
Fabrique de l'application Flask (pattern "application factory").

Depuis la v0.8, l'administration est à la racine de la boîte :
http://contar.local (ou http://<adresse-de-la-boîte>). Les anciennes
adresses en /HDP/... renvoient vers les nouvelles.
"""

import secrets
from datetime import timedelta

import ipaddress
import socket

from flask import Flask, redirect, request

from app.database import get_connection, init_database

# Durée d'inactivité avant déconnexion automatique. Flask prolonge
# l'expiration à chaque requête par défaut, donc c'est bien 2h
# d'inactivité, pas 2h depuis la connexion.
SESSION_LIFETIME = timedelta(hours=2)


def _get_or_create_secret_key() -> str:
    """
    Clé utilisée pour signer les cookies de session. Générée une seule fois
    puis conservée en base, pour que les sessions ne soient pas invalidées
    à chaque redémarrage du serveur.
    """
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = 'flask_secret_key'").fetchone()
    if row is not None:
        conn.close()
        return row["value"]

    key = secrets.token_hex(32)
    conn.execute("INSERT INTO settings (key, value) VALUES ('flask_secret_key', ?)", (key,))
    conn.commit()
    conn.close()
    return key


def create_app() -> Flask:
    init_database()

    # Régénère le fichier miroir lu par le point d'accès de secours (Wifi
    # Direct, voir app/wifi_fallback.py) à chaque démarrage — y compris le
    # tout premier, avant même qu'un parent n'ait ouvert Réglages → Réseau.
    from app.wifi_fallback import sync_fallback_conf
    sync_fallback_conf()

    # Réapplique le dernier réglage Énergie enregistré (HDMI, mode éco
    # CPU) — sans quoi le Pi repartirait dans son état matériel par
    # défaut (HDMI allumé, gouverneur normal) à chaque redémarrage,
    # indépendamment de ce que le parent a choisi. Contrairement à la
    # sortie audio, pas de watchdog en continu ici : rien ne peut
    # "dériver" tout seul, une application au démarrage suffit (voir
    # app/power_settings.py).
    from app.power_settings import apply_saved_power_settings, apply_saved_wifi
    apply_saved_power_settings()
    apply_saved_wifi()

    app = Flask(__name__)
    app.secret_key = _get_or_create_secret_key()
    app.permanent_session_lifetime = SESSION_LIFETIME
    # Limite large mais raisonnable : plusieurs longs livres audio à la fois si besoin.
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 Mo par envoi

    from app.config import APP_NAME, APP_VERSION
    from app.i18n import current_language, tr
    from app.web.icons import icon, logo
    app.jinja_env.globals["_"] = tr         # {{ _('Texte en français') }} dans les gabarits
    app.jinja_env.globals["icon"] = icon    # {{ icon('book') }}
    app.jinja_env.globals["logo"] = logo
    app.jinja_env.globals["APP_NAME"] = APP_NAME
    app.jinja_env.globals["APP_VERSION"] = APP_VERSION

    def human_size(count) -> str:
        """12345678 -> « 12 Mo » ; virgule en français et en occitan."""
        count = int(count or 0)
        if count >= 1_000_000_000:
            number, unit = f"{count / 1_000_000_000:.1f}", "{n} Go"
        else:
            number, unit = f"{max(1, round(count / 1_000_000))}", "{n} Mo"
        if current_language() != "en":
            number = number.replace(".", ",")
        return tr(unit, n=number)

    def short_date(stamp) -> str:
        """« 2026-10-09 15:56 » -> « 09/10/2026 15:56 »."""
        try:
            day, clock = str(stamp).split(" ")
            year, month, date = day.split("-")
            return f"{date}/{month}/{year} {clock}"
        except ValueError:
            return str(stamp or "")

    app.jinja_env.filters["taille"] = human_size
    app.jinja_env.filters["quand"] = short_date

    @app.context_processor
    def _inject_language():
        # Sert à l'attribut lang de la page (lecteurs d'écran, césures).
        return {"lang": current_language()}

    from app.web.routes import main_bp
    app.register_blueprint(main_bp)

    @app.route("/HDP/", defaults={"rest": ""})
    @app.route("/HDP/<path:rest>")
    def old_address(rest):
        # Favoris et raccourcis d'avant la v0.8 (http://<boîte>/HDP/...).
        query = request.query_string.decode("utf-8", "replace")
        return redirect("/" + rest + ("?" + query if query else ""), code=301)

    @app.before_request
    def captive_portal():
        """Sur le réseau de secours, ouvre la page de la boîte toute seule.

        Sur ce réseau, la boîte répond à TOUTES les adresses demandées
        (réglage posé par install_pi.sh : /etc/NetworkManager/
        dnsmasq-shared.d/contar-portail.conf). Un téléphone qui vient de s'y
        connecter interroge une adresse de test de son fabricant pour savoir
        s'il a Internet ; en lui répondant par un renvoi vers la boîte, on
        lui fait afficher « Se connecter au réseau », qui ouvre
        l'administration. Ne fait rien hors du réseau de secours."""
        if _is_own_host(request.host):
            return None
        from app import wifi_fallback
        if not wifi_fallback.is_ap_active():
            return None
        return redirect(f"http://{wifi_fallback.AP_ADDRESS}/", code=302)

    return app


def _is_own_host(host_header: str) -> bool:
    """Vrai si l'adresse demandée désigne bien la boîte : une adresse IP,
    son nom (contar, contar.local, contar.home...) ou localhost. Tout le
    reste (captive.apple.com, connectivitycheck.gstatic.com...) est une
    adresse extérieure, que seul le réseau de secours peut amener ici."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):                      # adresse IPv6 : [::1]:80
        host = host[1:].split("]")[0]
    elif host.count(":") == 1:                    # nom:port ou IPv4:port
        host = host.split(":")[0]
    if not host or host == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "." not in host or host.endswith(".local"):
        return True
    return host.split(".")[0] == socket.gethostname().lower().split(".")[0]
