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

from diski9.api_football.markets import Market, Outcome
from diski9.challenge.structured import SelectionBlock, assess_outcome, selection_blocks
from diski9.odds.value import (
    MARKET_ORDER,
    OUTCOME_KEY,
    MarketValue,
    OutcomeValue,
    edge_pp,
    expected_value,
)
from diski9.screener import market_fit

from .. import lab
from ..data import MARKET_KEYS
from . import components as c
from .service import key_str

MARKET_OF_SCREENER = {"1X2": "1X2", "BTTS": "BTTS", "OU25": "OU25"}


def personal_probabilities(data, snap, lab_store) -> dict[tuple, float]:
    """{outcome key: Your View probability} for the round's matches you adjusted **in
    the frozen Weekly Challenge context** (approved at the 6C.3 checkpoint): the
    adjustments made on the snapshot's frozen baseline, never live-context ones.
    Matches without a frozen adjustment are left out (the baseline is used). A match
    frozen without independent estimated goals is adjusted from its frozen
    market-implied fit (Phase 8 CP2B.1)."""
    from diski9.app.lab_context import frozen_key

    out: dict[tuple, float] = {}
    if not lab_store or snap is None:
        return out
    stamps = lab_store.get(lab.CONTEXT_KEY) or {}
    for f in snap.fixtures:
        key = frozen_key(snap.round_id, f.fixture_id)
        stored = lab_store.get(key)
        if not stored:
            continue
        stamp = stamps.get(key) or ""
        if f.estimated_goals is not None:
            base = {
                "home": round(f.estimated_goals[0], 2),
                "away": round(f.estimated_goals[1], 2),
            }
            if stamp.split("|", 1)[-1] != f"{f.fixture_id}|{base['home']:.2f}|{base['away']:.2f}":
                continue  # made against another baseline: never applied
        else:
            # frozen market-implied starting point (CP2B.1): the whole stamp, including
            # the fit's input identity, must match; fitted only for adjusted matches
            mf = market_fit.frozen_fit(snap, f.fixture_id)
            if not mf.reliable or stamp != mf.stamp():
                continue
            base = {"home": round(mf.lambda_home, 2), "away": round(mf.lambda_away, 2)}
        state = lab.normalise_state(stored, base)
        if not lab.has_adjustment(state):
            continue
        b = lab.breakdown(base, state)
        probs = lab.adjusted_probabilities({s: b[s]["final"] for s in lab.SIDES})
        for o in snap.outcomes:
            if o.fixture_id == f.fixture_id:
                out[o.key] = float(probs[lab.OUTCOME_KEY[Outcome(str(o.outcome))]])
    return out


def adjusted_fixture_ids(personal: dict[tuple, float]) -> set:
    return {k[0] for k in personal}


# ------------------------------------------------------------- screener view
SNAPSHOT_MARKET = {"1X2": Market.MATCH_RESULT, "BTTS": Market.BTTS, "OU25": Market.OVER_UNDER_25}


def frozen_market_value(outs, market: str) -> MarketValue | None:
    """Model versus market for one fixture and market, from the **frozen round
    snapshot**: the snapshot's Diski 9 probabilities and its margin-adjusted market
    probabilities and reference odds. The edge and EV use the shared definitions in
    ``diski9.odds.value``; nothing is refreshed or substituted. None when the market
    is not in the snapshot or the fixture has no Diski 9 probability (Goal Model 1.1:
    model-absent fixtures can be eligible; no edge or EV is ever fabricated)."""
    m = SNAPSHOT_MARKET[market]
    by = {Outcome(str(o.outcome)): o for o in outs if str(o.market) == str(m)}
    if not by or any(o.model_probability is None for o in by.values()):
        return None
    rows = []
    for oc in MARKET_ORDER[m]:
        o = by.get(oc)
        if o is None:
            continue
        rows.append(
            OutcomeValue(
                key=OUTCOME_KEY[oc],
                outcome=oc,
                probability=float(o.model_probability),
                odds=o.reference_odds,
                market_probability=float(o.market_probability),
                edge=edge_pp(float(o.model_probability), float(o.market_probability)),
                ev=expected_value(float(o.model_probability), o.reference_odds),
            )
        )
    return MarketValue(m, tuple(rows), len(rows) == len(MARKET_ORDER[m]))


def frozen_probabilities(outs) -> dict:
    """{"model": {key: Goal Model p}, "market": {key: market p}} from snapshot outcomes,
    keyed like the Screener's model probabilities (home, draw, away, btts_yes, ...)."""
    return {
        "model": {OUTCOME_KEY[Outcome(str(o.outcome))]: float(o.model_probability)
                  for o in outs if o.model_probability is not None},
        "market": {OUTCOME_KEY[Outcome(str(o.outcome))]: float(o.market_probability)
                   for o in outs},
    }  # fmt: skip


def challenge_cells(service, state, market: str) -> dict | None:
    """Screener data for the Weekly Challenge view: exactly the fixtures of the
    active round snapshot, each with its frozen model-versus-market comparison for
    the chosen market (shown exactly like "All upcoming matches") and the outcome in
    the participant's portfolio, if any."""
    from . import pages

    state = pages.sync(service, state)
    mode, snap, avail, sels = pages.current(service, state)
    if snap is None or not avail.playable:
        return {"ids": set(), "values": {}, "picked": {}, "odds": {}, "frozen": {},
                "message": avail.message, "snapshot": None}  # fmt: skip
    chosen = set(sels)
    by_fx: dict = {}
    for o in snap.outcomes:
        by_fx.setdefault(o.fixture_id, []).append(o)
    values, picked, odds, frozen = {}, {}, {}, {}
    for fid, outs in by_fx.items():
        frozen[fid] = frozen_probabilities(outs)
        values[fid] = frozen_market_value(outs, market)
        in_market = [o for o in outs if str(o.market) == str(SNAPSHOT_MARKET[market])]
        order = {oc: i for i, oc in enumerate(MARKET_ORDER[SNAPSHOT_MARKET[market]])}
        in_market.sort(key=lambda o: order.get(Outcome(str(o.outcome)), 99))
        odds[fid] = (
            " · ".join(f"{o.reference_odds:.2f}" for o in in_market)
            if in_market
            else "Not in this market"
        )
        p = next((o for o in outs if key_str(o.key) in chosen), None)
        if p is not None:
            picked[fid] = c.outcome_text(p)
    return {
        "ids": set(by_fx),
        "values": values,
        "picked": picked,
        "odds": odds,
        "frozen": frozen,
        "message": None,
        "snapshot": snap,
    }


def challenge_cell(challenge: dict, market: str, fid: int, mode: str, threshold) -> dict:
    """The Market / Edge cell for one fixture in the Weekly Challenge view."""
    from ..data import fill_value_cell

    mv = challenge["values"].get(fid)
    snap = challenge["snapshot"]
    cell = {
        "mode": mode,
        "status": "fresh",
        "main": None,
        "sub": None,
        "cls": "na",
        "outcome": None,
        "title": (
            f"Frozen Weekly Challenge snapshot ({snap.snapshot_at:%d %b %Y, %H:%M} UTC): "
            "Diski 9 and margin-adjusted market probabilities, reference odds "
            f"{challenge['odds'].get(fid, '')}. Edge = Diski 9 minus market probability in "
            "percentage points (not expected value). Payouts use these frozen odds."
        ),
    }
    if mv is None:
        in_market = challenge["odds"].get(fid, "Not in this market") != "Not in this market"
        frozen_model = ((challenge.get("frozen") or {}).get(fid) or {}).get("model")
        if in_market and not frozen_model:  # frozen market, no Diski 9 probability
            fill_value_cell(cell, market, None, None, mode, False)
        else:
            cell["main"] = "Not in this market"
    else:
        pick = mv.best_ev(threshold) if mode == "ev" else mv.best_edge(threshold)
        fill_value_cell(cell, market, mv, pick, mode, True)
    if fid in challenge["picked"]:
        cell["picked"] = challenge["picked"][fid]
    return cell


FROZEN_MISSING = "Not in the round snapshot for this market"
FROZEN_NO_MODEL = "No Diski 9 estimate for this match (not enough current-season data)"


def frozen_universe(data, challenge: dict, market: str, leagues, start, end) -> list[dict]:
    """The Weekly Challenge match universe as Screener payloads built **from the round
    snapshot**: every snapshot fixture passing the league and date filters, with the
    snapshot's frozen Goal Model 1.0 probabilities and estimated goals in place of the
    live model cache. A market the snapshot does not hold for a fixture is marked
    unavailable (never filled in from live data)."""
    snap = challenge.get("snapshot")
    if snap is None:
        return []
    keys = [k for k, _ in MARKET_KEYS[market]]
    out = []
    for fx in snap.fixtures:
        if leagues is not None and fx.league_id not in leagues:
            continue
        day = fx.kickoff.astimezone(data.tz).date()
        if (start and day < start) or (end and day > end):
            continue
        model = (challenge["frozen"].get(fx.fixture_id) or {}).get("model", {})
        complete = all(k in model for k in keys)
        in_market = challenge["odds"].get(fx.fixture_id, "Not in this market") != (
            "Not in this market"
        )
        eg = fx.estimated_goals
        out.append(
            {
                "fixture": {
                    "id": fx.fixture_id,
                    "kickoff": fx.kickoff.isoformat(),
                    "competition_id": fx.league_id,
                    "competition": fx.league,
                    "home": fx.home,
                    "away": fx.away,
                },
                "goal_model": {
                    "available": complete,
                    "probabilities": dict(model) if complete else {},
                    "estimated_goals": {"home": eg[0], "away": eg[1]} if eg else {},
                    "message": FROZEN_NO_MODEL if in_market and not model else FROZEN_MISSING,
                    "frozen": True,
                },
            }
        )
    return out


def frozen_order(challenge: dict, results: list, market: str, direction: str, threshold) -> list:
    """Filter and rank the frozen universe with the same rules as the live Screener
    (Phase 8 CP3A-3): the Minimum Market Probability keeps a fixture when an outcome's
    **frozen** market probability meets it (inclusive; no live freshness test), then
    kickoff order, model-probability order (fixtures without that frozen probability
    last, never removed), or edge / EV over the qualifying outcomes."""
    from diski9.screener.rank import VALUE_DIRECTIONS, rank

    if threshold is not None:
        keys = [k for k, _ in MARKET_KEYS[market]]

        def meets(r: dict) -> bool:
            mkt = (challenge["frozen"].get(r["fixture"]["id"]) or {}).get("market", {})
            return any(k in mkt and mkt[k] >= threshold - 1e-12 for k in keys)

        results = [r for r in results if meets(r)]
    if direction in VALUE_DIRECTIONS:
        return challenge_rank(challenge, results, direction, threshold)
    return rank(results, direction)


def frozen_row(challenge: dict, market: str, row: dict, r: dict) -> dict:
    """Display values from the snapshot: estimated goals, Diski 9 and market
    probabilities and reference odds (the live odds strip is never shown here)."""
    fid = row["id"]
    gm = r["goal_model"]
    eg = gm.get("estimated_goals") or {}
    if gm["available"]:
        row["estimated_goals"] = f"{eg['home']:.2f} – {eg['away']:.2f}" if eg else "—"
    mkt = (challenge["frozen"].get(fid) or {}).get("market", {})
    keys = [k for k, _ in MARKET_KEYS[market]]
    row["market"] = (
        " · ".join(f"{mkt[k] * 100:.0f}%" for k in keys)
        if all(k in mkt for k in keys)
        else "Not in snapshot"
    )
    row["market_status"] = "fresh" if all(k in mkt for k in keys) else "unavailable"
    row["odds"] = challenge["odds"].get(fid, "Not in snapshot")
    row["odds_status"] = "fresh"
    row["frozen"] = True
    return row


def challenge_rank(challenge: dict, results: list, mode: str, threshold) -> list:
    """Edge / EV ranking of the Weekly Challenge view from the frozen snapshot values
    (the same ordering rule as the Screener's live ranking)."""
    from diski9.screener.rank import rank_by_value

    def value_of(r):
        mv = challenge["values"].get(r["fixture"]["id"])
        if mv is None:
            return False, None
        has = mv.complete if mode == "edge" else True
        pick = mv.best_ev(threshold) if mode == "ev" else mv.best_edge(threshold)
        if pick is None:
            return has, None
        return True, pick.ev if mode == "ev" else pick.edge

    return rank_by_value(results, value_of)


def data_context(service, data, universe: str | None) -> html.Div | None:
    """One compact line above the match list: the frozen Weekly Challenge snapshot
    (stored frozen time and deadline) or the latest available data (the model's
    stored update time). Times come from the data; nothing is called live."""
    from . import pages

    if universe == "challenge":
        snap = service.snapshot("live")
        if snap is None:
            return None
        rv = service.round_view()
        frozen = rv.snapshot_at if rv else snap.snapshot_at
        deadline = rv.deadline_at if rv else snap.deadline
        parts = [
            html.Span("Weekly Challenge snapshot", className="ctx-tag frozen"),
            html.Span(f"Frozen: {data.local(frozen)} SAST", className="muted"),
        ]
        if deadline is not None:
            parts.append(html.Span(f"Deadline: {data.local(deadline)} SAST", className="muted"))
        return html.Div(
            [html.Div(parts, className="ctx-line"),
             html.P(pages.FROZEN_NOTE, className="muted small ctx-note")],
            className="data-context small",
        )  # fmt: skip
    updated = data.snapshot().cache_calculated_at
    return html.Div(
        html.Div(
            [
                html.Span("Latest available data", className="ctx-tag latest"),
                html.Span(
                    f"Model updated: {data.local(updated)} SAST" if updated else "",
                    className="muted",
                ),
                html.Span("Bookmaker prices carry their own collection times.", className="muted"),
            ],
            className="ctx-line",
        ),
        className="data-context small",
    )


def progress_strip(service, state) -> html.Div | None:
    from . import pages

    state = pages.sync(service, state)
    mode, snap, avail, sels = pages.current(service, state)
    if snap is None or not avail.playable:
        return None
    cfg = snap.config
    chosen = service.outcomes_for(snap, sels)
    counts = {b.code: 0 for b in cfg.buckets}
    for o in chosen:
        code = cfg.classify(o.market_probability)
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
                for b in cfg.buckets
            ],
            html.Strong(
                f"{len(chosen)}/9",
                className="ch-strip-total",
                title="Predictions in your portfolio (all nine form The Diski 9)",
            ),
            dcc.Link("Open builder →", href="/", className="ch-lab-link"),
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
    if pages.locked(avail):  # Phase 8 CP3A-3: read-only after the deadline
        return html.Div(
            [
                html.Strong("Weekly Challenge: "),
                "entries are closed. You can analyse this match, but predictions can no "
                "longer be added or changed.",
            ],
            className="ch-labpanel muted small",
        )
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
    cfg = snap.config
    chosen = service.outcomes_for(snap, sels)
    blocks = selection_blocks(chosen, snap.outcomes, snap.snapshot_at, cfg)
    taken = next((o for o in chosen if o.fixture_id == fixture_id), None)
    # what would be possible if the current pick on this match were swapped out
    swap_blocks = (
        selection_blocks(
            [o for o in chosen if o is not taken], snap.outcomes, snap.snapshot_at, cfg
        )
        if taken is not None
        else {}
    )
    adjusted = fixture_id in adjusted_fixture_ids(personal)
    locked = pages.locked(avail)
    by_market: dict[str, list] = {}
    for o in outs:
        by_market.setdefault(str(o.market), []).append(o)
    groups = []
    for m in ("1X2", "BTTS", "OU25"):
        cards = []
        for o in by_market.get(m, []):
            a = assess_outcome(o, snap.snapshot_at, cfg)
            bucket = a.bucket if a.eligible else None
            block = blocks.get(o.key)
            can_replace = (
                block is SelectionBlock.FIXTURE_TAKEN
                and taken is not None
                and bucket is not None
                and swap_blocks.get(o.key) is None  # only replacements that validate
            )
            cards.append(
                c.outcome_button(
                    o,
                    bucket,
                    block,
                    locked,
                    personal.get(o.key),
                    id_type="labreplace" if can_replace else "labpick",
                    show_you=True,
                    replace_from=c.outcome_text(taken) if can_replace else None,
                    config=cfg,
                )
            )
        groups.append(
            html.Div(
                [
                    html.Div(c.MARKET_SHORT[m], className="ch-mkt"),
                    html.Div(
                        cards or [html.Span("Not in this round", className="muted small")],
                        className=f"ch-outs n{max(len(cards), 1)}",
                    ),
                ],
                className=f"ch-mkt-group m-{m.lower()}",
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
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        "Weekly Challenge"
                        + (" · demonstration round" if snap.is_demo else f" · {snap.round_id}"),
                        className="strong",
                    ),
                    html.Span(
                        ["Portfolio ", html.Strong(f"{len(chosen)}/9", className="ch-strip-total")],
                        className="muted small",
                    ),
                    dcc.Link("Open builder →", href="/", className="ch-lab-link"),
                ],
                className="ch-row-between",
            ),
            html.Div(
                [
                    html.Span([html.B("Mkt"), " market probability (sets the bucket)"]),
                    html.Span([html.B("D9"), " Diski 9 model"]),
                    html.Span([html.B("You"), " Your View"]),
                    html.Span("Odds are the frozen round reference odds"),
                ],
                className="ch-lab-legend small muted",
            ),
            notice,
            html.Div(groups, className="ch-mkts ch-lab-mkts"),
            html.P(
                [
                    c.icon("user", "ic-sm"),
                    " Your View uses your adjusted expected goals from the Match Lab above."
                    if adjusted
                    else " No adjustments for this match yet, so Your View equals Diski 9 "
                    "(shown as You = D9). Adjust expected goals above to form your own view.",
                    " It never changes buckets, odds or payouts.",
                ],
                className="muted small ch-lab-foot",
            ),
        ],
        className="ch-labpanel",
        id="lab-challenge-panel",
    )
