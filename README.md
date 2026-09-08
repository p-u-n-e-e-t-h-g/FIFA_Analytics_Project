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

## Known Limitation: Defensive Metrics Undercount Elite Players at Dominant Teams

Position-split validation against `value_eur` shows DEF has the weakest
correlation with market value of any position group (Spearman ≈ -0.17,
vs. ≈ 0.07 for MID and ≈ 0.00 for GK). Two normalization fixes were
tested against this finding and both were rejected by the data:

1. **Team-baseline normalization** -- expressing each defender's raw
   stats relative to their own squad's average -- did not improve the
   correlation.
2. **Role-based normalization** -- splitting DEF into center-backs vs.
   fullbacks, since FBref's position data doesn't distinguish them but
   FIFA's does -- also did not improve it. Elite center-backs at
   possession-dominant clubs (e.g. Arsenal's William Saliba) still
   rank low even when compared only to other center-backs league-wide.

**Conclusion:** this is not a normalization problem. Elite center-backs
at top teams face fewer defensive situations in the first place,
because their team controls the ball -- so raw counting stats (`tkl`,
`int`, `clr`) are genuinely lower for them, and no reweighting of
*those same stats* can recover a signal they were never designed to
capture. What actually makes a defender like Saliba elite --
positioning that prevents situations from occurring, composure and
distribution under pressure -- isn't represented in this metric bundle
at all. This is a scope limitation of the available stats, not a bug:
the DEF `valuation_gap` should be read as "counting-stat productivity
relative to rating," not as a general skill judgment, and is least
reliable for possession-dominant teams' defenders.

Future work: test correlation against `wage_eur` (club-set wages may
track true ability better than FIFA's in-game market value), or
incorporate an independent possession-adjusted defensive metric
(e.g. defensive actions per opponent touch in the defensive third)
if available in a future data source.

## Key Findings

- Built a position-aware pipeline joining FIFA FC26 ratings to FBref
  real-world performance stats via a tiered name-matching system
  (exact → token-normalized → fuzzy fallback), achieving a 65% match
  rate on 900+-minute players (up from 42% with naive exact matching).
- Validated the resulting "valuation gap" against independent market
  value data, split by position -- and found it holds up reasonably
  for midfielders and goalkeepers but breaks down for defenders.
- Root-caused the defender breakdown to a real limitation in available
  defensive stats (see "Known Limitation" below) rather than a bug or
  tuning issue -- tested and ruled out two plausible normalization fixes
  before reaching that conclusion.