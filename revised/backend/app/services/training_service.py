import logging
from pathlib import Path
from typing import Callable, Optional, Union
import torch
from app.config import settings
from app.db.repositories import model_repo
from app.services import pgn_service

logger = logging.getLogger(__name__)


def get_games_for_opponent(opp: str, limit: int = 60) -> list[dict]:
    """Fetch games for opponent in memory without creating temporary CSV files."""
    opp_clean = opp.strip().lower()

    # 1. Fetch live from Chess.com Public API
    try:
        games = pgn_service.fetch_user_games(opp_clean, limit=limit)
        if games:
            logger.info("fetched %d games from Chess.com in-memory for '%s'", len(games), opp_clean)
            return games
    except Exception as e:
        logger.warning("Chess.com API live fetch failed for '%s': %s", opp_clean, e)

    # 2. Check existing local fallback archive if present in project root
    candidate = settings.PROJECT_ROOT / f"{opp_clean}.csv"
    if candidate.is_file():
        import csv
        logger.info("reading existing fallback archive: %s", candidate.name)
        with open(candidate, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                return rows
                if rows:
                    return rows

    raise RuntimeError(f"Could not fetch or locate games for opponent '{opp}'.")


def train_clone_mlp(dataset_or_tensors: Union[Path, dict[str, torch.Tensor]], out_weights: Path) -> Path:
    """Train Clone MLP directly from in-memory tensors and save final checkpoint."""
    from app.ml.implementation import Clone, compute_loss

    out_weights.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(dataset_or_tensors, dict):
        tensors = dataset_or_tensors
    else:
        tensors = torch.load(dataset_or_tensors, map_location="cpu", weights_only=False)

    game_ids = tensors.get("game_ids", [])
    if not game_ids or len(tensors["X"]) == 0:
        raise ValueError("Dataset contains no snapshot tensors to train on.")

    # Split 80/20 by unique games to prevent data leakage
    unique_games = list(dict.fromkeys(game_ids))
    n_train_games = max(1, int(len(unique_games) * 0.8))
    train_set = set(unique_games[:n_train_games])

    train_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid in train_set], dtype=torch.long)
    val_idx = torch.tensor([i for i, gid in enumerate(game_ids) if gid not in train_set], dtype=torch.long)
    if len(val_idx) == 0:
        val_idx = train_idx

    train = (
        tensors["X"][train_idx],
        tensors["maia_logits"][train_idx],
        tensors["mask"][train_idx],
        tensors["target_idx"][train_idx],
        tensors["seconds"][train_idx],
    )
    val = (
        tensors["X"][val_idx],
        tensors["maia_logits"][val_idx],
        tensors["mask"][val_idx],
        tensors["target_idx"][val_idx],
        tensors["seconds"][val_idx],
    )

    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = Clone().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    batch_size = 128
    n_samples = len(train[0])

    train_dev = tuple(t.to(device) for t in train)
    val_dev = tuple(t.to(device) for t in val)

    best_val, best_state, patience, bad = float("inf"), None, 5, 0

    for epoch in range(40):
        model.train()
        perm = torch.randperm(n_samples, device=device)
        for i in range(0, n_samples, batch_size):
            idx = perm[i : i + batch_size]
            batch = [t[idx] for t in train_dev]
            loss, _, _ = compute_loss(model, *batch)
            opt.zero_grad()
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            _, v_move, _ = compute_loss(model, *val_dev)

        if v_move < best_val:
            best_val = v_move.item()
            bad = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break

    if best_state is None:
        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    from app.ml.implementation import move_accuracy
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        val_acc = move_accuracy(model, val_dev[0], val_dev[1], val_dev[2], val_dev[3])

    torch.save(best_state, out_weights)
    logger.info("Saved clone model checkpoint to %s (val_loss=%.4f, val_acc=%.4f)", out_weights, best_val, val_acc)
    return out_weights, float(best_val), float(val_acc)


def run_training_pipeline(
    opp: str,
    broadcast_cb: Optional[Callable[[str, int, str], None]] = None,
    trained_by_user_id: Optional[str] = None,
) -> Path:
    """Run end-to-end training pipeline in memory without creating intermediate CSV files."""
    def notify(status: str, progress: int, msg: str):
        logger.info("[Training: %s] %d%% - %s", opp, progress, msg)
        if broadcast_cb:
            try:
                broadcast_cb(status, progress, msg)
            except Exception:
                pass

    opp_clean = opp.strip().lower()
    models_dir = settings.MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)
    final_weights = models_dir / f"{opp_clean}.pt"

    # Step 1: Fetch games in memory (30%)
    notify("fetching_data", 30, f"Fetching games from Chess.com for {opp}...")
    games = get_games_for_opponent(opp_clean, limit=60)
    if not games:
        raise ValueError(f"No games found to train clone for {opp_clean}")

    # Step 2: Extract Maia-3 logits and feature tensors directly in memory (70%)
    notify("maia_features", 70, "Extracting move snapshots and Maia-3 logits in memory...")
    from app.ml.maia_extractor import extract_snapshots_and_maia_logits
    from app.services.inference_service import ensure_maia_checkpoint
    maia_ckpt = str(ensure_maia_checkpoint())
    _, tensors = extract_snapshots_and_maia_logits(
        rows=games,
        checkpoint_path=maia_ckpt,
        limit_games=60,
        batch_size=64,
        player_id=opp_clean,
    )

    # Step 3: Train Clone MLP directly from in-memory tensors (90%)
    notify("training", 90, "Training personalized clone neural network...")
    _, val_loss, val_acc = train_clone_mlp(tensors, final_weights)

    # Step 4: Register model checkpoint in PostgreSQL models table
    model_repo.register_model_weights(
        opp_clean,
        f"models/{opp_clean}.pt",
        trained_by_user_id=trained_by_user_id,
        val_accuracy=val_acc,
        val_loss=val_loss,
    )
    notify("completed", 100, f"Model for {opp} trained and cached! (Loss: {val_loss:.4f}, Acc: {val_acc*100:.1f}%)")

    return final_weights


def sync_and_train_user_clone(chess_handle: str, user_id: str) -> None:
    """Fetch user's games into PostgreSQL and train their personal AI clone model."""
    from app.db.repositories import game_repo
    from app.services import commentary_service
    from app.workers import queue_manager

    clean_handle = chess_handle.strip().lower()
    logger.info("Starting automatic games cache & clone training for @%s (user %s)", clean_handle, user_id)

    # 1. Fetch and cache recent games from Chess.com into PostgreSQL
    try:
        games = game_repo.sync_user_games_from_chess_com(clean_handle, user_id=user_id, limit=50)
        logger.info("Cached %d games in database for @%s", len(games), clean_handle)
    except Exception as e:
        logger.warning("Error fetching games from Chess.com for @%s: %s", clean_handle, e)

    # 2. Train personal AI clone if not already cached
    if not queue_manager.is_cached(clean_handle):
        try:
            logger.info("Training personal clone network for @%s...", clean_handle)
            run_training_pipeline(clean_handle, trained_by_user_id=user_id)
            logger.info("Personal clone model successfully trained and registered for @%s", clean_handle)
        except Exception as e:
            logger.warning("Personal clone training error for @%s: %s", clean_handle, e)

    # 3. Generate Gemma playing style profile & vector embeddings
    try:
        commentary_service.describe_clone_style(clean_handle, refresh=True)
        logger.info("Gemma playing style profile generated for @%s", clean_handle)
    except Exception as e:
        logger.warning("Gemma style description error for @%s: %s", clean_handle, e)
