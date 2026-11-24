# Journal des versions

Chaque archive livrée à partir de maintenant porte un numéro de version
incrémental (visible aussi dans `VERSION`). Avant la v0.5, le projet a
évolué par petites livraisons ponctuelles sans numérotation — cette
version regroupe tout ce qui a été construit jusqu'ici en une seule base
de référence propre.

## v0.5 (base de référence)

Fonctionnalités NFC/écran/énergie construites lors de cette phase du
projet, en plus de la base "boîte à histoires" déjà existante (Wifi,
sortie audio, réinitialisation usine, bibliothèque de médias) :

- **Tags NFC/RFID** : un tag = un livre ou un album entier, associable
  depuis Réglages → Tags NFC ou directement depuis les fiches
  livre/album (badge rouge/vert). Lecteur PC/SC (Omnikey, pour test PC)
  et PN532 en I2C (lecteur définitif de la boîte) derrière une interface
  commune (`app/tag_reader.py`), interchangeables sans dupliquer la
  logique d'association/déclenchement.
- **Écran LCD 16x2 I2C** : message d'accueil, confirmation de tag
  (reconnu/inconnu), titre en défilement + statut + temps restant
  pendant la lecture, indicateur de volume, message avant extinction,
  rétroéclairage coupé après inactivité (délai réglable, Réglages →
  Énergie).
- **Reprise après redémarrage** : le bouton ▶️⏸️ relance la dernière
  lecture si rien n'est chargé, plus une action "Reprendre" dédiée.
- **Réglage Énergie** : Bluetooth/LEDs/détection caméra-écran désactivés
  en permanence (aucun usage dans le projet) ; HDMI et mode éco CPU
  réglables, HDMI toujours réactivé automatiquement si le son en dépend.
- **Mode silencieux programmé** : les plages horaires de Réglages →
  Horaires (déjà en place, jamais appliquées avant cette version)
  bloquent désormais le lancement d'une histoire par tag hors des
  horaires autorisés.
- **Correctifs d'installation** notables sur Raspberry Pi OS Trixie :
  polkit pour l'accès pcscd, wheel précompilé pour `lgpio`, chargement
  permanent du module `i2c-dev`, et connexion Wifi "à l'aveugle" (sans
  scan préalable) pour que la saisie manuelle du Wifi fonctionne
  vraiment depuis le point d'accès de secours.

## v0.6

- **Suppression de livres/albums** (`app/library_delete.py`) : bouton 🗑️
  sur la liste des livres, la fiche livre, la ligne d'album et la fiche
  album — retire la ligne en base, le(s) fichier(s) audio et la jaquette
  du disque, les tags associés et les entrées de listes de lecture qui
  pointaient dessus.
- **Écran LCD traduit** (français/occitan) : réutilise le système `t()`
  déjà en place pour l'interface web (`app/i18n.py`) — accueil, tag
  reconnu/inconnu, silence programmé, volume, extinction, lecture/pause.
- **Plafond de volume** configurable (Réglages → Sortie audio),
  appliqué dans `player.py::set_volume()`.
- **Correctif** : un tag pointant vers un livre/album supprimé affichait
  quand même "Tag reconnu" avec l'ancien titre en mémoire — vérifie
  maintenant que la lecture démarre vraiment avant d'afficher quoi que
  ce soit (`app/nfc_controller.py`).

## v0.7 — Contar, habillage Audiolibre

La boîte rejoint la suite Audiolibre sous le nom **Contar** (« raconter »
en occitan), à côté de Jogar et Crear. Cette version ne change que
l'habillage de l'administration : le moteur (lecture, tags, boutons,
écran LCD, réseau, énergie) est celui de la v0.6, et une boîte déjà
installée garde ses histoires, ses tags et ses réglages.

- **Charte Audiolibre** : fond clair, teinte miel, titres en Bricolage
  Grotesque, texte en Figtree. Le thème « nuit étoilée » disparaît.
- **Icônes dessinées** à la place des emojis (`app/web/icons.py`).
- **Polices embarquées** (`app/web/static/fonts/`) : rien n'est téléchargé
  depuis Internet, l'administration s'affiche pareil sur le point d'accès
  de secours.
- **Nouveau menu** : Lecture, Bibliothèque, Tags, Import, Réglages. En bas
  de l'écran sur téléphone, à gauche sur ordinateur.
  - *Bibliothèque* regroupe Histoires, Musique et Listes en trois onglets.
  - *Tags* sort des réglages et devient une entrée du menu.
  - *Import* (nouvelle page, `/HDP/import`) regroupe les deux formulaires
    d'envoi de fichiers, auparavant en haut des pages Livres et Musique.
- **Trois langues** : français, occitan, anglais, sur toutes les pages et
  sur l'écran LCD (Réglages → Langue de l'interface). Les traductions
  sont rangées dans `app/i18n_texts.py`, une ligne par texte ;
  `python3 tools/check_i18n.py` signale un texte oublié. L'occitan est à
  faire relire par un locuteur. Quelques messages techniques renvoyés par
  le système (détail d'une erreur réseau, par exemple) restent en français.
- **Réinitialisation usine** : le mot à recopier suit la langue
  (RÉINITIALISER, REINICIALIZAR, RESET).
- **Assistant de bienvenue** : textes adaptés au nouveau menu, une diapo
  ajoutée sur les tags.
- **Après une mise à jour**, le navigateur recharge tout seul la nouvelle
  feuille de style (numéro de version ajouté à l'adresse des fichiers).
- Adresses inchangées (`/HDP/...`), noms internes inchangés (service
  `histoiresdusoir`, dossier `HDP`, base de données).

Non modifié dans cette version, prévu ensuite : import par clé USB et
tags maîtres (v0.8), minuterie de coucher réellement appliquée et noms de
tags (v0.9), lien avec Jogar (v1.0).

## v0.7.1 — écran ou lecteur NFC absent

Correction d'un défaut présent depuis la v0.5, révélé en débranchant
l'écran pendant des essais de câblage.

- **Écran LCD absent : l'administration finissait par ne plus répondre.**
  Sans écran, `app/lcd_display.py` recréait l'objet d'affichage toutes les
  0,4 s ; chaque essai ouvrait le bus I2C sans le refermer. Au bout de
  quelques minutes le programme avait épuisé son quota de fichiers
  ouverts : plus de base de données (« unable to open database file »),
  plus de pages web. Désormais la boîte vérifie d'abord que l'écran
  répond (test qui referme le bus) et ne retente que toutes les 15 s.
- **Écran ou lecteur NFC branché après le démarrage** : repris tout seul
  en 15 s environ, sans redémarrer la boîte. Avant, l'écran restait sur
  des carrés et le lecteur n'était jamais relancé.
- **Journal** : une absence d'écran ou de lecteur est signalée une seule
  fois, au lieu d'une ligne toutes les 0,4 s.

Fichiers modifiés : `app/lcd_display.py`, `app/tag_reader.py`.

## v0.8 — socle Contar : renommage, adresse simple, réseau fiable

### Tout s'appelle Contar

| Élément | Avant | Maintenant |
|---|---|---|
| Adresse de l'administration | `http://<boîte>:5000/HDP` | `http://contar.local` (port 80, sans suffixe) |
| Dossier d'installation | `/opt/histoiresdusoir` | `/opt/contar` |
| Fichiers audio | `HDP/Livres`, `HDP/Musiques` | `Bibliotheque/Livres`, `Bibliotheque/Musiques` |
| Base de données | `data/histoiresdusoir.db` | `data/contar.db` |
| Services | `histoiresdusoir`, `-wifi-fallback`, `-audio-watchdog` | `contar`, `contar-wifi-secours`, `contar-audio` |
| Utilisateur système | `hds` | `contar` |
| Réseau de secours | `HistoiresDuSoir-Secours` / `histoiresdusoir` | `Contar-Secours` / `audiolibre` |
| Dossier du projet, archive | `histoiresdusoir-pi` | `contar` |
| Variable du dossier de données | `HDS_BASE_DIR` | `CONTAR_BASE_DIR` |

- `install_pi.sh` **reprend une ancienne installation** : il arrête les
  anciens services, déplace histoires, musiques et base vers les nouveaux
  emplacements, corrige les chemins enregistrés dans la base
  (`tools/migrate_old_install.py`), puis retire l'ancien dossier et
  l'ancien utilisateur.
- Les anciennes adresses en `/HDP/...` renvoient vers les nouvelles. Le
  port 5000 n'est plus utilisé sur la boîte (il le reste pour `run.py`,
  les essais sur PC).
- Retirés : la version PC plein écran (`run_box.py`, `setup_kiosk.sh`,
  `GUIDE_INSTALLATION.md`), abandonnée depuis longtemps.

### Changer de Wifi sans se couper

- **Essai avant adoption** (`bin/apply-network-config.sh`,
  `app/network_apply.py`). Un Wifi saisi est d'abord essayé pendant 40
  secondes sur un profil provisoire. Accepté : il devient le Wifi de la
  boîte. Refusé : la boîte revient à son Wifi précédent, ou rouvre son
  réseau de secours, et dit pourquoi (mot de passe refusé, réseau
  introuvable). Avant, l'ancien réglage était supprimé d'emblée et un
  échec était annoncé comme une réussite.
- **Page d'attente** pendant l'essai, qui se met à jour dès que l'appareil
  retrouve la boîte ; résultat rappelé en haut de la page Réseau.
- **Le nom de la boîte ne change plus tout seul.** La page Réseau
  renvoyait un nom pré-rempli à `histoiresdusoir` : enregistrer n'importe
  quel réglage renommait la boîte, qui ne répondait plus à son adresse.
  Le nom affiché est maintenant celui du système, et il n'est appliqué
  que s'il a été modifié.
- **Enregistrer sans rien changer ne touche plus au Wifi.** Avant, chaque
  enregistrement supprimait et recréait la connexion.
- **Wifi en WPA3 seul et réseaux cachés** pris en charge.

### Réseau de secours

- **Page ouverte toute seule** : sur le réseau de secours, la boîte répond
  à toutes les adresses et renvoie vers son administration ; le téléphone
  propose « Se connecter au réseau ». Selon les appareils, la page s'ouvre
  seule ou après un appui sur cette notification.
- **Plus de coupure pendant qu'on configure** : la boîte ne quitte plus le
  réseau de secours pour retenter le Wifi de la maison tant qu'un appareil
  y est connecté (avant : toutes les 3 minutes, quoi qu'il arrive).
- **Retour au Wifi de la maison même s'il a été réglé à la préparation de
  la carte SD** (inconnu de l'administration) : avant, une boîte dans ce
  cas ne quittait plus jamais son réseau de secours.
- **Nom et mot de passe modifiés pris en compte** : le profil du réseau de
  secours est recréé à chaque ouverture.

### Écran de la boîte

- Au démarrage et à chaque changement : `Wifi maison` et l'adresse.
- Pendant un essai : `Essai du Wifi`, puis `Wifi OK` et l'adresse, ou
  `Echec du Wifi` / `Secours actif`.
- Sur le réseau de secours, l'écran d'attente alterne avec le nom du
  réseau puis son mot de passe.

### Sous le capot

- Dans les scripts réseau, les tests du type `nmcli ... | grep -q` pouvaient
  répondre « absent » à tort (interaction avec `pipefail`) ; remplacés.
- Essais sans boîte, avec un faux `nmcli` : essai du Wifi (14 situations),
  veille du réseau de secours (8 situations), parcours complet depuis la
  page Réseau. **Non essayé sur un vrai Raspberry Pi** : le comportement
  réel de NetworkManager, l'ouverture du portail sur les téléphones, le
  port 80 et la reprise d'une ancienne installation sont à valider sur la
  boîte.

## v0.9 — import par clé USB et tags maîtres

### Importer avec une clé USB

On branche une clé sur la boîte ; elle doit contenir un dossier
`Audiolibre` rangé comme la bibliothèque : `Audiolibre/Livres` (un fichier
= une histoire) et `Audiolibre/Musiques` (un sous-dossier = un album).
Formats MP3, M4A, M4B ; clés FAT32 ou exFAT. Deux actions :

- **Ajouter** copie ce qui n'est pas encore sur la boîte. Ne supprime et
  ne modifie rien ; un fichier de même nom mais de contenu différent est
  laissé tel quel et signalé.
- **Remplacer** : après l'import, la boîte contient exactement ce qu'il y
  a sur la clé. Ce qui est identique n'est pas recopié et garde son tag,
  sa position de lecture et sa place dans les listes. Ce qui n'est plus
  sur la clé part en **réserve**.

Garde-fous (`app/usb_import.py`) :

- La clé est reliée **en lecture seule** (`bin/usb-key.sh`, lancé par
  sudo, qui refuse tout ce qui n'est pas une clé USB). La retirer à
  n'importe quel moment ne l'abîme pas.
- **Copie d'abord, mise en place ensuite.** Les fichiers arrivent dans un
  dossier d'attente ; rien ne change avant la fin. Clé retirée ou coupure
  de courant : la boîte repart comme avant (reprise au démarrage).
- **Réserve et annulation.** Ce que Remplacer retire reste sur la boîte
  jusqu'au prochain import réussi, avec une copie des fiches (tags,
  positions, listes). L'écran Import propose « Annuler le dernier
  remplacement ».
- **Place vérifiée avant de copier.** S'il en manque, l'ancienne réserve
  est vidée d'abord ; si cela ne suffit pas, l'import est refusé.
- Pendant l'import, la lecture s'arrête et les tags d'histoire sont
  ignorés ; l'envoi et la suppression de fichiers par l'administration
  attendent la fin. L'import fonctionne à toute heure.
- Une histoire envoyée depuis un téléphone **après** un remplacement est
  gardée si l'on annule ce remplacement.
- Les raccourcis (liens) présents sur une clé ne sont jamais suivis.

### Tags maîtres

- Deux tags réservés, déclarés dans **Tags → Tags maîtres** par la même
  capture que les tags d'histoire : « Ajouter » et « Remplacer ».
- Remplacer demande de **reposer le tag dans les 10 secondes** (et pas
  avant 1 seconde).
- **Lecteur de tags plus tolérant** (`app/tag_reader.py`) : une lecture
  manquée ne fait plus croire qu'un tag resté posé vient d'être reposé ;
  il faut deux lectures vides de suite (environ 1,5 seconde hors du
  lecteur). Un autre tag est pris en compte tout de suite. Sans cela, un
  faux contact aurait pu confirmer « Remplacer » à la place du parent.
- Un tag maître ne peut pas lancer une histoire, et inversement.

### Sur la boîte : écran et sons, sans annonce parlée

| Moment | Écran | Son |
|---|---|---|
| Clé reconnue | Clé prête / Posez un tag | bip court |
| Clé sans dossier Audiolibre | Clé non reconnue | double bip |
| Tag maître sans clé | Branchez une clé | double bip |
| Remplacer, première pose | Remplacer tout ? / Reposez le tag | bip court |
| Copie | Import 7/23 / titre | aucun |
| Fin | Import fini / 12 ajoutées | carillon |
| Ensuite | Retirez la clé | aucun |
| Refus | Pas assez / de place, ou Rien à importer | double bip |

Messages en français, occitan et anglais (sans accents : l'écran ne les
connaît pas). Deux sons ajoutés (`tools/make_sounds.py`).

### Écran Import de l'administration

- Cadre **Clé USB**, mis à jour tout seul : ce que contient la clé, ce
  qui serait copié, ce que Remplacer retirerait, la place libre ; boutons
  **Ajouter les nouveautés** et **Remplacer tout** ; barre d'avancement ;
  bilan.
- **Dernier remplacement** : ce qui est en réserve, bouton d'annulation.
- **Derniers imports par clé** : date, action, par tag ou par
  l'administration, résultat (table `imports`).
- L'envoi de fichiers depuis le téléphone ou l'ordinateur reste en dessous.

### Réseau de secours : page ouverte toute seule, deuxième essai

Sur la boîte de référence, la page ne s'ouvrait pas seule sur téléphone.
Cause probable : beaucoup de téléphones Android écartent un portail dont
l'adresse est privée (10.42.0.1). La boîte répond désormais par une
adresse d'apparence extérieure, et une règle du pare-feu (`nft`) ramène
vers elle le trafic web du réseau de secours
(`bin/wifi-fallback-watchdog.sh`, `portal_setup`). Sans `nft`, l'ancienne
méthode est gardée. **Non vérifié sur un vrai téléphone.**

### Pour essayer sans Raspberry Pi

`CONTAR_CLE_SIMULEE=/chemin/vers/un/dossier python run.py` : ce dossier
tient lieu de clé tant qu'il existe.

### Limites connues

- Les histoires rangées dans un sous-dossier de `Livres`, et les fichiers
  plus profonds qu'un album dans `Musiques`, sont ignorés (et comptés).
- Une clé préparée à la main n'apporte pas ses tags : ils s'associent
  ensuite dans l'administration. Les tags apportés par Jogar arrivent
  avec la v1.0.
- Lecture d'une vraie clé (montage FAT32 ou exFAT) et tags maîtres sur le
  vrai lecteur : essayés seulement avec du matériel simulé.
- Les scripts lancés avec les droits d'administration (`bin/*.sh`)
  appartiennent à l'utilisateur de l'appli, comme depuis le début du
  projet : qui prendrait la main sur l'administration web pourrait les
  modifier. Sans conséquence pour une boîte à la maison ; à revoir si une
  boîte devait un jour être exposée sur Internet.

## v0.10 — finitions

### Noms de tags

- Chaque tag peut recevoir un nom (« Loup bleu ») : à l'association, ou
  plus tard par **Nommer / Renommer** dans la page Tags. Table `tags`.
- Le nom suit le tag : il est gardé si le tag change d'histoire ou n'est
  plus associé à rien, et il est proposé d'office quand on repose le tag.
- Dans la Bibliothèque, la pastille verte porte le nom du tag.

### Filtre « Sans tag »

- Histoires et albums : deux pastilles sous les onglets, **Toutes / Sans
  tag**, avec les comptes. Le filtre n'apparaît que s'il reste des
  éléments sans tag. Associer un tag depuis la liste filtrée la vide au
  fur et à mesure.
- Après un import par clé, l'écran Import rappelle combien d'histoires et
  d'albums n'ont pas encore de tag, avec un lien vers cette liste.

### Minuterie de coucher : enfin appliquée

Le réglage existait depuis le début mais n'avait aucun effet. Désormais
(`app/player.py`) :

- la lecture se met **en pause** N minutes après le dernier lancement
  voulu : tag posé, bouton lecture, lecture demandée depuis
  l'administration, morceau changé à la main ;
- un album ou une liste qui enchaîne tout seul **ne relance pas** le
  compteur ;
- le son **baisse sur les 15 dernières secondes**, puis le volume est
  rétabli pour la prochaine fois ; l'histoire reprendra au même endroit ;
- une pause à la main arrête le compteur, la reprise le relance en entier ;
- l'écran affiche « Bonne nuit ! / Minuterie finie » ; la page Lecture
  affiche « Pause dans 12 min » ;
- changer le réglage s'applique tout de suite à la lecture en cours.

### Assistant de bienvenue

- Nouvelle étape facultative **Import par clé USB** (3 sur 4) : déclarer
  les deux tags maîtres sans quitter l'assistant.
- Diapos mises à jour (clé USB, minuterie).

### Retiré

- Les « dossiers supplémentaires » hérités de la version Android (jamais
  proposés dans l'administration) : la boîte ne lit plus que
  `Bibliotheque/Livres` et `Bibliotheque/Musiques`. Les anciens réglages
  sont effacés au démarrage.

### Limites connues

- Minuterie, noms de tags et filtre essayés sur matériel simulé (faux
  lecteur audio) : la baisse du son en fin de minuterie reste à écouter
  sur la vraie boîte.

## v0.10.1 — ampli MAX98357A, bouton déplacé, écran tout juste branché

### Ampli MAX98357A (son par les broches)

- `install_pi.sh` ajoute `dtoverlay=max98357a,no-sdmode` à `config.txt` :
  après un redémarrage, l'ampli apparaît comme une carte son « MAX98357A ».
- **L'ampli passe avant la prise casque d'origine du Pi** pour la sortie
  « haut-parleurs » (`app/audio_output.py`). Avant, la première carte
  listée gagnait — en général la prise casque — et l'ampli restait muet.
  Un adaptateur jack USB branché garde la priorité, comme avant.
- Câblage et essai : voir `GUIDE_RASPBERRY.md`, « Ampli MAX98357A ».

### Le bouton de la broche GPIO 19 passe sur la GPIO 16

L'ampli occupe les broches GPIO 18, 19 et 21 : un bouton ne peut plus se
trouver sur la 19. Il passe sur la 16, sa voisine (broche physique 36, en
face de la 35) — **un fil à déplacer d'un cran**. Les réglages déjà faits
(action du bouton, combinaison d'extinction) suivent tout seuls.

Au passage : une broche occupée n'empêche plus la boîte de démarrer, le
bouton concerné est simplement ignoré (avant, tout le programme s'arrêtait).

### Écran LCD tout juste branché

Un écran branché pendant que la boîte tourne était mis en route à
l'instant où il répondait, parfois avant d'être prêt. La boîte attend
maintenant une seconde et vérifie qu'il répond toujours.

Nouvel outil `tools/test_ecran.py` : essaie l'écran seul, sans le reste du
programme (mode d'emploi en tête du fichier et dans le guide).

## v0.10.2 — ampli sans souffle, écran repris plus vite

### Plus de souffle au début des lectures

L'ampli MAX98357A s'endort dès que le Pi cesse de lui envoyer du son et
se réveille avec un souffle bref : on l'entendait à chaque lancement et à
chaque reprise. Remède habituel pour ce composant, appliqué ici :

- un mélangeur partagé `contar_ampli` est posé sur la carte de l'ampli
  (`/etc/alsa/conf.d/60-contar-ampli.conf`) ;
- un service `contar-ampli` y joue du silence en permanence : l'ampli
  reste éveillé ;
- la boîte joue à travers ce mélangeur (`bin/set-audio-output.sh`). Effet
  secondaire utile : les bips de la boîte peuvent se superposer à une
  histoire en cours.

Conséquence pour les essais à la main : l'ampli n'est plus joignable
directement (`plughw:MAX98357A,0` répond « occupé »). Utiliser
`aplay -D plug:contar_ampli fichier.wav`.

**Essayé ici seulement pour la syntaxe du réglage** (pas de carte son sur
le banc) : à écouter sur la boîte.

### Écran LCD

- Après une erreur d'écriture, l'écran est repris au bout de 2 secondes
  au lieu de 15 : une perturbation passagère ne le laisse plus figé sur
  une lettre. Après 5 erreurs de suite, retour au rythme lent.
- `tools/test_ecran.py` explique une liaison perturbée en clair, au lieu
  d'afficher une erreur technique.

## v0.10.3 — tonalité du haut-parleur, câblage de référence

### Tonalité du haut-parleur

Réglages → Volume et sortie audio : trois curseurs, **graves, médiums,
aigus**, de −12 à +12 dB, appliqués à l'instant (on règle à l'oreille
pendant une lecture), et un bouton « Remettre à plat ».

- Le réglage ne s'applique que lorsque le son sort par le haut-parleur de
  la boîte ; au casque ou en HDMI, le son reste tel quel.
- Renforcer une bande baisse un peu le volume général, pour éviter la
  saturation.
- S'appuie sur l'égaliseur de VLC (`app/player.py::apply_tone`).

### Ampli : les deux canaux réunis

Avec sa broche SD reliée au 3,3 V, le MAX98357A ne joue que le canal
gauche. La boîte lui envoie maintenant les deux canaux réunis
(`contar_ampli_mono`) : rien ne se perd sur une musique en stéréo.

### Boutons : broches du schéma de câblage

Les boutons sont écoutés sur les broches du schéma de la boîte : GPIO 17
(retour), 27 (lecture/pause), 22 (avance), 5 (volume −), 6 (volume +).
Les broches 13, 16 et 26 des versions précédentes restent écoutées.

### Limites connues

- Tonalité et canaux réunis essayés sans carte son (faux lecteur audio,
  sortie factice) : à écouter sur la boîte.

## Versions suivantes

À compléter à chaque nouvelle archive (résumé bref des changements,
pas un historique détaillé — le "pourquoi" de chaque décision reste dans
les fichiers de code concernés, pas ici).

## v0.11.0 — le tag devient la télécommande, le câble USB-C remplace la clé

Refonte profonde du fonctionnement de la boîte. Une boîte déjà installée
garde ses histoires, ses tags, ses listes et ses réglages.

**Le geste de l'enfant**
- **Poser un tag** joue son contenu, **le retirer** met en pause en douceur
  (fondu court) et enregistre l'avancement, **le reposer dans les 3 s**
  remet à zéro (son « rembobinage »). Délai réglable, et désactivable, dans
  Tags (`app/tag_gesture.py`, `app/nfc_controller.py`).
- Le lecteur signale désormais l'arrivée **et le retrait** d'un tag ; une
  lecture ratée de temps en temps n'est pas prise pour un retrait (0,5 s
  sans lecture avant de conclure, `app/tag_reader.py`).
- **Avancement par tag** (table `tag_progress`) : deux tags peuvent lancer
  la même histoire sans se gêner. Reprise avec 3 s de recul pour une
  histoire. À la fin du contenu, l'avancement est effacé.
- **Un tag joue une histoire, un album ou une liste de lecture**, avec sa
  façon de jouer : reprendre ou toujours au début, ordre mélangé,
  recommencer à la fin (`app/tag_playback.py`, page Tags).

**Le câble USB-C**
- Relié à un ordinateur, le port USB-C du Pi 4 se présente comme une carte
  réseau (administration sur `http://10.55.0.1`) et un disque « CONTAR »
  (dépôt) : copier, éjecter, la boîte range et joue un carillon
  (`bin/usb-gadget.sh`, `app/usb_gadget.py`, `app/depot_import.py`).
- Mode transfert pendant la connexion : lecture en pause, tags inactifs
  (sauf pour les associer), voyant vert qui clignote.
- Alimentation trop faible de l'ordinateur détectée et signalée (Import).

**Énergie**
- Veille légère après 1 min sans rien, extinction après 15 min, réglables
  (Réglages → Énergie, `app/power_manager.py`). Jamais pendant un transfert.
- Bouton de réveil sur la GPIO 3 (broche 5 contre la masse) : rallume la
  boîte éteinte ; boîte allumée, un appui long l'éteint.
- Démarrage plus rapide : le service n'attend plus le réseau, services
  inutiles coupés, `boot_delay=0`, pas d'écran de démarrage.

**Voyants** (`app/leds.py`) : vert = allumée (clignote vite : reliée à un
ordinateur, lentement : en veille) ; rouge = lecture en cours. GPIO 23 et 24.

**Wi-Fi activable au choix** (Réglages → Réseau). Coupé, la boîte se règle
par le câble USB-C ; le réseau de secours ne s'ouvre plus.

**Mise à jour depuis GitHub** (Réglages → Mise à jour, `app/updater.py`,
`bin/update-contar.sh`) : vérifie la dernière version publiée du dépôt et
relance `install_pi.sh` dessus. Dépôt privé : jeton en lecture seule.

**Retiré**
- Import par clé USB, tags maîtres « Ajouter »/« Remplacer » et leur étape
  dans l'assistant de bienvenue (`app/usb_import.py`, `bin/usb-key.sh`).
- Écran LCD (`app/lcd_display.py`, `tools/test_ecran.py`, RPLCD, smbus2).
  Les dossiers de travail de l'ancien import sont nettoyés au démarrage ;
  `Bibliotheque/.reserve` (ce qu'un ancien « Remplacer » avait retiré) est
  laissé en place : `sudo rm -rf /opt/contar/Bibliotheque/.reserve` pour
  récupérer la place.

**Matériel** : le PN532 passe en **SPI** (SCK 23, MISO 21, MOSI 19, SS 22)
pour libérer la GPIO 3. Une boîte pas encore recâblée :
`sudo NFC_BUS=i2c bash install_pi.sh . gpio` (sans bouton de réveil).

**Correctif** : un album ou une liste ne passait à l'élément suivant que si
la vérification (une par seconde) tombait dans la dernière demi-seconde du
morceau ; sinon la lecture s'arrêtait. La fin du fichier est désormais
reconnue telle quelle.

**Tests** : `python -m pytest tests/` (geste, parcours complet avec le vrai
lecteur, pages de l'administration, rangement du dépôt).
