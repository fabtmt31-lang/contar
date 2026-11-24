# Installer "Contar" sur le vrai Raspberry Pi

Ce guide couvre l'installation sur un Raspberry Pi qui tourne "headless" :
pas d'écran, pas de mode kiosque — la boîte est pilotée entièrement depuis
l'interface web, ouverte depuis un téléphone, une tablette ou un PC sur le
même réseau.

Pour les actions de base (lecture/pause, avance/recul, volume), deux
méthodes sont possibles :

- **Manette USB type NES/Super NES (par défaut actuellement)** : on
  branche, ça marche, rien à souder ni câbler. C'est le choix retenu pour
  le moment, le temps de prototyper sans passer par l'assemblage physique
  des boutons.
- **5 boutons câblés sur les GPIO** : approche prévue depuis le début du
  projet pour la boîte finale assemblée, toujours disponible en changeant
  simplement le mode d'installation (voir plus bas).

Les deux méthodes déclenchent exactement les 5 mêmes actions
(`app/controls/actions.py`) — rien ne change côté application, seule la
source du signal physique diffère.

Une partie des astuces ci-dessous vient du retour d'expérience d'un autre
projet similaire (player Debian en kiosque) — les pièges généraux sur
Debian/systemd sont souvent les mêmes, même si ce projet-ci n'a pas
d'écran à gérer.

## Vue d'ensemble

| Fichier | Rôle |
|---|---|
| `run_pi_gamepad.py` | Point d'entrée par défaut : serveur web + manette USB |
| `run_pi.py` | Point d'entrée alternatif : serveur web + contrôle GPIO |
| `app/controls/gamepad_controller.py` | Lit la manette USB (déjà existant, partagé avec la branche PC x86) |
| `app/controls/gpio_controller.py` | Les 5 boutons physiques câblés (déjà existant) |
| `test_gamepad.py` | Calibration de la manette (les clones USB varient d'une marque à l'autre) |
| `install_pi.sh` | Installe et configure tout automatiquement, dans le mode choisi |
| `GUIDE_RASPBERRY.md` | Ce document |

## Étape 0 — Matériel nécessaire

- Un Raspberry Pi (3, 4 ou 5) avec Raspberry Pi OS installé (Lite
  recommandé — pas besoin de bureau graphique)
- Une carte SD (ou SSD si boot USB) avec de la place pour les histoires
- Une manette USB filaire type NES/Super NES (mode par défaut) — ou, si
  vous préférez déjà passer par le câblage GPIO, 5 boutons-poussoirs (voir
  `app/controls/gpio_controller.py` pour le schéma)
- De quoi accéder au réseau (Wifi ou Ethernet)

## Étape 1 — Installer Raspberry Pi OS

Avec [Raspberry Pi Imager](https://www.raspberrypi.com/software/) :

1. Choisissez **Raspberry Pi OS Lite (64 bits)**.
2. Dans les réglages avancés (icône ⚙, ou `Ctrl+Shift+X`) :
   - Définissez un nom d'utilisateur et un mot de passe (le compte `pi`
     par défaut n'existe plus sur les versions récentes, pour la
     sécurité — un compte personnalisé est obligatoire).
   - **Activez SSH** (avec mot de passe, ou une clé si vous en avez une).
     `install_pi.sh` s'assure aussi que SSH est actif, donc ce n'est pas
     bloquant si vous l'oubliez ici, juste plus simple de le faire tout
     de suite.
   - Configurez le Wifi si vous n'utilisez pas de câble Ethernet.
   - Réglez la disposition du clavier sur "fr" si vous comptez brancher
     un clavier physique sur le Pi — `install_pi.sh` le fait de toute
     façon automatiquement, mais autant partir avec le bon réglage.
3. Flashez la carte SD, insérez-la dans le Pi, démarrez.

## Étape 2 — Trouver l'adresse IP du Pi et s'y connecter

Depuis un autre PC sur le même réseau :

```bash
ping raspberrypi.local     # ou le nom que vous avez choisi à l'imaging
```

Si ça ne répond pas, regardez la liste des appareils connectés depuis
l'interface de votre routeur/box internet pour trouver l'IP. Puis :

```bash
ssh <votre-utilisateur>@<IP-du-Pi>
```

## Étape 3 — Copier le projet sur le Pi

Depuis votre PC, avec le dossier du projet en local :

```bash
scp -r contar/ <votre-utilisateur>@<IP-du-Pi>:~
```

## Étape 4 — Lancer l'installation

Sur le Pi (via SSH) :

```bash
cd ~/contar
sudo bash install_pi.sh
```

Par défaut, ça installe le **mode manette USB** (`run_pi_gamepad.py`).
Pour installer plutôt le mode boutons câblés sur GPIO :

```bash
sudo bash install_pi.sh . gpio
```

Le script (quelques minutes) :

1. Configure le clavier console en **AZERTY français** (persistant +
   immédiat)
2. Active l'accès **SSH** s'il ne l'était pas déjà
3. Installe les paquets nécessaires (Python, VLC...)
4. Force la sortie audio sur le jack plutôt que sur HDMI (sans quoi le
   son part par défaut vers une sortie HDMI muette, sans écran branché)
5. Crée un utilisateur dédié `contar`, l'ajoute aux groupes `audio`, `gpio`
   et `input` (les deux groupes de contrôle sont toujours ajoutés, pour
   pouvoir rejouer le script plus tard avec l'autre mode sans souci de
   permissions)
6. Copie le projet vers `/opt/contar`
7. Installe les dépendances Python dans un environnement virtuel, puis
   selon le mode choisi : `lgpio` (backend GPIO) en mode `gpio`, ou une
   règle udev pour lire la manette sans droits root en mode `gamepad`
8. Autorise le bouton "Éteindre" de l'interface web à fonctionner (règle
   sudoers dédiée, limitée à la seule commande `shutdown`)
9. Installe le serveur applicatif comme service système, dans le mode
   choisi (démarre tout seul au boot, redémarre tout seul en cas de
   plantage)

À la fin, le script affiche l'adresse à ouvrir depuis un téléphone/tablette
(`http://contar.local`, ou `http://<IP-du-Pi>` ; l'adresse s'affiche aussi sur l'écran de la boîte au démarrage).

### Calibrer la manette (mode gamepad)

Les clones USB de manette NES/Super NES envoient des codes assez
variables d'une marque à l'autre. Après l'installation, vérifiez que la
vôtre est bien reconnue :

```bash
/opt/contar/venv/bin/python /opt/contar/test_gamepad.py
```

Appuyez sur chaque bouton et la croix dans les 4 directions : le script
affiche le code exact et vous dit s'il est déjà connu. S'il ne l'est pas,
inutile de modifier du code : ouvrez l'interface web, **Réglages →
Boutons / manette**, choisissez l'action voulue, touchez « Ajouter un
bouton » puis appuyez sur ce bouton — il est capturé et assigné
automatiquement (voir section suivante). Éditer
`app/controls/gamepad_controller.py` à la main ne reste utile que dans un
cas très précis : un axe/croix directionnelle envoyé sous un nom que le
script ne reconnaît même pas comme axe (rare) — il faudrait alors
l'ajouter à `RECOGNIZED_AXIS_CODES` dans ce fichier.

### Réassigner les boutons et sécuriser l'extinction

Depuis **Réglages → Boutons / manette** (téléphone/tablette/PC sur le même
réseau), un parent peut, sans toucher au code :

- Voir et changer quel bouton déclenche quelle action (lecture/pause,
  retour, avance, volume + / -) — une action peut avoir plusieurs
  boutons (pratique si l'enfant confond deux boutons voisins).
- Ajouter un bouton : touchez « Ajouter un bouton », puis appuyez
  physiquement dessus (manette ou boîtier GPIO) — il est détecté et
  assigné automatiquement, quel que soit son code exact.
- Retirer un bouton d'une action (toujours au moins un bouton gardé par
  action, impossible de la vider complètement).
- Réinitialiser tous les boutons aux réglages d'usine en un clic.

**Extinction — sécurité enfant, non désactivable** : la boîte ne s'éteint
jamais sur un simple appui, quel que soit le bouton. Il faut maintenir
**deux boutons précis enfoncés ensemble pendant 2 secondes**. Ces deux
boutons sont réassignables individuellement (même page, section
« Extinction »), mais le principe des deux boutons maintenus ensemble,
lui, ne l'est pas — impossible de repasser à un seul bouton depuis
l'interface.

Cette page n'apparaît utile qu'une fois la manette ou les boutons GPIO
réellement actifs (elle affiche un message d'explication tant que ce
n'est pas le cas, par exemple pendant des tests sur PC avec le clavier).

### Basculer entre manette et GPIO plus tard

Les deux modes cohabitent dans le projet sans rien dupliquer côté logique
métier. Pour changer de mode une fois la boîte déjà installée : recopiez
le projet à jour sur le Pi (étape 3) puis relancez le script avec l'autre
mode, par exemple :

```bash
sudo bash install_pi.sh . gpio       # passer du mode manette au câblage GPIO
```

## Ampli MAX98357A (haut-parleur de la boîte)

Câblage, boîte éteinte :

| MAX98357A | Raspberry Pi |
|---|---|
| VIN | 5 V — broche 4 |
| GND | masse — broche 14 |
| BCLK | GPIO 18 — broche 12 |
| LRC | GPIO 19 — broche 35 |
| DIN | GPIO 21 — broche 40 |
| SD | 3,3 V — broche 17 |
| GAIN | non branché |
| + et − | le haut-parleur (4 à 8 ohms) |

Avec SD au 3,3 V, l'ampli ne joue que le canal gauche : la boîte lui
envoie donc les deux canaux réunis, rien ne se perd.

Le reste du câblage de la boîte (schéma complet dans le cahier des
charges, « Câblage ») :

| Module | Fil | Broche du Pi |
|---|---|---|
| Écran LCD | VCC | 2 (5 V) |
| | GND | 6 |
| | SDA, SCL | 3, 5 |
| Lecteur NFC PN532 | VCC | 1 (3,3 V) |
| | GND | 20 |
| | SDA, SCL | 3, 5 (partagées avec l'écran) |
| Boutons | retour, lecture/pause, avance | 11, 13, 15 (GPIO 17, 27, 22) |
| | volume −, volume + | 29, 31 (GPIO 5, 6) |
| | masse commune | 25 |

Le rôle de chaque bouton se règle dans Réglages → Boutons (« Ajouter un
bouton », puis un appui sur le bouton voulu). La GPIO 19 (broche 35) est
réservée à l'ampli : aucun bouton ne doit s'y trouver.

Après l'installation de la v0.10.1 et un redémarrage (`sudo reboot`) :

```bash
aplay -l                      # une ligne « MAX98357A » doit apparaître
aplay -D plug:contar_ampli /opt/contar/app/assets/sounds/startup.wav
```

La seconde commande joue le carillon de démarrage dans le haut-parleur,
sans passer par le programme de la boîte. (Depuis la v0.10.2, l'ampli est
tenu éveillé par le service `contar-ampli`, qui l'occupe en permanence :
on passe par `contar_ampli`, et non plus par `plughw:MAX98357A,0`.) Ensuite, la boîte choisit
d'elle-même cet ampli (Réglages → Sortie audio l'indique) ; un adaptateur
jack USB branché garde la priorité : débranchez-le pour l'essai.

- Pas de ligne « MAX98357A » : `grep max98357a /boot/firmware/config.txt`
  doit montrer `dtoverlay=max98357a,no-sdmode` ; sinon relancez
  l'installation, puis redémarrez.
- La ligne est là mais aucun son : revoir BCLK, LRC et DIN (trois fils
  faciles à croiser), l'alimentation en 5 V, et les deux fils du
  haut-parleur.

## Essayer l'écran LCD seul

```bash
sudo systemctl stop contar
sudo -u contar /opt/contar/venv/bin/python /opt/contar/tools/test_ecran.py
sudo systemctl start contar
```

Trois écrans s'affichent à la suite ; le terminal dit ce qu'on doit lire.

## Importer des histoires avec une clé USB (v0.9)

1. Sur la clé (FAT32 ou exFAT), créez un dossier `Audiolibre` avec deux
   dossiers : `Livres` (un fichier = une histoire) et `Musiques` (un
   sous-dossier = un album). Formats : MP3, M4A, M4B.
2. Branchez la clé sur un port USB de la boîte. Après quelques secondes :
   un bip, et l'écran affiche **Clé prête / Posez un tag**.
3. Posez le tag maître **Ajouter** (copie ce qui manque), ou le tag maître
   **Remplacer** deux fois de suite (la boîte contiendra exactement ce
   qu'il y a sur la clé). Sans tags maîtres : ouvrez **Import** dans
   l'administration, les deux boutons y sont.
4. L'écran suit la copie (**Import 7/23**), puis **Import fini** avec un
   carillon, puis **Retirez la clé**.

Les deux tags maîtres se déclarent une fois, dans **Tags → Tags maîtres**.

La clé n'est jamais modifiée. Ce que Remplacer retire reste en réserve
sur la boîte jusqu'au prochain import réussi : **Import → Annuler le
dernier remplacement** remet la boîte comme avant.

Si l'écran reste sur l'attente habituelle après le branchement :

```bash
lsblk -o NAME,TRAN,FSTYPE,LABEL,SIZE      # la clé doit apparaître, TRAN = usb
sudo journalctl -u contar -n 40 | grep -i "clé\|import"
```

## Wifi de secours si la connexion à la maison échoue ("Wifi Direct")

La boîte n'a pas d'écran : si elle n'arrive pas à se connecter au Wifi de
la maison (pas encore configuré au premier démarrage, mot de passe changé,
borne hors de portée...), impossible normalement d'ouvrir l'interface web
pour corriger ça. Pour éviter d'être bloqué, la boîte diffuse alors
automatiquement, au bout d'environ une minute, son propre réseau Wifi :

1. Depuis un téléphone, cherchez le réseau Wifi **Contar-Secours**,
   mot de passe **`audiolibre`** (identique sur toutes les boîtes et à
   chaque réinitialisation usine, pour pouvoir s'y connecter dès le tout
   premier démarrage sans devoir déjà être connecté à l'interface web —
   modifiable ensuite dans **Réglages → Réseau**, section « Point d'accès
   de secours », si vous préférez en choisir un autre pour votre famille).
2. Connectez-vous dessus : la page de la boîte s'ouvre en général toute
   seule (touchez la notification « Se connecter au réseau » si le
   téléphone en affiche une). Sinon, ouvrez `http://10.42.0.1`. Le nom du
   réseau et son mot de passe s'affichent en alternance sur l'écran de la
   boîte tant qu'elle est sur ce réseau.
3. Dans Réglages → Réseau, **la liste "Réseaux Wifi détectés à proximité"
   sera toujours vide** (page prévenue : "Scan indisponible via le point
   d'accès de secours") — normal, pas un bug : la boîte n'a qu'UNE seule
   antenne Wifi, qui ne peut pas diffuser ce point d'accès de secours ET
   chercher d'autres réseaux en même temps. **Saisissez donc le nom et le
   mot de passe du Wifi de la maison directement dans les champs**, sans
   passer par cette liste.
4. Enregistrez : la boîte retente aussitôt une connexion, et coupe son
   point d'accès de secours dès qu'elle a réussi (sinon elle retente
   automatiquement toutes les quelques minutes, sans rien à faire).

Ce comportement tourne dans un service à part
(`contar-wifi-secours.service`, voir
`journalctl -u contar-wifi-secours -f` pour l'observer),
indépendant du service applicatif — désactivable depuis Réglages → Réseau
si vous ne voulez jamais qu'un point d'accès ouvert apparaisse.

## Devenir root (rappel)

| Commande | Effet |
|---|---|
| `sudo -i` | Ouvre un shell root persistant — pratique pour enchaîner plusieurs commandes |
| `sudo <commande>` | Exécute une seule commande en root |
| `su - contar` | Bascule sur l'utilisateur de la boîte pour inspecter ses fichiers |
| `whoami` | Affiche l'utilisateur actif — utile après plusieurs `su`/`sudo` enchaînés |

> **Piège fréquent** : si un clavier physique est branché directement sur
> le Pi et que le mot de passe contient des chiffres, vérifiez que
> **Verr Num** est activé — sinon le pavé numérique envoie autre chose que
> des chiffres et l'authentification échoue silencieusement.

## Pas de son au casque/haut-parleur branché sur le jack

Symptôme typique : l'interface web indique bien une lecture en cours (la
barre de progression avance), mais rien ne sort du jack 3.5mm. Trois
causes possibles, à vérifier dans cet ordre.

### 1. Le son sort peut-être sur HDMI plutôt que sur le jack

**Depuis la dernière version, `install_pi.sh` corrige ça automatiquement** :
il détecte la carte "Headphones" (`/proc/asound/cards`) et écrit
`/etc/asound.conf` pour en faire la sortie par défaut, à la place des
sorties HDMI (choisies sinon en priorité par ALSA, muettes puisque sans
écran branché — c'est ce qui provoque un `alsamixer` vide et une erreur
`speaker-test` du type "Playback open error: -524"). Si vous avez installé
une version antérieure, récupérez le projet à jour et relancez
`sudo bash install_pi.sh`, ou appliquez le correctif à la main :

```bash
sudo tee /etc/asound.conf > /dev/null <<'EOF'
pcm.!default {
    type plug
    slave.pcm "hw:Headphones,0"
}
ctl.!default {
    type hw
    card Headphones
}
EOF
sudo systemctl restart contar
```

Vous pouvez vérifier que le jack fonctionne matériellement en le ciblant
directement, avant même ce réglage :

```bash
speaker-test -c2 -t wav -D plughw:2,0    # le numéro de carte peut varier, voir aplay -l
```

Si votre Pi n'a pas de jack 3.5mm physique (le Raspberry Pi 5, notamment,
ne l'a plus), `/proc/asound/cards` ne montrera aucune carte "Headphones" —
il faut alors un adaptateur audio USB (quelques euros), reconnu nativement
sans configuration particulière.

### 2. Le mixeur ALSA est peut-être coupé ou à volume nul

Le réglage de volume dans l'appli (VLC) est indépendant du volume matériel
de la carte son — les deux doivent être corrects.

```bash
alsamixer
# Flèches haut/bas pour monter le volume, "m" pour couper/rétablir le son
# (si la ligne "Headphone" ou "PCM" apparaît coupée, en rouge, appuyez sur "m" dessus)
```

Testez ensuite le son au niveau du système, indépendamment de
l'application, pour confirmer que le matériel fonctionne :

```bash
speaker-test -c2 -t wav
# Ctrl+C pour arrêter après avoir entendu le son test
```

Si vous n'entendez toujours rien à cette étape, le souci est matériel/système
(câblage du casque, réglage raspi-config, carte son) — pas côté application.

### 3. VLC choisit un module de sortie audio qui n'existe pas dans ce contexte

C'est la cause la plus probable si l'étape 2 fonctionne (`speaker-test`
produit du son) mais que l'application reste muette. Le service tourne
comme service systemd, sans session graphique/utilisateur ouverte — or
Raspberry Pi OS (depuis Bookworm) utilise PipeWire pour l'audio, qui ne
démarre que dans une vraie session utilisateur connectée. Sans lui, VLC
peut "jouer" en silence : la position avance normalement dans l'interface,
mais aucune sortie audio réelle n'est ouverte.

**Corrigé dans le code** (`app/player.py`) : sur Linux, VLC est maintenant
lancé avec `--aout=alsa`, qui parle directement au pilote de la carte son
au lieu de passer par PipeWire/PulseAudio. Si vous avez déjà installé une
version antérieure du projet, récupérez la dernière version (`app/player.py`
en particulier), recopiez-la sur le Pi et redémarrez :

```bash
sudo systemctl restart contar
```

## Commandes utiles de dépannage

```bash
# Logs du serveur en direct
journalctl -u contar -f

# Redémarrer le serveur après une modif du code
sudo systemctl restart contar

# Vérifier que SSH est bien actif
sudo systemctl status ssh

# Vérifier la disposition clavier actuelle
localectl status | grep Layout
```

Pour appliquer une mise à jour du code : recopiez le projet sur le Pi
(étape 3) puis relancez `sudo bash install_pi.sh` (rejouable sans risque,
ne touche jamais à `Bibliotheque/`, `data/` ni `venv/`).

## Pièges classiques (retour d'expérience)

- **Pas de son alors que la lecture progresse dans l'interface web.** Deux
  causes se cumulent souvent sur un Pi headless (sans écran HDMI branché) :
  (1) ALSA choisit par défaut une sortie HDMI muette plutôt que le jack —
  `install_pi.sh` corrige ça automatiquement (`/etc/asound.conf`, carte
  "Headphones" par défaut) ; (2) VLC tourne comme service systemd sans
  session utilisateur, or PipeWire (audio par défaut depuis Bookworm) n'y
  démarre pas — corrigé par `--aout=alsa` forcé sur Linux dans
  `app/player.py`. Voir la section dédiée
  [Pas de son au casque/haut-parleur](#pas-de-son-au-casquehaut-parleur-branché-sur-le-jack)
  plus haut pour le diagnostic complet (symptôme identique aux deux
  causes : `alsamixer` vide et/ou `speaker-test` en erreur "-524").

- **Clavier en QWERTY US par défaut sur les consoles texte.** Même une
  installation faite en français peut laisser un clavier physique branché
  sur le Pi en disposition US, faussant la saisie des mots de passe et
  commandes. `install_pi.sh` corrige ça automatiquement
  (`/etc/default/keyboard`, `setupcon --save`, `loadkeys fr`) — mais si
  vous éditez ce fichier à la main plus tard, pensez à relancer ces deux
  commandes pour appliquer le changement.

- **Chemins relatifs cassés dans un script bash après un `cd`.** Un script
  qui utilise `cd /opt/...` puis encore des chemins relatifs pointe au
  mauvais endroit une fois déplacé. `install_pi.sh` calcule son propre
  chemin absolu en tout début de script et s'en sert partout — bonne
  pratique à garder si vous le modifiez.

- **Un service qui tourne comme utilisateur normal ne peut pas exécuter
  `sudo` sans y être explicitement autorisé.** Le bouton "Éteindre" du
  réglages appelle `sudo shutdown -h now` — sans la règle sudoers dédiée
  que le script installe, cette commande resterait bloquée indéfiniment
  en attente d'un mot de passe qu'elle ne recevra jamais (le service n'a
  pas de terminal). Si un jour vous ajoutez une autre action qui a besoin
  de droits root (redémarrage, mise à jour Wifi...), il faudra une règle
  sudoers similaire, ciblée sur la commande précise — jamais un accès
  root généralisé à l'utilisateur `contar`.

- **`pip install -r requirements.txt` ne doit pas dépendre de paquets
  spécifiques au Pi.** `lgpio` (le backend GPIO, mode `gpio` uniquement)
  est installé à part par `install_pi.sh`, pas dans `requirements.txt`
  partagé avec les versions PC — sinon `pip install -r requirements.txt`
  échouerait sur un PC de développement Windows/Mac qui n'a pas accès à ce
  paquet. `inputs` (mode `gamepad`), en revanche, est bien multiplateforme
  et reste dans `requirements.txt`.

- **Écran noir/rien ne répond juste après le démarrage : normal quelques
  secondes.** Le service met un instant à démarrer (Python + VLC). Si ça
  persiste, `journalctl -u contar -f` via SSH montre exactement
  où ça bloque.

## Et la version PC avec écran ?

Elle a été retirée du projet en v0.8 (elle n'était plus entretenue). Le
lancement sur PC avec le clavier (`run.py`) reste disponible pour les essais.

Le contrôle par manette USB (`app/controls/gamepad_controller.py`,
`test_gamepad.py`) est exactement le même code des deux côtés — rien de
spécifique au Pi ni au PC là-dedans, juste de la lecture de périphérique
USB standard. Une correction ou un nouveau mapping de bouton fait dans ce
fichier profite donc automatiquement aux deux cibles.
