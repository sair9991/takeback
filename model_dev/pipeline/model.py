"""
pipeline/model.py - MLP Adapter model and Linear baseline for chess player clones.

Architecture (per PRD Section 5 & PDF):
  Input per move slot m: x(m) in R^28
  Shared trunk:
    Linear(28, 64) -> ReLU
    Linear(64, 64) -> ReLU
  Move head:
    Linear(64, 1) -> offset d(m). Initialized to 0.
    Adjusted logit = maia_logit(m) + d(m)
  Time head:
    Linear(64, 2) -> [mu(m), rho(m)], sigma(m) = softplus(rho) + 1e-4

Loss:
  move_loss = -log q(target_idx)
  time_loss = 0.5 * log(2*pi*sigma^2) + (log_seconds - mu)^2 / (2*sigma^2)
  offset_penalty = mean(d(m)^2 over legal moves)
  total = move_loss + 0.5 * time_loss + 0.01 * offset_penalty
"""

from __future__ import annotations

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class MaiaAdapterMLP(nn.Module):
    def __init__(self, input_dim: int = 28, hidden_dim: int = 64):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        # Shared trunk: 28 -> 64 -> 64
        self.trunk = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        # Move head: 64 -> 1 (score offset d(m))
        self.move_head = nn.Linear(hidden_dim, 1)

        # Time head: 64 -> 2 (mu, rho)
        self.time_head = nn.Linear(hidden_dim, 2)

        # Initialize move head to exactly 0 so initial predictions match Maia-3 100%
        nn.init.zeros_(self.move_head.weight)
        nn.init.zeros_(self.move_head.bias)

        # Initialize time head mu around typical log-seconds (~2.0) and rho for reasonable sigma
        nn.init.normal_(self.time_head.weight, std=0.01)
        with torch.no_grad():
            self.time_head.bias[0] = 2.0  # e^2 ~ 7.4 seconds
            self.time_head.bias[1] = 0.54  # softplus(0.54) ~ 1.0

    def forward(
        self,
        X: torch.Tensor,            # (B, 64, 28)
        maia_logits: torch.Tensor,  # (B, 64)
        mask: torch.Tensor,         # (B, 64)
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns:
          adjusted_logits: (B, 64) with -inf on padding slots
          probs: (B, 64)
          mu: (B, 64)
          sigma: (B, 64)
        """
        B, M, D = X.shape

        # Pass through trunk
        h = self.trunk(X)  # (B, 64, 64)

        # Move offset d(m)
        offset = self.move_head(h).squeeze(-1)  # (B, 64)

        # Combine Maia logit and offset
        raw_adjusted = maia_logits + offset  # (B, 64)

        # Mask padding slots to -inf
        bool_mask = mask.bool()
        adjusted_logits = torch.where(
            bool_mask,
            raw_adjusted,
            torch.full_like(raw_adjusted, float("-inf")),
        )

        # Probabilities
        probs = F.softmax(adjusted_logits, dim=-1)

        # Time parameters
        time_params = self.time_head(h)  # (B, 64, 2)
        mu = time_params[..., 0]         # (B, 64)
        rho = time_params[..., 1]
        sigma = F.softplus(rho) + 1e-4   # (B, 64)

        return adjusted_logits, probs, mu, sigma, offset


class MaiaAdapterLinear(nn.Module):
    """Linear baseline (ablation): directly maps 28 inputs to move offset and time."""
    def __init__(self, input_dim: int = 28):
        super().__init__()
        self.move_head = nn.Linear(input_dim, 1)
        self.time_head = nn.Linear(input_dim, 2)

        nn.init.zeros_(self.move_head.weight)
        nn.init.zeros_(self.move_head.bias)
        nn.init.normal_(self.time_head.weight, std=0.01)
        with torch.no_grad():
            self.time_head.bias[0] = 2.0
            self.time_head.bias[1] = 0.54

    def forward(
        self,
        X: torch.Tensor,
        maia_logits: torch.Tensor,
        mask: torch.Tensor,
    ):
        offset = self.move_head(X).squeeze(-1)
        raw_adjusted = maia_logits + offset
        bool_mask = mask.bool()
        adjusted_logits = torch.where(
            bool_mask,
            raw_adjusted,
            torch.full_like(raw_adjusted, float("-inf")),
        )
        probs = F.softmax(adjusted_logits, dim=-1)

        time_params = self.time_head(X)
        mu = time_params[..., 0]
        sigma = F.softplus(time_params[..., 1]) + 1e-4

        return adjusted_logits, probs, mu, sigma, offset


def compute_clone_loss(
    adjusted_logits: torch.Tensor,  # (B, 64)
    probs: torch.Tensor,            # (B, 64)
    mu: torch.Tensor,               # (B, 64)
    sigma: torch.Tensor,            # (B, 64)
    offset: torch.Tensor,           # (B, 64)
    mask: torch.Tensor,             # (B, 64)
    target_idx: torch.Tensor,       # (B,)
    seconds: torch.Tensor,          # (B,)
    time_label_valid: torch.Tensor, # (B,)
    time_loss_weight: float = 0.5,
    offset_penalty_weight: float = 0.01,
) -> dict[str, torch.Tensor]:
    """Computes move loss, time loss, offset penalty, and total loss."""
    B = adjusted_logits.size(0)
    batch_idx = torch.arange(B, device=adjusted_logits.device)

    # 1. Move loss: negative log-likelihood of target move
    # F.cross_entropy correctly handles masked -inf slots
    move_loss = F.cross_entropy(adjusted_logits, target_idx)

    # 2. Time loss: Gaussian NLL for the chosen move
    target_mu = mu[batch_idx, target_idx]
    target_sigma = sigma[batch_idx, target_idx]

    log_secs = torch.log(torch.clamp(seconds, min=0.1))
    # Gaussian NLL: 0.5 * log(2*pi*sigma^2) + (y - mu)^2 / (2*sigma^2)
    # = log(sigma) + 0.5 * log(2*pi) + 0.5 * ((y - mu) / sigma)^2
    var = target_sigma ** 2
    per_sample_time_nll = 0.5 * torch.log(2.0 * math.pi * var) + ((log_secs - target_mu) ** 2) / (2.0 * var)

    valid_mask = time_label_valid.float()
    if valid_mask.sum() > 0:
        time_loss = (per_sample_time_nll * valid_mask).sum() / valid_mask.sum()
    else:
        time_loss = torch.tensor(0.0, device=adjusted_logits.device)

    # 3. Offset penalty: mean square of d(m) over valid legal moves
    offset_sq = (offset ** 2) * mask
    offset_penalty = offset_sq.sum() / torch.clamp(mask.sum(), min=1.0)

    # Total loss
    total_loss = move_loss + time_loss_weight * time_loss + offset_penalty_weight * offset_penalty

    # Metrics
    with torch.no_grad():
        pred_top1 = torch.argmax(adjusted_logits, dim=-1)
        top1_acc = (pred_top1 == target_idx).float().mean()

        # Top-3 accuracy
        _, top3_indices = torch.topk(adjusted_logits, k=min(3, adjusted_logits.size(1)), dim=-1)
        top3_acc = (top3_indices == target_idx.unsqueeze(-1)).any(dim=-1).float().mean()

    return {
        "loss": total_loss,
        "move_loss": move_loss,
        "time_loss": time_loss,
        "offset_penalty": offset_penalty,
        "top1_acc": top1_acc,
        "top3_acc": top3_acc,
    }

