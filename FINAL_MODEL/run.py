import sys
from pathlib import Path

from snapshots import run as make_snapshots
from maia_extractor import run as extract
from implementation import train
from play_clone import play

if __name__ == "__main__":
    csv = sys.argv[1]
    folder = Path(__file__).resolve().parent.parent

    make_snapshots(csv, folder / "snapshots.csv")
    dataset_pt = extract(csv, folder / "snapshots_with_logits.csv", folder / "snapshots_dataset.pt")
    weights = train(dataset_pt)
    play(weights)
