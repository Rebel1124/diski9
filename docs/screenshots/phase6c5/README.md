# Phase 6C.5 Stage E screenshots

Captured by `tools/e2e_6c5/shots.js` from the real app, the local Supabase Auth
harness and the seeded development database (`tools/e2e_6c5/seed.py`). That
database has 60 participants, two championships, a practice round, a void round,
a refunded entry, a corrected round, a D-30a invalidation, a reopened round and a
provisional round.
- Prefixes `desktop_` (1360 px), `tablet_` (768 px) and `mobile_` (390 px) give
  the width.
- Desktop captures are full page; tablet and mobile keep the top 2,400 px.

| File (desktop_…) | Shows |
|---|---|
| `guest_weekly` | Guest view: public table, "Sign in to see your position" |
| `weekly_provisional` | Default round (settling): returned so far, settled and pending counts, no points |
| `weekly_final` | Final competitive round: podium (capped), shared ranks, your highlighted row, points |
| `weekly_page2` | Page 2 of 2: "Showing 51–60 of 60", own position independent of the page |
| `weekly_corrected` | Republished after a correction: "Corrected · version 2" |
| `weekly_under_review` | Reopened round: last published results, no longer definitive |
| `weekly_practice` | Practice round: no points column, practice explanation |
| `weekly_void` | Void round: no table, refund explanation |
| `weekly_refunded` | A round in which another participant's entry was refunded (all nine void) |
| `championship_in_progress` | Current championship: 1 of 10 rounds, your standing |
| `championship_completed_d30a_review` | Historical championship: completed with 9 rounds after an invalidation (D-30a disclosure), joint champions, Under review and Corrected indicators |
| `my_challenge_current` | Current tab with the real championship summary |
| `history` | Statistics, the two cumulative charts and every entry type |
| `history_championship_scope` | The same for one championship |
| `history_detail_under_review` | Drill-down of a reopened round: last published official result next to the current settlement (6C.4 panel) |
