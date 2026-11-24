# Contar — boîte à histoires Audiolibre (Raspberry Pi)

Contar est la boîte à histoires de la suite Audiolibre, à côté de Jogar
(lecteur) et de Crear (création). Un enfant pose un tag, une histoire
démarre ; les parents règlent tout depuis une page web.

- **Installer ou mettre à jour** : `GUIDE_RASPBERRY.md`, puis
  `sudo bash install_pi.sh . gpio` (boutons câblés) ou
  `sudo bash install_pi.sh` (manette USB).
- **Ouvrir l'administration** : `http://contar.local` (l'adresse s'affiche
  aussi sur l'écran de la boîte au démarrage).
- **Ce qui a changé d'une version à l'autre** : `CHANGELOG.md`.

> La suite de ce document est le journal de construction d'origine, du
> temps où le projet s'appelait « Histoires du Soir ». Il décrit le
> moteur, toujours valable, mais nomme encore les anciens onglets
> (« Livres », « Musique », « Réglages → Tags NFC ») et l'ancienne
> présentation. Les noms de dossiers, de services et les adresses y ont
> été mis à jour (v0.8) ; en cas de doute, le code et `CHANGELOG.md` font foi.

## Étape 1 livrée : base de données, PIN, réglages, scan de bibliothèque

Ce qui a été porté depuis la version Android, fidèlement à la logique
d'origine :

| Fichier             | Portage de                                  |
|----------------------|----------------------------------------------|
| `app/database.py`   | `AppDatabase` (schéma Room → SQLite)         |
| `app/pin.py`        | `PinManager.kt`                              |
| `app/settings.py`   | `SettingsManager.kt`                         |
| `app/audio_meta.py` | `MediaMetadataRetriever` (via `mutagen`)     |
| `app/library_scan.py` | `BookRepository.scanLocalFolder` + `MusicRepository.scan` |

La convention de dossiers `Bibliotheque/Livres` et `Bibliotheque/Musiques` est conservée à
l'identique. Tout ce qui concernait l'écran, le mode kiosque et les
permissions de stockage Android a été volontairement laissé de côté (plus
nécessaire, l'app sera pilotée via l'interface web).

## Comment tester sur votre PC

1. Installez les dépendances (une seule fois) :
   ```
   pip install -r requirements.txt
   ```

2. Déposez quelques fichiers `.mp3` dans `Bibliotheque/Livres/`, et/ou créez un
   sous-dossier dans `Bibliotheque/Musiques/` avec quelques `.mp3` dedans (chaque
   sous-dossier devient un album).

3. Lancez :
   ```
   python test_step1.py
   ```

Le script crée la base de données (`data/contar.db`), teste le
PIN et les réglages, scanne vos dossiers, puis affiche tout ce qu'il a
trouvé. Relancez-le après avoir ajouté d'autres fichiers : seuls les
nouveaux sont ajoutés (comme sur Android).

## Étape 2 livrée : lecteur audio

| Fichier          | Portage de                                   |
|-------------------|-----------------------------------------------|
| `app/player.py`  | `PlaybackService.kt` + `PlayerViewModel.kt`   |

C'est le module central de lecture : play/pause, avance/retour rapide,
positionnement direct, volume, sauvegarde automatique de la position
chaque seconde, marquage "terminé". Toutes les entrées à venir (interface
web, clavier, boutons GPIO) appelleront ces mêmes méthodes.

### Tester avec du vrai son

1. Assurez-vous que VLC (l'application) est installé sur votre PC.
2. Installez la nouvelle dépendance :
   ```
   pip install -r requirements.txt
   ```
3. Lancez la console de test interactive :
   ```
   python test_step2.py
   ```
4. Exemple de session :
   ```
   > list
   > play book 1
   > state
   > seek +30
   > vol 50
   > pause
   > resume
   > stop
   > quit
   ```

## Étape 3a livrée : squelette de l'interface web

| Fichier                  | Rôle                                                       |
|----------------------------|-------------------------------------------------------------|
| `app/web/__init__.py`    | Fabrique de l'app Flask, montée à la racine depuis la v0.8                |
| `app/web/routes.py`      | PIN + session, pages, API du lecteur (JSON)                |
| `app/web/templates/`     | Pages HTML (Jinja)                                          |
| `app/web/static/`        | CSS + JavaScript                                             |
| `run.py`                 | Point d'entrée du serveur                                    |

Fonctionnel dès maintenant : connexion par PIN (code par défaut `1234`
tant qu'aucun n'est configuré), session qui reste active 2h d'inactivité,
page "lecture en cours" complète (cover, barre d'avancement cliquable,
play/pause, ⟲10/⟳10, volume), et la navigation basse vers Livres / Musique
/ Réglages (ces trois pages affichent "à venir" pour l'instant — leur
contenu arrive à l'étape suivante, la structure et la protection par PIN
sont déjà en place).

### Tester

1. `pip install -r requirements.txt` (ajoute Flask)
2. `python run.py`
3. Ouvrez `http://127.0.0.1:5000` dans votre navigateur (PIN par défaut : `1234`)
4. Pour tester depuis votre téléphone : assurez-vous d'être sur le même
   Wifi que votre PC, trouvez l'adresse IP locale de votre PC (`ipconfig`
   sous Windows), puis ouvrez `http://<cette-adresse>:5000` depuis le
   téléphone.

Astuce : lancez `python test_step1.py` avant si votre base est vide, pour
avoir des livres/morceaux à afficher en "dernière lecture".

## Étape 3b livrée : bibliothèque + upload de fichiers

- **Livres** (`/Bibliotheque/livres`) : liste de toutes les histoires, dépôt de
  nouveaux fichiers (upload → enregistrement dans `Bibliotheque/Livres` → scan
  automatique → apparition immédiate dans la liste), bascule
  visible/masqué à l'enfant, et lecture en tapant sur la couverture.
- **Musique** (`/Bibliotheque/musique`) : grille d'albums, upload avec nom d'album
  optionnel (crée un sous-dossier dans `Bibliotheque/Musiques`, ou dépose à la
  racine si laissé vide), détail d'un album avec ses morceaux, lecture en
  tapant sur un morceau.

Les noms de fichiers sont nettoyés automatiquement (caractères spéciaux,
espaces) et un fichier de même nom n'écrase jamais un fichier existant
(suffixe `(1)`, `(2)`... ajouté si besoin).

### Tester

1. `python run.py`
2. Onglet **Livres** : déposez un ou deux `.mp3`, ils doivent apparaître
   dans la liste juste après l'envoi (rechargement automatique de la page)
3. Onglet **Musique** : donnez un nom d'album (ex. `Comptines`) et déposez
   des fichiers, un nouvel album doit apparaître dans la grille
4. Tapez sur une couverture ou un morceau : vous devez être renvoyé sur
   "Lecture en cours" avec la lecture démarrée

## Corrections apportées après retour utilisateur

- **Fiches détaillées** : taper sur un livre ou un morceau ouvre désormais
  sa fiche (auteur/artiste, album, année, durée, progression) *avant* de
  lancer la lecture — un bouton dédié "Lire" déclenche la lecture depuis
  la fiche. Ça ne se lance plus automatiquement au clic dans la liste.
- **Jaquettes réelles** : les vignettes extraites des fichiers audio à
  l'étape 1 étaient bien en base, mais jamais servies par le serveur web —
  ajout de la route `/Bibliotheque/covers/<fichier>` et de l'affichage conditionnel
  (image réelle si disponible, sinon le cercle emoji/couleur) dans toutes
  les listes, fiches, et sur la page "lecture en cours".

## Étape 4 livrée : contrôles physiques (clavier PC / GPIO Pi)

| Fichier                          | Rôle                                                        |
|-----------------------------------|----------------------------------------------------------------|
| `app/controls/actions.py`        | Point d'entrée central des 5 actions (rejoue vers `player.py`) |
| `app/controls/keyboard_controller.py` | Contrôle clavier, pour tester sur PC                    |
| `app/controls/gpio_controller.py`| Contrôle par boutons GPIO, pour le vrai Raspberry Pi          |
| `run.py`                         | Serveur web + clavier (à utiliser sur PC)                     |
| `run_pi.py`                      | Serveur web + GPIO (à utiliser sur le Pi)                     |

Les 5 actions (retour 10s, lecture/pause, avance 10s, volume -, volume +)
passent toutes par `app/controls/actions.py`, qui appelle le même
contrôleur central que l'interface web (`app/player.py`). Peu importe
d'où vient l'action — bouton physique ou clic dans le navigateur —
l'état reste toujours cohérent partout.

### Tester le clavier sur PC

1. `pip install -r requirements.txt` (ajoute `keyboard`)
2. Chargez une histoire au préalable (via `test_step2.py` ou l'interface web)
3. Lancez `python run.py` (au lieu de l'ancien `run.py`, celui-ci démarre
   aussi l'écoute clavier)
4. Ouvrez `http://127.0.0.1:5000` dans votre navigateur sur la page
   "lecture en cours"
5. Appuyez sur **Espace** (lecture/pause), **←/→** (retour/avance 10s),
   **↑/↓** (volume) — la page doit se mettre à jour en moins d'une
   seconde, sans même cliquer dans le navigateur

Vous pouvez aussi tester sans navigateur avec `python test_step4_controls.py`,
qui affiche l'état dans la console à chaque appui.

### Le GPIO (`gpio_controller.py`, `run_pi.py`)

Ne peut être testé que sur le vrai Raspberry Pi (nécessite du vrai
matériel). Le câblage attendu : 5 boutons, chacun reliant un GPIO à une
broche GND — pas de résistance externe nécessaire. Numéros de broches
BCM par défaut dans `gpio_controller.py`, à ajuster selon votre câblage
une fois la boîte assemblée.

## Ajout : navigation suivant/précédent pour la musique

Les boutons ⟲/⟳ (web, clavier, et plus tard GPIO) s'adaptent maintenant
selon ce qui est chargé :

- **Livre** : comportement inchangé, avance/recule de 10 secondes.
- **Musique** : ⟳ passe au morceau suivant de l'album. ⟲ suit la
  convention classique des lecteurs audio — un appui simple relance le
  morceau depuis le début, un double appui rapproché (moins de 1,2s)
  revient au morceau précédent.

Cette logique vit dans `app/player.py` (`skip_forward`/`skip_back`), donc
web, clavier et GPIO en bénéficient automatiquement sans rien dupliquer.

## Correction critique : erreur 500 sur toute musique en lecture

Bug trouvé grâce au traceback partagé : `_display_state()` (utilisée par
`/Bibliotheque/api/state`, `/api/toggle`, `/api/play`...) lisait `row["emoji"]` et
`row["color_hex"]` en supposant que ces colonnes existent toujours — or
elles n'existent que dans `books` et `albums`, **pas** dans `tracks` (une
musique n'a pas son propre emoji/couleur, c'est son album qui en a un).
Résultat : toute lecture de musique faisait planter en boucle l'appel
d'état interrogé chaque seconde par la page, empêchant l'interface de
refléter play/pause correctement (l'action fonctionnait bien côté
serveur, seule la confirmation JSON échouait). Les livres n'étaient pas
concernés, d'où le bug qui semblait spécifique à la musique.

Corrigé : `_display_state()` récupère maintenant l'emoji/couleur/jaquette
depuis l'album quand il s'agit d'un morceau.

## Étape 3c livrée : page Réglages complète

| Fonctionnalité | Où |
|---|---|
| Minuterie de coucher + plages horaires par jour | `/Bibliotheque/reglages/temps` |
| Catégories (tags) + assignation sur la fiche livre | `/Bibliotheque/reglages/categories`, sélecteur sur `/Bibliotheque/livres/<id>` |
| Changement du code PIN | `/Bibliotheque/reglages/pin` |
| Configuration réseau (nom de la boîte, Wifi domicile) | `/Bibliotheque/reglages/reseau` |
| Mentions légales (modèle générique à adapter) | `/Bibliotheque/reglages/mentions-legales` |
| Aide et utilisation | `/Bibliotheque/reglages/aide` |
| Extinction du Pi | Bouton dans le menu réglages |
| Déconnexion | Bouton dédié + lien déjà présent en haut de chaque page |
| Langue (français / occitan) | Sélecteur dans le menu réglages |

**Important sur la partie réseau** : les champs (nom de la boîte, Wifi
domicile) sont enregistrés en base dès maintenant, mais **rien n'est
réellement appliqué tant qu'on n'est pas sur le vrai Raspberry Pi** — ce
sera fait à l'étape 5, à partir de ces valeurs déjà enregistrées.

**Sur le bouton "Éteindre"** : ne fait rien de destructif sur PC (message
affiché indiquant que ça ne fonctionne que sur le vrai Pi) — sur le Pi, il
exécutera `sudo shutdown -h now`.

**Sur la langue occitane** : traduction de bonne foi (pas relue par un
locuteur natif) pour l'instant limitée à la navigation, la page de
connexion et le menu réglages — le système (`app/i18n.py`) est prêt pour
étendre la traduction au reste de l'interface au fur et à mesure, il
suffit d'ajouter des clés dans `TRANSLATIONS`.

## Cible principale : Raspberry Pi, piloté depuis l'interface web

Retour à l'idée d'origine du projet, avec les manques comblés pour un
vrai déploiement : le Pi tourne "headless" (pas d'écran ni de mode
kiosque), tout se pilote depuis l'interface web ouverte sur un
téléphone/tablette/PC du même réseau.

Pour les actions de base (lecture/pause, avance/recul, volume), deux
modes au choix, installés par `install_pi.sh` :

- **Manette USB type NES/Super NES** (mode par défaut actuellement) —
  rien à câbler, on branche et ça marche. Réutilise exactement le même
  code que la branche PC x86 (`app/controls/gamepad_controller.py`).
- **5 boutons câblés sur GPIO** — approche prévue pour la boîte finale
  assemblée, toujours disponible (`sudo bash install_pi.sh . gpio`).

| Fichier | Rôle |
|---|---|
| `run_pi_gamepad.py` | Serveur web + manette USB (mode par défaut) |
| `run_pi.py` | Serveur web + contrôle GPIO (mode alternatif) |
| `install_pi.sh` | Installe et configure tout automatiquement sur Raspberry Pi OS, dans le mode choisi |
| `GUIDE_RASPBERRY.md` | Procédure complète : installation, SSH, clavier AZERTY, calibration manette, dépannage |

Ajouts apportés par `install_pi.sh` (absents jusqu'ici) : accès **SSH**
activé par défaut, clavier console forcé en **AZERTY français**, et une
règle **sudoers** dédiée pour que le bouton "Éteindre" de l'interface web
fonctionne réellement (le service tourne sous un utilisateur non-root,
qui a besoin d'une autorisation explicite et limitée pour ça).

## Étape 5 livrée : listes de lecture ("Liste de lecture")

Nouvel onglet dans la navigation basse (📻), entre Musique et Réglages.
Permet de créer des listes de lecture qui peuvent **librement mélanger
livres et morceaux de musique** dans une même liste, avec lecture en
**boucle** et/ou en **aléatoire**.

| Fichier | Rôle |
|---|---|
| `app/playlist.py` | `PlaylistManager` — CRUD des listes et de leur contenu (tables `playlists` / `playlist_items` dans `app/database.py`) |
| `app/player.py` | Moteur de file d'attente ajouté à `PlayerController` : `play_playlist()`, enchaînement automatique à la fin de chaque élément (`_advance_queue()`), respect du mode boucle/aléatoire |
| `app/web/routes.py` | Routes `/Bibliotheque/listes*` : liste, détail, créer, renommer, supprimer, régler les modes, ajouter/retirer/réordonner un élément, lancer la lecture |
| `app/web/templates/playlists.html` | Page liste des listes de lecture + création |
| `app/web/templates/playlist_detail.html` | Détail d'une liste : renommer, modes boucle/aléatoire, contenu réordonnable, ajout de livres/morceaux, suppression |

Fonctionnement de l'enchaînement automatique : pas de nouveau thread ni
minuteur — la détection de fin de lecture réutilise la boucle de
sauvegarde de position déjà existante (1×/seconde). Quand un élément d'une
liste se termine, le suivant démarre automatiquement (dans l'ordre, ou
mélangé si le mode aléatoire est actif) ; en fin de liste, elle boucle sur
le premier élément si le mode boucle est actif, sinon la lecture s'arrête
proprement. Une lecture manuelle d'un livre/morceau isolé (depuis la
bibliothèque, le clavier, la manette ou les boutons GPIO) sort
automatiquement du contexte de liste en cours, comme attendu.

La page "Lecture en cours" affiche un petit badge (📻 *nom de la liste*)
quand la liste en cours de lecture provient d'une liste de lecture.

## Étape 6 livrée : configurateur de boutons / manette

Nouvelle page **Réglages → Boutons / manette**, pour reconfigurer sans
toucher au code quel bouton physique (manette USB ou GPIO) déclenche
quelle action, avec une capture "appuyez sur le bouton" (pas besoin de
connaître son code exact).

| Fichier | Rôle |
|---|---|
| `app/controls/mapping.py` | Mapping bouton→action (par mode), capture, et détection de l'appui simultané maintenu pour l'extinction — commun à `gamepad_controller.py` et `gpio_controller.py` |
| `app/system_control.py` | `shutdown_now()` partagé entre le bouton "Éteindre" web et la combinaison de boutons |
| `app/web/routes.py` | Routes `/Bibliotheque/reglages/manette*` : lister, capturer, assigner/retirer un bouton, régler la combinaison d'extinction, réinitialiser |
| `app/web/templates/settings_controls.html` + `app/web/static/js/controls.js` | Page de réglage + capture en direct (sondage de l'état de capture, sans rechargement de page à chaque appui) |

**Sécurité enfant, point non négociable et non désactivable** : l'extinction
n'est jamais assignable à un seul bouton — uniquement à un **appui
simultané maintenu sur deux boutons pendant 2 secondes**. Les deux
boutons de cette combinaison sont réassignables individuellement ; le
principe des deux boutons maintenus ensemble, lui, ne l'est pas.

Chaque action (lecture/pause, retour, avance, volume +/-) peut avoir
plusieurs boutons ; un bouton donné n'appartient qu'à une seule action à
la fois (le réassigner ailleurs l'y déplace automatiquement). Cette page
ne montre quelque chose d'utile qu'une fois la manette ou les boutons
GPIO réellement actifs sur le Pi (affiche un message explicatif sinon,
par exemple pendant les tests sur PC avec le clavier).

## Étape 7 livrée : affichage du Wifi réellement connecté

`app/network_status.py` (nouveau) lit `nmcli`/`hostname` pour afficher, en
haut de **Réglages → Réseau**, le SSID auquel la boîte est *réellement*
connectée et son adresse IP actuelle — jusqu'ici la page ne montrait que
la configuration enregistrée, jamais l'état réel. L'application
effective de la configuration Wifi saisie au système reste, elle, non
faite (toujours prévue plus tard, voir Prochaines étapes).

## Étape 8 livrée : sélecteur de sortie audio (jack / USB / HDMI / Bluetooth)

Nouvelle page **Réglages → Sortie audio**. Liste les sorties filaires
détectées (`aplay -l`) avec un bouton "Utiliser" chacune, et une section
Bluetooth (scan 8s, associer = appairer + connecter + activer comme
sortie en une seule action, oublier). Changer de sortie s'applique à la
prochaine lecture, pas besoin de redémarrer la boîte.

| Fichier | Rôle |
|---|---|
| `app/audio_output.py` | Détection ALSA (`aplay -l`), scan/appairage Bluetooth (`bluetoothctl`), écriture de la sortie active |
| `bin/set-audio-output.sh` | Seul point d'écriture de `/etc/asound.conf`, appelé en sudo (règle sudoers dédiée, même principe que le bouton "Éteindre") |
| `app/web/routes.py` | Routes `/Bibliotheque/reglages/audio*` |
| `app/web/templates/settings_audio.html` | Page de réglage |

La sortie Bluetooth passe par `bluealsa` (paquet `bluez-alsa-utils`,
installé par `install_pi.sh`) : VLC est lancé en `--aout=alsa` direct
(pas de session PipeWire/Pulse dans le contexte du service systemd),
donc un appareil Bluetooth appairé doit être exposé comme carte ALSA
pour être utilisable — c'est le rôle de bluealsa. Si ce paquet n'est pas
disponible sur une version donnée de Raspberry Pi OS, l'installation
continue quand même (avertissement affiché), seule la sortie Bluetooth
reste indisponible.

**Non testé sur vrai matériel** (scan/appairage Bluetooth, cartes ALSA
réelles) — uniquement vérifié avec des sorties système simulées dans cet
environnement de développement (parsing `aplay -l`/`bluetoothctl`,
routes web, enchaînement des actions). À valider sur le vrai Pi.

## Étape 9 livrée : application réelle de la config réseau

**Réglages → Réseau** applique désormais vraiment le nom d'hôte et le
Wifi saisis, au lieu de juste les enregistrer.

| Fichier | Rôle |
|---|---|
| `app/network_apply.py` | Appelle `bin/apply-network-config.sh` en sudo (mot de passe Wifi transmis par entrée standard, jamais en argument — invisible dans `ps aux`) |
| `bin/apply-network-config.sh` | `hostnamectl set-hostname` + mise à jour `/etc/hosts`, puis `nmcli device wifi connect` |

Même principe de sécurité que le bouton "Éteindre" et la sortie audio :
sudoers n'autorise QUE ce script précis, pas un accès root généralisé.
`install_pi.sh` installe `network-manager` et déploie le script.

⚠️ Un SSID/mot de passe incorrect peut faire perdre la connexion réseau à
la boîte — un accès physique serait alors nécessaire pour corriger (voir
avertissement affiché sur la page). Non testé sur vrai matériel.

## Étape 10 livrée : retours du premier test réel sur le Pi

- **IP fixe** : "Réglages → Réseau" propose maintenant DHCP ou IP manuelle
  (IP, masque, passerelle, DNS), appliqué via `nmcli con mod` (voir
  `bin/apply-network-config.sh`, `app/network_apply.py`).
- **`http://<nom>.local` corrigé** : `avahi-daemon` (mDNS)
  installé et activé par `install_pi.sh` — probablement absent/inactif
  jusqu'ici. Ne fonctionne nativement que sur macOS/Linux/iOS ; sous
  Windows sans Bonjour installé, utilisez l'adresse IP affichée sur
  "Réglages → Réseau".
- **Boutons/manette** : plus de configuration d'usine — aucun bouton
  n'est assigné par défaut (ni combinaison d'extinction), à régler
  entièrement via "Ajouter un bouton" (capture). Ajout des actions
  "Piste précédente"/"Piste suivante". **Corrigé** : un axe/croix
  directionnelle envoyé sur un code non reconnu par défaut (variable
  selon les clones de manette) est maintenant capturé normalement
  pendant "Ajouter un bouton", et devient utilisable ensuite — plus
  besoin d'éditer `gamepad_controller.py` à la main pour ce cas.
- **État du stockage** : nouvelle section dans "Réglages", avertit si
  l'espace disque dépasse 85% (`app/storage_status.py`).
- **Musique — enchaînement par défaut** : à la fin d'une piste (hors
  liste de lecture), la piste suivante du même dossier/album démarre
  automatiquement, comme un lecteur audio classique (`app/player.py`,
  réutilise `next_track()` déjà existant).

Le Wifi Direct / point d'accès de secours évoqué n'a pas été traité dans
ce lot (chantier à part, plus gros) — reste en backlog.

## Étape 11 livrée : Wifi Direct / point d'accès de secours

- Si la boîte n'arrive pas à se connecter au Wifi de la maison (jamais
  configuré, mot de passe faux/changé, borne hors de portée), elle
  diffuse maintenant automatiquement, au bout d'environ une minute, son
  propre réseau Wifi (`Contar-Secours` par défaut) — s'y
  connecter depuis un téléphone puis ouvrir `http://10.42.0.1`
  suffit à reconfigurer le Wifi sans écran ni câble Ethernet.
- Repose sur le mode hotspot intégré de NetworkManager (`nmcli device
  wifi hotspot`), pas sur hostapd/dnsmasq séparés — une seule carte Wifi
  fait donc soit client (Wifi maison), soit point d'accès, jamais les
  deux à la fois.
- Nouveau service système indépendant, en root,
  `contar-wifi-secours.service` (`bin/wifi-fallback-watchdog.sh`,
  installé/activé par `install_pi.sh`) : vérifie la connexion toutes les
  30s, bascule sur le point d'accès après un court délai de grâce au
  démarrage, et retente périodiquement le Wifi de la maison — dès que ça
  fonctionne, le point d'accès de secours est coupé automatiquement.
- Volontairement un service à part (pas de sudoers dédié comme pour
  l'extinction/l'audio) : il n'est pas déclenché à la demande par
  l'appli, il tourne en continu et a besoin d'un accès root permanent à
  NetworkManager.
- Configurable depuis "Réglages → Réseau" (nom/mot de passe du réseau de
  secours, activable/désactivable) — mot de passe généré aléatoirement à
  la première visite de la page (`app/settings.py`,
  `app/wifi_fallback.py`).
- Communication appli → service via un fichier miroir en texte brut
  (`data/wifi_fallback.conf`, régénéré à chaque enregistrement des
  réglages réseau et au démarrage de l'appli), lu ligne à ligne par le
  script bash — jamais via `source` — pour ne jamais risquer d'exécuter
  du contenu arbitraire si un mot de passe contenait des caractères
  spéciaux du shell.

## Étape 12 livrée : retours du deuxième test réel (Bluetooth, croix, Wifi, extinction)

- **Bluetooth ne trouvait aucun appareil (corrigé)** : `scan_bluetooth_devices()`
  s'appuyait sur `bluetoothctl --timeout N scan on`, dont le comportement
  exact varie trop selon les versions de BlueZ (parfois n'active aucun
  scan réel). Remplacé par la méthode standard : `scan on` lancé en tâche
  de fond, délai d'attente, puis `scan off` explicite dans un appel
  séparé — plus fiable sur le terrain. Ajout d'un déblocage rfkill
  défensif (`app/audio_output.py`).
- **Croix directionnelle : gauche/haut non détectés (corrigé)** — bug
  différent de celui déjà corrigé à l'étape 10. Certains clones de
  manette simulent la croix sur un axe générique (ABS_X/Y) avec une
  plage brute 0-255 : leur extrémité "gauche"/"haut" vaut exactement 0,
  qui était interprété à tort comme "relâché" (un raccourci de code
  traitait toute valeur déjà dans {-1, 0, 1} comme la direction finale,
  peu importe le type d'axe). "Droite"/"bas" (valeur haute, 255)
  fonctionnaient car jamais ambigus. Corrigé en distinguant par code :
  seuls les vrais codes de hat switch (`ABS_HAT0X/Y`...) sont pris tels
  quels, tout axe générique passe systématiquement par le seuillage
  (`app/controls/gamepad_controller.py`).
- **Réglages → Réseau, interface Wifi revue** : liste déroulante des
  réseaux Wifi détectés à proximité (`nmcli dev wifi list`, triée par
  signal, dédoublonnée) au lieu d'un simple champ texte — la sélectionner
  remplit automatiquement le nom du réseau, le champ texte restant
  disponible pour un réseau caché ou si le scan échoue
  (`app/network_status.py::scan_wifi_networks`).
- **`http://<nom>.local` toujours capricieux** : `avahi-daemon` est
  maintenant explicitement redémarré après chaque changement de nom
  d'hôte (`bin/apply-network-config.sh`) pour que la nouvelle annonce
  mDNS parte immédiatement. Ajout d'une explication directement dans
  l'interface : cette adresse fonctionne nativement sur iPhone/iPad/Mac
  et Linux, demande d'installer "Bonjour" sous Windows, et n'est pas
  toujours fiable sur Android selon le navigateur — l'adresse IP affichée
  juste au-dessus reste la solution universelle.
- **Bouton "Éteindre" renommé** : "Éteindre le Raspberry Pi" devient
  "Éteindre la boîte à histoires", avec un rappel en dessous qu'il faudra
  débrancher/rebrancher la boîte pour qu'elle refonctionne
  (`app/i18n.py`, `settings_menu.html`).

## Étape 13 livrée : retours du troisième test réel (Bluetooth toujours muet, oublier un réseau)

- **Bluetooth toujours aucun appareil trouvé, malgré la réécriture de
  l'étape 12** : cause probable identifiée — bluetoothd tourne en root, et
  sa politique D-Bus système par défaut refuse en général tout appel
  venant d'un utilisateur non-root, y compris "activer le Bluetooth" et
  "scanner" — ces deux appels échouaient donc probablement en silence
  depuis le début (leur résultat n'était jamais vérifié). Deux
  changements : `install_pi.sh` installe désormais une règle D-Bus dédiée
  qui autorise explicitement l'utilisateur de l'appli (`contar`) à piloter
  Bluetooth (nouvelle section 6, sans toucher à la politique par défaut
  ni donner de droits root) ; et `scan_bluetooth_devices()` vérifie
  maintenant chaque étape et renvoie un message précis (adaptateur
  absent / accès refusé / scan effectivement vide) au lieu d'un
  silencieux "0 appareil trouvé" qui ne permettait pas de savoir où ça
  coinçait — nécessite une réinstallation avec `install_pi.sh` pour
  prendre effet.
- **Bouton "Oublier ce réseau Wifi"** : dans "Réglages → Réseau", sous le
  champ SSID, un bouton (visible seulement si un réseau est enregistré)
  supprime la connexion NetworkManager correspondante ET efface le
  SSID/mot de passe enregistrés côté appli — repart de zéro avant de
  choisir un autre réseau dans la liste déroulante. Nouveau script
  dédié + règle sudoers (`bin/forget-wifi.sh`,
  `app/network_apply.py::forget_wifi_network`), même principe que les
  autres actions privilégiées du projet.

## Étape 14 livrée : le Wifi Direct ne basculait pas tant que le Wifi de la maison restait visible

Retour de test réel après réinstallation : le point d'accès de secours
fonctionne bien, mais ne se déclenchait QUE si le routeur de la maison
était complètement éteint — s'il restait visible (même sans connexion
réussie, ex: mot de passe faux), la bascule ne se produisait pas.

Cause : NetworkManager retente tout seul, en continu, de se connecter au
profil Wifi connu dès qu'il est visible (comportement "autoconnect"
standard, indépendant de notre script) — même en boucle d'échec. Cette
tentative peut monopoliser la carte Wifi et empêcher la création du point
d'accès de secours tant qu'elle est en cours.

Fix : `start_ap()` libère maintenant explicitement la carte Wifi
(`nmcli device disconnect`) juste avant de créer le point d'accès, pour
ne plus dépendre du bon vouloir d'une tentative de connexion bloquée.
En profite pour journaliser le message d'erreur exact de nmcli en cas
d'échec (`start_ap()` et `try_home_wifi()`), au lieu de l'avaler
silencieusement — visible via
`journalctl -u contar-wifi-secours -f`.
(`bin/wifi-fallback-watchdog.sh`)

## Étape 15 livrée : retours du quatrième test réel — Bluetooth, cause racine enfin trouvée

Après les fix D-Bus (étape 13) et Wifi Direct (étape 14), réinstallation
complète et propre — mais le Bluetooth échouait encore, avec un message
différent : `org.bluez.Error.Failed` au lieu de `NotAuthorized`. Diagnostic
fait en direct en SSH sur le Pi (`rfkill list`, `systemctl status bluetooth
hciuart`, `hciconfig -a`, `journalctl -u bluetooth`) : `hci0` restait
**"Soft blocked: yes"**.

`app/audio_output.py` tentait déjà `rfkill unblock bluetooth` avant chaque
scan (ajouté à l'étape 12), mais échouait silencieusement à chaque fois :
`/dev/rfkill` n'est modifiable que par root ou le groupe `netdev` (ni l'un
ni l'autre pour l'utilisateur `contar`), et rien ne vérifiait le résultat de
cette commande.

Fix : nouvelle section 7 dans `install_pi.sh` (sections 7-11 renumérotées
en 8-12) posant une règle sudoers dédiée (`contar-bluetooth-rfkill`,
même principe que le bouton "Éteindre" — restreinte à
`rfkill unblock bluetooth` uniquement) + déblocage immédiat au moment de
l'install. `scan_bluetooth_devices()` appelle maintenant
`sudo rfkill unblock bluetooth`, puis **vérifie explicitement** via
`rfkill list bluetooth` que le déblocage a réellement pris effet avant de
poursuivre — sinon renvoie un message actionnable (commande manuelle de
secours en SSH) plutôt que l'erreur bluez générique et peu claire.
Nécessite une réinstallation avec `install_pi.sh` pour prendre effet (règle
système, pas seulement du code applicatif).

## Étape 16 livrée : Bluetooth, le scan trouvait toujours "0 appareil" une fois rfkill/D-Bus réglés

Retour de test réel juste après l'étape 15 : `power on` réussit désormais,
mais le scan renvoyait quand même "0 appareil trouvé" alors qu'un appareil
était bien en attente d'appairage à proximité.

1ère tentative de fix (sans effet, retour de test à l'appui) : forcer un
tampon ligne par ligne côté sortie (`stdbuf -oL -eL`), au cas où les
événements `[NEW] Device ...` restaient coincés dans un tampon plein avant
d'être coupés par `terminate()`. N'a rien changé — la vraie cause était plus
fondamentale.

Cause réelle trouvée : `scan_bluetooth_devices()` lançait `bluetoothctl scan
on` sans jamais lui donner d'entrée standard ouverte — il héritait donc de
celle du service systemd de l'appli, généralement `/dev/null`. Une entrée
standard déjà à EOF fait quitter bluetoothctl quasiment tout de suite après
avoir traité la commande initiale, bien avant la fin du délai d'attente. Or
BlueZ arrête AUTOMATIQUEMENT la découverte dès que le client qui l'a
démarrée se déconnecte du bus D-Bus (comportement documenté de
StartDiscovery/StopDiscovery) : le scan s'arrêtait donc en réalité presque
aussitôt, quel que soit le temps laissé passer.

Fix : bluetoothctl est maintenant lancé avec `stdin=PIPE`, gardé ouvert
nous-mêmes pendant toute la durée du scan (rien n'y est écrit d'autre que
`scan on`, puis `scan off` et `quit` une fois le délai écoulé) — la session
de découverte reste donc active jusqu'à ce qu'on la coupe explicitement.
`stdbuf -oL -eL` (repli sur l'appel direct si absent) reste en place en
complément. En profite pour détecter explicitement un échec du démarrage du
scan lui-même (`Failed to start discovery`, ex: `org.bluez.Error.InProgress`)
et le signaler clairement au lieu du "0 appareil trouvé" trompeur qui
laissait croire à une simple absence d'appareil à proximité
(`app/audio_output.py`).

## Étape 17 livrée : casque Bluetooth appairé, sélectionné, aucune erreur — mais silence total

Retour de test réel juste après l'étape 16 (le scan trouve enfin les
appareils) : le casque s'appaire et se connecte sans problème, apparaît
bien comme sortie audio active, la lecture démarre sans la moindre erreur
— mais aucun son ne sort.

Cause probable : le profil A2DP a deux rôles distincts — SOURCE (envoie
l'audio) et SINK (le reçoit). La boîte doit jouer le rôle SOURCE pour
envoyer du son vers un casque/une enceinte Bluetooth. `bluealsa` (le pont
Bluetooth ↔ ALSA utilisé par `app/audio_output.py`) tourne bien, l'appairage
et la connexion Bluetooth eux-mêmes réussissent (ce sont des couches
indépendantes du rôle audio), mais l'unité systemd packagée sur Debian
n'active pas forcément le rôle `a2dp-source` par défaut — sans lui,
bluealsa n'a tout simplement jamais de canal pour émettre du son vers le
casque, sans que rien ne "plante" nulle part (d'où l'absence totale
d'erreur signalée).

Fix : `install_pi.sh` pose désormais un override systemd
(`/etc/systemd/system/bluealsa.service.d/contar-a2dp-source.conf`)
qui force explicitement `bluealsa -p a2dp-source -p a2dp-sink`, sans
dépendre des valeurs par défaut du paquet (qui peuvent changer d'une
version à l'autre). Nécessite une réinstallation (règle systemd, pas du
code applicatif) — et de reconnecter le casque une fois faite (le service
bluealsa redémarre avec les nouveaux rôles, l'ancienne connexion ne
"rattrape" pas automatiquement le nouveau profil).

## Étape 18 livrée : casque Bluetooth enfin fonctionnel, cause finale — cache ALSA par processus

Retour de test réel après l'étape 17 (rôle a2dp-source forcé) : `bluealsa-aplay -l`
confirme que bluealsa voit bien le casque comme périphérique de lecture A2DP
fonctionnel — la chaîne Bluetooth est donc intégralement opérationnelle.
Mais toujours aucun son via l'appli, jusqu'à ce qu'un redémarrage MANUEL du
service (`sudo systemctl restart contar`) règle immédiatement le
problème.

Cause : la bibliothèque ALSA lit `/etc/asound.conf` UNE SEULE FOIS par
processus — mise en cache dès la première ouverture d'un périphérique
audio, jamais relue automatiquement ensuite. Le service applicatif, déjà en
cours d'exécution au moment où l'utilisateur appaire son casque et change
la sortie audio, avait presque certainement déjà ouvert un périphérique
audio au moins une fois (sortie jack par défaut) — sa copie en mémoire de
la configuration ALSA restait donc figée sur l'ancienne sortie, quel que
soit le nouveau contenu du fichier sur disque.

Fix : `bin/set-audio-output.sh` redémarre maintenant lui-même le service
`contar` juste après avoir écrit le nouveau fichier — en tâche de
fond avec un court délai, pour laisser la requête web qui vient de
déclencher ce changement répondre normalement avant que le processus qui la
sert ne soit coupé. Message affiché à l'utilisateur corrigé en conséquence
(l'ancien "effective à la prochaine lecture" était faux) : une lecture en
cours sera interrompue par ce redémarrage, désormais annoncé clairement
dans l'interface (`app/web/templates/settings_audio.html`).

## Étape 19 livrée : casque muet après reboot/cycle secteur, page "Associer" qui plante, + Oublier/sortie manuelle

Trois retours groupés après l'étape 18 (le fix auto-restart marche pour un
changement de sortie fait en direct) :

- **Casque muet après un redémarrage du Pi, ou juste après l'avoir
  éteint/rallumé** : il apparaît bien comme appairé, mais aucun son ne sort
  tant qu'on n'a pas relancé un scan et ré-associé le casque à la main.
  Cause : l'adaptateur Bluetooth du Pi reste ÉTEINT par défaut au démarrage
  de `bluetoothd` tant que rien n'appelle explicitement "power on" — ce qui,
  dans cette appli, n'arrivait que depuis les pages Scanner/Associer. Sans
  adaptateur alimenté, impossible pour un casque déjà appairé de se
  reconnecter tout seul (la reconnexion A2DP est à l'initiative du casque,
  mais seulement si le Pi est déjà joignable en Bluetooth). Fix :
  `install_pi.sh` active `AutoEnable=true` dans `/etc/bluetooth/main.conf` —
  l'adaptateur s'alimente désormais automatiquement dès que `bluetoothd`
  démarre, permettant à un appareil de confiance de se reconnecter sans
  aucune action côté appli.
- **La page "Associer" affichait parfois "Cette page ne fonctionne pas"**
  (la reconnexion avait pourtant réussi côté serveur — le son fonctionnait
  après avoir rechargé la page à la main) : cette route fait déjà
  pair+trust+connect (potentiellement plusieurs secondes) avant d'appeler
  `set_output()`, qui redémarre le service (étape 18) après un délai fixe —
  avec seulement 1 seconde, la réponse HTTP de cette requête (déjà bien
  entamée) pouvait se faire couper par le redémarrage. Délai remonté à 3
  secondes dans `bin/set-audio-output.sh`, large marge de sécurité.
- **Bouton "Oublier un appareil Bluetooth" et sortie manuelle** : le bouton
  "Oublier" existait déjà mais était réduit à une simple icône "✕" sans
  texte, facile à manquer — rendu plus visible ("🗑️ Oublier", avec
  confirmation). Ajout d'une section "Sortie manuelle (avancé)" avec un
  champ texte libre pour indiquer directement une cible ALSA (utile si un
  appareil Bluetooth connu doit être réutilisé sans repasser par un scan,
  ou pour tout cas non couvert par les listes automatiques) — réutilise la
  route `apply_audio_output` déjà générique, qui refuse maintenant
  proprement (message d'erreur, pas de plantage) une cible laissée vide.

## Étape 20 livrée : toujours muet après reboot malgré AutoEnable — reconnexion active au démarrage

Retour de test réel après l'étape 19 : `AutoEnable=true` ne suffisait pas,
le casque restait muet après un redémarrage du Pi.

Cause probable, en deux parties : `AutoEnable` alimente bien l'adaptateur
Bluetooth au démarrage de `bluetoothd`, mais ne force PAS activement une
reconnexion — il laisse seulement la porte ouverte pour que le casque la
déclenche de son côté, ce qui n'est ni instantané ni garanti (un casque
peut abandonner s'il ne retrouve pas le Pi assez vite). Et même quand la
reconnexion finit par réussir, elle peut arriver APRÈS que le service
applicatif (VLC compris) a déjà démarré et tenté sa première ouverture
audio, sans nouvelle tentative ensuite selon le comportement de libvlc.

Fix : nouvelle fonction `reconnect_configured_bluetooth_device()`
(`app/audio_output.py`) qui tente activement plusieurs reconnexions
espacées, appelée par un nouveau script `bin/reconnect_bluetooth_audio.py`
posé en `ExecStartPre` du service principal (`install_pi.sh` section 12) —
le démarrage du service est donc désormais bloqué le temps de cette
tentative de reconnexion (bornée, jamais indéfiniment : le tiret devant la
commande dans `ExecStartPre=-...` garantit qu'un échec total — casque
éteint ou hors de portée — n'empêche jamais le service de démarrer quand
même). `After=` de l'unité complété avec `bluetooth.service bluealsa.service`
pour un ordonnancement plus correct au boot.

## Étape 21 livrée : la reconnexion au boot (étape 20) abandonnait après une seule tentative

Retour de test réel, journal à l'appui (`journalctl -u contar`) :
les deux lignes de log ("Tentative de reconnexion" / "Non reconnecté")
apparaissaient à la MÊME seconde — bien trop rapide pour les 5 essais
espacés de 2 secondes prévus par l'étape 20.

Cause trouvée grâce à ce log : `reconnect_configured_bluetooth_device()`
n'appelait `bluetoothctl power on` qu'UNE SEULE FOIS, hors de la boucle de
réessais. Une seule exception à cet appel (cause probable : bluetoothd/le
bus D-Bus pas encore pleinement opérationnels à ce stade très précoce du
démarrage — `After=bluetooth.service` garantit seulement que le SERVICE a
démarré, pas que son adaptateur soit déjà utilisable) faisait alors
abandonner IMMÉDIATEMENT toute la fonction, sans jamais entrer dans la
boucle de réessais censée laisser le temps à bluetoothd de finir son
initialisation.

Fix : `power on` (et le déblocage rfkill) sont désormais À L'INTÉRIEUR de
la boucle de tentatives, comme le reste — un échec à n'importe quelle
étape ne fait plus qu'attendre le délai puis réessayer TOUT depuis le
début, au lieu d'abandonner au premier pépin. Le script de démarrage
(`bin/reconnect_bluetooth_audio.py`) appelle maintenant cette fonction
avec des paramètres plus généreux qu'à l'usage courant (10 essais espacés
de 3s, jusqu'à ~30s dans le pire cas) pour laisser une vraie marge au
démarrage, sans risquer d'atteindre le délai par défaut de systemd pour le
démarrage d'un service. Nouveau test qui reproduit exactement le
scénario confirmé en vrai (`power on` qui échoue les 2 premiers essais
puis réussit) pour éviter une régression future sur ce point précis.

## Étape 22 livrée : le log ne disait pas la vérité — print() bufferisé par bloc sous systemd

Retour de test réel : fix de l'étape 21 confirmé bien déployé (vérifié via
`grep power_out` directement sur `/opt/contar/app/audio_output.py`,
le fichier réellement utilisé par le service — pas la copie source dans
`~/contar/`, qui avait d'abord fait croire à tort à un défaut
de déploiement) — et pourtant même symptôme : les deux lignes de log
toujours à la même seconde, alors que la boucle interne devrait maintenant
prendre jusqu'à ~30 secondes.

Cause trouvée : ce n'est pas la boucle qui s'arrêtait tôt, c'est le LOG qui
mentait. `print()` en Python est bufferisé PAR BLOC (pas ligne par ligne)
dès que sa sortie standard n'est pas un vrai terminal — exactement la même
famille de piège que `bluetoothctl scan on` plus tôt dans ce projet (étape
16). Sous systemd, la sortie standard du service est un tube vers
journald, jamais un terminal : les deux `print()` de
`bin/reconnect_bluetooth_audio.py` restaient donc coincés dans le tampon
jusqu'à la fin du script, écrits dans le journal TOUS LES DEUX D'UN COUP à
ce moment précis — quel que soit le temps réel écoulé entre les deux.
Impossible de savoir, avec seulement ces deux lignes, si la boucle avait
vraiment tourné en tentant plusieurs fois pour de bon (et avait fini par
échouer malgré tout — un échec Bluetooth réel, pas un bug de boucle) ou si
elle s'arrêtait encore tout de suite pour une autre raison.

Fix : chaque tentative de reconnexion journalise désormais sa propre ligne
détaillée (`app/audio_output.py::reconnect_configured_bluetooth_device()`),
avec `flush=True` explicite partout dans `bin/reconnect_bluetooth_audio.py`
en plus de `Environment=PYTHONUNBUFFERED=1` posé sur le service entier par
`install_pi.sh` — pour que TOUS les logs du service (pas seulement ceux-ci)
reflètent enfin l'ordre et le moment réels des événements. Le prochain
retour de log dira la vérité sur ce qui se passe à chaque essai plutôt que
de tout compresser en une seule ligne trompeuse.

## Étape 23 livrée : la reconnexion Bluetooth au boot ne doit plus être forcée depuis le Pi

Retour de test réel : fix de log de l'étape 22 confirmé — les logs
montrent enfin honnêtement 10 vraies tentatives, étalées sur ~90 secondes
comme attendu. Mais le vrai symptôme, maintenant visible sans ambiguïté :
un échec net et identique à chaque tentative, `br-connection-page-timeout`
(erreur BR/EDR normalisée : le Pi a "sonné" le casque au niveau radio et
n'a reçu aucune réponse), alors que le casque était confirmé allumé et à
portée pendant TOUTE la séquence de démarrage. Plus un problème de
timing logiciel : une vraie tentative de connexion Bluetooth qui échoue
franchement, dix fois de suite.

Cause probable : certains casques ne répondent pas volontiers à une
connexion initiée par l'hôte après leur propre mise sous tension — ils
préfèrent reprendre la main eux-mêmes et "sonner" activement leur dernier
appareil appairé. Pire, le fait que `reconnect_configured_bluetooth_device()`
insiste avec `bluetoothctl connect` (qui occupe le contrôleur Bluetooth du
Pi le temps de chaque tentative, ~10s) peut activement gêner cette
reconnexion côté casque au lieu de l'aider, en rendant le Pi injoignable
pendant les fenêtres où le casque, de son côté, tente justement de le
"sonner".

Fix : `reconnect_configured_bluetooth_device()` (`app/audio_output.py`) ne
force plus la connexion depuis le Pi. Elle se contente désormais de garder
l'adaptateur allumé et disponible (rfkill + power on, toujours retentés à
chaque itération) puis ATTEND, en interrogeant périodiquement l'état
(`bluetoothctl info`), que le casque établisse lui-même la connexion à son
rythme — ce que permet déjà le simple fait que l'adaptateur soit
"connectable" dès qu'il est allumé, indépendamment du mode "discoverable"
(inutile ici puisque l'appareil est déjà appairé). Le service continue de
bloquer son démarrage pendant cette attente (bornée, ~30s par défaut), pour
laisser sa chance à une reconnexion qui arrive souvent avec quelques
secondes de retard sur le boot du Pi — mais sans plus jamais y insister
activement.

## Étape 24 livrée : Bluetooth retiré, sortie audio restructurée (gpio / jack USB / hdmi1 / hdmi2)

Retour de test réel : même le fix de l'étape 23 (attente passive de la
reconnexion, plus aucune connexion forcée depuis le Pi) n'a rien changé —
le Bluetooth ne fonctionne toujours pas correctement. Décision : le
retirer pour l'instant plutôt que de continuer à s'acharner dessus, pour
se concentrer sur la stabilité du reste et les autres améliorations. Tout
l'historique de dépannage (D-Bus, rfkill, AutoEnable, bufferisation des
logs, échec de connexion persistant...) reste consigné ci-dessus
("Étape 20" à "Étape 23") si le sujet est repris plus tard.

En même temps, restructuration complète de la sortie audio, qui n'était
plus adaptée une fois le Bluetooth retiré :
- **gpio** : les haut-parleurs intégrés à la boîte, câblés en dur sur un
  ampli séparé branché sur les broches GPIO (distinct de la prise jack
  3.5mm du Pi) — TOUJOURS disponible, sortie par défaut.
- **jack** : un jack branché via un adaptateur audio USB. Un Raspberry Pi
  standard n'a pas de détection matérielle d'insertion jack (pas de
  "jack sense") — la présence du jack est donc détectée indirectement,
  via l'apparition/disparition du périphérique audio USB correspondant
  dans `aplay -l` (déjà exploité pour distinguer les sorties, voir
  `app/audio_output.py::_is_usb_card()`, qui vérifie
  `/proc/asound/cardN/usbid`, posé par le noyau uniquement pour les
  cartes son USB — fiable, pas une supposition sur le nom de la carte).
- **hdmi1** / **hdmi2** : les deux sorties HDMI d'un Pi qui en a deux,
  distinguées par leur index de carte (ex: "vc4hdmi0"/"vc4hdmi1").

Règle demandée : le jack, s'il est branché, prend TOUJOURS la priorité,
quel que soit le réglage manuel choisi — ce réglage (un sélecteur
gpio/hdmi1/hdmi2 dans Réglages → Sortie audio) ne sert qu'à départager
les haut-parleurs et les deux sorties HDMI quand aucun jack n'est
branché. Implémentation :
- `app/audio_output.py::resolve_effective_output(preference)` — jack
  détecté ? on l'utilise ; sinon la préférence manuelle ; sinon "gpio"
  par défaut.
- Nouveau réglage persistant `audio_output_preference` (gpio par défaut)
  dans `app/settings.py`, distinct du réglage existant `audio_output` qui
  reflète toujours la sortie RÉELLEMENT appliquée à cet instant (laquelle
  peut différer de la préférence si un jack est branché).
- Nouveau service systemd `contar-audio.service`
  (`bin/audio_output_watchdog.py`), qui tourne EN CONTINU (même principe
  que le watchdog Wifi de secours existant) pour réagir à un
  branchement/débranchement de jack EN COURS DE LECTURE, pas seulement
  au démarrage de la boîte — il ne redémarre le lecteur (via
  `set_output()`, déjà nécessaire à cause du cache ALSA par processus,
  voir plus haut) que quand la sortie effective a réellement changé
  depuis son dernier passage, pour ne pas couper une lecture en cours
  toutes les 5 secondes pour rien.
- Remplace l'ancien `bin/reconnect_bluetooth_audio.py` (ExecStartPre
  ponctuel) : la bascule audio n'est pas un événement qu'on ne traite
  qu'au boot, elle peut arriver à tout moment.

Page Réglages → Sortie audio mise à jour en conséquence : section
Bluetooth remplacée par une note expliquant qu'il est temporairement
retiré, section "Sorties filaires" (avec un bouton "Utiliser" par carte)
remplacée par un sélecteur gpio/hdmi1/hdmi2 unique (pour éviter que deux
mécanismes différents — boutons par carte et préférence stockée —
finissent par se contredire), section "Sortie manuelle (avancé)"
conservée pour les cas non couverts.

## Étape 25 livrée : réinitialisation usine + assistant de bienvenue

Demande : pouvoir confier la boîte à quelqu'un d'autre, donc un bouton qui
efface tout (livres, musique, tags, listes de lecture, Wifi de la maison,
mapping boutons) puis redémarre — et qu'au redémarrage, la boîte redemande
un code PIN, propose le Wifi, puis affiche quelques diapos d'explication,
comme à la toute première utilisation.

**Réinitialisation** (`app/factory_reset.py::perform_factory_reset()`),
dans un ordre précis :
1. Le Wifi de la maison est "oublié" côté NetworkManager (réutilise
   `forget_wifi_network()`, déjà utilisé par "Oublier ce réseau") PENDANT
   que le SSID est encore lisible en base — l'effacer après coup l'aurait
   rendu introuvable.
2. Toute la base SQLite (livres, catégories/tags, albums, morceaux,
   listes de lecture, plages horaires, ET la table `settings` en entier —
   code PIN et mapping boutons compris, c'est délibéré) : le fichier est
   supprimé puis recréé vide plutôt que vidé table par table.
3. Le CONTENU de `Bibliotheque/Livres`, `Bibliotheque/Musiques` et `data/covers` est effacé
   (pas les dossiers eux-mêmes, pour ne pas avoir à les recréer avec les
   bonnes permissions).
4. `wifi_fallback.sync_fallback_conf()` régénère le point d'accès de
   secours à partir des réglages désormais vides — génère au passage un
   nouveau mot de passe aléatoire (mécanisme d'auto-génération déjà en
   place, réutilisé tel quel).
5. Une clé `onboarding_pending` est posée à "1" — TOUJOURS en dernier,
   puisque l'étape 2 vient de tout effacer, y compris cette clé si elle
   avait déjà été posée.

Ne touche volontairement PAS aux dossiers `extra_book_folders`/
`extra_music_folders` (ajoutés par un parent en plus de `Bibliotheque/`) : seule la
RÉFÉRENCE à ces dossiers (qui vit dans `settings`) disparaît, pas les
fichiers eux-mêmes, potentiellement hors du périmètre de cette appli.

**Redémarrage** : nouvelle fonction `app/system_control.py::reboot_now()`,
jumelle de `shutdown_now()` existante (`sudo shutdown -r now` au lieu de
`-h now`) — RÉUTILISE la règle sudoers déjà posée pour le bouton
"Éteindre" (`NOPASSWD: /sbin/shutdown`, sans restriction d'arguments,
donc `-r now` est déjà couvert) : aucune modification d'`install_pi.sh`
nécessaire pour ça.

**Confirmation** : un simple `confirm()` JavaScript n'a pas semblé assez
sûr vu l'irréversibilité — la page dédiée (`/reglages/reinitialisation-usine`)
liste précisément ce qui va être effacé et exige de taper la phrase
"RÉINITIALISER" (insensible à la casse) avant d'agir ; sans la bonne
phrase, rien n'est touché.

**Assistant de bienvenue** ("Étape 25", nouvelles routes `/bienvenue/...`
dans `app/web/routes.py`) : tant que `SettingsManager.is_onboarding_pending()`
répond vrai, un nouveau hook `require_onboarding` (`before_request`,
enregistré juste après `require_login`) redirige TOUT accès au reste de
l'appli vers `/bienvenue/pin` — impossible de le contourner par un lien
direct. Trois étapes obligatoires dans l'ordre : création d'un vrai code
PIN (min. 4 chiffres, pas besoin de connaître l'ancien puisqu'il vient
d'être effacé), connexion Wifi (facultative, bouton "Passer cette étape"
explicite), puis 5 diapos statiques expliquant les grandes fonctions de
la boîte. La dernière diapo pose `onboarding_pending` à "0" et rend enfin
la main sur l'appli normale.

**Important pour ne PAS régresser les boîtes déjà en service** :
`is_onboarding_pending()` renvoie `"0"` par défaut quand la clé est
ABSENTE de la base (`_get_setting("onboarding_pending", "0")`) — une
boîte déjà installée avant l'ajout de cette fonctionnalité n'a jamais
cette clé, donc une simple mise à jour du code ne lui impose JAMAIS
l'assistant par surprise. Seule une réinitialisation usine EXPLICITE pose
cette clé à "1".

Bouton d'accès : nouvelle section "⚠️ Zone de danger" tout en bas de
Réglages (`settings_menu.html`).

Vérifié par tests Python purs bout en bout : base + fichiers factices
(livre, album/morceau, tag, playlist, Wifi, PIN, mapping boutons) créés,
réinitialisation appelée, vérification que tout est bien vide/effacé et
que les dossiers eux-mêmes survivent, qu'une boîte "jamais réinitialisée"
(clé absente) n'est pas mise en attente d'assistant, puis parcours web
complet avec le vrai client de test Flask (connexion → redirection forcée
vers l'assistant → création du PIN avec validation → étape Wifi passée →
diapos → fin d'assistant → accès à nouveau autorisé), et enfin la page de
confirmation qui refuse d'agir sans la phrase exacte. Aucun accès à du
vrai matériel dans cet environnement de dev — **à confirmer au prochain
test réel : le redémarrage a-t-il bien lieu derrière la réinitialisation,
et l'assistant apparaît-il bien au premier login qui suit ?**

## Étape 26 livrée : la réinitialisation usine n'oubliait pas TOUS les réseaux Wifi

Retour de test réel : après une réinitialisation usine (étape 25),
d'autres réseaux Wifi restaient enregistrés côté Raspberry Pi OS — seul
demandé : qu'il ne reste que le Wifi de secours après un reset.

Cause : `perform_factory_reset()` n'oubliait que le SEUL SSID connu de
l'appli (`settings.net_wifi_ssid`, via `forget_wifi_network(ssid)`) — mais
NetworkManager peut avoir enregistré D'AUTRES connexions Wifi au fil du
temps sans jamais passer par cette appli : réglées à la main via
`nmtui`/`raspi-config` pendant l'installation initiale, laissées par un
ancien propriétaire, ou d'un déménagement où la boîte a été connectée
ailleurs. L'appli ne les "connaît" pas (elle ne garde qu'un seul SSID en
mémoire), donc ne les oubliait jamais.

Fix : `bin/forget-wifi.sh` gagne un second mode, `--toutes` (en plus du
mode existant `<ssid>`, inchangé, toujours utilisé par "Oublier ce
réseau" dans Réglages → Réseau) : liste TOUTES les connexions
NetworkManager de type Wifi (`802-11-wireless`), et les supprime une par
une — sauf le point d'accès de secours ("Contar-Secours") qui doit
justement survivre au reset, pour rester joignable juste après le
redémarrage qui suit. `app/network_apply.py::forget_all_wifi_networks()`
appelle ce nouveau mode ; `app/factory_reset.py` l'utilise désormais à la
place du simple SSID connu. Aucune règle sudoers supplémentaire dans
`install_pi.sh` : la règle déjà posée pour `bin/forget-wifi.sh`
(`NOPASSWD: $APP_DIR/bin/forget-wifi.sh`, sans restriction d'arguments)
couvre déjà `--toutes`.

Vérifié par test qui exécute RÉELLEMENT `bin/forget-wifi.sh --toutes` en
bash (pas juste un mock Python) avec un faux `nmcli` listant 3 réseaux
Wifi + 1 connexion Ethernet + le point d'accès de secours : confirme que
seuls les 2 vrais réseaux Wifi tiers sont supprimés, que le point d'accès
de secours et la connexion Ethernet sont épargnés, et que
`perform_factory_reset()` appelle bien `forget_all_wifi_networks()` sans
argument (donc sans plus se limiter au SSID que l'appli connaissait).

## Étape 27 livrée : mot de passe fixe pour le Wifi de secours (plus aléatoire)

Retour signalé en discutant du fix de l'étape 26 (réseaux Wifi oubliés au
reset) : question posée sur le mot de passe du point d'accès de secours
("Contar-Secours"). Réponse initiale : il était généré au hasard
(`secrets.token_hex(4)`) à la toute première lecture — donc inconnaissable
d'avance, et re-généré différemment à chaque réinitialisation usine
puisque ce réglage est effacé comme le reste (étape 26). Problème
remonté : ça rend le point d'accès de secours inutilisable pour une
personne lambda qui déballe la boîte ou vient de faire un reset usine —
justement les deux seuls moments où il sert, puisque c'est le SEUL moyen
d'atteindre l'interface web tant que le vrai Wifi n'est pas configuré (il
faudrait déjà être connecté au Wifi pour lire ce mot de passe dans
Réglages → Réseau, ce qui est exactement ce qu'on essaie de faire).

Fix : `SettingsManager.DEFAULT_WIFI_FALLBACK_PASSWORD`, une valeur FIXE
(`"audiolibre"` depuis la v0.8, 10 caractères, largement au-dessus des 8 minimum
requis pour du WPA2), identique sur toutes les installations et à chaque
reset usine — choisie plutôt qu'un mot de passe par boîte pour rester
simple à documenter et à retenir pour "une personne lambda", au prix d'un
mot de passe connu de quiconque a lu le guide (accepté : ce réseau ne
donne accès qu'à l'assistant de première config, jamais à Internet ni aux
données de la boîte). `GUIDE_RASPBERRY.md` indique désormais ce mot de
passe en clair dans la procédure, au lieu de renvoyer vers une page
elle-même inaccessible sans être déjà connecté. Reste modifiable ensuite
par un parent depuis Réglages → Réseau (`set_wifi_fallback_config()`,
inchangé) : ce n'est qu'une valeur de départ, pas une contrainte
permanente.

Vérifié par test : première lecture (base vide) renvoie bien la valeur
fixe, deux lectures consécutives renvoient exactement la même valeur (pas
régénérée à chaque appel), la personnalisation par un parent fonctionne
toujours, une réinitialisation usine complète (`perform_factory_reset()`)
retombe bien sur la MÊME valeur fixe après coup (et non une nouvelle
valeur aléatoire), le guide ne mentionne plus "généré au hasard" et
indique le mot de passe en clair, et plus aucune trace de
`secrets.token_hex` dans `app/settings.py`.

## Étape 28 livrée : le scan Wifi ne trouve jamais rien tant qu'on est connecté au point d'accès de secours

Retour signalé juste après l'étape 27 (mot de passe de secours fixé) :
une fois connecté au Wifi de secours pour reconfigurer le vrai Wifi, la
liste "Réseaux Wifi détectés à proximité" (Réglages → Réseau) reste
toujours vide, même entouré d'autres réseaux qui devraient apparaître.

Diagnostic : ce n'est PAS un bug réparable côté scan. La boîte n'a qu'UNE
seule antenne/puce Wifi (comme la quasi-totalité des Raspberry Pi et des
dongles USB) : tant que NetworkManager l'utilise pour DIFFUSER le point
d'accès de secours (mode hotspot), cette même antenne ne peut PAS, en
parallèle, faire un scan actif pour chercher d'autres réseaux —
limitation matérielle/pilote, pas quelque chose que
`nmcli device wifi rescan` (`app/network_status.py::scan_wifi_networks()`,
inchangé) peut contourner. La liste sera donc TOUJOURS vide dans ce mode
précis, quel que soit le nombre de réseaux à portée.

Fix : pas de réparation du scan (impossible sans 2e antenne), mais de
l'honnêteté côté interface. `settings_network.html` reçoit déjà
`fallback_status.active` (utilisé pour le bandeau "Point d'accès de
secours actif") — exploité maintenant pour remplacer, dans ce mode
précis, le message générique trompeur ("Wifi caché, ou hors de portée du
scan") par une explication claire de la vraie cause, plus un bandeau
d'avertissement au-dessus du sélecteur qui pousse directement vers la
saisie manuelle du SSID/mot de passe — qui, elle, fonctionne très bien
dans ce mode (déjà le cas avant, juste jamais mis en avant). Si des
réseaux sont malgré tout détectés (cas limite, adaptateur Wifi USB
secondaire par exemple), la liste s'affiche normalement, sans message
contradictoire. `GUIDE_RASPBERRY.md` prévient désormais de la même chose
dans la procédure pas à pas du Wifi de secours.

Vérifié par test avec le vrai client de test Flask (pas un simple test de
template isolé) : point d'accès actif + aucun réseau → message honnête
affiché, ancien message trompeur absent ; Wifi normal + aucun réseau →
ancien comportement générique inchangé ; point d'accès actif + réseaux
quand même détectés → liste affichée normalement, pas de message
"scan indisponible" contradictoire ; guide à jour.

## Branche parallèle : boîte PC x86 / clé USB (retirée en v0.8)

Une autre cible avait été explorée : un PC x86 qui démarre en plein écran
sur l'application. Elle n'était plus entretenue et a été retirée du projet
en v0.8 (`run_box.py`, `setup_kiosk.sh`, `GUIDE_INSTALLATION.md`).

Les deux cibles restantes (Pi, PC clavier) partagent strictement
la même logique métier (`app/controls/actions.py`, `app/player.py`, base
de données, interface web) — seule la source de contrôle physique change.

## v0.9 : import par clé USB et tags maîtres

Voir `CHANGELOG.md` (section v0.9) pour le détail, `app/usb_import.py` pour
le fonctionnement, et `GUIDE_RASPBERRY.md` pour le mode d'emploi. Pour
l'essayer sur PC sans clé ni Raspberry Pi :

```bash
mkdir -p /tmp/ma_cle/Audiolibre/Livres /tmp/ma_cle/Audiolibre/Musiques
# déposez quelques .mp3 dans ces dossiers, puis :
CONTAR_CLE_SIMULEE=/tmp/ma_cle python run.py
```

## Prochaines étapes

- Tester `install_pi.sh` sur un vrai Raspberry Pi
- Valider sur du vrai matériel : sélecteur de sortie audio / Bluetooth (étape 8),
  application réelle de la config réseau (étape 9), point d'accès de secours (étape 11)
- Wiki d'installation (Artifact + HTML) à republier — en retard depuis plusieurs fonctionnalités
