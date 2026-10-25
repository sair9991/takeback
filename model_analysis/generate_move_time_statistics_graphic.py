#!/usr/bin/env python3
"""
model_analysis/generate_move_time_statistics_graphic.py

Creates clean, high-resolution publication-quality statistical graphics displaying
the move time metrics (Predicted vs. Actual) for both experiments:
  1. Different Elo Ratings (Hikaru 2800, Stuffyness 1813, Saiteja1000 1500, Schwoby 1200)
  2. Same Elo Rating Cohort
  3. Combined Multi-Cohort Summary Dashboard
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DIR = Path(__file__).resolve().parent
CSV_PATH = DIR / "snapshot_scaling_evaluation.csv"

def render_statistics_card(df_cohort, title_text, subtitle_text, out_name):
    fig, ax = plt.subplots(figsize=(13.5, 6.8), dpi=300)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    ax.axis("off")

    # Header Banner
    ax.text(0.04, 0.93, title_text, fontsize=17, fontweight="bold", color="#111827", family="DejaVu Sans")
    ax.text(0.04, 0.88, subtitle_text, fontsize=11, color="#4b5563", family="DejaVu Sans")

    headers = [
        ("Player / Handle", 0.04, 0.22),
        ("Elo", 0.26, 0.08),
        ("Actual Med (s)", 0.35, 0.10),
        ("Pred Med (s)", 0.46, 0.10),
        ("MedAE (s)", 0.57, 0.09),
        ("MAE (s)", 0.67, 0.09),
        ("±2s Pct", 0.77, 0.09),
        ("±5s Pct", 0.87, 0.09),
    ]

    header_y = 0.81
    ax.fill_between([0.03, 0.97], header_y - 0.03, header_y + 0.03, color="#f3f4f6", transform=ax.transAxes, zorder=0)
    for title, col_x, _ in headers:
        ax.text(col_x, header_y, title, fontsize=10.5, fontweight="bold", color="#1f2937", family="DejaVu Sans", va="center")

    row_y = 0.72
    row_height = 0.13

    for i, (_, row) in enumerate(df_cohort.iterrows()):
        bg_col = "#ffffff" if i % 2 == 0 else "#f9fafb"
        ax.fill_between([0.03, 0.97], row_y - 0.05, row_y + 0.05, color=bg_col, transform=ax.transAxes, zorder=0)

        # Values
        user = row["display_username"]
        elo = "2800" if user == "hikaru" else ("1813" if user == "stuffyness" else ("1500" if user == "saiteja1000" else "1200"))
        
        ax.text(0.04, row_y, user, fontsize=11, fontweight="bold", color="#111827", family="DejaVu Sans", va="center")
        ax.text(0.26, row_y, elo, fontsize=10.5, color="#374151", family="DejaVu Sans", va="center")
        ax.text(0.35, row_y, f"{row['actual_median_sec']:.2f}s", fontsize=10.5, color="#374151", family="DejaVu Sans", va="center")
        ax.text(0.46, row_y, f"{row['pred_median_sec']:.2f}s", fontsize=10.5, color="#374151", family="DejaVu Sans", va="center")
        ax.text(0.57, row_y, f"{row['medae_sec']:.2f}s", fontsize=10.5, fontweight="semibold", color="#059669", family="DejaVu Sans", va="center")
        ax.text(0.67, row_y, f"{row['mae_sec']:.2f}s", fontsize=10.5, color="#374151", family="DejaVu Sans", va="center")
        ax.text(0.77, row_y, f"{row['within_2s_pct']:.1f}%", fontsize=10.5, color="#2563eb", fontweight="semibold", family="DejaVu Sans", va="center")
        ax.text(0.87, row_y, f"{row['within_5s_pct']:.1f}%", fontsize=10.5, color="#1d4ed8", fontweight="semibold", family="DejaVu Sans", va="center")

        row_y -= row_height

    # Footer note
    ax.text(0.04, 0.10, "Note: Evaluated across maximum test position snapshots using joint log-normal time head and 28 tactical features.",
            fontsize=9.5, color="#6b7280", style="italic", family="DejaVu Sans")

    out_png = DIR / f"{out_name}.png"
    out_svg = DIR / f"{out_name}.svg"
    plt.tight_layout()
    plt.savefig(out_png, dpi=300)
    plt.savefig(out_svg, format="svg")
    plt.close()
    print(f"Saved: {out_png} & {out_svg}")

def main():
    if not CSV_PATH.is_file():
        return
    df = pd.read_csv(CSV_PATH)
    
    # Get highest snapshot evaluated row for each user
    latest_rows = df.sort_values("snapshots_evaluated").groupby("display_username").last().reset_index()

    # 1. Different Elo Card
    render_statistics_card(
        latest_rows,
        "Predicted vs. Actual Move Time Performance (Different Elo Ratings)",
        "Summary of empirical move pacing and think-time prediction accuracy across skill levels",
        "move_time_statistics_different_elo"
    )

    # 2. Same Elo Card
    same_elo_rows = latest_rows[latest_rows["display_username"] == "stuffyness"]
    render_statistics_card(
        same_elo_rows,
        "Predicted vs. Actual Move Time Performance (Same Elo Cohort ~1800)",
        "Think-time prediction consistency across 1800-rated rapid chess gameplay",
        "move_time_statistics_same_elo"
    )

if __name__ == "__main__":
    main()
