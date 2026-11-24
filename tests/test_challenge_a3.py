"""Scenario A3, Checkpoint 2: the ``a3-432-v1`` configuration is registered alongside
``broad60-432-v1`` (which stays the default and the only scheduled configuration).

Covers the configuration itself (exact boundaries at adjacent floating-point values,
no overlaps, exclusions, nothing but the two bands differs), D-28 opening and
distinct-fixture matching, A3 eligibility on the committed real-market research pool,
coexistence of both versions in the version-aware application paths, and the historical
v1 settlement regression against the outputs recorded by the pre-A3 code."""

from __future__ import annotations

import json
import math
import types
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import diski9.challenge.config as cfgmod
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import components as c
from diski9.app.challenge import pages
from diski9.app.challenge.service import ChallengeService, key_str
from diski9.challenge import analysis as pa
from diski9.challenge.config import (
    A3_432_V1,
    BROAD60_432_V1,
    DEFAULT_CONFIG,
    ConfigError,
    ProbabilitySource,
    get_config,
    register_config,
)
from diski9.challenge.roundsheet import assess_round, snapshot_from_research_pool
from diski9.challenge.scoring import EntryResult, RoundClassification, RoundResult, score_round
from diski9.challenge.settle import Leg, settle_entry
from diski9.challenge.structured import (
    assess_outcome,
    evaluate_groups,
    evaluate_market_and_model,
    make_outcome,
    portfolio_feasible,
    round_opening_report,
    validate_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
POOL = json.loads((ROOT / "docs/research/weekly_challenge_risk/pool_fortnight.json").read_text())
REG = json.loads((ROOT / "tests/fixtures/challenge/v1_settlement_regression.json").read_text())
LEAGUES = {39: "EPL", 40: "Championship", 61: "Ligue 1", 78: "Bundesliga", 135: "Serie A",
           140: "La Liga", 288: "PSL", 289: "PSL 1st Div"}  # fmt: skip
V1_FP = "b8cb7c0372e6aac15b1638e100be35955dacfd3f11c1f3654ad52c9263cbba94"
A3_FP = "91dba48a002a4fed3dc340764ef1717228f7dea61401f29621e799de401b094e"
down, up = (lambda x: math.nextafter(x, 0.0)), (lambda x: math.nextafter(x, 1.0))


# ===================================================================== configuration
def test_both_configurations_registered_and_a3_is_the_default():
    """Checkpoint 4C (Option D): A3 is the launch default; broad60 stays registered
    for every round already bound to it."""
    assert get_config("broad60-432-v1") is BROAD60_432_V1
    assert get_config("a3-432-v1") is A3_432_V1
    assert set(cfgmod._REGISTRY) == {"broad60-432-v1", "a3-432-v1"}
    assert DEFAULT_CONFIG is A3_432_V1


def test_fingerprints_are_pinned():
    assert BROAD60_432_V1.fingerprint() == V1_FP  # unchanged since before A3
    assert A3_432_V1.fingerprint() == A3_FP


def test_redefinition_is_refused_and_identical_registration_is_idempotent():
    with pytest.raises(ConfigError, match="already registered"):
        register_config(replace(A3_432_V1, nine_fold_name="Something else"))
    with pytest.raises(ConfigError, match="already registered"):
        register_config(replace(BROAD60_432_V1, buckets=A3_432_V1.buckets))
    assert register_config(A3_432_V1) is A3_432_V1
    assert get_config("a3-432-v1") is A3_432_V1


def test_unknown_versions_fail_safely():
    for v in ("a3-432-v2", "A3-432-V1", "", "broad60"):
        with pytest.raises(ConfigError):
            get_config(v)


def test_a3_differs_from_v1_only_in_version_and_the_two_approved_bands():
    v1, a3 = BROAD60_432_V1.canonical(), A3_432_V1.canonical()
    assert (v1["version"], a3["version"]) == ("broad60-432-v1", "a3-432-v1")
    assert a3["buckets"][0]["band"] == [repr(0.6), repr(0.9), True, True]  # Foundation
    assert a3["buckets"][1]["band"] == v1["buckets"][1]["band"]  # Balanced unchanged
    assert a3["buckets"][2]["band"] == [repr(0.1), repr(0.4), True, False]  # Challenger
    for d in (v1, a3):
        d.pop("version")
        for b in d["buckets"]:
            b.pop("band")
    assert v1 == a3  # sizes 4/3/2, credits 40/30/20/10, nine-fold, D-28, odds, sources


def test_classification_uses_market_probability_never_the_goal_model():
    with pytest.raises(ConfigError, match="market"):
        replace(A3_432_V1, version="x-model", classification_source=ProbabilitySource.MODEL)
    at = datetime(2026, 11, 20, tzinfo=UTC)
    low_market = make_outcome(1, "1X2", "AWAY", 0.15, "6.30", 0.05, 5, at, 39)
    low_model = make_outcome(2, "1X2", "AWAY", 0.05, "19.00", 0.15, 5, at, 39)
    assert assess_outcome(low_market, at, A3_432_V1).bucket == "C"  # market 15%
    assert not assess_outcome(low_model, at, A3_432_V1).eligible  # market 5%, model 15%


# ---------------------------------------------------------------- exact boundaries
A3_CASES = [
    (down(0.10), None), (0.10, "C"), (up(0.10), "C"),
    (down(0.40), "C"), (0.40, "B"), (up(0.40), "B"),
    (down(0.60), "B"), (0.60, "A"), (up(0.60), "A"),
    (down(0.90), "A"), (0.90, "A"), (up(0.90), None),
    (0.0, None), (0.0999, None), (0.9001, None), (0.95, None), (1.0, None),
]  # fmt: skip
V1_CASES = [
    (down(0.20), None), (0.20, "C"), (up(0.20), "C"), (0.15, None),
    (down(0.40), "C"), (0.40, "B"), (down(0.60), "B"), (0.60, "A"),
    (0.90, "A"), (up(0.90), "A"), (0.95, "A"), (up(0.95), None),
]  # fmt: skip


@pytest.mark.parametrize(("p", "bucket"), A3_CASES)
def test_a3_exact_boundaries_and_adjacent_floats(p, bucket):
    assert A3_432_V1.classify(p) == bucket


@pytest.mark.parametrize(("p", "bucket"), V1_CASES)
def test_v1_boundaries_are_unchanged(p, bucket):
    assert BROAD60_432_V1.classify(p) == bucket


def test_no_overlap_and_every_probability_from_10_to_90_is_in_exactly_one_bucket():
    bands = [b.band for b in A3_432_V1.buckets]
    assert not any(a.overlaps(b) for i, a in enumerate(bands) for b in bands[i + 1 :])
    for k in range(10_000, 90_001):  # 0.10000 ... 0.90000 in steps of 0.00001
        p = k / 100_000
        assert sum(b.contains(p) for b in bands) == 1, p
    for p in (0.10, 0.40, 0.60, 0.90, up(0.10), down(0.40), up(0.40), down(0.60), down(0.90)):
        assert sum(b.contains(p) for b in bands) == 1, p


def test_outcomes_below_10_or_above_90_percent_are_excluded():
    for k in range(0, 10_000):  # 0 ... 0.09999
        assert A3_432_V1.classify(k / 100_000) is None
    for k in range(90_001, 100_001):  # 0.90001 ... 1.0
        assert A3_432_V1.classify(k / 100_000) is None


# ====================================================== opening and portfolio feasibility
AT = datetime(2026, 11, 20, 8, tzinfo=UTC)


def _o(fid, p, outcome="HOME", league=39):
    return make_outcome(fid, "1X2", outcome, p, Decimal(str(round(0.95 / p, 2))), p, 5,
                        AT - timedelta(minutes=5), league)  # fmt: skip


def test_pool_feasible_only_through_the_new_challenger_outcomes():
    leagues = (39, 61, 78)
    pool = [_o(i, 0.70, league=leagues[i % 3]) for i in range(6)]  # Foundation
    pool += [_o(10 + i, 0.50, league=leagues[i % 3]) for i in range(6)]  # Balanced
    pool += [_o(20 + i, 0.15, "AWAY", leagues[i % 3]) for i in range(4)]  # 15%: new Challenger
    v1, a3 = (round_opening_report(pool, AT, cfg) for cfg in (BROAD60_432_V1, A3_432_V1))
    assert v1.eligible_fixtures == 12 and not v1.portfolio_feasible and not v1.opens
    assert a3.eligible_fixtures == 16 and a3.eligible_leagues == 3
    assert a3.portfolio_feasible and a3.opens
    assert a3.eligible_outcomes_by_bucket == {"A": 6, "B": 6, "C": 4}


def test_distinct_fixture_matching_under_a3():
    """Four fixtures carry both the only Foundation outcomes and the only Challenger
    outcomes: counts suffice, but nine distinct fixtures cannot be found."""
    pool = []
    for i in range(4):
        pool += [_o(i, 0.70), _o(i, 0.15, "AWAY")]
    pool += [_o(10 + i, 0.50) for i in range(3)]
    assert not portfolio_feasible(pool, AT, A3_432_V1)
    pool += [_o(30, 0.18, "DRAW"), _o(31, 0.12, "AWAY")]  # two more distinct fixtures
    assert portfolio_feasible(pool, AT, A3_432_V1)
    assert not portfolio_feasible(pool, AT, BROAD60_432_V1)  # 12% and 18% are not v1


# ---------------------------------------------------- real-market research pool (A3)
WINDOWS = {"20-23 Nov": ("2026-11-20", "2026-11-23"), "27-30 Nov": ("2026-11-27", "2026-11-30")}
# Reported by the research (docs/research/weekly_challenge_bucket_review.md, section 7;
# docs/research/weekly_challenge_buckets/summary.json availability.real).
EXPECTED = {
    "20-23 Nov": {"v1": (128, 57), "a3": (164, 60), "fixtures": 60, "leagues": 6},
    "27-30 Nov": {"v1": (65, 29), "a3": (74, 29), "fixtures": 29, "leagues": 3},
}


def _window_report(snap, config, lo, hi):
    outs = [
        o
        for o in snap.outcomes
        if lo <= snap.fixture(o.fixture_id).kickoff.date().isoformat() <= hi
    ]
    assessed = [assess_outcome(o, snap.snapshot_at, config) for o in outs]
    chal = [a for a in assessed if a.eligible and a.bucket == "C"]
    return outs, chal, round_opening_report(outs, snap.snapshot_at, config)


@pytest.mark.parametrize("window", list(WINDOWS))
def test_real_pool_reproduces_the_reported_a3_challenger_additions(window):
    lo, hi = WINDOWS[window]
    exp = EXPECTED[window]
    snaps = {v: snapshot_from_research_pool(POOL, "pool", LEAGUES, get_config(n))
             for v, n in (("v1", "broad60-432-v1"), ("a3", "a3-432-v1"))}  # fmt: skip
    for v in ("v1", "a3"):
        outs, chal, report = _window_report(snaps[v], snaps[v].config, lo, hi)
        assert (len(chal), len({a.outcome.fixture_id for a in chal})) == exp[v], (window, v)
        assert report.eligible_fixtures == exp["fixtures"]
        assert report.eligible_leagues == exp["leagues"]
        assert report.opens  # D-28 opening holds under both configurations
    # the additions are exactly the 10%-20% outcomes; nothing above 90% exists
    _, chal_v1, _ = _window_report(snaps["v1"], BROAD60_432_V1, lo, hi)
    _, chal_a3, _ = _window_report(snaps["a3"], A3_432_V1, lo, hi)
    added = {a.outcome.key for a in chal_a3} - {a.outcome.key for a in chal_v1}
    probs = [o.market_probability for o in snaps["a3"].outcomes if o.key in added]
    assert len(added) == exp["a3"][0] - exp["v1"][0]
    assert all(0.10 <= p < 0.20 for p in probs)
    assert max(o.market_probability for o in snaps["a3"].outcomes) < 0.90


# ========================================================== version coexistence
def _service(snap):
    data = types.SimpleNamespace(clock=lambda: snap.snapshot_at + timedelta(hours=1), engine=None)
    return ChallengeService(data=data)


def _snaps():
    v1 = snapshot_from_research_pool(POOL, "co", LEAGUES, BROAD60_432_V1)
    a3 = snapshot_from_research_pool(POOL, "co", LEAGUES, A3_432_V1)
    return v1, a3


def _portfolio(snap, config):
    """Nine distinct fixtures (20-23 Nov) matched 4/3/2 under ``config``."""
    used, picks = set(), {"A": [], "B": [], "C": []}
    for o in snap.outcomes:
        if not ("2026-11-20" <= snap.fixture(o.fixture_id).kickoff.date().isoformat()
                <= "2026-11-23"):  # fmt: skip
            continue
        b = config.classify(o.market_probability)
        if b and o.fixture_id not in used and len(picks[b]) < {"A": 4, "B": 3, "C": 2}[b]:
            picks[b].append(o)
            used.add(o.fixture_id)
    return [o for b in "ABC" for o in picks[b]]


def _a3_only_portfolio(snap):
    """Nine distinct fixtures (20-23 Nov) with a 10%-20% Challenger pick: valid only under A3."""
    window = [
        o
        for o in snap.outcomes
        if "2026-11-20" <= snap.fixture(o.fixture_id).kickoff.date().isoformat() <= "2026-11-23"
    ]
    used, picks = set(), {"A": [], "B": [], "C": []}
    low = next(o for o in window if 0.10 <= o.market_probability < 0.20)
    picks["C"].append(low)
    used.add(low.fixture_id)
    for o in window:
        b = A3_432_V1.classify(o.market_probability)
        if b and o.fixture_id not in used and len(picks[b]) < {"A": 4, "B": 3, "C": 2}[b]:
            if b == "C" and o.market_probability < 0.20:
                continue  # exactly one sub-20% pick
            picks[b].append(o)
            used.add(o.fixture_id)
    return [o for b in "ABC" for o in picks[b]]


def test_snapshots_resolve_their_own_configuration_and_labels():
    v1, a3 = _snaps()
    assert v1.config is BROAD60_432_V1 and a3.config is A3_432_V1
    assert pages.rules_config(v1) is BROAD60_432_V1 and pages.rules_config(a3) is A3_432_V1
    labels = {s.config_version: [c.band_text(b.band) for b in s.config.buckets] for s in (v1, a3)}
    assert labels == {
        "broad60-432-v1": ["60%–95%", "40% to under 60%", "20% to under 40%"],
        "a3-432-v1": ["60%–90%", "40% to under 60%", "10% to under 40%"],
    }
    assert c.eligible_range_text(v1.config) == "20%–95%"
    assert c.eligible_range_text(a3.config) == "10%–90%"
    o = next(x for x in a3.outcomes if x.market_probability < 0.10)
    _, _, t_v1 = c.outcome_state(o, None, None, False, config=v1.config)
    _, _, t_a3 = c.outcome_state(o, None, None, False, config=a3.config)
    assert "20%–95%" in t_v1 and "10%–90%" in t_a3


def test_a3_portfolio_is_valid_only_on_an_a3_snapshot():
    v1, a3 = _snaps()
    chosen = _a3_only_portfolio(a3)
    keys = [key_str(o.key) for o in chosen]
    assert _service(a3).portfolio(a3, keys) is not None
    assert _service(v1).portfolio(v1, keys) is None  # the 10-20% pick is not eligible in v1
    cards, _ = pages.fixture_list(_service(a3), a3, [], {"bucket": "C"}, lambda d, f="": "", False)
    assert cards  # the A3 builder lists Challenger outcomes including 10-20%


def test_confirmation_uses_the_snapshot_configuration_not_the_default():
    _, a3 = _snaps()
    svc = _service(a3)
    keys = [key_str(o.key) for o in _a3_only_portfolio(a3)]
    avail = assess_round(a3, svc.now())
    assert avail.playable and DEFAULT_CONFIG is A3_432_V1
    s = {"fp": a3.fingerprint, "selections": keys, "submitted": None}
    s, flash = cb.submit(svc, s, a3, avail)
    assert s["submitted"] is not None and s["submitted"]["config"] == "a3-432-v1", flash
    assert {p["bucket"] for p in s["submitted"]["picks"]} == {"A", "B", "C"}
    # with A3 as the default, a v1 snapshot is still confirmed under its own version
    v1, _ = _snaps()
    v1_keys = [key_str(o.key) for o in _portfolio(v1, BROAD60_432_V1)]
    v1_avail = assess_round(v1, _service(v1).now())
    s1 = {"fp": v1.fingerprint, "selections": v1_keys, "submitted": None}
    s1, flash1 = cb.submit(_service(v1), s1, v1, v1_avail)
    assert s1["submitted"] is not None and s1["submitted"]["config"] == "broad60-432-v1", flash1
    # an unknown version is refused, never confirmed under the default
    bad = replace(a3, config_version="not-registered")
    s2 = {"fp": bad.fingerprint, "selections": keys, "submitted": None}
    s2, flash2 = cb.submit(_service(bad), s2, bad, avail)
    assert s2["submitted"] is None and flash2 is not None


def test_bucket_completion_probabilities_unchanged_for_portfolios_valid_in_both():
    v1, a3 = _snaps()
    for e in REG["entries"]:
        chosen = [v1.outcome((fid, m, oc)) for _, fid, m, oc, _, _, _ in e["legs"]]
        for prob in (pa.market_probability, pa.model_probability):
            s1 = pa.bucket_stats(chosen, prob, BROAD60_432_V1)
            s3 = pa.bucket_stats(chosen, prob, A3_432_V1)
            assert s1 == s3
        p1 = validate_portfolio(chosen, v1.snapshot_at, BROAD60_432_V1, pool=v1.outcomes)
        p3 = validate_portfolio(chosen, a3.snapshot_at, A3_432_V1, pool=a3.outcomes)
        assert [[o.key for o in b] for b in p1.buckets] == [[o.key for o in b] for b in p3.buckets]
        assert pa.evaluate_with(p1, pa.market_probability) == pa.evaluate_with(
            p3, pa.market_probability
        )


# ================================================= historical v1 settlement regression
def _legs(entry):
    return [Leg(pos, fid, m, oc, b, Decimal(odds)) for pos, fid, m, oc, b, odds, _ in entry["legs"]]


def _settled(es) -> dict:
    return {
        "gross": str(es.gross), "complete": es.complete, "all_void": es.all_void,
        "recovered": es.recovered, "rank_eligible": es.rank_eligible,
        "win_vector": list(es.win_vector) if es.win_vector is not None else None,
        "accumulators": [
            [a.code, a.stake, a.status, None if a.effective_odds is None else str(a.effective_odds),
             None if a.payout is None else str(a.payout)]
            for a in es.accumulators
        ],
    }  # fmt: skip


def _evaluation(ev) -> dict:
    return {
        "p_recover": repr(ev.p_recover), "expected_gross": repr(ev.expected_gross),
        "max_gross": str(ev.max_gross),
        "buckets": [[b.code, str(b.combined_odds), repr(b.win_probability), str(b.payout)]
                    for b in ev.buckets],
        "nine_fold": [str(ev.nine_fold.combined_odds), str(ev.nine_fold.payout)],
        "states": [[list(s.wins), str(s.gross), repr(s.probability)] for s in ev.states],
    }  # fmt: skip


def test_regression_fixture_provenance():
    assert REG["config_version"] == "broad60-432-v1"
    assert REG["config_fingerprint"] == V1_FP
    assert len(REG["entries"]) == 12
    assert set(REG["verdict_vectors"]) >= {"all_won", "all_void", "pending", "voids_each_bucket"}


@pytest.mark.parametrize("idx", range(12))
def test_v1_settlement_reproduces_the_original_recorded_results(idx):
    """Frozen legs (v1 buckets) settled with the round's v1 configuration give exactly
    what the pre-A3 code recorded, for every verdict vector."""
    entry = REG["entries"][idx]
    legs = _legs(entry)
    for name, verdicts in REG["verdict_vectors"].items():
        v = {(x.fixture_id, x.market, x.outcome): verdicts[x.position] for x in legs}
        es = settle_entry(legs, v, get_config(REG["config_version"]))
        assert _settled(es) == entry["settlement"][name], (entry["id"], name)


@pytest.mark.parametrize("idx", range(12))
def test_v1_portfolio_and_confirmation_states_reproduce_from_the_pool(idx):
    """The same portfolio rebuilt from the committed pool under v1 gives the same frozen
    buckets and the same eight-state evaluation stored at confirmation."""
    entry = REG["entries"][idx]
    snap = snapshot_from_research_pool(POOL, "v1-regression", LEAGUES, BROAD60_432_V1)
    chosen = [snap.outcome((fid, m, oc)) for _, fid, m, oc, _, _, _ in entry["legs"]]
    port = validate_portfolio(chosen, snap.snapshot_at, snap.config, pool=snap.outcomes)
    rebuilt = [[code, o.fixture_id] for code, b in zip("ABC", port.buckets, strict=True) for o in b]
    assert rebuilt == [[b, fid] for _, fid, _, _, b, _, _ in entry["legs"]]
    market, model = evaluate_market_and_model(port)
    assert _evaluation(market.result) == entry["evaluation"]["market"]
    assert _evaluation(model.result) == entry["evaluation"]["model"]


def _valid_in_both(entry) -> bool:
    """Every frozen leg would fall in the same bucket under A3 (no reclassification)."""
    return all(A3_432_V1.classify(float(p)) == b for _, _, _, _, b, _, p in entry["legs"])


def test_portfolios_valid_in_both_settle_identically_under_a3_without_reclassification():
    both = [e for e in REG["entries"] if _valid_in_both(e)]
    assert len(both) == 12  # the pool has no outcome above 90%, so every v1 portfolio qualifies
    for entry in both:
        legs = _legs(entry)  # the frozen v1 buckets, never reassigned
        for name, verdicts in REG["verdict_vectors"].items():
            v = {(x.fixture_id, x.market, x.outcome): verdicts[x.position] for x in legs}
            assert _settled(settle_entry(legs, v, A3_432_V1)) == entry["settlement"][name]
        groups = [[(1.0, x.odds) for x in legs if x.bucket == b] for b in "ABC"]
        e1 = evaluate_groups(groups, BROAD60_432_V1.stakes, BROAD60_432_V1.nine_fold_credits)
        e3 = evaluate_groups(groups, A3_432_V1.stakes, A3_432_V1.nine_fold_credits)
        assert e1 == e3


def test_a_v1_portfolio_with_a_90_95_percent_leg_is_not_treated_as_valid_in_both():
    entry = json.loads(json.dumps(REG["entries"][0]))
    entry["legs"][0][6] = repr(0.92)  # a v1 Foundation leg A3 would exclude
    assert not _valid_in_both(entry)
    # settlement still uses the frozen v1 bucket and the round's v1 configuration
    legs = _legs(entry)
    v = {(x.fixture_id, x.market, x.outcome): "won" for x in legs}
    assert _settled(settle_entry(legs, v, BROAD60_432_V1)) == entry["settlement"]["all_won"]


def test_v1_scoring_reproduces_the_original_recorded_round():
    rr = RoundResult("v1-regression", "ch", RoundClassification.COMPETITIVE,
                     tuple(EntryResult(r["participant"], Decimal(r["gross"])) for r in REG["round"]),
                     "points-150-75-v2")  # fmt: skip
    scores = {s.participant_id: s for s in score_round(rr).scores}
    for r in REG["round"]:
        s = scores[r["participant"]]
        assert (s.rank, s.points, s.recovered, s.qualifying_top10) == (
            r["rank"], r["points"], r["recovered"], r["top10"],
        )  # fmt: skip
