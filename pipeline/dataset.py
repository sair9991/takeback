"""
pipeline/dataset.py - Dataset and split management for snapshots.
Ensures zero game-level leakage between train, validation, and test sets.
"""

from __future__ import annotations

import torch
from torch.utils.data import Dataset, DataLoader
from typing import Optional


class ChessSnapshotDataset(Dataset):
    def __init__(
        self,
        X: torch.Tensor,
        maia_logits: torch.Tensor,
        mask: torch.Tensor,
        target_idx: torch.Tensor,
        seconds: torch.Tensor,
        time_label_valid: torch.Tensor,
        game_ids: list[str],
        plies: torch.Tensor,
    ):
        self.X = X
        self.maia_logits = maia_logits
        self.mask = mask
        self.target_idx = target_idx
        self.seconds = seconds
        self.time_label_valid = time_label_valid
        self.game_ids = game_ids
        self.plies = plies

    def __len__(self) -> int:
        return self.X.size(0)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        return {
            "X": self.X[idx],
            "maia_logits": self.maia_logits[idx],
            "mask": self.mask[idx],
            "target_idx": self.target_idx[idx],
            "seconds": self.seconds[idx],
            "time_label_valid": self.time_label_valid[idx],
            "ply": self.plies[idx],
        }


def split_snapshots_by_game(
    tensors: dict[str, Any],
    train_ratio: float = 0.80,
    val_ratio: float = 0.10,
    test_ratio: float = 0.10,
) -> tuple[ChessSnapshotDataset, ChessSnapshotDataset, ChessSnapshotDataset]:
    """
    Splits snapshots chronologically by game_id order:
    First train_ratio of unique games -> train
    Next val_ratio of unique games -> val
    Remaining unique games -> test
    """
    game_ids = tensors["game_ids"]
    # Preserve chronological order of appearance
    unique_games = []
    seen = set()
    for gid in game_ids:
        if gid not in seen:
            unique_games.append(gid)
            seen.add(gid)

    total_games = len(unique_games)
    n_train_games = int(total_games * train_ratio)
    n_val_games = int(total_games * val_ratio)

    train_game_set = set(unique_games[:n_train_games])
    val_game_set = set(unique_games[n_train_games : n_train_games + n_val_games])
    test_game_set = set(unique_games[n_train_games + n_val_games :])

    train_indices = [i for i, gid in enumerate(game_ids) if gid in train_game_set]
    val_indices = [i for i, gid in enumerate(game_ids) if gid in val_game_set]
    test_indices = [i for i, gid in enumerate(game_ids) if gid in test_game_set]

    def subset_dataset(indices: list[int]) -> ChessSnapshotDataset:
        idx_tensor = torch.tensor(indices, dtype=torch.long)
        return ChessSnapshotDataset(
            X=tensors["X"][idx_tensor],
            maia_logits=tensors["maia_logits"][idx_tensor],
            mask=tensors["mask"][idx_tensor],
            target_idx=tensors["target_idx"][idx_tensor],
            seconds=tensors["seconds"][idx_tensor],
            time_label_valid=tensors["time_label_valid"][idx_tensor],
            game_ids=[game_ids[i] for i in indices],
            plies=tensors["plies"][idx_tensor],
        )

    return (
        subset_dataset(train_indices),
        subset_dataset(val_indices),
        subset_dataset(test_indices),
    )

