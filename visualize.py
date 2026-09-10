"""Generate the project's summary visualizations.

Run with: python visualize.py
Saves PNGs to outputs/.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fifa_analysis import load_data_files, build_valuation_analysis, validate_valuation_analysis

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

COLOR_MAP = {"underrated": "#2E7D32", "overrated": "#C62828", "aligned": "#9E9E9E"}
POSITIONS = ["GK", "DEF", "MID", "FWD"]


def _load_comparison():
    data = load_data_files()
    fifa_key = next(k for k in data if "fc26" in k.lower() or "fifa" in k.lower())
    stats_key = next(k for k in data if "player" in k.lower() or "stats" in k.lower())
    comparison = build_valuation_analysis(data[fifa_key], data[stats_key])
    comparison["value_eur"] = pd.to_numeric(comparison["value_eur"], errors="coerce")
    comparison["market_value_percentile"] = comparison.groupby(
        "position_group_fifa"
    )["value_eur"].rank(pct=True)
    comparison["market_value_gap"] = (
        comparison["market_value_percentile"] - comparison["rating_percentile"]
    )
    comparison["valuation_gap"] = pd.to_numeric(comparison["valuation_gap"], errors="coerce")
    comparison["performance_percentile"] = pd.to_numeric(comparison["performance_percentile"], errors="coerce")
    validation = validate_valuation_analysis(data[fifa_key], data[stats_key])
    return comparison, validation


def plot_valuation_vs_market(comparison, save_path):
    """Faceted scatter: performance-based valuation_gap vs. market value gap, by position."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes = axes.flatten()

    for ax, pos in zip(axes, POSITIONS):
        sub = comparison[comparison["position_group_fifa"] == pos].dropna(
            subset=["valuation_gap", "market_value_gap"]
        )
        corr = sub["valuation_gap"].corr(sub["market_value_gap"], method="spearman")
        for label, color in COLOR_MAP.items():
            s = sub[sub["valuation"] == label]
            ax.scatter(s["valuation_gap"], s["market_value_gap"], c=color, label=label,
                       alpha=0.6, s=30, edgecolors="none")
        ax.axhline(0, color="black", linewidth=0.5, linestyle="--", alpha=0.4)
        ax.axvline(0, color="black", linewidth=0.5, linestyle="--", alpha=0.4)
        ax.set_title(f"{pos}  (n={len(sub)}, Spearman rho={corr:.2f})", fontsize=12, fontweight="bold")
        ax.set_xlabel("Performance-based valuation_gap")
        ax.set_ylabel("Market value gap")
        ax.grid(alpha=0.2)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=3, fontsize=11)
    fig.suptitle("Performance-based Valuation vs. Market Value, by Position",
                 fontsize=14, fontweight="bold", y=1.06)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_top_valuation_gaps(comparison, save_path, n=10):
    """Diverging horizontal bar chart: top N underrated and top N overrated players."""
    top_under = comparison.nlargest(n, "valuation_gap")[["player", "valuation_gap", "position_group_fifa"]]
    top_over = comparison.nsmallest(n, "valuation_gap")[["player", "valuation_gap", "position_group_fifa"]]
    combined = pd.concat([top_over.iloc[::-1], top_under]).reset_index(drop=True)

    colors = ["#C62828" if v < 0 else "#2E7D32" for v in combined["valuation_gap"]]
    labels = [f"{row.player} ({row.position_group_fifa})" for row in combined.itertuples()]

    fig, ax = plt.subplots(figsize=(9, 10))
    ax.barh(labels, combined["valuation_gap"], color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("valuation_gap  (performance percentile minus rating percentile)")
    ax.set_title(f"Most Underrated & Most Overrated Players\n(top {n} each, by valuation_gap)",
                 fontsize=13, fontweight="bold")
    ax.grid(axis="x", alpha=0.2)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_validation_by_position(validation, save_path):
    """Grouped bar chart: value_eur vs wage_eur correlation, by position."""
    value_by_pos = validation["market_value_validation_by_position"]
    wage_by_pos = validation["wage_validation_by_position"]

    positions = POSITIONS
    value_scores = [value_by_pos[p]["spearman_correlation"] for p in positions]
    wage_scores = [wage_by_pos[p]["spearman_correlation"] for p in positions]

    x = range(len(positions))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.bar([i - width / 2 for i in x], value_scores, width, label="value_eur", color="#1565C0")
    ax.bar([i + width / 2 for i in x], wage_scores, width, label="wage_eur", color="#EF6C00")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(positions)
    ax.set_ylabel("Spearman correlation with valuation_gap")
    ax.set_title("Model Validation: Correlation with Independent Targets, by Position",
                 fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_valuation_gap_distribution(comparison, save_path):
    """Box plot: spread of valuation_gap by position group."""
    fig, ax = plt.subplots(figsize=(8, 5.5))
    data_by_pos = [comparison[comparison["position_group_fifa"] == p]["valuation_gap"].dropna() for p in POSITIONS]
    bp = ax.boxplot(data_by_pos, tick_labels=POSITIONS, patch_artist=True, showmeans=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#90CAF9")
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_ylabel("valuation_gap")
    ax.set_title("Distribution of valuation_gap by Position", fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.2)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def generate_all():
    comparison, validation = _load_comparison()

    plot_valuation_vs_market(comparison, OUTPUT_DIR / "valuation_vs_market_value.png")
    plot_validation_by_position(validation, OUTPUT_DIR / "validation_by_position.png")
    plot_valuation_gap_distribution(comparison, OUTPUT_DIR / "valuation_gap_distribution.png")

    print(f"Saved 3 charts to {OUTPUT_DIR}/")


if __name__ == "__main__":
    generate_all()