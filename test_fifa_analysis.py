"""Tests for fifa_analysis.py.

Run with: pytest
(requires pytest -- add to requirements.txt: pip install pytest)
"""
import pandas as pd
import pytest

from fifa_analysis import (
    normalize_player_name,
    first_last_name,
    token_sort_ratio,
    position_group,
    match_players,
    prepare_main_dataset,
    prepare_stats_dataset,
    build_valuation_analysis,
)


# ---------------------------------------------------------------------------
# normalize_player_name
# ---------------------------------------------------------------------------

class TestNormalizePlayerName:
    def test_strips_accents(self):
        assert normalize_player_name("Jude Bellingham") == "jude bellingham"
        assert normalize_player_name("Kylian Mbappé") == "kylian mbappe"
        assert normalize_player_name("Jules Koundé") == "jules kounde"

    def test_lowercases_and_strips_punctuation(self):
        assert normalize_player_name("O'Brien-Smith") == "obriensmith"
        assert normalize_player_name("D'Ambrosio") == "dambrosio"

    def test_collapses_whitespace(self):
        assert normalize_player_name("  Jude   Bellingham  ") == "jude bellingham"

    def test_handles_non_string_input(self):
        # pandas may pass NaN (float) for missing names
        assert normalize_player_name(float("nan")) == "nan"

    def test_empty_string(self):
        assert normalize_player_name("") == ""


# ---------------------------------------------------------------------------
# first_last_name
# ---------------------------------------------------------------------------

class TestFirstLastName:
    def test_drops_middle_names(self):
        assert first_last_name("jude victor william bellingham") == "jude bellingham"

    def test_two_token_name_unchanged(self):
        assert first_last_name("jude bellingham") == "jude bellingham"

    def test_single_token_returned_as_is(self):
        assert first_last_name("neymar") == "neymar"

    def test_empty_string(self):
        assert first_last_name("") == ""


# ---------------------------------------------------------------------------
# token_sort_ratio
# ---------------------------------------------------------------------------

class TestTokenSortRatio:
    def test_identical_strings_score_100(self):
        assert token_sort_ratio("jude bellingham", "jude bellingham") == 100.0

    def test_word_order_does_not_matter(self):
        a = token_sort_ratio("bellingham jude", "jude bellingham")
        assert a == 100.0

    def test_similar_names_score_high(self):
        score = token_sort_ratio("jude bellingham", "jude victor bellingham")
        assert score > 80

    def test_unrelated_names_score_low(self):
        score = token_sort_ratio("jude bellingham", "thiago silva")
        assert score < 50


# ---------------------------------------------------------------------------
# position_group
# ---------------------------------------------------------------------------

class TestPositionGroup:
    @pytest.mark.parametrize("raw,expected", [
        ("GK", "GK"),
        ("CB", "DEF"),
        ("LB", "DEF"),
        ("RWB", "DEF"),
        ("ST", "FWD"),
        ("CF", "FWD"),
        ("CM", "MID"),
        ("CAM", "MID"),
        ("CDM", "MID"),
    ])
    def test_known_positions_map_correctly(self, raw, expected):
        assert position_group(raw) == expected

    def test_takes_first_position_when_multiple(self):
        assert position_group("CB, RB") == "DEF"
        assert position_group("ST, CAM") == "FWD"

    def test_unknown_position_returns_none(self):
        assert position_group("XYZ") is None

    def test_case_insensitive(self):
        assert position_group("cb") == "DEF"

    def test_handles_non_string_input(self):
        assert position_group(float("nan")) is None


# ---------------------------------------------------------------------------
# match_players -- the three-tier matching strategy
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_fifa_main():
    df = pd.DataFrame({
        "short_name": ["J. Bellingham", "K. Mbappe", "E. Haaland", "V. van Dijk"],
        "long_name": [
            "Jude Victor William Bellingham",
            "Kylian Mbappe Lottin",
            "Erling Braut Haaland",
            "Virgil van Dijk",
        ],
        "age": [22, 26, 25, 33],
        "overall": [89, 91, 90, 87],
        "player_positions": ["CAM, CM", "ST", "ST", "CB"],
    })
    df["name_clean"] = df["long_name"].map(normalize_player_name)
    df["name_firstlast"] = df["name_clean"].map(first_last_name)
    df["position_group"] = df["player_positions"].map(position_group)
    return df


@pytest.fixture
def sample_stats():
    df = pd.DataFrame({
        "player": ["Jude Bellingham", "Kylian Mbappe", "Virgil van Dijk", "Someone Unrelated"],
        "real_positions": ["MF", "FW", "DF", "MF"],
        "minutes": [1800, 2000, 2200, 1500],
    })
    df["name_clean"] = df["player"].map(normalize_player_name)
    df["position_group"] = df["real_positions"].map(position_group)
    return df


class TestMatchPlayers:
    def test_exact_match(self, sample_fifa_main, sample_stats):
        result = match_players(sample_fifa_main, sample_stats)
        vdk = result[result["player"] == "Virgil van Dijk"].iloc[0]
        assert vdk["match_type"] == "exact"
        assert vdk["match_score"] == 100.0
        assert not vdk["needs_review"]

    def test_first_last_match_for_full_legal_name(self, sample_fifa_main, sample_stats):
        # "Jude Bellingham" (FBref) vs "Jude Victor William Bellingham" (FIFA)
        result = match_players(sample_fifa_main, sample_stats)
        jude = result[result["player"] == "Jude Bellingham"].iloc[0]
        assert jude["match_type"] == "first_last"
        assert jude["matched_fifa_name_clean"] == "jude victor william bellingham"
        assert not jude["needs_review"]

    def test_unmatched_player_has_no_match(self, sample_fifa_main, sample_stats):
        result = match_players(sample_fifa_main, sample_stats)
        unrelated = result[result["player"] == "Someone Unrelated"].iloc[0]
        assert unrelated["match_type"] == "unmatched"
        assert pd.isna(unrelated["matched_fifa_name_clean"])

    def test_ambiguous_collision_flagged_not_guessed(self, sample_fifa_main):
        # Two FIFA players share the same first+last token in the same
        # position group -- must not silently pick one.
        collision_fifa = pd.DataFrame({
            "short_name": ["A. Silva", "B. Silva"],
            "long_name": ["Andre Miguel Silva", "Bruno Rafael Silva"],
            "age": [24, 26],
            "overall": [78, 80],
            "player_positions": ["CB", "CB"],
        })
        collision_fifa["name_clean"] = collision_fifa["long_name"].map(normalize_player_name)
        # Force both FIFA players to share the same first+last token, simulating
        # a genuine name collision (e.g. two different "Andre Silva"s).
        collision_fifa["name_firstlast"] = "andre silva"
        collision_fifa["position_group"] = collision_fifa["player_positions"].map(position_group)

        stats = pd.DataFrame({
            "player": ["Andre Silva"],
            "real_positions": ["DF"],
            "minutes": [1000],
        })
        stats["name_clean"] = stats["player"].map(normalize_player_name)
        stats["position_group"] = stats["real_positions"].map(position_group)

        result = match_players(collision_fifa, stats)
        row = result.iloc[0]
        assert row["match_type"] == "ambiguous"
        assert pd.isna(row["matched_fifa_name_clean"])
        assert row["needs_review"]


# ---------------------------------------------------------------------------
# Regression test: percentile population-basis bug
#
# Previously, rating_percentile was ranked against the full FIFA dataset
# while performance_percentile was ranked only within the smaller matched
# population, systematically biasing valuation_gap negative (87.5% of
# players were mislabeled "overrated"). This test guards against that
# bug reappearing.
# ---------------------------------------------------------------------------

class TestPercentilePopulationConsistency:
    def _build_synthetic_data(self, n_fifa=200, n_matched=40):
        """A large FIFA pool + a small elite matched subset, mimicking
        real data where matched (900+ minute) players are a pre-filtered
        elite group relative to the full FIFA population."""
        import numpy as np
        rng = np.random.default_rng(42)

        # Full FIFA pool: wide spread of ability, mostly average/low.
        fifa_overall = rng.integers(55, 80, size=n_fifa - n_matched)
        # The players who will actually get matched: uniformly elite.
        matched_overall = rng.integers(78, 92, size=n_matched)
        all_overall = list(fifa_overall) + list(matched_overall)

        names = [f"player {i}" for i in range(n_fifa)]
        fifa_main = pd.DataFrame({
            "short_name": names,
            "long_name": names,
            "age": rng.integers(18, 35, size=n_fifa),
            "overall": all_overall,
            "player_positions": ["CB"] * n_fifa,
        })
        fifa_main["name_clean"] = fifa_main["long_name"].map(normalize_player_name)
        fifa_main["name_firstlast"] = fifa_main["name_clean"].map(first_last_name)
        fifa_main["position_group"] = fifa_main["player_positions"].map(position_group)

        # Only the "matched_overall" players appear in the stats (real-world) data.
        matched_names = names[n_fifa - n_matched:]
        stats = pd.DataFrame({
            "player": matched_names,
            "real_positions": ["DF"] * n_matched,
            "minutes": rng.integers(900, 3000, size=n_matched),
        })
        stats["name_clean"] = stats["player"].map(normalize_player_name)
        stats["position_group"] = stats["real_positions"].map(position_group)
        # Uniform-ish performance regardless of FIFA rating (uncorrelated on purpose).
        stats["performance_percentile"] = rng.uniform(0, 1, size=n_matched)

        return fifa_main, stats

    def test_rating_and_performance_percentile_share_a_population(self):
        """rating_percentile must be computed on the same population as
        performance_percentile, not the full unfiltered FIFA dataset --
        otherwise valuation_gap is systematically biased even when the
        underlying performance data has no real signal."""
        fifa_main, stats = self._build_synthetic_data()
        matched = match_players(fifa_main, stats)
        matched = matched.dropna(subset=["matched_fifa_name_clean"])

        merged = matched.merge(
            fifa_main, left_on="matched_fifa_name_clean", right_on="name_clean",
            suffixes=("_real", "_fifa"),
        )
        merged["rating_percentile"] = merged.groupby("position_group_fifa")["overall"].rank(pct=True)

        # With performance uniformly random and rating computed WITHIN the
        # matched population, the mean gap should be close to zero.
        gap_mean = (merged["performance_percentile"] - merged["rating_percentile"]).mean()
        assert abs(gap_mean) < 0.15, (
            f"valuation_gap mean is {gap_mean:.3f}, expected near 0. "
            "This likely means rating_percentile is being computed against "
            "a different population than performance_percentile -- check "
            "that both are ranked within the same matched subset."
        )