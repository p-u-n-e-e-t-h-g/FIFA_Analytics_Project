from pathlib import Path
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

# --- tunable constants (previously magic numbers buried in functions) ---
MIN_MINUTES_DEFAULT = 900
VALUATION_GAP_THRESHOLD = 0.2
FUZZY_MATCH_MIN_SCORE = 90  # 0-100; only used for the tier-3 fallback


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
        loaded[file.stem] = pd.read_csv(file, low_memory=False)
    return loaded


def standardize_columns(df):
    """Normalize dataframe column names."""
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    return df


def normalize_player_name(value):
    """Create a consistent join key for player names (strip accents, punctuation, case)."""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-zA-Z0-9 ]", "", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def first_last_name(name_clean):
    """Collapse a full name to 'first last', dropping middle names.

    FIFA's long_name is often a full legal name ('Jude Victor William
    Bellingham') while FBref-style stats use the common public name
    ('Jude Bellingham'). This bridges that gap for the common case.
    """
    tokens = name_clean.split()
    if len(tokens) < 2:
        return name_clean
    return f"{tokens[0]} {tokens[-1]}"


def token_sort_ratio(a, b):
    """Order-independent similarity score (0-100) between two name strings."""
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    return SequenceMatcher(None, a_sorted, b_sorted).ratio() * 100


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


def prepare_main_dataset(fifa_df):
    """Create a cleaned FIFA metadata set for joining/analysis."""
    fifa_df = standardize_columns(fifa_df)

    use_cols = [
        "short_name", "long_name", "age", "overall", "potential", "value_eur",
        "player_positions", "club_name", "nationality_name", "league_name",
    ]
    use_cols = [c for c in use_cols if c in fifa_df.columns]

    fifa_main = fifa_df[use_cols].copy()
    fifa_main["name_clean"] = fifa_main["long_name"].map(normalize_player_name)
    fifa_main["name_firstlast"] = fifa_main["name_clean"].map(first_last_name)
    fifa_main = fifa_main.dropna(subset=["name_clean", "player_positions"])
    fifa_main = fifa_main.drop_duplicates(subset=["name_clean"])
    fifa_main["position_group"] = fifa_main["player_positions"].map(position_group)
    return fifa_main


def prepare_stats_dataset(stats_df, min_minutes=MIN_MINUTES_DEFAULT):
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

    return stats.dropna(subset=["performance_percentile"])


def match_players(fifa_main, stats):
    """Join stats players to FIFA players using a three-tier name-matching strategy.

    Tier 1: exact match on normalized long_name.
    Tier 2: exact match on 'first + last' token, restricted to same position
            group (handles FIFA's full-legal-name vs FBref's common-name gap).
            Ambiguous collisions (2+ candidates) are left unmatched and flagged
            for manual review rather than guessed.
    Tier 3: fuzzy fallback (token-sort similarity), same position group,
            only above FUZZY_MATCH_MIN_SCORE.

    Returns stats with extra columns: matched_fifa_name_clean, match_type,
    match_score (NaN/None where unmatched).
    """
    fifa_exact = set(fifa_main["name_clean"])

    firstlast_map = {}
    for idx, row in fifa_main.iterrows():
        firstlast_map.setdefault(row["name_firstlast"], []).append(idx)

    fifa_by_group = {
        group: fifa_main[fifa_main["position_group"] == group]
        for group in fifa_main["position_group"].dropna().unique()
    }

    matched_name, match_type, match_score, review_flag = [], [], [], []

    for _, row in stats.iterrows():
        name = row["name_clean"]
        group = row["position_group"]

        if name in fifa_exact:
            matched_name.append(name)
            match_type.append("exact")
            match_score.append(100.0)
            review_flag.append(False)
            continue

        candidates_idx = [
            i for i in firstlast_map.get(name, [])
            if fifa_main.loc[i, "position_group"] == group
        ]
        if len(candidates_idx) == 1:
            matched_name.append(fifa_main.loc[candidates_idx[0], "name_clean"])
            match_type.append("first_last")
            match_score.append(95.0)
            review_flag.append(False)
            continue
        if len(candidates_idx) > 1:
            # Genuine ambiguity (name collision) -- don't guess.
            matched_name.append(None)
            match_type.append("ambiguous")
            match_score.append(None)
            review_flag.append(True)
            continue

        pool = fifa_by_group.get(group)
        if pool is None or pool.empty:
            matched_name.append(None)
            match_type.append("unmatched")
            match_score.append(None)
            review_flag.append(False)
            continue

        scores = pool["name_clean"].map(lambda c: token_sort_ratio(name, c))
        best_idx = scores.idxmax()
        best_score = scores[best_idx]
        if best_score >= FUZZY_MATCH_MIN_SCORE:
            matched_name.append(pool.loc[best_idx, "name_clean"])
            match_type.append("fuzzy")
            match_score.append(round(best_score, 1))
            review_flag.append(best_score < 95)  # flag lower-confidence fuzzy hits
        else:
            matched_name.append(None)
            match_type.append("unmatched")
            match_score.append(None)
            review_flag.append(False)

    stats = stats.copy()
    stats["matched_fifa_name_clean"] = matched_name
    stats["match_type"] = match_type
    stats["match_score"] = match_score
    stats["needs_review"] = review_flag
    return stats


def build_valuation_analysis(fifa_df, stats_df, min_minutes=MIN_MINUTES_DEFAULT, include_needs_review=False):
    """Compare FIFA ratings with position-adjusted real-world production.

    By default, matches flagged by match_players() as needing manual review
    (low-confidence fuzzy matches, name collisions) are excluded from the
    returned rankings -- a flagged match can be a genuinely wrong join (see
    e.g. 'Jon Martin' matched to 'Martin Gjone' at ~91% fuzzy similarity),
    and letting those into headline "underrated"/"overrated" rankings risks
    reporting noise as signal. Pass include_needs_review=True to get the
    full unfiltered set (useful for auditing match quality itself).
    """
    fifa_main = prepare_main_dataset(fifa_df)
    stats = prepare_stats_dataset(stats_df, min_minutes=min_minutes)
    if stats.empty:
        return pd.DataFrame()

    stats = match_players(fifa_main, stats)
    matched_stats = stats.dropna(subset=["matched_fifa_name_clean"]).copy()

    fifa_main["rating_percentile"] = fifa_main.groupby("position_group")["overall"].rank(pct=True)

    comparison = matched_stats.merge(
        fifa_main,
        left_on="matched_fifa_name_clean",
        right_on="name_clean",
        suffixes=("_real", "_fifa"),
    )
    comparison = comparison[
        comparison["position_group_real"] == comparison["position_group_fifa"]
    ].copy()
    comparison["valuation_gap"] = (
        comparison["performance_percentile"] - comparison["rating_percentile"]
    )
    comparison["valuation"] = comparison["valuation_gap"].map(
        lambda gap: "underrated" if gap >= VALUATION_GAP_THRESHOLD
        else "overrated" if gap <= -VALUATION_GAP_THRESHOLD
        else "aligned"
    )
    comparison = comparison.sort_values("valuation_gap", ascending=False)

    if not include_needs_review:
        comparison = comparison[~comparison["needs_review"]].copy()

    return comparison


def validate_valuation_analysis(fifa_df, stats_df, min_minutes=MIN_MINUTES_DEFAULT):
    """Return quality checks for the valuation analysis inputs and output."""
    fifa = standardize_columns(fifa_df)
    stats_std = standardize_columns(stats_df)
    fifa_main = prepare_main_dataset(fifa)
    prepared_stats = prepare_stats_dataset(stats_std, min_minutes=min_minutes)
    matched_stats = match_players(fifa_main, prepared_stats) if not prepared_stats.empty else prepared_stats
    comparison = build_valuation_analysis(fifa, stats_std, min_minutes=min_minutes)

    match_type_counts = (
        matched_stats["match_type"].value_counts().to_dict() if not matched_stats.empty else {}
    )
    needs_review_count = (
        int(matched_stats["needs_review"].sum()) if not matched_stats.empty else 0
    )
    position_counts = comparison["position_group_fifa"].value_counts().to_dict() if not comparison.empty else {}

    report = {
        "fifa_rows": len(fifa),
        "stats_rows": len(stats_std),
        "eligible_stats_rows": len(prepared_stats),
        "match_type_breakdown": match_type_counts,
        "match_rate_pct": round(
            sum(v for k, v in match_type_counts.items() if k != "unmatched" and k != "ambiguous")
            / len(prepared_stats) * 100, 1
        ) if len(prepared_stats) else 0,
        "ambiguous_collisions": match_type_counts.get("ambiguous", 0),
        "matches_needing_manual_review": needs_review_count,
        "position_consistent_matches": len(comparison),
        "position_counts": position_counts,
        "duplicate_fifa_ids": int(fifa["player_id"].duplicated().sum())
        if "player_id" in fifa.columns else None,
    }

    if not comparison.empty and "value_eur" in comparison.columns:
        comparison = comparison.copy()
        comparison["value_eur"] = pd.to_numeric(comparison["value_eur"], errors="coerce")
        comparison["market_value_percentile"] = comparison.groupby(
            "position_group_fifa"
        )["value_eur"].rank(pct=True)
        comparison["market_value_gap"] = (
            comparison["market_value_percentile"] - comparison["rating_percentile"]
        )
        market_check = comparison[
            ["position_group_fifa", "valuation_gap", "market_value_gap"]
        ].dropna()
        report["market_value_validation"] = {
            "spearman_correlation": round(
                market_check["valuation_gap"].corr(
                    market_check["market_value_gap"], method="spearman"
                ), 3,
            ) if len(market_check) > 1 else None,
            "players_checked": len(market_check),
        }

        by_position = {}
        for group, group_df in market_check.groupby("position_group_fifa"):
            by_position[group] = {
                "spearman_correlation": round(
                    group_df["valuation_gap"].corr(
                        group_df["market_value_gap"], method="spearman"
                    ), 3,
                ) if len(group_df) > 1 else None,
                "players_checked": len(group_df),
            }
        report["market_value_validation_by_position"] = by_position

    sensitivity = {}
    for threshold in (600, 900, 1200):
        sensitivity[threshold] = len(build_valuation_analysis(fifa, stats_std, min_minutes=threshold))
    report["comparison_count_by_minutes"] = sensitivity

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

    fifa_main = prepare_main_dataset(fifa_df)
    print("Loaded files:", list(data.keys()))
    print("FIFA main shape:", fifa_main.shape)

    if stats_df is not None:
        # Headline rankings exclude low-confidence/ambiguous matches by default.
        comparison = build_valuation_analysis(fifa_df, stats_df)
        # Full set (incl. flagged matches) so we can show what was excluded and why.
        comparison_all = build_valuation_analysis(fifa_df, stats_df, include_needs_review=True)

        validation = validate_valuation_analysis(fifa_df, stats_df)
        print("\nValidation report:")
        for k, v in validation.items():
            print(f"  {k}: {v}")

        print("\nMost underrated players:")
        print(comparison[comparison["valuation"] == "underrated"][
            ["player", "position_group_fifa", "overall", "performance_percentile", "valuation_gap", "match_type"]
        ].head(10).to_string(index=False))

        print("\nMost overrated players:")
        print(comparison[comparison["valuation"] == "overrated"][
            ["player", "position_group_fifa", "overall", "performance_percentile", "valuation_gap", "match_type"]
        ].tail(10).sort_values("valuation_gap").to_string(index=False))

        print("\nMatches excluded from rankings above (flagged for manual review -- fuzzy/collisions):")
        review_rows = comparison_all[comparison_all["needs_review"]]
        if not review_rows.empty:
            print(review_rows[["player", "long_name", "match_type", "match_score"]].to_string(index=False))
        else:
            print("  none")

    return fifa_main


if __name__ == "__main__":
    run_project_analysis()