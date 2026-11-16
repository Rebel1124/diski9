"""Research only: cross-league validation - UEFA stage rules."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from research_goal_crossleague import FROZEN, uefa_stage  # noqa: E402


@pytest.mark.parametrize(
    "label,expected",
    [
        ("1st Qualifying Round", ("qualifying", None)),
        ("Preliminary Round", ("qualifying", None)),
        ("Play-offs", ("qualifying", None)),
        ("Group C - 4", ("group", 4)),
        ("Group Stage - 2", ("group", 2)),
        ("League Stage - 7", ("league", 7)),
        ("Knockout Round Play-offs", ("knockout", None)),
        ("Round of 16", ("knockout", None)),
        ("Semi-finals", ("knockout", None)),
        ("Final", ("final", None)),
    ],
)
def test_uefa_stage(label, expected):
    assert uefa_stage(label) == expected


def test_parameters_are_frozen():
    assert (FROZEN.k_o, FROZEN.k_t, FROZEN.m0, FROZEN.window) == (12, 96, 30.0, "season")
