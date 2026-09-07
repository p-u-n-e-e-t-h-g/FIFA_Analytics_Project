from pathlib import Path
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
        "player_positions",
        "club_name",
        "nationality_name",
        "league_name",
    ]
    use_cols = [c for c in use_cols if c in fifa_df.columns]

    fifa_main = fifa_df[use_cols].copy()
    fifa_main["name_clean"] = (
        fifa_main["long_name"].astype(str).str.lower().str.strip()
    )
    fifa_main = fifa_main.dropna(subset=["name_clean", "player_positions"])
    fifa_main = fifa_main.drop_duplicates(subset=["name_clean"])
    return fifa_main


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

    return fifa_main


if __name__ == "__main__":
    run_project_analysis()
