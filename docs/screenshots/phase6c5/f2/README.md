# Phase 6C.5 Stage F2 browser evidence

Captured by `tools/e2e_6c5/journeys.js` (the twelve §17.3 journeys) and
`tools/e2e_6c5/f2_current.js` (My Challenge Current result states) on 21 Nov 2026
against the real app, real PostgreSQL and the local Supabase Auth harness, using the
isolated development databases `diski9_f2_e2e` and `diski9_f2_e2e_nochamp`. All data
is synthetic development data (throw-away local accounts and generated participants).

* **Naming:** `<width>_j<NN>_<viewer>_<state>.png` for the journeys (width = desktop
  1360, tablet 768, mobile 390; viewer = `guest` or `you`, the signed-in participant),
  and `<width>_current_<state>.png` for the Current result panel.
* **Coverage:** desktop has every journey; tablet and mobile keep the key states, to
  avoid duplicate screenshots. Each page was also checked programmatically against
  the authoritative read services (implementation record §7.4); a screenshot is never
  the only evidence.
* **Captures** are cropped to the top 3200 (desktop) or 2400 (tablet, mobile) CSS
  pixels at device scale 2.
* **Development codes:** the Current-state rounds use long development codes
  (`dev-f2-current-…`); they are test data, not real round codes.

| Journey | Files |
|---|---|
| J1 provisional weekly | `*_j01_*` |
| J2 final weekly, personal highlight, page two | `*_j02_*` |
| J3 shared rank across the 50-row boundary | `*_j03_*` |
| J4 practice round | `*_j04_*` |
| J5 void round | `*_j05_*` |
| J6 championship in progress | `*_j06_*` |
| J7 joint champions (also under review, corrected after completion, D-30a) | `*_j07_*` |
| J8 no champion | `*_j08_*` |
| J9 weekly under review | `*_j09_*` |
| J10 weekly corrected | `*_j10_*` |
| J11 My Challenge History, filters, drill-down | `*_j11_*` |
| J12 guest view | `*_j12_*` |
| Current result: refund, void, negative, under review, corrected | `*_current_*` |
