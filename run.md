# End-to-End Chess Player Clone Pipeline

This project builds a personalized chess move and think-time clone from Chess.com game archives using **Maia-3** and a custom **MLP Adapter**.

---

## ⚡ Quickstart

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Run unit tests
PYTHONPATH=. .venv/bin/pytest tests/test_pipeline.py -v

# 3. Train from any games CSV
python train_and_play.py stuffyness.csv

# 4. Train and immediately play against the clone in terminal
python train_and_play.py stuffyness.csv --play
```

---

## Project Structure

```
├── Model/
│   ├── snapshots.py         # Replays games and extracts per-move snapshots
│   ├── features.py          # Builds the 28-feature representation per move slot
│   ├── maia_extractor.py    # Runs Maia-3 inference to get legal move logits
│   ├── implementation.py    # Clone MLP model architecture & training loss
│   ├── play_clone.py        # Interactive terminal chess game against the clone
│   └── service.py           # Clean service functions for backend integration
├── src/
│   ├── backend/
│   │   └── model_service.py # Exported backend functions for web API routes
│   └── frontend/
├── data/
│   ├── stuffyness.csv       # Sample player games (500 games)
│   ├── hikaru.csv           # Hikaru Nakamura rapid games
│   └── chess_pgn_parser.py  # Utility to download games from Chess.com API
├── tests/
│   └── test_pipeline.py     # Unit tests for zero-offset, features, clocks
├── train_and_play.py        # Unified CLI pipeline runner
└── run.md                   # Documentation
```

---

## Backend Integration API

To connect the model pipeline to a web backend (FastAPI / Flask / Django), import the clean functions from `src.backend.model_service`:

```python
from src.backend.model_service import (
    create_snapshots,
    extract_maia_logits,
    train_clone,
    evaluate_clone,
    predict_move,
    train_from_csv,
)

# 1. Complete end-to-end training job:
result = train_from_csv("data/stuffyness.csv", out_model_path="Model/clone.pt", epochs=30)
print(result["evaluation"])

# 2. Live position prediction during web game:
import chess
board = chess.Board()
move_result = predict_move(
    board=board,
    elo=1800,
    own_clock=500.0,
    opp_clock=520.0,
    clone_weights_path="Model/clone.pt",
)
print("Clone played:", move_result["chosen_san"])
print("Thinking time:", move_result["think_seconds"])
```

---

## Command-Line Options for `train_and_play.py`

| Flag | Default | Description |
| :--- | :--- | :--- |
| `csv` | `stuffyness.csv` | Input CSV path of games. |
| `--epochs` | `50` | Maximum training epochs (early stopping applies). |
| `--batch-size` | `128` | Batch size for Maia-3 GPU/MPS inference. |
| `--train-batch-size` | `256` | Batch size for MLP adapter training. |
| `--limit-games` | `None` | Limit number of games (e.g. `--limit-games 10` for fast testing). |
| `--skip-extraction` | `False` | Skip Maia-3 extraction if `snapshots_dataset.pt` already exists. |
| `--play` | `False` | Launch interactive terminal match after training. |

