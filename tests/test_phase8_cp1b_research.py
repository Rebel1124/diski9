"""Research only (Phase 8 CP1 supplementary): Goal Model simplification - the
strength/tempo = attack x defence equivalence, the unshrunk model's exact zeros
(no hidden safeguard) and the realised-probability bookkeeping."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import research_phase8_cp1b as rb  # noqa: E402
from test_phase8_cp1_research import _rows  # noqa: E402


def _r(team, hg=None, ag=None):
    r = _rows(team, cur_n=40, cur_hg=60, cur_ag=44)
    if hg is not None:
        r.hg, r.ag = np.array(hg, float), np.array(ag, float)
    return r


TEAMS = [
    [3, 2, 7, 3, 2, 4] + [2, 3, 3, 5, 4, 6],
    [1, 1, 5, 0, 3, 1] + [1, 1, 0, 2, 1, 4],
    [10, 9, 25, 9, 14, 11] + [9, 10, 8, 12, 10, 15],
]


@pytest.mark.parametrize("k", [6, 12, 24, 48, 96])
def test_equal_shrinkage_strength_tempo_equals_attack_defence(k):
    r = _r(TEAMS)
    ok = np.ones(len(TEAMS), bool)
    a = rb.model_a(r, ok, k, k)
    b = rb.model_b(r, k, ok)
    assert np.allclose(a[0], b[0], atol=1e-12, rtol=0)
    assert np.allclose(a[1], b[1], atol=1e-12, rtol=0)


def test_model_a_matches_cp1_reference():
    r = _r(TEAMS)
    ok = np.ones(len(TEAMS), bool)
    ref = rb.r8.predict(r, rb.GATE)
    lh, la, _ = rb.model_a(r, ok)
    assert np.allclose(lh, ref[1], atol=1e-12, rtol=0)
    assert np.allclose(la, ref[2], atol=1e-12, rtol=0)


def test_unshrunk_model_gives_exact_zero_without_safeguards():
    # home team conceded 0 in 2 matches -> away lambda exactly 0 under Model C
    team = [[1, 1, 8, 0, 0, 0] + [2, 0, 3, 1, 0, 0]]
    r = _r(team, hg=[2], ag=[1])
    ok = np.ones(1, bool)
    lh, la, fac = rb.model_b(r, 0.0, ok)
    assert la[0] == 0.0 and fac[1][0] == 0.0
    mk = rb.markets(lh, la)
    assert mk["away"][0] == pytest.approx(0.0, abs=1e-15)
    assert mk["btts_yes"][0] == 0.0
    rob = rb.robustness(mk, lh, la, r)
    assert rob["lambda_zero"] == 1
    assert rob["impossible_events"] == 1  # 2-1: BTTS Yes happened at probability 0
    # shrinkage keeps every lambda positive for the same record
    lh12, la12, _ = rb.model_b(r, 12.0, ok)
    assert la12[0] > 0


def test_realised_probabilities_pick_the_actual_outcomes():
    r = _r([TEAMS[0]], hg=[0], ag=[3])
    ok = np.ones(1, bool)
    lh, la, _ = rb.model_a(r, ok)
    mk = rb.markets(lh, la)
    rp = rb.realised_probs(mk, r)
    assert rp[0, 0] == pytest.approx(mk["away"][0])
    assert rp[0, 1] == pytest.approx(1 - mk["btts_yes"][0])
    assert rp[0, 2] == pytest.approx(mk["over"][0])
