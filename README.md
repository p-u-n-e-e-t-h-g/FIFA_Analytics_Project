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

## What Counts As Validation

The current validation report checks that the pipeline is reliable and also compares the valuation gap with FIFA `value_eur`. That comparison is only a diagnostic because `value_eur` comes from the same game ecosystem, not an independent real-world source. A negative or weak correlation must be reported as a failed validation signal, not hidden or tuned away.

Real validation requires an independent target, such as real transfer values, wages, expert rankings, team-of-the-season selections, or a later season of performance. We should test whether high positive gaps predict that independent target while controlling for position, playing time, age, and league. Until that data is added, the project validates its calculations and assumptions, but not the truth of the underrated or overrated labels.

## Known Limitation: Defensive Metrics Favour Weaker Teams

Position-split validation against `value_eur` shows DEF has the weakest
correlation with market value of any position group (Spearman ≈ -0.18,
vs. ≈ 0.07 for MID and ≈ 0.00 for GK). Digging into the largest
disagreements shows a consistent pattern:

- Aging defenders on weaker teams (e.g. players in their early-to-mid
  30s at mid-table clubs) score highly on raw defensive counting
  stats (tackles, interceptions, clearances) simply because their
  team spends more time defending.
- Elite defenders at possession-dominant clubs (e.g. players compared
  to Arsenal's or Inter's first-choice center-backs) score *lower* on
  the same metrics, despite both FIFA rating and market value agreeing
  they are excellent, because their team controls the ball and rarely
  needs defending.

This is a known bias in raw defensive counting stats, not a bug in the
matching or scoring code: `tkl`, `int`, and `clr` per 90 measure
defensive *activity*, not defensive *quality*, and activity is driven
as much by team style as by individual skill. The current DEF metric
bundle (`tkl, int, clr, won_pct, prgp`) should be read with this in
mind -- a low performance_percentile for a defender at a dominant team
is not strong evidence of overrating.

Possible future fixes: normalize defensive actions by team possession
share or opponent touches in the defensive third (if available in the
source data), or weight progressive/ball-playing metrics (`prgp`) more
heavily relative to raw defensive counting stats for this position group.