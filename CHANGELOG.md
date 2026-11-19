# Changelog

Versions follow the repository's release tags. Diski 9 is an educational football
analytics product; it uses virtual credits only and involves no real money.

## v4.0.0 — Weekly Challenge functional prototype (2026-11-19)

The Diski 9 Weekly Challenge is introduced as an **accepted functional
prototype**. Portfolios persist only in the browser session; there are no user
accounts, permanent portfolios, server-side rounds, automated settlement or live
multiplayer leaderboards yet (Phase 6C onwards). Not deployed publicly.

* Weekly Challenge, My Challenge and Leaderboards pages, integrated with the
  Match Lab (one shared portfolio and Your View).
* Risk-structured portfolio engine `broad60-432-v1` (Foundation 60–95%,
  Balanced 40–60%, Challenger 20–40%; strict 4/3/2 picks; 40/30/20/10 credits),
  exact eight-state payouts with D-15 rounding and the 512-combination analysis.
* Championship scoring engine `points-150-75-v2` with the approved tie,
  participation, continuation and void rules.
* Frozen round snapshots, submission, replacement and withdrawal in the browser
  session, Your View session persistence with model-context stamps.
* Decision register and Phase 6C architecture documents.
* Unchanged: Goal Model 1.0 (k_s 12, k_t 96, m0 30), odds ingestion, consensus
  and freshness rules, Edge/EV, forecast snapshots and the football schema.

Details: [`docs/releases/v4.0.0.md`](docs/releases/v4.0.0.md).

## v3.2.0 — Eight-League Bookmaker Odds Coverage (2026-11-17)

Odds collection for all eight Goal Model 1.0 leagues, league-level failure
isolation, and the `odds-coverage` diagnostic command.

## v3.1.0 — Model vs Market Edge and Expected Value

Screener rankings by probability edge and expected value, the model vs market
table, and the Match Lab value check.

## v3.0.0 — Engine 3.0 and The Match Lab

Goal Model 1.0 estimated goals and probabilities for eight domestic leagues, The
Match Lab, pre-kickoff forecast snapshots and monthly monitoring.
