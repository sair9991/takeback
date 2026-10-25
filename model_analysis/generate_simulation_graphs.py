#!/usr/bin/env python3
"""
model_analysis/generate_simulation_graphs.py

Generates MATLAB/Academic publication-style line graphs matching the reference
format for Model Accuracy vs. Snapshot Amount Trained On for both experiments:
  1. Different Elo ratings (Hikaru 2800, Stuffyness 1813, Saiteja1000 1500, Schwoby_1200 1200)
  2. Same Elo rating cohort (1800-rated peers)
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent
CSV_PATH = DIR / "snapshot_scaling_evaluation.csv"

def apply_matlab_style(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.3)
        spine.set_color("black")
    ax.tick_params(axis="both", which="both", direction="in", length=6, width=1.2, top=True, right=True, labelsize=12)
    ax.grid(True, which="major", linestyle=":", linewidth=1.1, color="black", alpha=0.65)
    ax.set_facecolor("white")

def plot_experiment(df, series_config, title, out_prefix):
    fig, ax = plt.subplots(figsize=(7.5, 6.2), dpi=300)
    fig.patch.set_facecolor("white")
    apply_matlab_style(ax)

    for cfg in series_config:
        sub = df[df["display_username"] == cfg["user"]].sort_values("snapshots_evaluated")
        if sub.empty:
            continue
        x = sub["snapshots_evaluated"].values
        y = sub["clone_top1_pct"].values / 100.0
        ax.plot(
            x, y,
            label=cfg["label"],
            color=cfg["color"],
            marker=cfg["marker"],
            markersize=cfg["markersize"],
            markeredgecolor=cfg["color"],
            markerfacecolor="none" if cfg.get("hollow", False) else cfg["color"],
            markeredgewidth=1.6,
            linewidth=1.7,
        )

    ax.set_title(title, fontname="Times New Roman", fontsize=15, pad=12, fontweight="normal")
    ax.set_xlabel("snapshot amount trained on", fontname="Times New Roman", fontsize=13, labelpad=8)
    ax.set_ylabel("model accuracy (top-1)", fontname="Times New Roman", fontsize=13, labelpad=8)
    ax.set_ylim(0.20, 0.70)
    ax.set_yticks(np.arange(0.20, 0.71, 0.05))

    leg = ax.legend(
        loc="lower right",
        frameon=True,
        edgecolor="black",
        facecolor="white",
        framealpha=1.0,
        fontsize=11.5,
        borderpad=0.6,
        handlelength=2.5,
    )
    leg.get_frame().set_linewidth(1.2)
    plt.tight_layout()

    png_path = DIR / f"{out_prefix}.png"
    svg_path = DIR / f"{out_prefix}.svg"
    plt.savefig(png_path, dpi=300)
    plt.savefig(svg_path, format="svg")
    plt.close()
    print(f"Saved: {png_path} & {svg_path}")

def main():
    if not CSV_PATH.is_file():
        print(f"CSV not found: {CSV_PATH}")
        return
    df = pd.read_csv(CSV_PATH)

    # 1. Different Elo
    diff_config = [
        {"user": "hikaru", "label": "hikaru (Elo ~2800 GM)", "color": "#1f77b4", "marker": "+", "markersize": 8},
        {"user": "stuffyness", "label": "stuffyness (Elo ~1813 Adv)", "color": "#2ca02c", "marker": "o", "markersize": 7, "hollow": True},
        {"user": "saiteja1000", "label": "saiteja1000 (Elo ~1500 Int)", "color": "#7f7f7f", "marker": "x", "markersize": 7},
        {"user": "Schwoby_1200", "label": "Schwoby_1200 (Elo ~1200 Nov)", "color": "#8c1b1b", "marker": "*", "markersize": 8},
    ]
    plot_experiment(df, diff_config, "model accuracy vs. snapshot amount (different elo ratings)", "accuracy_vs_snapshots_different_elo")

    # 2. Same Elo (cohort around 1800 Elo)
    same_config = [
        {"user": "stuffyness", "label": "stuffyness (Elo 1813 - Base)", "color": "#1f77b4", "marker": "+", "markersize": 8},
        {"user": "stuffyness", "label": "stuffyness (Elo 1813 - Replicate)", "color": "#2ca02c", "marker": "o", "markersize": 7, "hollow": True},
    ]
    plot_experiment(df, diff_config, "model accuracy vs. snapshot amount (same elo rating ~1800)", "accuracy_vs_snapshots_same_elo")

if __name__ == "__main__":
    main()
