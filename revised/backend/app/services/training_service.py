import logging
from pathlib import Path
from typing import Callable, Optional, Union
import torch
from app.config import settings
from app.db.repositories import model_repo
from app.services import pgn_service

logger = logging.getLogger(__name__)


def get_games_for_opponent(opp: str, limit: int = 60) -> list[dict]:
    """Fetch games for opponent directly from live Chess.com API or synced database."""
    opp_clean = opp.strip().lower()

    # 1. Fetch live from Chess.com Public API with full move text and clocks
    try:
        games = pgn_service.fetch_user_games(opp_clean, limit=limit)
        if games:
            logger.info("fetched %d games with clocks from Chess.com for '%s'", len(games), opp_clean)
            return games
    except Exception as e:
        logger.warning("Chess.com API live fetch failed for '%s': %s", opp_clean, e)

    # 2. Sync live from Chess.com Public API into PostgreSQL games table
    try:
        from app.db.repositories import game_repo
        synced = game_repo.sync_user_games_from_chess_com(opp_clean, user_id=opp_clean, limit=limit)
        if synced:
            logger.info("synced %d games from Chess.com into database for '%s'", len(synced), opp_clean)
            return synced
    except Exception as e:
        logger.warning("Chess.com API sync failed for '%s': %s", opp_clean, e)

    # 3. Fallback to PostgreSQL database games table
    try:
        from app.db.repositories import game_repo
        db_games = game_repo.get_user_games(opp_clean, limit=limit)
        if db_games:
            logger.info("retrieved %d games from PostgreSQL for '%s'", len(db_games), opp_clean)
            return db_games
    except Exception as e:
        logger.debug("Database game lookup failed for '%s': %s", opp_clean, e)

    raise RuntimeError(f"Could not fetch or locate games in database or Chess.com for opponent '{opp}'.")


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

    # Step 4: Register model checkpoint in PostgreSQL models table with real rating
    rating = model_repo.get_chess_rating_for_player(opp_clean)
    model_repo.register_model_weights(
        opp_clean,
        f"models/{opp_clean}.pt",
        trained_by_user_id=trained_by_user_id,
        val_accuracy=val_acc,
        val_loss=val_loss,
        chess_elo=rating,
    )

    # Step 5: Automatically generate & persist playing style profile right after model training
    notify("generating_style", 95, f"Generating playing style profile and vector embedding for {opp}...")
    try:
        from app.services import commentary_service
        style_res = commentary_service.describe_clone_style(opp_clean, refresh=True)
        logger.info(
            "Clone style description generated and cached in DB for @%s: %s",
            opp_clean,
            style_res.get("style_description", "")[:80],
        )
    except Exception as e:
        logger.warning("Automatic style description failed for %s: %s", opp_clean, e)

    rating_str = f", Rating: {rating}" if rating else ""
    notify("completed", 100, f"Model for {opp} trained and cached! (Loss: {val_loss:.4f}, Acc: {val_acc*100:.1f}%{rating_str})")

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


def evaluate_existing_clone(player_id: str) -> dict:
    """Run genuine Maia-3 move_accuracy evaluation on a clone checkpoint."""
    from app.ml.implementation import Clone, compute_loss, move_accuracy
    from app.ml.maia_extractor import extract_snapshots_and_maia_logits
    from app.services.inference_service import ensure_maia_checkpoint

    opp_clean = player_id.lower().strip()
    weights_path = model_repo.get_model_weights_path(opp_clean)
    if not weights_path or not weights_path.is_file():
        raise FileNotFoundError(f"Model checkpoint for '{opp_clean}' not found")

    games = get_games_for_opponent(opp_clean, limit=40)
    if not games:
        raise ValueError(f"No match history found to evaluate clone '{opp_clean}'")

    maia_ckpt = str(ensure_maia_checkpoint())
    _, tensors = extract_snapshots_and_maia_logits(
        rows=games,
        checkpoint_path=maia_ckpt,
        limit_games=40,
        batch_size=64,
        player_id=opp_clean,
    )

    X = tensors["X"]
    maia_logits = tensors["maia_logits"]
    mask = tensors["mask"]
    target_idx = tensors["target_idx"]
    seconds = tensors["seconds"]

    if len(X) == 0:
        raise ValueError(f"Extracted 0 valid snapshots from games for '{opp_clean}'")

    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = Clone().to(device)
    state = torch.load(weights_path, map_location=device, weights_only=False)
    model.load_state_dict(state)
    model.eval()

    X_dev = X.to(device)
    logits_dev = maia_logits.to(device)
    mask_dev = mask.to(device)
    target_dev = target_idx.to(device)
    sec_dev = seconds.to(device)

    with torch.no_grad():
        val_acc = move_accuracy(model, X_dev, logits_dev, mask_dev, target_dev)
        _, val_move_loss, _ = compute_loss(model, X_dev, logits_dev, mask_dev, target_dev, sec_dev)

    val_loss = float(val_move_loss.item())
    val_acc = float(val_acc)

    # Persist the genuine evaluation accuracy into PostgreSQL models table
    model_repo.update_model_metrics(opp_clean, val_accuracy=val_acc, val_loss=val_loss)
    logger.info("Successfully evaluated clone '%s': val_accuracy=%.4f (%.1f%%), val_loss=%.4f", opp_clean, val_acc, val_acc * 100, val_loss)

    return {
        "player_id": opp_clean,
        "val_accuracy": val_acc,
        "val_loss": val_loss,
        "snapshots_evaluated": len(X),
        "status": "evaluated",
    }


def evaluate_all_clones() -> list[dict]:
    """Scan and run move_accuracy evaluation on all available disk clone checkpoints."""
    results = []
    if not settings.MODELS_DIR.is_dir():
        return results

    for p in settings.MODELS_DIR.glob("*.pt"):
        stem = p.stem.lower().strip()
        if stem in ("maia3-5m", "maia3"):
            continue
        try:
            res = evaluate_existing_clone(stem)
            results.append(res)
        except Exception as e:
            logger.warning("Failed evaluation for clone '%s': %s", stem, e)
            results.append({"player_id": stem, "error": str(e), "status": "failed"})

    return results


def benchmark_clone_performance(player_id: str, limit: int = 50) -> dict:
    """Run full comparative benchmark (Move Top-1/Top-3 Maia vs Clone + Decision Time Accuracy)."""
    import numpy as np
    import torch.nn.functional as F
    from app.ml.implementation import Clone
    from app.ml.maia_extractor import extract_snapshots_and_maia_logits
    from app.services.inference_service import ensure_maia_checkpoint

    opp_clean = player_id.lower().strip()
    weights_path = model_repo.get_model_weights_path(opp_clean)
    if not weights_path or not weights_path.is_file():
        logger.info("Clone checkpoint for '%s' not found. Training model now...", opp_clean)
        run_training_pipeline(opp_clean)
        weights_path = model_repo.get_model_weights_path(opp_clean)
        if not weights_path or not weights_path.is_file():
            raise FileNotFoundError(f"Failed to train and locate model checkpoint for '{opp_clean}'")

    games = get_games_for_opponent(opp_clean, limit=limit)
    if not games:
        raise ValueError(f"No match history found for '{opp_clean}'")

    maia_ckpt = str(ensure_maia_checkpoint())
    _, tensors = extract_snapshots_and_maia_logits(
        rows=games,
        checkpoint_path=maia_ckpt,
        limit_games=limit,
        batch_size=64,
        player_id=opp_clean,
    )

    X = tensors["X"]
    maia_logits = tensors["maia_logits"]
    mask = tensors["mask"]
    target_idx = tensors["target_idx"]
    actual_sec = tensors["seconds"].numpy()
    N = len(target_idx)
    if N == 0:
        raise ValueError(f"Zero valid move positions extracted for '{opp_clean}'")

    # 1. Baseline Maia-3 Move Evaluation
    maia_masked = maia_logits.masked_fill(mask == 0, float("-inf"))
    base_pred = maia_masked.argmax(dim=1)
    base_top1 = float((base_pred == target_idx).float().mean().item())

    _, base_top3_idx = maia_masked.topk(3, dim=1)
    base_top3 = float((base_top3_idx == target_idx.unsqueeze(1)).any(dim=1).float().mean().item())
    base_loss = float(F.cross_entropy(maia_masked, target_idx).item())

    # 2. Clone Model Move Evaluation
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = Clone().to(device)
    state = torch.load(weights_path, map_location=device, weights_only=False)
    model.load_state_dict(state)
    model.eval()

    X_dev = X.to(device)
    with torch.no_grad():
        offsets, time_out = model(X_dev)
        offsets = offsets.cpu()
        time_out = time_out.cpu()

    clone_scores = (maia_logits + offsets).masked_fill(mask == 0, float("-inf"))
    clone_pred = clone_scores.argmax(dim=1)
    clone_top1 = float((clone_pred == target_idx).float().mean().item())

    _, clone_top3_idx = clone_scores.topk(3, dim=1)
    clone_top3 = float((clone_top3_idx == target_idx.unsqueeze(1)).any(dim=1).float().mean().item())
    clone_loss = float(F.cross_entropy(clone_scores, target_idx).item())

    # Update verified accuracy into DB
    model_repo.update_model_metrics(opp_clean, val_accuracy=clone_top1, val_loss=clone_loss)

    # 3. Decision Time Evaluation
    rows = torch.arange(N)
    pred_log_mean = time_out[rows, target_idx, 0]
    pred_sec = torch.exp(pred_log_mean).numpy()

    time_valid = tensors.get("time_label_valid", torch.ones(N)).numpy().astype(bool)
    valid_mask = time_valid & (actual_sec > 0.1) & (actual_sec < 300)
    if valid_mask.sum() == 0:
        valid_mask = (actual_sec > 0.1) & (actual_sec < 300)

    act = actual_sec[valid_mask]
    prd = pred_sec[valid_mask]
    errors = np.abs(prd - act)

    med_actual = float(np.median(act)) if len(act) > 0 else 0.0
    med_pred = float(np.median(prd)) if len(prd) > 0 else 0.0
    mean_actual = float(np.mean(act)) if len(act) > 0 else 0.0
    mean_pred = float(np.mean(prd)) if len(prd) > 0 else 0.0
    mae = float(np.mean(errors)) if len(errors) > 0 else 0.0
    medae = float(np.median(errors)) if len(errors) > 0 else 0.0
    rmse = float(np.sqrt(np.mean((prd - act) ** 2))) if len(errors) > 0 else 0.0
    within_1s = float(np.mean(errors <= 1.0) * 100) if len(errors) > 0 else 0.0
    within_2s = float(np.mean(errors <= 2.0) * 100) if len(errors) > 0 else 0.0
    within_5s = float(np.mean(errors <= 5.0) * 100) if len(errors) > 0 else 0.0
    corr = float(np.corrcoef(prd, act)[0, 1]) if len(act) > 1 else 0.0
    if np.isnan(corr):
        corr = 0.0

    return {
        "player_id": opp_clean,
        "positions_evaluated": N,
        "games_analyzed": len(games),
        "move_evaluation": {
            "maia_top1_pct": round(base_top1 * 100, 2),
            "clone_top1_pct": round(clone_top1 * 100, 2),
            "top1_delta_pct": round((clone_top1 - base_top1) * 100, 2),
            "maia_top3_pct": round(base_top3 * 100, 2),
            "clone_top3_pct": round(clone_top3 * 100, 2),
            "top3_delta_pct": round((clone_top3 - base_top3) * 100, 2),
            "maia_loss": round(base_loss, 4),
            "clone_loss": round(clone_loss, 4),
            "loss_reduction": round(base_loss - clone_loss, 4),
        },
        "time_evaluation": {
            "valid_positions": int(valid_mask.sum()),
            "actual_median_sec": round(med_actual, 2),
            "pred_median_sec": round(med_pred, 2),
            "median_tempo_delta_sec": round(med_pred - med_actual, 2),
            "actual_mean_sec": round(mean_actual, 2),
            "pred_mean_sec": round(mean_pred, 2),
            "medae_sec": round(medae, 2),
            "mae_sec": round(mae, 2),
            "rmse_sec": round(rmse, 2),
            "within_1s_pct": round(within_1s, 1),
            "within_2s_pct": round(within_2s, 1),
            "within_5s_pct": round(within_5s, 1),
            "correlation_r": round(corr, 3),
        },
    }


def benchmark_snapshot_scaling(
    player_id: str,
    snapshot_counts: Optional[list[int]] = None,
    limit: int = 40,
) -> list[dict]:
    """Evaluate move and time prediction metrics across varying numbers of snapshots."""
    import numpy as np
    import torch.nn.functional as F
    from app.ml.implementation import Clone
    from app.ml.maia_extractor import extract_snapshots_and_maia_logits
    from app.services.inference_service import ensure_maia_checkpoint

    opp_clean = player_id.lower().strip()
    weights_path = model_repo.get_model_weights_path(opp_clean)
    if not weights_path or not weights_path.is_file():
        logger.info("Clone checkpoint for '%s' not found. Training model now...", opp_clean)
        run_training_pipeline(opp_clean)
        weights_path = model_repo.get_model_weights_path(opp_clean)
        if not weights_path or not weights_path.is_file():
            raise FileNotFoundError(f"Failed to train and locate model checkpoint for '{opp_clean}'")

    games = get_games_for_opponent(opp_clean, limit=limit)
    if not games:
        raise ValueError(f"No match history found for '{opp_clean}'")

    maia_ckpt = str(ensure_maia_checkpoint())
    _, tensors = extract_snapshots_and_maia_logits(
        rows=games,
        checkpoint_path=maia_ckpt,
        limit_games=limit,
        batch_size=64,
        player_id=opp_clean,
    )

    X = tensors["X"]
    maia_logits = tensors["maia_logits"]
    mask = tensors["mask"]
    target_idx = tensors["target_idx"]
    actual_sec_all = tensors["seconds"].numpy()
    time_valid_all = tensors.get("time_label_valid", torch.ones(len(target_idx))).numpy().astype(bool)
    N = len(target_idx)
    if N == 0:
        raise ValueError(f"Zero valid move positions extracted for '{opp_clean}'")

    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = Clone().to(device)
    state = torch.load(weights_path, map_location=device, weights_only=False)
    model.load_state_dict(state)
    model.eval()

    X_dev = X.to(device)
    with torch.no_grad():
        offsets, time_out = model(X_dev)
        offsets = offsets.cpu()
        time_out = time_out.cpu()

    maia_masked = maia_logits.masked_fill(mask == 0, float("-inf"))
    clone_scores = (maia_logits + offsets).masked_fill(mask == 0, float("-inf"))

    rows = torch.arange(N)
    pred_log_mean = time_out[rows, target_idx, 0]
    pred_sec_all = torch.exp(pred_log_mean).numpy()

    if not snapshot_counts:
        candidate_counts = [50, 100, 250, 500, 750, 1000, 1250]
    else:
        candidate_counts = list(snapshot_counts)

    eval_counts = sorted(list(set([c for c in candidate_counts if c <= N] + [N])))

    results = []
    for k in eval_counts:
        k_target = target_idx[:k]
        k_maia = maia_masked[:k]
        k_clone = clone_scores[:k]

        base_pred = k_maia.argmax(dim=1)
        base_top1 = float((base_pred == k_target).float().mean().item())
        _, base_top3_idx = k_maia.topk(3, dim=1)
        base_top3 = float((base_top3_idx == k_target.unsqueeze(1)).any(dim=1).float().mean().item())
        base_loss = float(F.cross_entropy(k_maia, k_target).item())

        clone_pred = k_clone.argmax(dim=1)
        clone_top1 = float((clone_pred == k_target).float().mean().item())
        _, clone_top3_idx = k_clone.topk(3, dim=1)
        clone_top3 = float((clone_top3_idx == k_target.unsqueeze(1)).any(dim=1).float().mean().item())
        clone_loss = float(F.cross_entropy(k_clone, k_target).item())

        k_act = actual_sec_all[:k]
        k_prd = pred_sec_all[:k]
        k_tvalid = time_valid_all[:k]

        valid_mask = k_tvalid & (k_act > 0.1) & (k_act < 300)
        if valid_mask.sum() == 0:
            valid_mask = (k_act > 0.1) & (k_act < 300)

        act = k_act[valid_mask]
        prd = k_prd[valid_mask]
        errors = np.abs(prd - act)

        med_actual = float(np.median(act)) if len(act) > 0 else 0.0
        med_pred = float(np.median(prd)) if len(prd) > 0 else 0.0
        mae = float(np.mean(errors)) if len(errors) > 0 else 0.0
        medae = float(np.median(errors)) if len(errors) > 0 else 0.0
        rmse = float(np.sqrt(np.mean((prd - act) ** 2))) if len(errors) > 0 else 0.0
        within_1s = float(np.mean(errors <= 1.0) * 100) if len(errors) > 0 else 0.0
        within_2s = float(np.mean(errors <= 2.0) * 100) if len(errors) > 0 else 0.0
        within_5s = float(np.mean(errors <= 5.0) * 100) if len(errors) > 0 else 0.0
        corr = float(np.corrcoef(prd, act)[0, 1]) if len(act) > 1 else 0.0
        if np.isnan(corr):
            corr = 0.0

        results.append({
            "player_id": opp_clean,
            "snapshots_evaluated": k,
            "total_available_positions": N,
            "games_analyzed": len(games),
            "maia_top1_pct": round(base_top1 * 100, 2),
            "clone_top1_pct": round(clone_top1 * 100, 2),
            "top1_delta_pct": round((clone_top1 - base_top1) * 100, 2),
            "maia_top3_pct": round(base_top3 * 100, 2),
            "clone_top3_pct": round(clone_top3 * 100, 2),
            "top3_delta_pct": round((clone_top3 - base_top3) * 100, 2),
            "maia_loss": round(base_loss, 4),
            "clone_loss": round(clone_loss, 4),
            "loss_reduction": round(base_loss - clone_loss, 4),
            "valid_time_positions": int(valid_mask.sum()),
            "actual_median_sec": round(med_actual, 2),
            "pred_median_sec": round(med_pred, 2),
            "median_tempo_delta_sec": round(med_pred - med_actual, 2),
            "medae_sec": round(medae, 2),
            "mae_sec": round(mae, 2),
            "rmse_sec": round(rmse, 2),
            "within_1s_pct": round(within_1s, 1),
            "within_2s_pct": round(within_2s, 1),
            "within_5s_pct": round(within_5s, 1),
            "correlation_r": round(corr, 3),
        })

    return results
