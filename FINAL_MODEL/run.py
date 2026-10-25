import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
ROOT = DIR.parent
for p in (str(ROOT / "maia3"), str(ROOT), str(DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from snapshots import run as make_snapshots
from maia_extractor import run as extract
from implementation import train
from play_clone import play
from chess_pgn_parser import fetch_user_games_and_save
try:
    from src.backend.database import Database
except ImportError:
    Database = None

if __name__ == "__main__":
    db = Database()

    if len(sys.argv) > 1:
        target = sys.argv[1].strip()
    else:
        target = input("Enter chess.com username or path to CSV [default: stuffyness]: ").strip()
        if not target:
            target = "stuffyness"

    # 1. Determine if target is a file path or a username
    if Path(target).is_file():
        csv = Path(target)
        player_id = csv.stem.lower()
        db.create_or_get_user(user_id=player_id, chess_com_username=player_id)
        db.import_games_csv(csv, src="chess.com", default_player_id=player_id)
    else:
        player_id = target.lower()
        # Look for local cached CSV first
        local_csv = next(
            (p for p in [
                DIR / f"{player_id}.csv",
                ROOT / f"{player_id}.csv",
                ROOT / "model_dev" / f"{player_id}.csv",
                ROOT / "data" / f"{player_id}.csv",
            ] if p.is_file()),
            None,
        )

        if local_csv:
            csv = local_csv
            db.create_or_get_user(user_id=player_id, chess_com_username=target)
            db.import_games_csv(csv, src="chess.com", default_player_id=player_id)
        else:
            print(f"Fetching games from Chess.com for user '{target}'...")
            csv, _ = fetch_user_games_and_save(target, limit=500, out_csv=DIR / f"{player_id}.csv")

    folder = ROOT

    make_snapshots(str(csv), str(folder / "snapshots.csv"))
    dataset_pt = extract(str(csv), str(folder / "snapshots_with_logits.csv"), str(folder / "snapshots_dataset.pt"))
    weights = train(dataset_pt)

    # 2. Save model weights keyed by user_id in the models table
    db.save_model_weights(player_id=player_id, weights_path=weights)
    print(f"Saved model weights for {player_id} to database models table.")

    play(weights)
