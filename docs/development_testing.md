# Development testing and verification policy

Approved by the owner on 21 Nov 2026 (Phase 6C.6 Stage A decisions; CI efficiency
review). The aim is faster feedback and fewer redundant runs, **not** less assurance:
the exact final application-code candidate of every stage always gets an
independent full GitHub CI run before acceptance.

## The three levels

| | Level 1 — development | Level 2 — implementation checkpoint | Level 3 — formal acceptance |
|---|---|---|---|
| When | while implementing, before each local commit | end of a coherent change; before pushing application code | every stage acceptance; the final application-code candidate |
| Checks | `ruff check`, `ruff format --check`, the test files for the modules touched (table below) and the cross-cutting core | Level 1 plus the broader tests of the affected area, including PostgreSQL and Supabase Auth integration where relevant | the complete suite, migration up/down/up, lint, format, fingerprint, migration head — on GitHub CI against the **exact** candidate commit |
| Where | local | local (GitHub CI runs on every code push but is not waited for) | GitHub CI (mandatory); a local full run only if CI is unavailable |
| Typical time | 1–5 min | 2–20 min, by area | ~21 min on GitHub today |

**Escalate straight to Level 3** for changes to: migrations; authentication,
permissions or operator commands; scoring, settlement, finalisation or championship
processing; competition configuration; dependencies (`pyproject.toml`, `uv.lock`);
CI workflows; or whenever the fingerprint changes or an unexpected test fails.

Results from Levels 1 and 2 are working evidence only; they are never cited as
acceptance evidence.

## Focused test selection (Level 1)

Run the tests for what you changed plus the **cross-cutting core**:

```bash
uv run pytest -q tests/backend/test_backend_migrations.py tests/backend/test_backend_auth_unit.py tests/test_championship_scoring.py tests/test_ci_change_scope.py
```

| Changed area | Also run |
|---|---|
| `backend/auth/*`, `cli.py` `account`/`round`, `settlement_cli.py` | `tests/backend/test_backend_s07_remediation.py`, `test_backend_operator_cli.py`, `test_backend_accounts.py`, `test_backend_auth_web.py` |
| `backend/services/rounds.py`, `entries.py`, `drafts.py` | `tests/backend/test_backend_rounds*.py`, `test_backend_entries*.py`, `test_backend_drafts*.py` |
| `backend/services/settlement*.py`, `results.py`, `corrections.py` | `tests/backend/test_backend_settlement*.py`, `test_backend_results.py`, `test_backend_corrections.py`, `test_backend_scenarios.py` |
| `backend/services/competition*.py`, `championships.py`, `leaderboards.py`, `challenge_history.py` | `tests/backend/test_backend_champ*.py`, `test_backend_f3_*.py`, `test_backend_stage_e*.py`, `test_backend_weekly_results.py` |
| `challenge/*` (engine, configuration) | `tests/test_challenge_*.py`, `tests/test_championship_*.py` and the fingerprint (`uv run python tools/phase6c3_quant_regression.py 2>/dev/null \| sha256sum`) |
| `app/*` (Dash pages) | the matching `tests/test_*.py` UI and browser tests |
| `migrations_app/*` | Level 3 |
| `tools/ci/*`, `.github/*` | `tests/test_ci_change_scope.py`, then Level 3 |

When unsure which tests cover a change, run the whole affected directory
(`tests/backend` or `tests`) — that is still Level 2, not a reason to skip tests.

## Commit and push discipline

* Commit freely; push at meaningful points (a coherent change, the end of a working
  session, a checkpoint). Pushing remains the backup and recovery point.
* Do not wait for GitHub CI on intermediate pushes; wait only at Level 3.
* Do not run the full suite locally **and** on GitHub for the same unchanged
  candidate: GitHub CI is the independent Level 3 run.

## Documentation-only CI path

`.github/workflows/ci.yml` runs `tools/ci/change_scope.py` first. When **every**
file changed in the push (or the whole pull request since its merge base) is
documentation that no code or test reads, the job still runs lint, formatting and a
relative-link check of the changed Markdown, and skips the migration, Supabase Auth
and test-suite steps. The status check (`checks`) is unchanged and always reports.

* Documentation = Markdown outside `src/`, `tests/`, `tools/`, `migrations*/`,
  `.github/` and `scripts/`, plus `docs/screenshots/` and `docs/benchmarks/`.
* Always full: `docs/legal/` (terms pages served by the app), `docs/research/`
  (data read by the app and tests), `docs/methodology.md` (asserted by a test), any
  other file, mixed changes, new branches, manual runs and any detection failure.
* `tests/test_ci_change_scope.py` fails if code starts reading a `docs/` path that
  is not excluded, so the allowlist cannot silently drift.
