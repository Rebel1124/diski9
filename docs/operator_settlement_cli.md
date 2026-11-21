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

Since Phase 6C.6 Stage B (S-07) the 6C.3 commands `round create / publish / lock /
dev-open` and the `account` administration commands authenticate the same way as
the settlement commands (`--operator EMAIL` and your password). The former
`--by-email` option was removed and only prints guidance; a manual `round lock`
always needs an operator (no system fallback in the CLI).

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

### Championships (Phase 6C.5 Stage C)

| Command | What it does |
|---|---|
| `diski9 competition status --operator EMAIL` | Read-only. Each stream (development, beta, official): the current championship and its progress, rounds whose championship assignment is pending, final rounds without official results, notes on legitimate states (rounds under review, pending assignments, D-30a historical corrections, restored rounds without capacity, championships reopened by an invalidation) and findings (`repairable:` / `needs investigation:`). Exit code 1 when a finding exists; notes alone are not faults |
| `diski9 competition verify --operator EMAIL` | Read-only integrity check (Stage D): published weekly results re-scored from the authoritative settlement; re-finalised rounds without official results; membership in the stream; names and start dates against the first associated round; roles against the authoritative outcomes; counter (at most ten), slots, status (including L-33 and D-30a), versions, champion counts and standings recomputed with the scoring engine; fixed boundaries; rounds that could be assigned but are not; development isolation. **Repairable** findings can be fixed by `competition repair`; **needs investigation** findings are material (ambiguous or non-authoritative data) and are never repaired automatically. Legitimate review, pending assignment and D-30a states are printed as notes |
| `diski9 competition backfill --operator EMAIL [--preview-only \| --token T]` | Publishes the official weekly results of rounds finalised before `app_0007`, in deadline order and one transaction per round, then assigns rounds to championships. The preview does the real work in a transaction that is rolled back. Execution needs the preview's token (or typing `backfill`) and refuses if anything changed. Rounds that cannot be classified reliably are listed as excluded and never assigned. Resumable and idempotent; audited |
| `diski9 competition repair --operator EMAIL [--stream S] [--reason TEXT] [--preview-only \| --token T]` | Stage D, audited. Rebuilds **derived** competition records from authoritative settlement and published weekly results through the normal services: publishes a re-finalised round's missing official results, applies outstanding role changes, assigns rounds that can be assigned and writes a new championship version (cause `repair`) only where the standings, status or counter differ. It never edits history, moves a membership, sets points or winners, or touches settlement or football results. The preview (work rolled back) lists findings, rounds to publish, each championship's before and after (status, rounds, version), standings and leader changes, boundary implications and anything that cannot be repaired. A stream with a material finding is refused. Applying needs `--reason`, the preview's token (or typing `repair`), a password entered within the last 15 minutes, and refuses if anything changed since the preview. One transaction per round, then per stream; resumable and idempotent |

**Membership verification limitation.** `competition verify` checks membership structurally:
* every member belongs to the stream;
* names and start dates match the first associated round;
* roles match authoritative outcomes;
* waiting rounds that could be assigned are reported.

It does not replay the full assignment history: membership depends on chronological lifecycle and correction events, so a replay from the current state alone would report false differences. To investigate a membership decision, use the recorded history:
* `championship_rounds.assigned_at`;
* the `championship_created` domain events;
* the insert-only `championship_versions` (cause, reason, actor, round list);
* the `championship.version` audit records.

Normal operation needs no command. Official weekly results and championship
processing happen inside `round finalise`, and rounds are assigned at publication
and lock. **Do not run a material backfill on a real database without the owner's
approval.**

## Development-only commands

All refuse production, real (non-development) rounds and synthetic input on real
rounds. Synthetic observations are stored only in PostgreSQL, scoped to the one
development round, and never touch the football data store.

```
uv run diski9 round dev-open --operator EMAIL --deadline-minutes 6 --spacing-minutes 1 --code dev-accept-a
uv run diski9 dev-results test-entry --round CODE --participant EMAIL [--variant N]
uv run diski9 round lock --code CODE --operator EMAIL
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

## Development championships (Phase 6C.5 Stage F1; development only)

These commands run whole championships locally through the real services. They are
refused in production and act on development rounds only. They never rank, score,
settle, assign or publish anything themselves: every step is the same service call
the operator commands make.

### Development participants
```
uv run diski9 dev-results participants --count 8 --operator EMAIL [--preview-only]
```
* **Accounts created:** `devp-0001` … `devp-0008`. Each is a development identity
  (provider `development`, never issued by Supabase Auth), so **nobody can sign in as
  them**. They have no e-mail address and no role.
* **Repeatable:** an existing participant is reused, never duplicated.
* **Audited:** each creation writes the audit event `dev_participants_created`.
* **Who may run it:** an operator only, after the password prompt. At most 500
  participants (ordinary testing; large-scale generation belongs to F3).
* **Use:** only by the development tools, and only for development rounds.

### Entries for every development participant
```
uv run diski9 dev-results test-entry --round CODE --all-dev-participants --operator EMAIL \
    [--count N] [--variants spread|groups|pairs] [--seed 2026]
```
* **How:** one confirmed entry per participant, through the ordinary draft and entry
  services. Deadline, eligibility, frozen odds, the 4/3/2 buckets and the four
  accumulators are all checked as usual.
* **Variants:** deterministic.
  - `spread`: every participant different;
  - `groups`: three shared portfolios, so weekly ties;
  - `pairs`: participants 2j and 2j+1 identical, so championship ties.
* **Repeatable:** participants who already have an entry are skipped.
* **Refused** for non-development rounds.

### `dev-championship`
```
uv run diski9 dev-championship presets
uv run diski9 dev-championship plan --preset NAME [--required 10] > plan.json
uv run diski9 dev-championship run (--preset NAME | --scenario-plan plan.json) \
    --operator EMAIL [--owner EMAIL] [--run-id ID] [--rounds K]
uv run diski9 dev-championship status (--preset NAME | --scenario-plan plan.json) --run-id ID
```
For each round, `run`:
1. opens a development round whose real deadline is `deadline_seconds` away (default
   60 s; 20 synthetic fixtures, kickoffs a minute apart);
2. creates the participants (first round only) and submits their entries;
3. **waits for the real deadline** on the database clock;
4. locks the round;
5. sets the synthetic result mode and records the round's 6C.4 scenario (evidence
   `evidence_seconds` after the deadline);
6. settles with `as_of` just after the cutoff;
7. finalises at the printed earliest finalisation, using the existing
   development-only time overrides;
8. checks that `competition verify` reports the development stream consistent.

Plan actions then reopen a finalised round, through the owner's audited service with
reason, evidence and preview token. The round is either corrected (valid to valid)
or invalidated by the operator, and then re-finalised.

**Duration:** about one minute per round (the 60 s deadline plus a few seconds of
work). The measured ten-round run took about **10 minutes**. Reopen actions also wait for the round's synthetic evidence
time (up to 4 minutes with the default plan).

**Progress:** every step is printed as it happens (round n/K, opened, entries,
waiting for the deadline with a countdown, locked, results, settled, final, verify),
followed by a closing championship summary.

**Presets** (each built for the stream's rounds per championship R; real streams use
10):

| Preset | Exercises |
|---|---|
| `ten-round-complete` | R valid competitive rounds with varied results (refunds included) |
| `with-practice` | round 2 has three entries (practice): it does not count, so R+1 rounds complete it |
| `with-invalidated` | round 2 fails D-32b (void): it does not count |
| `weekly-ties` | shared portfolios: shared weekly ranks with the same points |
| `championship-tie` | identical pairs: joint champions |
| `zero-points` | nobody recovers: completed, no champion |
| `rollover` | R+2 rounds: the next championship starts |
| `historical-invalidation-before-next` | after R rounds, round 2 is invalidated before the next championship starts (L-33: it reopens and round R+1 completes it) |
| `historical-invalidation-after-next` | after R+1 rounds, round 2 is invalidated (D-30a: the completed championship keeps its boundary with R-1 rounds) |
| `reopen-and-correct` | round 2 reopened and corrected (valid to valid): republished, standings recalculated |

**Example: a ten-round development championship from start to finish**
```
uv run diski9 dev-championship run --preset ten-round-complete --operator EMAIL --run-id demo1
# ... about 10 minutes of progress lines; Ctrl-C once to stop safely, then the same command resumes
uv run diski9 dev-championship status --preset ten-round-complete --run-id demo1
uv run diski9 competition verify --operator EMAIL
```
Then open Leaderboards and My Challenge (`DISKI9_SHOW_DEVELOPMENT_ROUNDS=1`), and
choose **Development**.

**A populated My Challenge Current "Your result" panel** (you, signed in,
competing with the development participants):
```
uv run diski9 round dev-open --operator EMAIL --deadline-minutes 1 --spacing-minutes 1 --fixtures 40 --code dev-mine
uv run diski9 dev-results test-entry --round dev-mine --participant YOUR_EMAIL --variant 1
uv run diski9 dev-results test-entry --round dev-mine --all-dev-participants --operator EMAIL
# after the deadline:
uv run diski9 round lock --code dev-mine
uv run diski9 dev-results set-mode --round dev-mine --mode synthetic --operator EMAIL
uv run diski9 dev-results scenario --round dev-mine --name all-correct --operator EMAIL
uv run diski9 settle run --round dev-mine --as-of CUTOFF_PLUS_1S --operator EMAIL   # provisional
uv run diski9 round finalise-check --code dev-mine --operator EMAIL                 # prints --as-of
uv run diski9 round finalise --code dev-mine --as-of T --operator EMAIL             # final
```
`tools/e2e_6c5/f1_current_steps.py` scripts exactly these steps.

**Scenario-plan file** (`dev-championship plan` prints one):
```json
{"name": "my-plan", "participants": 8, "seed": 2026, "deadline_seconds": 60,
 "evidence_seconds": 480, "fixtures": 20,
 "rounds": [{"scenario": "all-correct", "participants": null, "variants": "spread"}],
 "actions": [{"after": 2, "action": "correct", "round": 2}]}
```
* **Round scenarios:** only those that finalise without alert handling: `all-correct`,
  `all-incorrect`, `one-bucket-wins`, `partial-void`, `bucket-all-void`,
  `entry-all-void`, `round-invalid-majority` and `repeat`.
* **Participants per round:** `participants` can lower a round's count; below five,
  the round is a practice round.
* **Actions:** each is `correct` or `invalidate`, with at most one action per round.

**Stopping and resuming:**
* **The runner keeps no state of its own.** Round codes are `dev-<run-id>-<plan
  hash>-r01` …, and before every step the runner reads the round's real state
  (status, entries, result mode, evidence, settlement, publications) and does only
  the next missing step. Duplicate entries, settlements, memberships or points are
  therefore impossible on resume.
* **Ctrl-C once** stops at the next safe point, between two service calls. **Ctrl-C
  twice** aborts at once: the step in progress either committed or rolled back as a
  whole, because each step is one service transaction.
* **To resume,** run the same command with the same `--run-id`. The id is printed at
  the start; a new id is generated if you leave it out.
* **A different plan** under an existing run id is refused.
* **`--rounds K`** pauses after round K, so you can look at the app part way through.
* **`status`** shows each planned round's stage and the championships. It is read-only
  and needs no password.

**Passwords:**
* The operator password is asked once at the start, and the owner's when a plan
  reopens a round (`--owner`, default the operator).
* Before every write, the principal is re-evaluated at the database clock: the
  operator needs a password check within 12 hours, and reopening and invalidation need
  one within 15 minutes.
* When a check is too old, the runner asks for the password again at a terminal.
  Without a terminal it stops safely: run the same command again.
* No password is stored, logged or written to the plan.

**Troubleshooting:**

| Message | Meaning |
|---|---|
| `Development tooling is refused in production.` | The database settings say production |
| `Run 'X' already exists with a different scenario plan` | Use the original plan, or a new `--run-id` |
| `re-authentication required` | The password check is too old and no terminal is attached; run the same command again in a terminal |
| `verification failed: …` | `competition verify` found a problem; the run stops; inspect with `competition verify` |
| `… is reopened (under review)` | A previous run stopped in the middle of an action; run the same plan again to finish it |
| A practice round where you expected a competitive one | Fewer than five entries at lock (rule unchanged): create more participants |

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
