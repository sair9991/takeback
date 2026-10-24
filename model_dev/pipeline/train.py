"""
pipeline/train.py - Train and evaluate the Maia Adapter MLP and baselines.

Evaluates:
  1. Plain Maia-3 baseline (Move NLL, Top-1, Top-3)
  2. Constant Think-Time baseline (Time NLL)
  3. Linear Adapter baseline (Ablation)
  4. MLP Adapter Model (28 -> 64 -> 64 -> heads)
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Optional

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from pipeline.dataset import ChessSnapshotDataset, split_snapshots_by_game
from pipeline.model import MaiaAdapterLinear, MaiaAdapterMLP, compute_clone_loss


def evaluate_model(
    model: Optional[torch.nn.Module],
    loader: DataLoader,
    device: str,
    constant_time_params: Optional[tuple[float, float]] = None,
) -> dict[str, float]:
    """
    Evaluates a model (or plain Maia-3 if model is None).
    """
    if model is not None:
        model.eval()

    total_samples = 0
    total_valid_time_samples = 0
    sum_move_nll = 0.0
    sum_top1_correct = 0.0
    sum_top3_correct = 0.0
    sum_time_nll = 0.0

    const_mu, const_sigma = constant_time_params if constant_time_params else (2.0, 1.0)
    const_var = const_sigma ** 2

    with torch.no_grad():
        for batch in loader:
            X = batch["X"].to(device)
            maia_logits = batch["maia_logits"].to(device)
            mask = batch["mask"].to(device)
            target_idx = batch["target_idx"].to(device)
            seconds = batch["seconds"].to(device)
            time_valid = batch["time_label_valid"].to(device)

            B = X.size(0)
            total_samples += B

            if model is None:
                # Plain Maia-3
                bool_mask = mask.bool()
                logits = torch.where(bool_mask, maia_logits, torch.full_like(maia_logits, float("-inf")))
                mu = torch.full_like(logits, const_mu)
                sigma = torch.full_like(logits, const_sigma)
            else:
                logits, _, mu, sigma, _ = model(X, maia_logits, mask)

            # Move NLL
            move_nll = F.cross_entropy(logits, target_idx, reduction="sum").item()
            sum_move_nll += move_nll

            # Top-1 accuracy
            pred_top1 = torch.argmax(logits, dim=-1)
            sum_top1_correct += (pred_top1 == target_idx).sum().item()

            # Top-3 accuracy
            _, pred_top3 = torch.topk(logits, k=min(3, logits.size(1)), dim=-1)
            sum_top3_correct += (pred_top3 == target_idx.unsqueeze(-1)).any(dim=-1).sum().item()

            # Time NLL
            batch_idx = torch.arange(B, device=device)
            target_mu = mu[batch_idx, target_idx]
            target_sigma = sigma[batch_idx, target_idx]
            log_secs = torch.log(torch.clamp(seconds, min=0.1))

            var = target_sigma ** 2
            per_sample_time_nll = 0.5 * torch.log(2.0 * math.pi * var) + ((log_secs - target_mu) ** 2) / (2.0 * var)

            valid_mask = time_valid.float()
            sum_time_nll += (per_sample_time_nll * valid_mask).sum().item()
            total_valid_time_samples += valid_mask.sum().item()

    avg_move_nll = sum_move_nll / total_samples
    avg_top1 = sum_top1_correct / total_samples
    avg_top3 = sum_top3_correct / total_samples
    avg_time_nll = sum_time_nll / max(total_valid_time_samples, 1)

    return {
        "move_nll": avg_move_nll,
        "top1_acc": avg_top1,
        "top3_acc": avg_top3,
        "time_nll": avg_time_nll,
    }


def compute_constant_time_baseline(train_loader: DataLoader) -> tuple[float, float]:
    """Computes empirical mean and std of log_seconds on training set."""
    valid_log_secs = []
    for batch in train_loader:
        seconds = batch["seconds"]
        time_valid = batch["time_label_valid"]
        valid_s = seconds[time_valid]
        if len(valid_s) > 0:
            valid_log_secs.append(torch.log(torch.clamp(valid_s, min=0.1)))

    if valid_log_secs:
        all_logs = torch.cat(valid_log_secs)
        mu = float(all_logs.mean().item())
        sigma = float(all_logs.std().item())
        return mu, max(sigma, 0.1)
    return 2.0, 1.0


def train_adapter_model(
    model: torch.nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    device: str,
    epochs: int = 40,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    time_loss_weight: float = 0.5,
    offset_penalty_weight: float = 0.01,
    patience: int = 5,
    checkpoint_out: str = "adapter_checkpoint.pt",
) -> dict[str, Any]:
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=2)

    best_val_move_nll = float("inf")
    patience_counter = 0
    history = []

    model.to(device)

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss_total = 0.0
        train_move_loss_total = 0.0
        train_time_loss_total = 0.0
        train_samples = 0

        for batch in train_loader:
            X = batch["X"].to(device)
            maia_logits = batch["maia_logits"].to(device)
            mask = batch["mask"].to(device)
            target_idx = batch["target_idx"].to(device)
            seconds = batch["seconds"].to(device)
            time_valid = batch["time_label_valid"].to(device)

            optimizer.zero_grad()
            adjusted_logits, probs, mu, sigma, offset = model(X, maia_logits, mask)
            loss_dict = compute_clone_loss(
                adjusted_logits=adjusted_logits,
                probs=probs,
                mu=mu,
                sigma=sigma,
                offset=offset,
                mask=mask,
                target_idx=target_idx,
                seconds=seconds,
                time_label_valid=time_valid,
                time_loss_weight=time_loss_weight,
                offset_penalty_weight=offset_penalty_weight,
            )

            loss = loss_dict["loss"]
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            B = X.size(0)
            train_loss_total += loss.item() * B
            train_move_loss_total += loss_dict["move_loss"].item() * B
            train_time_loss_total += loss_dict["time_loss"].item() * B
            train_samples += B

        # Validation
        val_metrics = evaluate_model(model, val_loader, device)
        scheduler.step(val_metrics["move_nll"])

        avg_train_loss = train_loss_total / train_samples
        avg_train_move_nll = train_move_loss_total / train_samples
        avg_train_time_nll = train_time_loss_total / train_samples

        epoch_stat = {
            "epoch": epoch,
            "train_loss": avg_train_loss,
            "train_move_nll": avg_train_move_nll,
            "val_move_nll": val_metrics["move_nll"],
            "val_top1": val_metrics["top1_acc"],
            "val_top3": val_metrics["top3_acc"],
            "val_time_nll": val_metrics["time_nll"],
        }
        history.append(epoch_stat)

        # Check for best checkpoint
        if val_metrics["move_nll"] < best_val_move_nll:
            best_val_move_nll = val_metrics["move_nll"]
            patience_counter = 0
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "epoch": epoch,
                    "val_metrics": val_metrics,
                },
                checkpoint_out,
            )
            model_clone_path = Path("Model") / "clone.pt"
            if model_clone_path.parent.exists():
                torch.save(model.state_dict(), model_clone_path)
            improved_mark = " *"
        else:
            patience_counter += 1
            improved_mark = ""

        if epoch % 5 == 0 or epoch == 1 or improved_mark:
            print(
                f"Epoch {epoch:02d} | Train Move NLL: {avg_train_move_nll:.4f} | "
                f"Val Move NLL: {val_metrics['move_nll']:.4f} (Top-1: {val_metrics['top1_acc']*100:.1f}%) | "
                f"Val Time NLL: {val_metrics['time_nll']:.4f}{improved_mark}"
            )

        if patience_counter >= patience:
            print(f"Early stopping at epoch {epoch} (no val move NLL improvement for {patience} epochs).")
            break

    # Reload best weights
    best_ckpt = torch.load(checkpoint_out, map_location=device, weights_only=True)
    model.load_state_dict(best_ckpt["model_state_dict"])
    return {"history": history, "best_val_move_nll": best_val_move_nll}


def run_training_pipeline(
    dataset_pt_path: str = "snapshots_dataset.pt",
    batch_size: int = 256,
    epochs: int = 35,
    device: Optional[str] = None,
) -> dict[str, Any]:
    if device is None:
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    print(f"Loading pre-computed snapshot tensors from {dataset_pt_path}...")
    tensors = torch.load(dataset_pt_path, map_location="cpu", weights_only=False)

    train_ds, val_ds, test_ds = split_snapshots_by_game(tensors, 0.80, 0.10, 0.10)
    print(f"Dataset split by game: Train={len(train_ds)}, Val={len(val_ds)}, Test={len(test_ds)}")

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False)

    # 1. Compute constant time baseline
    const_mu, const_sigma = compute_constant_time_baseline(train_loader)
    print(f"Constant think-time baseline: mu={const_mu:.3f} ln(s), sigma={const_sigma:.3f}")

    # 2. Evaluate Plain Maia-3 Baseline
    print("\n--- Evaluating Plain Maia-3 Baseline ---")
    maia_val_metrics = evaluate_model(None, val_loader, device, (const_mu, const_sigma))
    maia_test_metrics = evaluate_model(None, test_loader, device, (const_mu, const_sigma))
    print(
        f"Plain Maia-3 on Test Set: Move NLL = {maia_test_metrics['move_nll']:.4f}, "
        f"Top-1 Acc = {maia_test_metrics['top1_acc']*100:.2f}%, "
        f"Top-3 Acc = {maia_test_metrics['top3_acc']*100:.2f}%, "
        f"Time NLL = {maia_test_metrics['time_nll']:.4f}"
    )

    # 3. Train Linear Adapter Baseline (Ablation)
    print("\n--- Training Linear Baseline Adapter ---")
    linear_model = MaiaAdapterLinear(input_dim=28).to(device)
    train_adapter_model(
        linear_model,
        train_loader,
        val_loader,
        device,
        epochs=15,
        checkpoint_out="linear_adapter_best.pt",
    )
    linear_test_metrics = evaluate_model(linear_model, test_loader, device)
    lin_rel_gain = ((maia_test_metrics["move_nll"] - linear_test_metrics["move_nll"]) / maia_test_metrics["move_nll"]) * 100
    print(
        f"Linear Adapter on Test Set: Move NLL = {linear_test_metrics['move_nll']:.4f} "
        f"({lin_rel_gain:+.2f}% vs Maia), Top-1 = {linear_test_metrics['top1_acc']*100:.2f}%, "
        f"Time NLL = {linear_test_metrics['time_nll']:.4f}"
    )

    # 4. Train MLP Adapter (Recommended 28 -> 64 -> 64)
    print("\n--- Training MLP Adapter Model (28 -> 64 -> 64) ---")
    mlp_model = MaiaAdapterMLP(input_dim=28, hidden_dim=64).to(device)
    mlp_train_res = train_adapter_model(
        mlp_model,
        train_loader,
        val_loader,
        device,
        epochs=epochs,
        lr=1e-3,
        weight_decay=1e-4,
        time_loss_weight=0.5,
        offset_penalty_weight=0.01,
        patience=5,
        checkpoint_out="mlp_adapter_best.pt",
    )
    mlp_test_metrics = evaluate_model(mlp_model, test_loader, device)
    mlp_rel_gain = ((maia_test_metrics["move_nll"] - mlp_test_metrics["move_nll"]) / maia_test_metrics["move_nll"]) * 100
    time_gain = ((maia_test_metrics["time_nll"] - mlp_test_metrics["time_nll"]) / maia_test_metrics["time_nll"]) * 100

    print(
        f"\nMLP Adapter on Test Set: Move NLL = {mlp_test_metrics['move_nll']:.4f} "
        f"({mlp_rel_gain:+.2f}% vs Maia), Top-1 = {mlp_test_metrics['top1_acc']*100:.2f}%, "
        f"Top-3 = {mlp_test_metrics['top3_acc']*100:.2f}%, "
        f"Time NLL = {mlp_test_metrics['time_nll']:.4f} ({time_gain:+.2f}% vs Constant)"
    )

    results = {
        "plain_maia": maia_test_metrics,
        "linear_adapter": linear_test_metrics,
        "mlp_adapter": mlp_test_metrics,
        "mlp_rel_move_gain_pct": mlp_rel_gain,
        "mlp_rel_time_gain_pct": time_gain,
    }
    return results


if __name__ == "__main__":
    run_training_pipeline()

