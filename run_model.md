# Running the End-to-End Chess Player Clone Pipeline

This guide outlines how to execute the full machine learning pipeline—from raw Chess.com game archives to a personalized move and think-time clone model using **Maia-3** and a custom **MLP Adapter**.

---

## 1. Environment & Prerequisites

Ensure you are working inside the project directory with the virtual environment activated:

```bash
cd /Users/sairajan/gator_hacks/gator_hacks_project
source .venv/bin/activate
```

Dependencies installed in `.venv`:
- `python-chess`
- `torch` (with Apple Silicon MPS acceleration support)
- `numpy`
- `pandas`
- `huggingface-hub`
- `pytest`
- Local `maia3` package (installed from `./maia3`)
- Maia-3 5M model weights cached at [`models/maia3-5m.pt`](file:///Users/sairajan/gator_hacks/gator_hacks_project/models/maia3-5m.pt)

---

## 2. Running Unit Tests

Run the test suite verifying mathematical consistency, feature integrity, and data leakage protection:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_pipeline.py -v
```

Tests include:
- **Zero-offset test**: Verifies that before training, the MLP adapter's move offset is exactly $0$, matching Maia-3 probabilities identically.
- **Feature count test**: Validates that every legal move receives exactly $28$ features ($16$ move features + $12$ clock/context features).
- **Clock arithmetic test**: Confirms clock calculations match ground truth think times.
- **Split integrity test**: Ensures no game ID appears in more than one data split.

---

## 3. Running the Complete End-to-End Pipeline

To replay games, compute Maia-3 logits, extract the 28-feature representation, save the snapshot table, and train all models:

```bash
PYTHONPATH=. .venv/bin/python run_pipeline.py --csv stuffyness.csv --epochs 30
```

### Useful Command-Line Arguments

| Argument | Default | Description |
| :--- | :--- | :--- |
| `--csv` | `stuffyness.csv` | Input games CSV (Chess.com archive export). |
| `--out-csv` | `snapshots_with_logits.csv` | Output tabular snapshot dataset with Maia logits. |
| `--out-pt` | `snapshots_dataset.pt` | Output PyTorch tensor bundle for training. |
| `--epochs` | `30` | Number of epochs for adapter training. |
| `--batch-size` | `128` | Batch size for Maia-3 GPU inference. |
| `--train-batch-size` | `256` | Batch size for adapter training. |
| `--limit-games` | `None` | Limit number of games to parse (e.g. `--limit-games 10` for quick runs). |
| `--skip-extraction` | `False` | Skip running Maia-3 if `snapshots_dataset.pt` already exists. |

#### Example: Fast Retraining (Skipping Maia Extraction)
If `snapshots_dataset.pt` has already been generated:
```bash
PYTHONPATH=. .venv/bin/python run_pipeline.py --skip-extraction --epochs 30
```

---

## 4. Evaluating the Trained Model

### Evaluate on Held-Out Test Games
Evaluate the best saved checkpoint ([`mlp_adapter_best.pt`](file:///Users/sairajan/gator_hacks/gator_hacks_project/mlp_adapter_best.pt)) against plain Maia-3 and constant time baselines on the $10\%$ held-out test split:

```bash
PYTHONPATH=. .venv/bin/python evaluate.py
```

### Test an Arbitrary Board Position (Interactive FEN Test)
Evaluate a custom board state, comparing the clone's adjusted probabilities and think times against Maia-3:

```bash
PYTHONPATH=. .venv/bin/python evaluate.py \
  --fen "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1" \
  --clock 450 \
  --opp-clock 480
```

---

## 5. Pipeline Artifacts & Output Files

- [`snapshots_with_logits.csv`](file:///Users/sairajan/gator_hacks/gator_hacks_project/snapshots_with_logits.csv): Tabular dataset (18,124 rows) with game IDs, FENs, played moves, think times, Maia-3 target logits, probabilities, and top-1 predictions.
- `snapshots_dataset.pt`: PyTorch tensor dictionary with inputs $X \in \mathbb{R}^{18124 \times 64 \times 28}$, `maia_logits`, `mask`, `target_idx`, and `seconds`.
- `mlp_adapter_best.pt`: Best saved MLP model weights ($28 \to 64 \to 64 \to \text{heads}$).
- `linear_adapter_best.pt`: Saved baseline linear model weights for ablation comparisons.

