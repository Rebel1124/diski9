# Changelog

Versions follow the repository's release tags. Diski 9 is an educational football
analytics product; it uses virtual credits only and involves no real money.

## v4.2.0 — Settlement, voids and corrections (2026-11-20)

A **stable development milestone** (Phase 6C.4, Stages A–G), accepted by the
product owner. Not production-ready and not deployed publicly. Leaderboards,
championship standings, administration and automated scheduling are future work
(Phase 6C.5 onwards).

* Approved `settle/v1` amendments (S-01 to S-11): completion-based cutoff, V3
  branches, conflicting results, 24-hour correction window, owner-only reopening,
  development result modes.
* Migration `app_0006`: insert-only result evidence with provenance, verdict rules,
  settlement versions, alerts; downgrade refused once settlement data exists.
* By-ID provider results import (≤ 20 fixtures per request; relevant fixtures only).
* Settlement through the unchanged engine: voids at 1.00 (D-32), D-15 rounding,
  all-nine-void refunds (D-33), D-32b round invalidation, partial settlement.
* Audited corrections, alert resolutions, operator invalidation, finalisation and
  owner-only reopening with previews, confirmation tokens and settlement versions.
* Operator commands with interactive Supabase password verification;
  development-only result scenarios and test entries.
* My Challenge shows the participant's own results (status, credits, recovery,
  accumulators, predictions with scores and void reasons); withdrawal clears the
  withdrawn portfolio's predictions.
* Validation: 1,481 tests passed (release baseline); quantitative fingerprint
  byte-identical to v4.1.0; 3 live provider requests; browser journeys; owner's
  local acceptance.
* Unchanged: Goal Model 1.0, Portfolio Analysis, odds ingestion, consensus, the
  football schema and ingestion, the research collector and the competition
  mathematics.

Details: [`docs/releases/v4.2.0.md`](docs/releases/v4.2.0.md).

## v4.1.0 — Competition backend and persistence (2026-11-19)

A **stable development milestone** (Phases 6C.1–6C.3), accepted by the product
owner. Not production-ready and not deployed publicly. Settlement, live
leaderboards, championship scoring, administration and automated scheduling are
future work (Phase 6C.4 onwards).

* PostgreSQL application database with Alembic migrations (`app_0001`–`app_0005`)
  and database-level integrity and security protections.
* Supabase Auth accounts, public usernames and anonymity, server-side sessions and
  capability-based permissions.
* Persistent rounds with immutable published snapshots; Friday 08:00 SAST standard
  publication target; server-authoritative deadlines.
* Persistent drafts with stale-edit protection; separate live and frozen Your
  View; guest-work adoption.
* Confirmation, replacement, withdrawal and re-entry with immutable submission
  history; practice versus competitive classification; most recent locked entry.
* Match Lab educational guidance and layout refinements; updated My Challenge.
* Validation: 1,304 tests passed, 1 skipped (hosted Supabase, deferred);
  quantitative outputs unchanged; migration and restart checks; browser journeys.
* Unchanged: Goal Model 1.0, odds ingestion, consensus, forecast snapshots, the
  football schema and the competition mathematics.

Details: [`docs/releases/v4.1.0.md`](docs/releases/v4.1.0.md).

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
