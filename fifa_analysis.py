from pathlib import Path
import re
import unicodedata

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"


def find_csv_files():
    """Return CSV files in the data directory."""
    return sorted(DATA_DIR.glob("*.csv"))


def load_data_files():
    """Load FIFA data and stats CSV files from the data folder."""
    csv_files = find_csv_files()
    if not csv_files:
        raise FileNotFoundError(
            "No CSV files found in the data folder. Add your FIFA CSV files there first."
        )

    loaded = {}
    for file in csv_files:
        key = file.stem
        loaded[key] = pd.read_csv(file, low_memory=False)

    return loaded


def standardize_columns(df):
    """Normalize dataframe column names."""
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


def normalize_player_name(value):
    """Create a consistent join key for player names."""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-zA-Z0-9 ]", "", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def position_group(position):
    """Map detailed game or real-world positions to comparable groups."""
    position = str(position).upper().split(",")[0].strip()
    if position == "GK":
        return "GK"
    if position in {"DF", "CB", "LB", "RB", "LWB", "RWB"}:
        return "DEF"
    if position in {"FW", "ST", "CF", "LF", "RF", "LS", "RS"}:
        return "FWD"
    if position in {"MF", "CM", "CAM", "CDM", "LM", "RM", "LW", "RW"}:
        return "MID"
    return None


def prepare_main_dataset(fifa_df, stats_df=None):
    """Create a cleaned FIFA metadata set for joining/analysis."""
    fifa_df = standardize_columns(fifa_df)
    if stats_df is not None:
        stats_df = standardize_columns(stats_df)

    use_cols = [
        "short_name",
        "long_name",
        "age",
        "overall",
        "potential",
        "value_eur",
        "player_positions",
        "club_name",
        "nationality_name",
        "league_name",
    ]
    use_cols = [c for c in use_cols if c in fifa_df.columns]

    fifa_main = fifa_df[use_cols].copy()
    fifa_main["name_clean"] = fifa_main["long_name"].map(normalize_player_name)
    fifa_main = fifa_main.dropna(subset=["name_clean", "player_positions"])
    fifa_main = fifa_main.drop_duplicates(subset=["name_clean"])
    fifa_main["position_group"] = fifa_main["player_positions"].map(position_group)
    return fifa_main


def prepare_stats_dataset(stats_df, min_minutes=900):
    """Prepare real-world player production for position-aware comparison."""
    stats = standardize_columns(stats_df).rename(
        columns={
            "player": "player",
            "pos": "real_positions",
            "min": "minutes",
            "save%": "save_pct",
            "won%": "won_pct",
        }
    )
    required = ["player", "real_positions", "minutes"]
    if not all(column in stats.columns for column in required):
        return pd.DataFrame()

    stats = stats.copy()
    stats["minutes"] = pd.to_numeric(stats["minutes"], errors="coerce")
    stats = stats[stats["minutes"] >= min_minutes].copy()
    stats = stats.sort_values("minutes", ascending=False).drop_duplicates("player")
    stats["name_clean"] = stats["player"].map(normalize_player_name)
    stats["position_group"] = stats["real_positions"].map(position_group)

    metric_columns = [
        "gls", "ast", "xg", "xag", "prgc", "prgp", "prgr", "sca",
        "tkl", "int", "clr", "save_pct", "won_pct",
    ]
    for column in metric_columns:
        if column in stats.columns:
            stats[column] = pd.to_numeric(stats[column], errors="coerce")
            if column not in {"save_pct", "won_pct"}:
                stats[column] = stats[column] / stats["minutes"] * 90

    metrics_by_group = {
        "GK": ["save_pct"],
        "DEF": ["tkl", "int", "clr", "won_pct", "prgp"],
        "MID": ["gls", "ast", "xag", "prgp", "sca", "tkl", "int"],
        "FWD": ["gls", "ast", "xg", "xag", "sca", "prgr"],
    }
    stats["performance_percentile"] = pd.NA
    for group, metrics in metrics_by_group.items():
        group_mask = stats["position_group"] == group
        available = [column for column in metrics if column in stats.columns]
        if not available:
            continue
        percentiles = stats.loc[group_mask, available].rank(pct=True)
        stats.loc[group_mask, "performance_percentile"] = percentiles.mean(axis=1)

    return stats[
        ["name_clean", "player", "real_positions", "minutes", "position_group", "performance_percentile"]
    ].dropna(subset=["performance_percentile"])


def build_valuation_analysis(fifa_df, stats_df, min_minutes=900):
    """Compare FIFA ratings with position-adjusted real-world production."""
    fifa_main = prepare_main_dataset(fifa_df)
    stats = prepare_stats_dataset(stats_df, min_minutes=min_minutes)
    if stats.empty:
        return pd.DataFrame()

    fifa_main["rating_percentile"] = fifa_main.groupby("position_group")["overall"].rank(pct=True)
    comparison = stats.merge(fifa_main, on="name_clean", suffixes=("_real", "_fifa"))
    comparison = comparison[
        comparison["position_group_real"] == comparison["position_group_fifa"]
    ].copy()
    comparison["valuation_gap"] = (
        comparison["performance_percentile"] - comparison["rating_percentile"]
    )
    comparison["valuation"] = comparison["valuation_gap"].map(
        lambda gap: "underrated" if gap >= 0.2 else "overrated" if gap <= -0.2 else "aligned"
    )
    return comparison.sort_values("valuation_gap", ascending=False)


def validate_valuation_analysis(fifa_df, stats_df, min_minutes=900):
    """Return quality checks for the valuation analysis inputs and output."""
    fifa = standardize_columns(fifa_df)
    stats = standardize_columns(stats_df)
    fifa_main = prepare_main_dataset(fifa)
    prepared_stats = prepare_stats_dataset(stats, min_minutes=min_minutes)
    comparison = build_valuation_analysis(fifa, stats, min_minutes=min_minutes)

    fifa_names = set(fifa_main["name_clean"])
    eligible_names = set(prepared_stats["name_clean"])
    exact_matches = fifa_names & eligible_names
    position_counts = comparison["position_group_fifa"].value_counts().to_dict()
    score_columns = ["performance_percentile", "rating_percentile", "valuation_gap"]

    report = {
        "fifa_rows": len(fifa),
        "stats_rows": len(stats),
        "eligible_stats_rows": len(prepared_stats),
        "exact_name_matches": len(exact_matches),
        "position_consistent_matches": len(comparison),
        "position_match_rate": round(
            len(comparison) / len(exact_matches), 3
        ) if exact_matches else 0,
        "duplicate_fifa_ids": int(fifa["player_id"].duplicated().sum())
        if "player_id" in fifa.columns else None,
        "duplicate_stats_names": int(stats["player"].duplicated().sum())
        if "player" in stats.columns else None,
        "position_counts": position_counts,
        "scores_in_expected_range": all(
            comparison[column].between(-1, 1).all() for column in score_columns
        ) if not comparison.empty else False,
    }

    sensitivity = {}
    for threshold in (600, 900, 1200):
        threshold_result = build_valuation_analysis(fifa, stats, min_minutes=threshold)
        sensitivity[threshold] = len(threshold_result)
    report["comparison_count_by_minutes"] = sensitivity

    if not comparison.empty and "value_eur" in comparison.columns:
        comparison["value_eur"] = pd.to_numeric(comparison["value_eur"], errors="coerce")
        comparison["market_value_percentile"] = comparison.groupby(
            "position_group_fifa"
        )["value_eur"].rank(pct=True)
        comparison["market_value_gap"] = (
            comparison["market_value_percentile"] - comparison["rating_percentile"]
        )
        market_check = comparison[["valuation_gap", "market_value_gap"]].dropna()
        report["market_value_validation"] = {
            "spearman_correlation": round(
                market_check["valuation_gap"].corr(
                    market_check["market_value_gap"], method="spearman"
                ),
                3,
            ) if len(market_check) > 1 else None,
            "players_with_positive_market_gap": int(
                (market_check["market_value_gap"] > 0).sum()
            ),
            "players_checked": len(market_check),
        }

    base = build_valuation_analysis(fifa, stats, min_minutes=900)
    for threshold in (600, 1200):
        alternate = build_valuation_analysis(fifa, stats, min_minutes=threshold)
        base_top = set(base.head(10)["name_clean"])
        alternate_top = set(alternate.head(10)["name_clean"])
        report[f"underrated_top_10_overlap_{threshold}_vs_900"] = len(
            base_top & alternate_top
        )

    return report


def run_project_analysis():
    """Main analysis entry point for the project."""
    data = load_data_files()
    fifa_key = next((k for k in data if "fc26" in k.lower() or "fifa" in k.lower()), None)
    stats_key = next((k for k in data if "player" in k.lower() or "stats" in k.lower()), None)

    if fifa_key is None:
        raise ValueError("Expected a FIFA CSV in the data folder.")

    fifa_df = data[fifa_key]
    stats_df = data[stats_key] if stats_key else None

    fifa_main = prepare_main_dataset(fifa_df, stats_df)
    print("Loaded files:", list(data.keys()))
    print("FIFA main shape:", fifa_main.shape)
    print(fifa_main.head())

    if stats_df is not None:
        comparison = build_valuation_analysis(fifa_df, stats_df)
        validation = validate_valuation_analysis(fifa_df, stats_df)
        print("Validation:", validation)
        print("Comparable players:", len(comparison))
        print("Most underrated players:")
        print(comparison[comparison["valuation"] == "underrated"][
            ["player", "position_group_fifa", "overall", "performance_percentile", "valuation_gap"]
        ].head(10).to_string(index=False))
        print("Most overrated players:")
        print(comparison[comparison["valuation"] == "overrated"][
            ["player", "position_group_fifa", "overall", "performance_percentile", "valuation_gap"]
        ].tail(10).sort_values("valuation_gap").to_string(index=False))

    return fifa_main


if __name__ == "__main__":
    run_project_analysis()
