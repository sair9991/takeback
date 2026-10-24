import torch
import torch.nn as nn
import torch.nn.functional as F

# ---- dummy dataset: 13k train snapshots, 3k val ----
S, Fdim = 64, 28

def make_data(N):
    X = torch.randn(N, S, Fdim)
    maia_logits = torch.randn(N, S)
    n_legal = torch.randint(20, 41, (N,))
    mask = (torch.arange(S).unsqueeze(0) < n_legal.unsqueeze(1)).float()
    X = X * mask.unsqueeze(-1)
    maia_logits = maia_logits * mask
    target_idx = (torch.rand(N) * n_legal).long()
    seconds = torch.rand(N).mul(20).clamp(min=0.1)
    return X, maia_logits, mask, target_idx, seconds

# ---- model (same as before) ----
class Clone(nn.Module):
    def __init__(self):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(28, 64), nn.ReLU(),
            nn.Linear(64, 64), nn.ReLU(),
        )
        self.move_head = nn.Linear(64, 1)
        self.time_head = nn.Linear(64, 2)
        nn.init.zeros_(self.move_head.weight)
        nn.init.zeros_(self.move_head.bias)

    def forward(self, X):
        h = self.trunk(X)
        return self.move_head(h).squeeze(-1), self.time_head(h)

# ---- loss for one batch ----
def compute_loss(model, X, maia_logits, mask, target_idx, seconds, lam=0.2):
    offsets, time_out = model(X)
    scores = (maia_logits + offsets).masked_fill(mask == 0, float("-inf"))
    move_loss = F.cross_entropy(scores, target_idx)

    rows = torch.arange(len(X))
    mean = time_out[rows, target_idx, 0]
    log_std = time_out[rows, target_idx, 1]
    y = torch.log(seconds)
    time_loss = (log_std + (y - mean) ** 2 / (2 * torch.exp(2 * log_std))).mean()

    return move_loss + lam * time_loss, move_loss, time_loss

def move_accuracy(model, X, maia_logits, mask, target_idx):
    model.eval()
    with torch.no_grad():
        offsets, _ = model(X)
        scores = (maia_logits + offsets).masked_fill(mask == 0, float("-inf"))
        pred = scores.argmax(dim=1)
        return (pred == target_idx).float().mean().item()

# ---- training loop ----
if __name__ == "__main__":
    from pathlib import Path

    train = make_data(13000)
    val = make_data(3000)

    model = Clone()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    BATCH = 256
    N = len(train[0])

    best_val, best_state, patience, bad = float("inf"), None, 5, 0

    for epoch in range(100):
        # train
        model.train()
        perm = torch.randperm(N)                      # shuffle each epoch
        for i in range(0, N, BATCH):
            idx = perm[i:i + BATCH]
            batch = [t[idx] for t in train]
            loss, _, _ = compute_loss(model, *batch)
            opt.zero_grad()
            loss.backward()
            opt.step()

        # validate (no weight updates)
        model.eval()
        with torch.no_grad():
            _, v_move, v_time = compute_loss(model, *val)
        acc = move_accuracy(model, *val[:4])

        print(f"epoch {epoch:3d}  val move {v_move:.4f}  val time {v_time:.4f}  acc {acc:.3f}")

        # early stopping on val MOVE loss
        if v_move < best_val:
            best_val, bad = v_move.item(), 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                print("early stop")
                break

    model.load_state_dict(best_state)                 # restore the best weights
    best_acc = move_accuracy(model, *val[:4])
    print(f"best val move accuracy {best_acc:.3f}")
    torch.save(best_state, Path(__file__).with_name("clone.pt"))