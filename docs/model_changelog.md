# Goal Model changelog

Each model version has fixed parameters and an evidence report. Parameters are
never changed in place; a change is a new version, approved only under the annual
review rule in [`methodology.md`](methodology.md#8-maintenance-policy).

| Version | Engine | Released | Parameters | Evidence |
|---|---|---|---|---|
| **Goal Model 1.0** | 3.0.0 | November 2026 | `k_s` 12, `k_t` 96, `m0` 30 | [`goal_distribution_research.md`](goal_distribution_research.md), [`goal_model_crossleague_validation.md`](goal_model_crossleague_validation.md) |

## Goal Model 1.0

**Method:** a season-to-date independent Poisson model with strength/tempo
shrinkage and a league home/away prior.

**Calibration data:** EPL, Championship, PSL and PSL 1st Division.
* Tuning seasons: 2023/24–2025/26.
* Out-of-sample test: 3,237 matches.

**Independent validation:** La Liga, Ligue 1, Bundesliga and Serie A, 4,515
matches.

**Not supported:** the Champions League and Europa League. They were tested and
do not meet the bar.

**Next review:** after the 2026/27 domestic seasons end (planned July 2027). The
held-out season will be 2026/27.
* Candidate to examine: slightly lower strength smoothing (`k_s`), pooled across
  all eight leagues.
* Adopt it only if it meets the rule.
