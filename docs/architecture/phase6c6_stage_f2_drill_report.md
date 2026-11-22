# Stage F2 local restore drill

> LOCAL RESTORE DRILL (Stage F2): disposable local databases and temporary football stores, mock providers. Establishes local backup creation, local verification and local restorability only; NOT an off-host copy and NOT an off-host restore.

Result: **PASSED** (2026-11-22T05:47:58+00:00 to 2026-11-22T05:48:38+00:00 UTC); pg_dump (PostgreSQL) 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1).

| Measure | Value |
|---|---|
| Source | 4 rounds, 2 championships (populated in 28.8 s) |
| Local football store backup (36.8 MB) | 0.218 s including verification |
| Drill store backup (CLI, incl. recording) | 0.21 s |
| Drill store restore (CLI, incl. verification and recording) | 0.26 s |
| pg_dump / pg_restore | 0.13 s / 0.55 s (0.32 MB custom format) |
| Tables compared (content hash and count) | 44; differing: none |
| Migration head before / after | app_0007 / app_0007 |
| competition verify before / after | development: consistent; beta: consistent / development: consistent; beta: consistent |
| Football store tables / checksum equal | True / True |
| Quantitative fingerprint before / after | `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4` / `88bcd717deca6c1c9b6bb7773126ac05ad109ca44291f9e700ac3467d047cec4` |
| Provider hold after the PostgreSQL restore | recorded True, active True, provider used False |

## Failure drills (local)

| Drill | Passed | Detail |
|---|---|---|
| store corruption then restore | True | corruption detected; verified backup restored into a new path |
| database unavailable | True | tick status unavailable |
| scheduler killed mid step | True | the interrupted results step was recorded as abandoned (Stage D rules) |
| interrupted refresh | True | covered in CI: test_backend_refresh::test_lock_lost_between_fetch_and_write_writes_nothing, ::test_a_failure_while_writing_rolls_the_league_back, ::test_interruption_during_a_pacing_wait_is_recovered |

Not established by this drill: an encrypted off-host copy, or a restore from an off-host copy (evidence levels 3 and 4).
