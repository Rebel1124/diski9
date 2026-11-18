"""Phase 6B.2 playtest refinements: presentation, icons and formatting."""

from __future__ import annotations

from pathlib import Path

from diski9.app import icons
from diski9.app.challenge import callbacks as cb
from diski9.app.challenge import components as comp
from diski9.app.challenge import integration
from diski9.app.challenge.service import key_str, parse_key
from diski9.challenge.config import DEFAULT_CONFIG as CFG
from diski9.challenge.structured import SelectionBlock, assess_outcome, selection_blocks

from .test_challenge_ui import (  # noqa: F401
    _DataWithResults,
    _lab_state,
    jtext,
    snap,  # noqa: F401
    svc,
    valid_keys,
)

ROOT = Path(__file__).parents[1]
APP = ROOT / "src/diski9/app"


def _walk(node):
    yield node
    kids = getattr(node, "children", None)
    if isinstance(kids, list | tuple):
        for k in kids:
            yield from _walk(k)
    elif kids is not None and not isinstance(kids, str | int | float):
        yield from _walk(kids)


def lab_cards(panel):
    return [n for n in _walk(panel) if isinstance(getattr(n, "id", None), dict)
            and n.id.get("t") in ("labpick", "labreplace")]  # fmt: skip


# ------------------------------------------------------------- Match Lab cards
def test_match_lab_cards_offer_only_valid_replacements(svc, snap):  # noqa: F811
    data = _DataWithResults(snap)
    keys = valid_keys(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    for k in keys:
        s, _ = cb.apply_action(svc, s, "pick", k)
    fid = parse_key(keys[0])[0]
    cards = lab_cards(integration.lab_panel(svc, data, s, fid, {}, None))
    outs = {key_str(o.key): o for o in snap.outcomes if o.fixture_id == fid}
    assert {c.id["k"] for c in cards} == set(outs)  # all seven (or fewer) outcomes
    chosen = svc.outcomes_for(snap, keys)
    rest = [o for o in chosen if o.fixture_id != fid]
    swap = selection_blocks(rest, snap.outcomes, snap.snapshot_at, CFG)
    for card in cards:
        o = outs[card.id["k"]]
        a = assess_outcome(o, snap.snapshot_at, CFG)
        valid = a.eligible and swap.get(o.key) is None and card.id["k"] != keys[0]
        assert (card.id["t"] == "labreplace") == valid, card.id
        if card.id["t"] == "labreplace":
            assert not card.disabled and "st-replace" in card.className
            s2, flash = cb.apply_action(svc, s, cb.ACTION_OF["labreplace"], card.id["k"])
            assert flash["kind"] == "confirm" and s2["selections"] == s["selections"]
            s3, _ = cb.apply_action(svc, s, "replace", card.id["k"])
            assert card.id["k"] in s3["selections"] and keys[0] not in s3["selections"]
        elif card.id["k"] != keys[0]:
            assert card.disabled and card.title  # the reason is stated
    selected = next(c for c in cards if c.id["k"] == keys[0])
    assert "is-selected" in selected.className and not selected.disabled  # tap removes


def test_match_lab_cards_show_three_probabilities(svc, snap):  # noqa: F811
    data = _DataWithResults(snap)
    s, _ = cb.apply_action(svc, None, "mode", "demo")
    fid = snap.fixtures[0].fixture_id
    plain = jtext(integration.lab_panel(svc, data, s, fid, {}, None))
    assert "Mkt " in plain and "D9 " in plain and "You = D9" in plain
    store = {str(fid): _lab_state(0.6)}
    personal = integration.personal_probabilities(data, snap, store)
    adj = jtext(integration.lab_panel(svc, data, s, fid, store, None))
    assert "You = D9" not in adj
    for o in snap.outcomes:
        if o.fixture_id == fid:
            assert f"You {comp.pct(personal[o.key], 1)}" in adj


def test_builder_cards_show_your_view_only_for_adjusted_matches(snap):  # noqa: F811
    o = snap.outcomes[0]
    a = assess_outcome(o, snap.snapshot_at, CFG)
    bucket = a.bucket if a.eligible else None
    off = jtext(comp.outcome_button(o, bucket, None, False, None))
    on = jtext(comp.outcome_button(o, bucket, None, False, 0.512, show_you=True))
    assert "You " not in off and "You 51.2%" in on
    assert f"Mkt {comp.pct_in_band(o.market_probability, bucket)}" in on  # Mkt always shown


def test_disabled_outcomes_explain_with_icon_and_text(snap):  # noqa: F811
    o = snap.outcomes[0]
    text = jtext(comp.outcome_button(o, "A", SelectionBlock.BUCKET_FULL, False))
    assert "ic-ban" in text and "Bucket full" in text


# ------------------------------------------------------------- icons, no emoji
def test_icon_stylesheet_is_generated_from_the_icon_set():
    assert (APP / "assets/icons.css").read_text() == icons.css()
    assert set(icons.ICONS) >= {"trophy", "medal", "circle-check", "undo", "calculator"}
