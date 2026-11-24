"""
Console interactive pour tester le lecteur audio (étape 2), avec du vrai
son. Nécessite que VLC (l'application) soit installé sur votre PC, et
qu'il y ait déjà des livres/morceaux en base (lancez test_step1.py avant
si ce n'est pas fait).

Commandes disponibles :
  list                  affiche les livres et morceaux disponibles avec leur id
  play book <id>        lance un livre
  play track <id>       lance un morceau
  pause                 met en pause
  resume                relance la lecture
  seek +10 / seek -10    avance / recule de 10 secondes
  seekto 30              se positionne à 30 secondes
  vol 80                 règle le volume à 80%
  vol+ / vol-             monte / baisse le volume
  state                   affiche l'état courant
  stop                    arrête la lecture
  quit                    quitte le programme
"""

from app.database import get_connection, init_database
from app.player import SEEK_STEP_MS, player_controller


def list_items() -> None:
    conn = get_connection()
    print("\n--- Livres ---")
    for row in conn.execute("SELECT id, title, author FROM books ORDER BY title"):
        print(f"  book {row['id']}: {row['title']} — {row['author']}")
    print("--- Morceaux ---")
    for row in conn.execute("SELECT id, title, artist FROM tracks ORDER BY title"):
        print(f"  track {row['id']}: {row['title']} — {row['artist'] or ''}")
    conn.close()
    print()


def print_state() -> None:
    state = player_controller.get_state()
    if state["kind"] is None:
        print("(rien en cours de lecture)")
        return
    pos_s = state["position_ms"] // 1000
    dur_s = state["duration_ms"] // 1000
    status = "lecture" if state["is_playing"] else "pause"
    print(f"[{status}] {state['title']} — {state['subtitle']} "
          f"| {pos_s}s / {dur_s}s | volume {state['volume']}%")


def main() -> None:
    init_database()
    print("=== Étape 2 : test du lecteur audio ===")
    list_items()
    print("Tapez 'help' pour revoir la liste des commandes, 'quit' pour arrêter.\n")

    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not command:
            continue
        parts = command.split()
        action = parts[0].lower()

        if action == "quit":
            break
        elif action == "help":
            print(__doc__)
        elif action == "list":
            list_items()
        elif action == "play" and len(parts) == 3 and parts[1] in ("book", "track"):
            ok = player_controller.play(parts[1], int(parts[2]))
            print("Lecture lancée." if ok else "Identifiant introuvable.")
        elif action == "pause":
            player_controller.pause()
        elif action == "resume":
            player_controller.resume()
        elif action == "seek" and len(parts) == 2:
            seconds = int(parts[1])
            player_controller.seek_relative(seconds * 1000)
        elif action == "seekto" and len(parts) == 2:
            player_controller.seek_to(int(parts[1]) * 1000)
        elif action == "vol" and len(parts) == 2:
            player_controller.set_volume(int(parts[1]))
        elif action == "vol+":
            player_controller.volume_up()
        elif action == "vol-":
            player_controller.volume_down()
        elif action == "state":
            print_state()
        elif action == "stop":
            player_controller.stop()
        else:
            print("Commande non reconnue. Tapez 'help' pour la liste des commandes.")

    player_controller.shutdown()
    print("Au revoir.")


if __name__ == "__main__":
    main()
