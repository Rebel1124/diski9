# Fixture detail: two-card layout (final UI refinement before the Challenge)

*16 November 2026. UI only: no calculation, schema, cache or API change. The
engine is still 2.1.0.*

## Layout (all three markets)

**Fixture heading:** teams, competition, kickoff, market and form basis.

**Card 1 — Diski 9 Match Analysis** (*Historical statistics*)
* Match Result: both teams' Diski Form Scores, recent results and match
  counts.
* BTTS and Over/Under 2.5: both teams' records ("BTTS in 6 of 10 / No BTTS in
  4 of 10"), then the league baseline, separated by a divider.
* Sample-size warnings, as before.
* **How it's calculated** (collapsed): the explanation plus the full
  calculation table (points, goal difference, matches, final scores; or
  records, the league-baseline arithmetic and the recent-occurrence note).
* **Matches used** (collapsed): the basis, the current-season and competition
  scope, "only matches played before kickoff", a per-team match count with a
  Limited tag, and the match tables.

**Card 2 — Bookmaker Market Reference** (*Market-implied probabilities are
derived from bookmaker prices, not Diski 9 predictions.*)
* Visible: the Fresh / Stale / Unavailable badge with both timestamps, the
  market-implied probabilities (the Home/Draw/Away bar, or the equal-weight
  Yes/No or Over/Under pair) and the reference odds.
* **Odds details and other markets** (collapsed): raw implied probabilities,
  bookmaker groups and margin for this market (its market-implied values are
  not repeated), the other two markets' figures, and the "about these
  figures" notes.
* No odds (PSL): a short one-line card. Nothing is invented.

**Then, collapsed:** League positions, Head-to-head, Other markets.

## Removed

* The Form Difference headline (+1.86) and its "similar Form Scores" note were
  removed from the detail. Form Difference remains in the table, the rankings,
  the threshold, the mobile cards, the "Other markets" summary, and as a
  definition in "How it's calculated".
* The separate "How it's calculated", "Matches used" and "Reference odds and
  market-implied probabilities" outer cards. Their content now sits inside
  Cards 1 and 2.
* The duplicated odds strip inside the first card.

## Mobile

* Team cards stack.
* Accordion rows are at least 44 px tall.
* Timestamps wrap.
* Below 720 px the market pair and the Home/Draw/Away values use a small grid
  without separators, so nothing dangles or overflows. This was verified at
  0 px horizontal overflow on iPhone 13.

## Screenshots (`docs/screenshots/`)

* Desktop:
  * `ui_desktop_1x2_detail.png`
  * `ui_desktop_1x2_calculation_open.png`
  * `ui_desktop_btts_detail.png`
  * `ui_desktop_btts_matches_open.png`
  * `ui_desktop_psl_market_unavailable.png`
* Mobile:
  * `ui_mobile_1x2_detail.png`
  * `ui_mobile_1x2_calculation_open.png`
  * `ui_mobile_btts_detail.png`

Reproduce with `node scripts/screenshots_detail.js http://127.0.0.1:8050/`
while `uv run diski9 serve` is running.
