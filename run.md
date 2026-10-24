# End-to-End Pipeline Execution Guide

This document provides step-by-step instructions to run the entire pipeline: from data preprocessing and Maia-3 logits extraction, to MLP adapter training, evaluation, and playing against your clone.

---

## ⚡ Quickstart (TL;DR)

Run these commands from the repository root:

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Run unit tests
PYTHONPATH=. .venv/bin/pytest tests/test_pipeline.py -v

# 3. Run full end-to-end extraction, training, and evaluation
PYTHONPATH=. .venv/bin/python run_pipeline.py --csv stuffyness.csv --epochs 30

# 4. View held-out test evaluation report
PYTHONPATH=. .venv/bin/python evaluate.py

# 5. Play against the trained clone in terminal!
PYTHONPATH=. .venv/bin/python Model/play_clone.py
```

---

## Step 1: Environment Setup & Maia-3 Weights

If you haven't set up the virtual environment or Maia-3 yet:

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install torch numpy pandas python-chess huggingface_hub pytest

# Clone and install Maia-3 locally
git clone https://github.com/CSSLab/maia3.git
pip install -e ./maia3 --no-deps

# Download the Maia-3 5M weights to ./models/
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='UofTCSSLab/Maia3-5M', filename='maia3-5m.pt', local_dir='./models')"
```

---

## Step 2: Run Unit Tests

Verify that all mathematical invariants, zero-offset initialization, feature dimensions, and leakage rules pass:

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_pipeline.py -v
```

**Checked tests:**
- `test_zero_offset_exact_match`: Ensures initial adapter offset $d(m) = 0$ exactly matches Maia-3 probabilities.
- `test_feature_count`: Confirms every legal move produces exactly $28$ features ($16$ move features + $12$ context features).
- `test_clock_arithmetic`: Verifies think-time calculations against sample ground truth.
- `test_split_integrity`: Verifies $0$ game overlap between train, validation, and test splits.

---

## Step 3: Run the Full Pipeline

Execute the end-to-end pipeline on your games CSV:

```bash
PYTHONPATH=. .venv/bin/python run_pipeline.py --csv stuffyness.csv --epochs 30
```

### What this does automatically:
1. **Replays all 500 games** from `stuffyness.csv` to create 18,124 player move snapshots.
2. **Runs Maia-3 in batches** on GPU/MPS to extract raw move logits for every legal move.
3. **Builds the 28-feature representation** for each move slot (padded to 64 slots).
4. **Saves snapshot outputs**:
   - `snapshots_with_logits.csv`: Human-readable table with Maia logits, probabilities, and ranks.
   - `snapshots_dataset.pt`: PyTorch tensor bundle for instant loading.
5. **Splits chronologically by game**:
   - **80% Train** (14,290 snapshots)
   - **10% Validation** (1,799 snapshots)
   - **10% Test** (2,035 snapshots)
6. **Trains the MLP Adapter** ($28 \to 64 \to 64$) with early stopping and AdamW.
7. **Saves trained model weights**:
   - `mlp_adapter_best.pt`
   - `Model/clone.pt` (directly used by `Model/play_clone.py`)
8. **Evaluates against baselines** and checks **PRD Decision Gate C**.

---

## Step 4: Model Evaluation

### 1. Evaluate on Held-Out Test Games
Compare Plain Maia-3, the Linear baseline, and the MLP Adapter:

```bash
PYTHONPATH=. .venv/bin/python evaluate.py
```

### 2. Test an Individual Board Position (FEN)
Test any position to compare Maia's probability vs. the clone's adjusted probability and predicted think time:

```bash
PYTHONPATH=. .venv/bin/python evaluate.py \
  --fen "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1" \
  --clock 450 \
  --opp-clock 480
```

---

## Step 5: Play Against the Clone

Play an interactive game against the trained clone in your terminal:

```bash
PYTHONPATH=. .venv/bin/python Model/play_clone.py
```

- Choose your color (`white` or `black`).
- Enter your Elo rating.
- Make your moves in standard algebraic notation (e.g., `e4`, `Nf6`, `O-O`).
- The clone calculates move probabilities, offsets, and pauses for its predicted thinking time before making its move!

---

## Useful Command-Line Flags for `run_pipeline.py`

| Flag | Default | Purpose |
| :--- | :--- | :--- |
| `--csv` | `stuffyness.csv` | Input CSV path of raw Chess.com games. |
| `--out-csv` | `snapshots_with_logits.csv` | Output path for the snapshot CSV table. |
| `--out-pt` | `snapshots_dataset.pt` | Output path for the PyTorch tensor file. |
| `--epochs` | `30` | Maximum training epochs. |
| `--batch-size` | `128` | Batch size for Maia-3 inference. |
| `--train-batch-size` | `256` | Batch size for MLP adapter training. |
| `--limit-games` | `None` | Limit number of games to parse (e.g. `--limit-games 10` for fast testing). |
| `--skip-extraction` | `False` | Skip running Maia-3 if `snapshots_dataset.pt` already exists. |

---

## Key Output Files

| File | Description |
| :--- | :--- |
| `snapshots_with_logits.csv` | Tabular dataset (18,124 rows) with FENs, clocks, played moves, Maia logits, and ranks. |
| `snapshots_dataset.pt` | PyTorch tensor dataset containing tensors $X$, `maia_logits`, `mask`, `target_idx`, and `seconds`. |
| `mlp_adapter_best.pt` | Best checkpoint from training the MLP adapter. |
| `Model/clone.pt` | Model checkpoint formatted for `Model/play_clone.py`. |

