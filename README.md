# FIFA Analytics Project

This project is a clean, minimal analytics workspace for working with FIFA player data and related stats.

## Structure

- `data/` - place your CSV files here
- `main.py` - project entry point
- `fifa_analysis.py` - analysis logic and helpers
- `requirements.txt` - Python dependencies

## Setup

1. Put your CSV files into the `data/` folder.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python main.py
   ```

## Notes

The project is intentionally lightweight and keeps everything in one main project folder with a separate `data` directory for your CSV files.

## Valuation Method

The analysis compares FIFA overall-rating percentiles with real-world performance percentiles within broad position groups: goalkeeper, defender, midfielder, and forward.

- Players must have at least 900 recorded minutes by default.
- Players are matched using normalized full names.
- Only matches with consistent position groups are included.
- A positive `valuation_gap` suggests a potentially underrated player.
- A negative `valuation_gap` suggests a potentially overrated player.

Run `python main.py` to see the rankings and the validation report. The report includes match coverage, duplicate checks, position consistency, score bounds, and sensitivity to the minutes threshold. These rankings are signals for further investigation, not proof of player quality: exact-name matching and the selected performance metrics limit coverage.
