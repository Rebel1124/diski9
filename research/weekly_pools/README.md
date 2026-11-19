# Weekly research pools (D-29)

Research data only. Written by the scheduled collector on the
`research/weekly-pools` branch; never read by the app and never written to a
competition database. Proposal and rules:
[`docs/research/weekly_pool_collection_proposal.md`](../../docs/research/weekly_pool_collection_proposal.md).

## Layout

```
research/weekly_pools/
  runs.jsonl                      one line per run (capture or results): status, requests, errors
  report.json                     latest status report (diski9 research-pool report)
  <round>/                        ISO week of the round's Friday, e.g. 2026-W48
    manifest.json                 attempts, accepted attempt, deadline, cutoff, fingerprint, state
    capture-<UTC stamp>/
      fixtures.json.gz            raw fixture items in the round window (all eight leagues)
      odds.json.gz                raw odds pages (1X2, BTTS, O/U 2.5), retrieval times, rate limits
      model.json.gz               frozen Goal Model 1.0 payloads for the window fixtures
      requests.json               every API request of the run (endpoint, params, status)
      pool.json                   normalised pool built from the files above
    results.jsonl                 result observations, appended only when they change
    verdicts.json                 settle/v1 verdicts derived from results.jsonl (observed, not simulated)
```

## Commands

* `uv run diski9 research-pool capture`: Thursday 08:00 SAST.
* `uv run diski9 research-pool results`: daily 09:15 SAST; no requests when no pool is open.
* `uv run diski9 research-pool replay [--round 2026-W48]`: rebuild pools offline and
  compare fingerprints, content and raw hashes (exit code 1 on any mismatch).
* `uv run diski9 research-pool report`: qualifying and non-qualifying pools, coverage gaps,
  observed voids, missing weeks and recorded API use.

Times are UTC in every file. `observed_at` in `results.jsonl` is when the provider's
result was received, not when the match finished (the provider gives no completion
time). Missing odds, results or captures are recorded as missing, never filled in.
