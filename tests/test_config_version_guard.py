"""Version-aware configuration (Scenario A3, Checkpoint 1).

Rounds, snapshots, entries and settlements are bound to the configuration version
they were frozen under. Production code must resolve that version explicitly
(``RoundSnapshot.config``, ``rounds.round_config``, ``rounds.schedule_config``,
``get_config(version)``) and must never fall back to ``DEFAULT_CONFIG``. These tests:

* guard against new production uses of ``DEFAULT_CONFIG`` (static allowlist with the
  reason for every remaining use);
* guard against calls that silently rely on a function's default ``config`` argument;
* check that unknown versions fail safely, that an explicit configuration takes
  precedence everywhere it is available, and that v1 behaviour is unchanged.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import diski9.challenge.config as cfgmod
from diski9.app.challenge import components as c
from diski9.app.challenge import pages
from diski9.challenge.config import (
    BROAD60_432_V1,
    DEFAULT_CONFIG,
    BucketSpec,
    ConfigError,
    ProbabilityBand,
    get_config,
)
from diski9.challenge.roundsheet import RoundSnapshot, SnapshotKind, assess_round
from diski9.challenge.settle import Leg, settle_entry
from diski9.challenge.structured import (
    assess_outcome,
    make_outcome,
    round_opening_report,
    validate_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]

# Every remaining reference to DEFAULT_CONFIG in production code, with its reason.
# A new reference fails this test: resolve the round, snapshot, schedule or entry
# configuration instead, or (only for genuinely free-standing data) add it here with
# a reason for review.
ALLOWED_DEFAULT_CONFIG = {
    "src/diski9/challenge/config.py": (1, "definition: DEFAULT_CONFIG = BROAD60_432_V1"),
    "src/diski9/challenge/structured.py": (7, "library default parameters (callers guarded)"),
    "src/diski9/challenge/analysis.py": (2, "library default parameters (callers guarded)"),
    "src/diski9/challenge/settle.py": (1, "library default parameter (callers guarded)"),
    "src/diski9/challenge/education.py": (1, "free-standing illustration (no round)"),
    "src/diski9/challenge/roundsheet.py": (
        2,
        "default for NEW snapshots built without a round (callers guarded)",
    ),
    "src/diski9/backend/devdata.py": (
        2,
        "synthetic dev snapshots with no round; round-creating callers pass config",
    ),
    "src/diski9/app/challenge/service.py": (
        2,
        "prototype live snapshot and demonstration round: new snapshots, no round record",
    ),
    "src/diski9/app/challenge/pages.py": (
        1,
        "rules_config(): explanatory text when no round exists at all",
    ),
}

# Functions whose ``config`` parameter has a library default: production callers must
# pass a configuration explicitly (positional index of ``config``, or the keyword).
CONFIG_PARAM = {
    "classify_probability": 1,
    "assess_outcome": 2,
    "portfolio_feasible": 2,
    "selection_blocks": 3,
    "round_opening_report": 2,
    "portfolio_progress": 2,
    "validate_portfolio": 2,
    "bucket_stats": 2,
    "state_label": 1,
    "snapshot_from_research_pool": 3,
    "build_live_snapshot": 6,
    "settle_entry": 2,
    "illustrate": 1,
}
DEV_SNAPSHOT_FUNCS = ("dev_snapshot", "mirror_snapshot")  # keyword ``config``


def _py_files(*dirs):
    for d in dirs:
        yield from sorted(p for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_default_config_references_are_allowlisted():
    found: dict[str, int] = {}
    aliases = []
    for f in _py_files("src/diski9", "tools"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id == "DEFAULT_CONFIG":
                found[_rel(f)] = found.get(_rel(f), 0) + 1
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == "DEFAULT_CONFIG" and a.asname:
                        aliases.append(f"{_rel(f)}:{n.lineno} imports DEFAULT_CONFIG as {a.asname}")
    assert not aliases, aliases  # an alias would hide uses from this guard
    expected = {k: v[0] for k, v in ALLOWED_DEFAULT_CONFIG.items()}
    assert found == expected, (
        "DEFAULT_CONFIG references changed. Resolve the round/snapshot/schedule/entry "
        f"configuration instead of the default.\nfound: {found}\nallowed: {expected}"
    )


def test_production_calls_pass_the_configuration_explicitly():
    problems = []
    for f in _py_files("src/diski9", "tools"):
        if _rel(f) == "src/diski9/challenge/portfolio.py":
            continue  # Phase 6A engine: an unrelated validate_selections, no config
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            kw = {k.arg for k in n.keywords}
            if name in CONFIG_PARAM and len(n.args) <= CONFIG_PARAM[name] and "config" not in kw:
                problems.append(f"{_rel(f)}:{n.lineno} {name}(...) without a configuration")
            if (
                name in DEV_SNAPSHOT_FUNCS
                and _rel(f) != "src/diski9/backend/devdata.py"
                and "config" not in kw
            ):
                problems.append(f"{_rel(f)}:{n.lineno} {name}(...) without config=")
            if name == "validate_selections" and len(n.args) < 3 and "config" not in kw:
                problems.append(f"{_rel(f)}:{n.lineno} validate_selections without config")
    assert not problems, "\n".join(problems)


def test_bucket_names_are_structural_in_every_registered_configuration():
    """Presentation uses the static BUCKET_NAME; a future version renaming a bucket
    must update the presentation layer deliberately."""
    for version, config in cfgmod._REGISTRY.items():
        assert config.bucket_codes == ("A", "B", "C"), version
        for b in config.buckets:
            assert c.BUCKET_NAME[b.code] == b.name, version
        assert c.BUCKET_NAME["NINE"] == config.nine_fold_name, version


# ------------------------------------------------------------------ v1 unchanged
def test_v1_remains_the_default_with_a3_registered_alongside():
    """A3 Checkpoint 2: a3-432-v1 is registered but not the default."""
    assert DEFAULT_CONFIG is BROAD60_432_V1
    assert set(cfgmod._REGISTRY) == {"broad60-432-v1", "a3-432-v1"}


def test_v1_fingerprint_is_pinned():
    assert BROAD60_432_V1.fingerprint() == (
        "b8cb7c0372e6aac15b1638e100be35955dacfd3f11c1f3654ad52c9263cbba94"
    )


def test_v1_labels_and_messages_are_unchanged():
    assert [c.band_text(b.band) for b in BROAD60_432_V1.buckets] == [
        "60%–95%",
        "40% to under 60%",
        "20% to under 40%",
    ]
    assert c.eligible_range_text(BROAD60_432_V1) == "20%–95%"


# ------------------------------------------------------------- fail safely
def _snapshot(version: str, probs=(0.70, 0.17, 0.13), fixtures=18, leagues=6) -> RoundSnapshot:
    at = datetime(2026, 11, 20, 8, tzinfo=UTC)
    outs = []
    for i in range(fixtures):
        fid = 1000 + i
        for oc, p in zip(("HOME", "DRAW", "AWAY"), probs, strict=True):
            outs.append(
                make_outcome(
                    fid,
                    "1X2",
                    oc,
                    p,
                    Decimal(str(round(0.95 / p, 2))),
                    p,
                    5,
                    at - timedelta(minutes=5),
                    10 + i % leagues,
                )  # fmt: skip
            )
    return RoundSnapshot(
        "test-round", SnapshotKind.LIVE, at, version,
        (at, at + timedelta(days=4)), (), tuple(outs),
    )  # fmt: skip


def test_unknown_snapshot_version_fails_instead_of_falling_back():
    snap = _snapshot("not-a-registered-version")
    with pytest.raises(ConfigError):
        _ = snap.config
    with pytest.raises(ConfigError):
        snap.opening_report()
    with pytest.raises(ConfigError):
        assess_round(snap, snap.snapshot_at)


def test_unknown_or_missing_entry_version_fails():
    with pytest.raises(ConfigError):
        pages.entry_config({"config": "not-a-registered-version"})
    with pytest.raises(KeyError):
        pages.entry_config({})


# --------------------------------------------- explicit configuration wins
VARIANT = replace(
    BROAD60_432_V1,
    version="test-variant-only",
    buckets=(
        BucketSpec("A", "Foundation", ProbabilityBand(0.60, 0.90, True, True), 4, 40),
        BucketSpec("B", "Balanced", ProbabilityBand(0.40, 0.60, True, False), 3, 30),
        BucketSpec("C", "Challenger", ProbabilityBand(0.10, 0.40, True, False), 2, 20),
    ),
)


@pytest.fixture
def variant_registered(monkeypatch):
    """A TEST-ONLY configuration registered in an isolated copy of the registry (never
    the production registry). Not A3: only used to prove version precedence."""
    monkeypatch.setattr(cfgmod, "_REGISTRY", dict(cfgmod._REGISTRY))
    cfgmod.register_config(VARIANT)
    return VARIANT


def test_snapshot_configuration_takes_precedence(variant_registered):
    v1 = _snapshot("broad60-432-v1", probs=(0.70, 0.17, 0.13))
    var = _snapshot(variant_registered.version, probs=(0.70, 0.17, 0.13))
    o_v1 = next(o for o in v1.outcomes if str(o.outcome) == "DRAW")
    o_var = next(o for o in var.outcomes if str(o.outcome) == "DRAW")
    # a 17% outcome: ineligible under v1 (20-40%), Challenger under the variant (10-40%)
    assert not assess_outcome(o_v1, v1.snapshot_at, v1.config).eligible
    assert assess_outcome(o_var, var.snapshot_at, var.config).bucket == "C"
    assert v1.opening_report().eligible_outcomes_by_bucket["C"] == 0
    assert var.opening_report().eligible_outcomes_by_bucket["C"] == 2 * 18  # draws and away wins
    # labels and messages follow the snapshot
    assert c.eligible_range_text(var.config) == "10%–90%"
    assert c.band_text(var.config.bucket("C").band) == "10% to under 40%"
    assert pages.rules_config(var) is variant_registered
    assert pages.rules_config(v1) is BROAD60_432_V1
    assert pages.rules_config(None) is DEFAULT_CONFIG  # no round at all
    assert pages.entry_config({"config": variant_registered.version}) is variant_registered


def test_outcome_titles_follow_the_round_configuration(variant_registered):
    snap = _snapshot("broad60-432-v1")
    o = snap.outcomes[0]
    _, _, title_v1 = c.outcome_state(o, None, None, False, config=BROAD60_432_V1)
    _, _, title_var = c.outcome_state(o, None, None, False, config=variant_registered)
    assert "20%–95%" in title_v1 and "10%–90%" in title_var


def test_portfolio_validation_uses_the_snapshot_configuration(variant_registered):
    """A portfolio with two 17% Challenger picks is valid only under the variant."""
    var = _snapshot(variant_registered.version, probs=(0.70, 0.17, 0.13))
    homes = [o for o in var.outcomes if str(o.outcome) == "HOME"]
    draws = [o for o in var.outcomes if str(o.outcome) == "DRAW"]
    # 4 Foundation (70% home), 3 Balanced needs 40-60%: rebuild three fixtures
    bal = [replace(o, market_probability=0.5) for o in homes[4:7]]
    pool = tuple(homes[:4] + bal + draws[7:9])
    port = validate_portfolio(list(pool), var.snapshot_at, var.config, pool=pool)
    assert [len(b) for b in port.buckets] == [4, 3, 2]
    with pytest.raises(ValueError):
        validate_portfolio(list(pool), var.snapshot_at, BROAD60_432_V1, pool=pool)
    report = round_opening_report(var.outcomes, var.snapshot_at, var.config)
    assert report.eligible_outcomes_by_bucket["C"] > 0


def test_settlement_uses_the_given_configuration_and_records_its_target():
    legs = [
        Leg(position=i, fixture_id=100 + i, market="1X2", outcome="HOME",
            bucket=b, odds=Decimal("2.00"))
        for i, b in enumerate("AAAABBBCC")
    ]  # fmt: skip
    verdicts = {(100 + i, "1X2", "HOME"): "won" for i in range(9)}
    es = settle_entry(legs, verdicts, get_config("broad60-432-v1"))
    assert es.recovery_target == Decimal("100.00") and es.recovered is True
