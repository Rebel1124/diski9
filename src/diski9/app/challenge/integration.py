"""Screener / Match Lab integration with the Weekly Challenge (Phase 6B.1).

* **Your View** - the participant's own probabilities from their Match Lab
  adjustments, computed with the Match Lab's own validated functions
  (``normalise_state`` -> ``user_estimates`` -> ``adjusted_probabilities``, i.e.
  Goal Model 1.0's ``markets`` for the adjusted expected goals). Matches the
  participant has not adjusted are absent, so they fall back to the unadjusted
  Diski 9 probability. Nothing here changes buckets, odds, eligibility, payouts,
  scoring or the stored model output.
* **Screener Weekly Challenge view** - the same frozen snapshot as the builder:
  fixture identities, eligible outcomes and frozen reference odds.
* **Match Lab panel** - the selected match's Challenge outcomes with the same
  add / remove / replace actions (and the same reducer and engine validation) as
  the builder.
"""

from __future__ import annotations

from dash import dcc, html

from diski9.api_football.markets import Outcome
from diski9.challenge.config import DEFAULT_CONFIG as CFG
from diski9.challenge.structured import SelectionBlock, assess_outcome, selection_blocks

from .. import lab
from . import components as c
from .service import key_str

MARKET_OF_SCREENER = {"1X2": "1X2", "BTTS": "BTTS", "OU25": "OU25"}


def personal_probabilities(data, snap, lab_store) -> dict[tuple, float]:
    """{outcome key: Your View probability} for adjusted matches in the snapshot."""
    out: dict[tuple, float] = {}
    if not lab_store or snap is None:
        return out
    results = data.snapshot().results.get("overall", {})
    wanted = {f.fixture_id for f in snap.fixtures}
    for fid_text, stored in lab_store.items():
        try:
            fid = int(fid_text)
        except (TypeError, ValueError):
            continue
        if fid not in wanted:
            continue
        r = results.get(fid)
        if not r or not (r.get("goal_model") or {}).get("available"):
            continue
        state = lab.normalise_state(stored, lab.baseline_rounded(r))
        probs = lab.adjusted_probabilities(lab.user_estimates(r, state))
        if not probs:
            continue
        for o in snap.outcomes:
            if o.fixture_id == fid:
                out[o.key] = float(probs[lab.OUTCOME_KEY[Outcome(str(o.outcome))]])
    return out


def adjusted_fixture_ids(personal: dict[tuple, float]) -> set:
    return {k[0] for k in personal}


# ------------------------------------------------------------- screener view
def challenge_cells(service, state, market: str) -> dict | None:
    """Screener data for the Weekly Challenge view: the frozen pool's fixture ids and,
    per fixture, the frozen odds of the chosen market and portfolio markers."""
    from . import pages

    state = pages.sync(service, state)
    mode, snap, avail, sels = pages.current(service, state)
    if snap is None or not avail.playable:
        return {"ids": set(), "cells": {}, "message": avail.message, "snapshot": None}
    chosen = {k for k in sels}
    cells = {}
    by_fx: dict = {}
    for o in snap.outcomes:
        by_fx.setdefault(o.fixture_id, []).append(o)
    for fid, outs in by_fx.items():
        mk = [o for o in outs if str(o.market) == MARKET_OF_SCREENER[market]]
        picked = next((o for o in outs if key_str(o.key) in chosen), None)
        odds = " · ".join(f"{o.reference_odds:.2f}" for o in mk) if mk else "Not in this market"
        cells[fid] = {
            "mode": "challenge",
            "status": "fresh",
            "main": odds,
            "sub": f"✓ {c.outcome_text(picked)}" if picked else "Challenge odds",
            "cls": "pos" if picked else "na",
            "title": "Frozen Weekly Challenge reference odds from the round snapshot (the same "
            "odds as the builder). Payouts use these odds.",
            "outcome": None,
            "odds_text": odds,
        }
    return {"ids": set(by_fx), "cells": cells, "message": None, "snapshot": snap}


def progress_strip(service, state) -> html.Div | None:
    from . import pages

    state = pages.sync(service, state)
    mode, snap, avail, sels = pages.current(service, state)
    if snap is None or not avail.playable:
        return None
    chosen = service.outcomes_for(snap, sels)
    counts = {b.code: 0 for b in CFG.buckets}
    for o in chosen:
        code = CFG.classify(o.market_probability)
        if code:
            counts[code] += 1
    return html.Div(
        [
            html.Span("Weekly Challenge" + (" (demo)" if snap.is_demo else ""), className="strong"),
            *[
                html.Span(
                    f"{b.name[0]} {counts[b.code]}/{b.selections}",
                    className=f"mini-{c.BUCKET_CLASS[b.code]}",
                )
                for b in CFG.buckets
            ],
            html.Strong(f"{len(chosen)}/9"),
            dcc.Link("Open builder →", href="/challenge", className="ch-lab-link"),
        ],
        className="ch-strip",
    )


# ------------------------------------------------------------- Match Lab panel
def lab_panel(service, data, state, fixture_id, lab_store, flash) -> html.Div | None:
    from . import pages

    if fixture_id is None:
        return None
    state = pages.sync(service, state)
    mode, snap, avail, sels = pages.current(service, state)
    if snap is None or not avail.playable:
        return html.Div(
            [
                html.Strong("Weekly Challenge: "),
                avail.message,
                " Open the Weekly Challenge to try the demonstration round.",
            ],
            className="ch-labpanel muted small",
        )
    outs = [o for o in snap.outcomes if o.fixture_id == fixture_id]
    if not outs:
        return html.Div(
            [
                html.Strong("Weekly Challenge: "),
                "this match isn't in this week's Challenge pool, "
                "so it can be analysed but not selected.",
            ],
            className="ch-labpanel muted small",
        )
    personal = personal_probabilities(data, snap, lab_store)
    chosen = service.outcomes_for(snap, sels)
    blocks = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, CFG)
    taken = next((o for o in chosen if o.fixture_id == fixture_id), None)
    # what would be possible if the current pick on this match were swapped out
    swap_blocks = (
        selection_blocks(
            [o for o in chosen if o is not taken], snap.outcomes, snap.snapshot_at, CFG
        )
        if taken is not None
        else {}
    )
    adjusted = fixture_id in adjusted_fixture_ids(personal)
    locked = pages.locked(avail)
    rows = []
    for o in outs:
        a = assess_outcome(o, snap.snapshot_at, CFG)
        bucket = a.bucket if a.eligible else None
        block = blocks.get(o.key)
        k = key_str(o.key)
        if block is SelectionBlock.SELECTED:
            action = html.Button(
                "✓ Added · Remove",
                id={"t": "labremove", "k": k},
                n_clicks=0,
                className="ch-btn small on",
                disabled=locked,
            )
        elif (
            block is SelectionBlock.FIXTURE_TAKEN
            and taken is not None
            and bucket
            and swap_blocks.get(o.key) is None
        ):
            action = html.Button(
                f"Replace {c.outcome_text(taken)}",
                id={"t": "labreplace", "k": k},
                n_clicks=0,
                className="ch-btn small ghost",
                disabled=locked,
            )
        elif block is None:
            action = html.Button(
                "Add to Weekly Challenge",
                id={"t": "labpick", "k": k},
                n_clicks=0,
                className="ch-btn small primary",
                disabled=locked,
            )
        else:
            action = html.Span(
                "⊘ " + (c.BLOCK_SHORT.get(block) or "Not eligible"),
                className="ch-tag off",
                title=c.BLOCK_HELP.get(block, ""),
            )
        yv = personal.get(o.key, o.model_probability)
        rows.append(
            html.Tr(
                [
                    html.Td(c.MARKET_SHORT[str(o.market)], className="muted"),
                    html.Td(c.OUTCOME_SHORT[str(o.outcome)]),
                    html.Td(
                        html.Span(
                            c.BUCKET_NAME[bucket], className=f"ch-tag b-{c.BUCKET_CLASS[bucket]}"
                        )
                        if bucket
                        else html.Span("Not eligible", className="ch-tag off")
                    ),
                    html.Td(c.pct_in_band(o.market_probability, bucket), className="num"),
                    html.Td(c.pct(o.model_probability, 1), className="num"),
                    html.Td(c.pct(yv, 1) + ("" if adjusted else "*"), className="num strong"),
                    html.Td(f"{o.reference_odds:.2f}", className="num"),
                    html.Td(action, className="num"),
                ]
            )
        )
    notice = None
    if flash and flash.get("replace"):
        notice = html.Div(
            [
                html.Span(flash["text"]),
                html.Button(
                    "Confirm replace",
                    id={"t": "confirmreplace", "k": flash["replace"]},
                    n_clicks=0,
                    className="ch-btn small primary",
                ),
                html.Button(
                    "Cancel",
                    id={"t": "cancelflash", "i": "lab"},
                    n_clicks=0,
                    className="ch-btn small ghost",
                ),
            ],
            className="ch-flash warn ch-confirm",
        )
    elif flash and flash.get("text"):
        notice = html.Div(
            flash["text"], className=f"ch-flash {flash.get('kind', 'info')}", role="status"
        )
    head = html.Tr(
        [
            html.Th("Market"),
            html.Th("Outcome"),
            html.Th("Bucket"),
            html.Th("Market", className="num"),
            html.Th("Diski 9", className="num"),
            html.Th("Your View", className="num"),
            html.Th("Odds", className="num"),
            html.Th(""),
        ]
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        "Weekly Challenge"
                        + (" · demonstration round" if snap.is_demo else f" · {snap.round_id}"),
                        className="strong",
                    ),
                    html.Span(f"Portfolio {len(chosen)}/9", className="muted small"),
                    dcc.Link("Open builder →", href="/challenge", className="ch-lab-link"),
                ],
                className="ch-row-between",
            ),
            notice,
            html.Div(
                html.Table([html.Thead(head), html.Tbody(rows)], className="ch-table lab"),
                className="ch-table-wrap",
            ),
            html.P(
                (
                    "Your View uses your adjusted expected goals from the Match Lab below."
                    if adjusted
                    else "* No adjustments for this match yet: Your View equals Diski "
                    "9. Adjust expected goals in the Match Lab below to set your own view."
                )
                + " Buckets and odds always come from the frozen market snapshot.",
                className="muted small",
            ),
        ],
        className="ch-labpanel",
        id="lab-challenge-panel",
    )
