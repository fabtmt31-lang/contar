"""
Sélection de la sortie audio (haut-parleurs GPIO / jack USB / HDMI1 / HDMI2).

Le Bluetooth a été retiré (voir README.md, "Étape 24") : dix tentatives
de reconnexion réelles, casque confirmé allumé et à portée pendant toute
la séquence, échouaient systématiquement (`br-connection-page-timeout`) —
en pause pour se concentrer sur la stabilité du reste plutôt que de
continuer à s'acharner dessus. Tout l'historique de dépannage (D-Bus,
rfkill, AutoEnable, bufferisation des logs...) reste dans README.md
("Étape 20" à "Étape 23") si le sujet est repris plus tard.

Nouvelle structure des sorties, décidée pour remplacer le Bluetooth :
- "gpio" : les haut-parleurs intégrés à la boîte, câblés en dur sur un
  ampli séparé branché sur les broches GPIO (I2S ou autre) — TOUJOURS
  disponible, c'est la sortie par défaut.
- "jack" : un jack 3.5mm branché via un adaptateur audio USB. Le Pi n'a
  pas de détection matérielle d'insertion jack (pas de "jack sense" sur
  ce genre de carte) — on détecte donc sa présence indirectement, via
  l'apparition/disparition du périphérique audio USB correspondant dans
  `aplay -l` (fiable : c'est un vrai événement de branchement/débranchement
  USB, pas une supposition). Cette sortie, quand elle est présente, prend
  TOUJOURS la priorité sur le réglage manuel gpio/hdmi1/hdmi2 (voir
  `resolve_effective_output()` plus bas, et `bin/audio_output_watchdog.py`
  qui l'applique en continu, y compris pendant la lecture).
- "hdmi1" / "hdmi2" : les deux sorties HDMI d'un Pi qui en a deux
  (distinguées par leur index de carte, ex: "vc4hdmi0"/"vc4hdmi1").

Changer de sortie revient à réécrire `/etc/asound.conf` pour pointer vers
une autre carte ALSA. Ça demande root : passe par un petit script wrapper
dédié (`bin/set-audio-output.sh`), autorisé en sudo sans mot de passe
UNIQUEMENT pour ce script précis (règle posée par install_pi.sh, même
principe que pour le bouton "Éteindre" — jamais un accès root généralisé).

Rien ici n'est testable avec du vrai matériel dans un environnement de
développement : chaque fonction est écrite pour échouer proprement
(renvoyer une liste vide / un message d'erreur) plutôt que de planter,
si les commandes système ne sont pas disponibles (PC de dev, etc.).
"""

import platform
import re
import subprocess

SET_OUTPUT_SCRIPT = "/opt/contar/bin/set-audio-output.sh"

_CARD_LINE = re.compile(r"^card (\d+): (\S+) \[(.*?)\], device (\d+): (.*?) \[(.*?)\]$")
_HDMI_INDEX = re.compile(r"hdmi\D*(\d)")


def _is_usb_card(card_index: str) -> bool:
    """Vrai si la carte ALSA d'index `card_index` correspond à un vrai
    périphérique USB (présence de /proc/asound/cardN/usbid, posé par le
    noyau UNIQUEMENT pour les cartes son USB) — c'est ce qui nous sert à
    détecter un adaptateur jack USB branché/débranché, sans dépendre du
    nom de carte (qui varie selon le modèle d'adaptateur)."""
    try:
        with open(f"/proc/asound/card{card_index}/usbid"):
            return True
    except OSError:
        return False


def _is_onboard_jack(card_id: str, long_name: str) -> bool:
    """Vrai pour la prise casque d'origine du Raspberry Pi (carte
    « Headphones », pilote bcm2835). Elle est rangée dans la même famille
    « gpio » que l'ampli branché sur les broches (MAX98357A, carte I2S),
    mais c'est l'ampli qui doit l'emporter quand les deux existent — voir
    find_output_by_kind()."""
    text = f"{card_id} {long_name}".lower()
    return "headphones" in text or "bcm2835" in text


def _classify(card_index: str, card_id: str, long_name: str) -> str:
    text = f"{card_id} {long_name}".lower()
    hdmi_match = _HDMI_INDEX.search(text)
    if hdmi_match:
        return "hdmi2" if hdmi_match.group(1) == "1" else "hdmi1"
    if "hdmi" in text:
        return "hdmi1"
    if _is_usb_card(card_index) or "usb" in text:
        return "jack"
    return "gpio"


def list_outputs() -> list[dict]:
    """Sorties audio détectées (gpio/jack/hdmi1/hdmi2), via `aplay -l`."""
    if platform.system() != "Linux":
        return []
    try:
        result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []

    outputs = []
    for line in result.stdout.splitlines():
        match = _CARD_LINE.match(line.strip())
        if not match:
            continue
        card_index, card_id, card_long, _device_index, _dev_name, _dev_long = match.groups()
        outputs.append({
            "alsa_target": f"hw:{card_id},0",
            "card_index": card_index,
            "card_id": card_id,
            "label": card_long,
            "kind": _classify(card_index, card_id, card_long),
            "onboard": _is_onboard_jack(card_id, card_long),
        })
    return outputs


def find_output_by_kind(kind: str) -> dict | None:
    """Première sortie détectée correspondant à ce kind (gpio/jack/hdmi1/hdmi2),
    ou None si aucune carte de ce type n'est actuellement branchée/visible."""
    matches = [output for output in list_outputs() if output["kind"] == kind]
    if not matches:
        return None
    # « gpio » : l'ampli branché sur les broches (carte I2S, par exemple
    # MAX98357A) passe avant la prise casque d'origine du Pi. Sans cela, la
    # première carte listée gagnait — en général la prise casque — et
    # l'ampli de la boîte restait muet (v0.10.1).
    for output in matches:
        if not output.get("onboard"):
            return output
    return matches[0]


def resolve_effective_output(preference: str) -> dict | None:
    """Résout la sortie à utiliser RÉELLEMENT à cet instant : un jack (via
    adaptateur USB) branché prend TOUJOURS la priorité, quel que soit le
    réglage manuel choisi (`preference`, un de "gpio"/"hdmi1"/"hdmi2") —
    c'est la règle demandée : "si on branche un jack il prend le dessus
    quoi qu'il arrive". S'il n'y a pas de jack branché, on retombe sur la
    préférence manuelle, ou sur "gpio" si même celle-ci est introuvable
    (adaptateur HDMI débranché entre-temps, par exemple).

    Appelée en continu par `bin/audio_output_watchdog.py`, pas seulement
    au démarrage — un jack branché ou débranché EN COURS DE LECTURE doit
    être pris en compte sans attendre un redémarrage de la boîte."""
    jack = find_output_by_kind("jack")
    if jack:
        return jack
    return find_output_by_kind(preference) or find_output_by_kind("gpio")


def set_output(alsa_target: str) -> tuple[bool, str]:
    """Écrit /etc/asound.conf pour pointer vers cette cible ALSA (carte du
    type "hw:vc4hdmi0,0", "hw:Device,0"...).

    Retour de test réel (à l'époque du Bluetooth, avant son retrait — voir
    README.md "Étape 24" — mais la mécanique ci-dessous reste valable pour
    n'importe quelle sortie) : sortie sélectionnée ici sans erreur, lecture
    démarrée sans erreur non plus — mais silence total, jusqu'à un
    redémarrage MANUEL du service. Cause : ALSA met en
    cache /etc/asound.conf une seule fois par processus (à la première
    ouverture d'un périphérique audio) ; le service déjà en cours
    d'exécution ne relit donc jamais ce fichier tout seul après une
    modification, quel que soit le message optimiste affiché ici avant ce
    correctif ("effective à la prochaine lecture" — faux). Fix : le script
    (bin/set-audio-output.sh, exécuté en root) redémarre maintenant
    lui-même le service quelques secondes après avoir écrit le fichier, en
    tâche de fond pour laisser cette requête web répondre normalement
    d'abord.
    """
    if platform.system() != "Linux":
        return False, "La sortie audio ne peut être changée que sur le vrai Raspberry Pi."
    try:
        result = subprocess.run(
            ["sudo", SET_OUTPUT_SCRIPT, alsa_target],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, (
                "Sortie audio mise à jour — le lecteur redémarre automatiquement "
                "(quelques secondes) pour en tenir compte."
            )
        return False, f"Échec : {result.stderr.strip() or result.stdout.strip()}"
    except FileNotFoundError:
        return False, "Script de configuration audio introuvable (réinstallez avec install_pi.sh)."
    except Exception as exc:
        return False, f"Impossible de changer la sortie audio : {exc}"

