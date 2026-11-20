# Operator settlement commands (Phase 6C.4)

Server-side commands for result evidence, settlement, corrections, finalisation and
owner reopening of weekly-challenge rounds, plus development-only result
scenarios. They call the settlement services directly; no settlement rule lives in
the command layer. The policy is `docs/product/weekly_challenge_settle_v1.md` and
decisions S-01 to S-11 (`docs/product/weekly_challenge_decisions.md`).

## Who you are: interactive password check (S-07)

Every command below (except `dev-results scenarios`) asks for **your own Supabase
password** and verifies it with Supabase Auth before doing anything:

```
uv run diski9 settle status --round 2026-W48-weekend --operator you@example.com
Supabase password for you@example.com:          <- typed, not shown
Verified yourname (roles: operator).
```

* The password is read from a real terminal with hidden input. It is never a
  command-line argument, an environment variable or piped input; a command run
  without a terminal stops before asking (`needs an interactive terminal`).
* Holding database credentials is **not** authority. Your roles come from the
  competition database for the account linked to the verified Supabase identity;
  nothing from the command line or provider metadata grants a role.
* The Supabase session is signed out immediately; no token is stored, logged or
  audited.
* Every check is for **one command**. Sensitive changes (corrections, alert
  resolutions, invalidation, reopening) need the password to have been checked
  within 15 minutes of the write (T-14). If you wait longer at a confirmation
  prompt, the change is refused ("Your password check is too old ...") and nothing
  changes; run the command again.
* If Supabase Auth is not configured or unavailable, or the password is wrong, the
  command fails closed and changes nothing.
* `--operator` may be omitted; the command then asks for your email too.

| Capability | Who | Commands |
|---|---|---|
| `jobs.run` | operator, owner | `results import/show`, `settle preview/run/status/alerts`, `round finalise/finalise-check`, `dev-results set-mode/scenario` |
| `result.correct` (sensitive) | operator, owner | `results correct/withdraw-correction`, `settle resolve-alert` |
| `round.void` (sensitive) | operator, owner | `round invalidate` |
| `round.reopen` (sensitive) | **owner only** | `round reopen` |
| participant (their own password) | the test participant | `dev-results test-entry` |

The scheduled-job actor (future automation, 6C.6) can only import, settle and
finalise; corrections, invalidation and reopening always need a person.

The 6C.3 commands `round create / publish / lock / dev-open` keep their existing
`--by-email` behaviour (unchanged in 6C.4; see limitations in the implementation
record).

## Commands

Round codes are given with `--round` (or `--code`). Times are ISO 8601 with a time
zone, for example `2026-11-30T17:05:00+00:00`.

### Results
```
uv run diski9 results import --round CODE --operator EMAIL [--full] [--update-football-store]
uv run diski9 results show   --round CODE --operator EMAIL [--fixture ID] [--all]
uv run diski9 results correct --round CODE --operator EMAIL --fixture ID --status FT \
    --home 2 --away 1 [--completed-at T] [--actual-kickoff-at T] [--kickoff-at T] \
    --reason "why" --evidence "source" [--preview-only | --token TOKEN]
uv run diski9 results withdraw-correction --round CODE --operator EMAIL --observation N --reason "why"
```
* `import` (real rounds only, after lock) fetches the round's **relevant** fixtures
  (selected in locked entries) by ID, 20 per provider request. Fixtures more than 30
  minutes from kickoff are skipped; fixtures final (or cancelled) and stable for six
  hours are skipped unless `--full`. **Use `--full` before finalising** (see
  operational notes). It prints the provider requests used and the remaining daily
  quota. `--update-football-store` also hands the same items to the unchanged
  football-store upsert.
* `show` lists each relevant fixture's current rule, 90-minute score and verdicts;
  with `--fixture` every observation in receipt order (source, receipt time, status,
  score, provider schedule, verified times, corrections).
* `correct` previews the impact, then asks you to type the round code. A full-time
  correction needs `--completed-at` (verified completion time) when no provider
  final was recorded by the cutoff (S-03). `--preview-only` prints a confirmation
  token; `--token` applies that preview later, and is refused if the round changed
  in between ("changed since the preview").

### Settlement
```
uv run diski9 settle preview --round CODE --operator EMAIL [--as-of T]
uv run diski9 settle run     --round CODE --operator EMAIL [--as-of T]
uv run diski9 settle status  --round CODE --operator EMAIL [--as-of T]
uv run diski9 settle alerts  --round CODE --operator EMAIL [--all]
uv run diski9 settle resolve-alert --round CODE --operator EMAIL --alert N --reason "why"
```
* `preview` writes nothing. `run` is idempotent: with unchanged evidence it records
  only a run.
* `status` shows the version, designation, validity, pending predictions, open
  alerts, earliest finalisation and every reason finalisation would be refused.
* `resolve-alert`: a `late_notification` alert is *confirmed* (the cutoff-based void
  stands); informational alerts are *acknowledged*; other blocking alerts need a
  correction.
* `--as-of` is accepted **only for development rounds** outside production; real
  rounds refuse it (service and database trigger).

### Round invalidation, finalisation, reopening
```
uv run diski9 round invalidate     --code CODE --operator EMAIL --reason "why" [--preview-only | --token T]
uv run diski9 round finalise-check --code CODE --operator EMAIL [--as-of T]
uv run diski9 round finalise       --code CODE --operator EMAIL [--as-of T]
uv run diski9 round reopen         --code CODE --operator OWNER_EMAIL --reason "why" \
    --evidence "source" [--fixture ID --status FT --home 1 --away 1 ...] [--preview-only | --token T]
```
* Finalisation needs: status `settling`, nothing relevant pending, no open blocking
  alert, round validity evaluated, and the database clock at or after
  max(cutoff, last material change) + the round's frozen correction window (24 h).
  The printed earliest time is followed by the exact `--as-of` value for development
  rounds (rounded up to the whole second, so it is never a fraction too early).
  A final settlement run is made first; if it changes anything material, the
  window restarts and nothing is finalised.
* Reopening is owner-only, with reason, evidence, preview and confirmation; the
  final version stays in history and a new version is written.

## Development-only commands

All refuse production, real (non-development) rounds and synthetic input on real
rounds. Synthetic observations are stored only in PostgreSQL, scoped to the one
development round, and never touch the football data store.

```
uv run diski9 round dev-open --by-email EMAIL --deadline-minutes 6 --spacing-minutes 1 --code dev-accept-a
uv run diski9 dev-results test-entry --round CODE --participant EMAIL [--variant N]
uv run diski9 round lock --code CODE
uv run diski9 dev-results set-mode --round CODE --mode synthetic --operator EMAIL
uv run diski9 dev-results scenarios
uv run diski9 dev-results scenario --round CODE --name NAME --operator EMAIL [--timeline prompt|standard]
```
* `--spacing-minutes 1` (new in 6C.4) builds a compressed synthetic round: kickoffs
  a minute apart, starting 15 minutes after the deadline; `--fixtures N` sets how many
  synthetic fixtures (default 20).
* `test-entry` confirms a deterministic nine-prediction portfolio for a test
  participant **with that participant's own password**, through the ordinary draft
  and entry services; `--variant` gives different portfolios (variants 0, 1 and 2
  start from different thirds of the fixture list). Five accounts make a
  competitive round (at least five valid entries at lock); the minimum is not
  changed.
* `set-mode` is set once per development round (`synthetic` or `real`), audited;
  the modes never mix.
* `--timeline prompt` (default) places the evidence 1–4 minutes after the deadline,
  so it is visible at the database clock almost at once; `standard` spreads it
  between the deadline and the cutoff (then use `settle run --as-of`).

### Scenario catalogue (deterministic; built from the round's own locked selections)

Fourteen scenarios were built in Stage C; `entry-all-void` was added in Stage E
because an individual all-nine-void refund (D-33) can only be seen in a round that
stays valid, which needs other entries with played predictions.

| Scenario | What it records | Expected result (single-entry practice round) |
|---|---|---|
| `all-correct` | every selected fixture final with a score that wins every selection | all four accumulators won; gross = the confirmed maximum; recovered |
| `all-incorrect` | scores losing every selection | every accumulator lost; gross 0.00; not recovered |
| `one-bucket-wins` | Foundation (A) fixtures win, the rest lose | Foundation pays; Balanced, Challenger, The Diski 9 0.00 |
| `partial-void` | one Foundation fixture cancelled, the rest win | that prediction void at 1.00; accumulators still won at reduced odds |
| `bucket-all-void` | every Balanced fixture cancelled | Balanced returns its stake (all legs at 1.00) |
| `all-nine-void` | every selected fixture cancelled | with one entry: every prediction void, so the whole **round** is void (D-32b) and refunded; use `entry-all-void` to see an individual refund |
| `entry-all-void` (added in Stage E) | cancels the fixtures of the entry sharing fewest matches with the others; everything else wins | that entry: D-33 refund 100.00, net 0.00, not rank-eligible, not "recovered"; the round stays valid. Needs at least two entries on different matches: `dev-open --fixtures 40` and `test-entry` variants 0, 1, 2 |
| `round-invalid-majority` | cancels fixtures until at least half of all locked predictions are void | D-32b fail: round void, every entry refunded |
| `pending` | the later half of the fixtures stay in play | partial settlement: settled-so-far totals, pending accumulators show no payout |
| `cutoff-boundary` | one final exactly at the cutoff, one a second after | first settles, second void V1; needs `settle run --as-of` after the cutoff |
| `late-notification` | a final first received an hour after the cutoff | void V1 stands; blocking `late_notification` alert; needs `--as-of` after the cutoff |
| `provider-correction` | a final whose score the provider later changes so the verdict flips | first score kept; blocking conflict alert until an audited correction |
| `status-regression` | a final later reported as not started | held pending; blocking alert |
| `early-start-unverified` | provider first-half time before the deadline, no corroboration | pending; blocking `early_start_unverified` alert |
| `repeat` | every final delivered twice, identically | stored once (idempotent); same result as `all-correct` |

### Time limits in development

The database clock is authoritative for corrections, alert resolutions,
invalidation and reopening, also in development (no override). Only `settle run`,
`settle preview`, `settle status` and `round finalise` accept `--as-of`, and only
for development rounds outside production. Prepared rounds (short deadline,
compressed kickoffs, prompt timeline) make the whole lifecycle testable within
minutes: finalise with `--as-of` set to the printed earliest finalisation, then
reopen at the real clock. Scenarios whose evidence lies at the real cutoff
(`cutoff-boundary`, `late-notification`) can only be settled with `--as-of`, and
corrections of those fixtures wait for the real cutoff.

## Operational notes (real rounds)

* **Before finalising**, run `results import --full` so every relevant fixture is
  re-checked regardless of its six-hour stability, then `settle run` and
  `round finalise-check`. (Automating this belongs to the 6C.6 finalisation job.)
* A re-check **after** the cutoff never establishes completion before the cutoff:
  completion needs a final observation *received* by the cutoff (our receipt time),
  or an operator correction with a verified completion time and evidence. The
  provider's event times are kept as supporting evidence only.
* Near the cutoff, import promptly: a final first received after the cutoff makes
  the match void with a blocking `late_notification` alert, resolved by an audited
  correction (with verified completion time) or a confirmation of the void.
* After finalisation routine polling may stop. A material change arriving later is
  detected **only when new evidence is received** (a `post_final_change` alert);
  nothing monitors historical rounds automatically.
