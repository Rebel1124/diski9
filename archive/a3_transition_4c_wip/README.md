# ARCHIVE — unfinished Scenario A3 Checkpoint 4C transition work (NOT APPROVED)

**Status: unfinished, untested, not reviewed, NOT approved for use or deployment.**

This branch preserves work from the original Checkpoint 4C proposal (future-dated
`weekend` v2 → v3 activation, pre-T cancellation, startup build identity). The owner
superseded that proposal with **Option D**: Scenario A3 active from day one through
the immediate migration `app_0009` on `feature/phase-6c6-operations`. Nothing here is
part of the MVP.

Contents (branched from `dfd81a6`, the accepted Checkpoint 4B follow-up):

* `src/diski9/backend/services/schedule_transitions.py` - draft activation and
  cancellation service (no CLI, no tests; never run against a database);
* `src/diski9/buildinfo.py` - draft build-identity module (no tests; never wired in);
* `archive/a3_transition_4c_wip/experiment/` - the 4C PostgreSQL concurrency
  experiment harness (`lockexp.py`) and its JSON results (41 of 41 cases passed,
  Claude-reported). It ran only against a throwaway local cluster that no longer
  exists; the connection strings name that local, password-less (trust) cluster
  and contain no credentials. The raw server log is deliberately not committed;
  the deadlock excerpt is quoted in
  `docs/architecture/weekly_challenge_a3_implementation.md` on the feature branch.

Key findings worth keeping (see the implementation record): `lock_timeout` bounds
advisory-lock waits (SQLSTATE 55P03); advisory-only schedule writes are deadlock-free
against application and direct-SQL round creation; adding an explicit table lock
after the advisory lock deadlocks (SQLSTATE 40P01); a pre-commit clock check cannot
guarantee when COMMIT completes.
