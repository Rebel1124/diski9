# Diski 9 Weekly Challenge — UX Specification (Phase 5C)

Status: **design for review**. Builds on the existing Diski 9 dark theme, type
and components (Screener cards, Match Lab sections, role tags, outcome colours
Home blue / Draw teal / Away amber).

## 1. Principles

1. **One central idea per screen.** Pick nine → see how grouping changes your
   chances → confirm.
2. **The chart is the lesson.** Everything else supports it: the recommendation,
   the details and the caveats.
3. **Plain words first, numbers on demand.** "Chance of getting your 100 credits
   back" before "P(R ≥ 100)". Technical terms live in expandable help.
4. **Never imply certainty.** Every probability is "modelled". Every price is a
   "reference price".
5. **Inspection is safe.** Exploring never submits. Submitting is explicit,
   reviewed and confirmed.

## 2. Navigation and screens (minimum set: 3 routes)

A slim navigation row is added to the existing header:

```
Diski 9  Screener | Weekly Challenge | Leaderboards            Times in SAST · Sign in / Thandi ▾
```

| Route | Screen | Contains |
|---|---|---|
| `/` | Screener and Match Lab | Unchanged |
| `/challenge` | **Weekly Challenge** (a three-step builder on one page) | Step 1 Pick nine · Step 2 Explore groupings · Step 3 Review and submit → receipt |
| `/challenge/me` | **My Challenge** | Current entry and status, live settlement, past rounds, season summary |
| `/leaderboards` | **Leaderboards** | This week · Season tabs |

The builder is one route with a stepper rather than three pages. That keeps the
draft in a single browser store and makes going back and forth instant. Portfolio
review and submission confirmation are steps of the builder, not separate pages.

## 3. Step 1: Pick nine

### Desktop wireframe

```
┌ Weekly Challenge · Weekend 20–23 Nov ─────────────────────────────────────────────────────┐
│ Deadline Fri 20 Nov, 20:45 SAST · 2 d 4 h left        [How it works ▸]                     │
│ ① Pick nine ── ② Explore groupings ── ③ Review & submit                                    │
├───────────────────────────────────────────────────────────────┬────────────────────────────┤
│ League [All 6 ▾]  Day [All ▾]  Market [All ▾]  🔍 team         │ YOUR NINE           6 / 9  │
│ 54 fixtures available · 14 more this weekend aren't [why?]     │ ┌────────────────────────┐ │
│                                                               │ │1 Man City v Fulham     │ │
│ Sat 21 Nov · EPL                                              │ │  Home · 55.2% · 1.41 ✕ │ │
│ Man City v Fulham                       14:00                 │ │2 Millwall v QPR        │ │
│ Result   [Home 55% · 1.41✓] [Draw 23% · 5.20] [Away 22% · 7.60] │  BTTS Yes · 59% · 1.57 │ │
│ BTTS     [Yes 52% · 1.75]   [No 48% · 2.05]                   │ │ …                      │ │
│ Goals    [Over 58% · 1.53]  [Under 42% · 2.45]                │ │7 – empty –             │ │
│                                                               │ └────────────────────────┘ │
│ Sat 21 Nov · Serie A                                          │ One pick per match. Tap    │
│ Como v Cagliari                         15:00                 │ another outcome to replace.│
│ …                                                             │ [Explore groupings ▸] (9/9)│
└───────────────────────────────────────────────────────────────┴────────────────────────────┘
```

Fixture names and the Man City Home price are from the 17 Nov research
snapshot. The other chip percentages and prices are illustrative.

**Behaviour:**
* **Only fixtures with at least one Challenge-eligible outcome are listed.** Below
  the filters: "14 more this weekend aren't available" with a disclosure listing
  them and the reason ("no qualifying reference odds"; for example, PSL fixtures).
  This keeps the list short and avoids disabled clutter.
* **Outcome chips** show "label · model % · reference odds". Ineligible outcomes
  within an eligible fixture appear disabled with "odds not available".
* **Tapping a chip** adds the pick. Tapping a different chip on the same fixture
  replaces it (toast: "Replaced Home with Over 2.5 for Man City v Fulham"). Tapping
  the selected chip removes it.
* **At 9 picks** the remaining chips are disabled with the hint "Remove a pick to
  change"; the Explore button activates.
* The fixture row links to its Match Lab ("Analyse ▸", which opens the Screener
  detail in the same tab, with the draft kept).
* **Market probability** appears in the chip tooltip ("Market 67%").

### Mobile (390 px)

* Single column. The fixture list is the main view.
* The slip becomes a bottom sheet bar: "6 / 9 picks · Explore ▸". Tapping it
  expands the list.
* Chips wrap to two per row.

## 4. Step 2: Explore groupings (the central screen)

### Desktop wireframe

```
┌ ② Explore groupings ────────────────────────────────────────────────────────────────────────┐
│ Your nine picks can be grouped into 280 different sets of three buckets.                     │
│ Each grouping changes your chance of getting your 100 credits back and the average return    │
│ the model expects.  [What does "efficient" mean? ▸]                                          │
├──────────────────────────────────────────────────────┬───────────────────────────────────────┤
│ Expected return (credits)                             │ SELECTED  ★ Recommended  #024|158|367 │
│ 57 ┤                    ●●                            │ Chance of getting 100 back   37.1%    │
│ 55 ┤        ·  ·  ·· ●     ★                          │ Expected return       52.5 credits    │
│ 53 ┤   · ·· ···· ··· ·· ●                             │ Best case (all win)  1,163 credits    │
│ 51 ┤  ·· ··· ·· ·   ·                                 │ ┌ Bucket A · 30 cr ── wins 14.1% ───┐ │
│    └──────────────────────────────────────────▶       │ │ Man City Home · Como Home · …    │ │
│     10%     20%      30%     40%                      │ │ odds 3.89 → pays 116.6  ✓ alone  │ │
│     Chance of getting your 100 credits back           │ └───────────────────────────────────┘ │
│ ● efficient (selectable)  · other groupings  ★ recommended  │ Bucket B … Bucket C … Nine-fold … │
│ 14 efficient of 280 · expected return varies by 5.5 credits │ [Review entry ▸]                  │
│ ▸ List efficient groupings (14)                               │                                │
└──────────────────────────────────────────────────────┴───────────────────────────────────────┘
```

(The coordinates in the wireframe are illustrative. The R1 slate from Phase 5B at
100 credits has 14 efficient groupings, and a recommended grouping with 37.1%
recovery and 52.5 expected credits.)

### 4.1 Chart interaction specification (Plotly via `dcc.Graph`)

| Element | Specification |
|---|---|
| Traces | (1) Dominated: grey, 6 px, opacity 0.45. (2) Efficient: teal, 9 px. (3) Recommended: star, 16 px, outlined. (4) Selected: ring overlay. |
| Axes | X = chance of recovering 100 credits, in % (range fitted to the data, padded 5%, ticks as %). Y = expected return in credits (fitted range, padded 10%, labelled ticks). The caption states the actual Y spread ("varies by 5.5 credits"), so a narrow range is never exaggerated silently. |
| Reference line | A dashed horizontal line at 100 credits ("your 100 credits"), only if it falls inside the plotted range or within 20% of it. |
| Hover (all points) | "Grouping 024\|158\|367 · Chance of 100 back 37.1% · Expected 52.5 cr". Dominated points add "Another grouping is at least as good on both counts". |
| Click / tap | An efficient point selects that grouping (updates the panel). A dominated point only shows the hover message; selection is unchanged. |
| Ties (identical coordinates) | One marker labelled "×3". Selecting it chooses the lowest ID and shows "3 groupings share this point" with a small chooser. No jitter: positions are never faked. |
| Frontier line | None drawn. The efficient points speak for themselves; there is no smoothing or interpolation. |
| Defaults | The recommended grouping is pre-selected on entry. Zoom is disabled; the mode bar is hidden; the chart is responsive. |
| Accessibility | "List efficient groupings" is a keyboard-operable table (rank by recovery, recovery %, expected credits, "Recommended" badge, Select button). It is the same selection state as the chart. The chart has an `aria-label` summary. |
| Degenerate cases | 1 efficient grouping: "Only one grouping is efficient for these picks" (selected). All 280 tie: "All groupings are equivalent for these picks" (one marker ×280). |

**Feasibility:**
* Dash 4 `dcc.Graph` with Plotly provides `clickData`, `customdata` for partition
  IDs, `hovertemplate`, marker symbols and responsive layout.
* No new dependency is needed. Tap events work on touch devices.

### 4.2 Portfolio detail panel

Each bucket card shows:

```
Bucket A · 30 credits                               Wins 15.7% (modelled)
  Man City v Fulham · Home          55.2% · 1.41
  Como v Cagliari · Home            53.9% · 1.30
  Norwich v Cardiff · Home          52.8% · 1.73
  Combined reference odds 3.17 → potential return 95.1 credits
  ✗ Not enough on its own to get your 100 back
```

* "✓ Enough on its own to get your 100 back" when 30 × odds ≥ 100.
* Probability, odds and payout use tabular figures.
* Outcome colours mark Home, Draw and Away chips. Text labels are always present.

**Nine-fold card:** the nine picks (compact), the modelled win chance (often
"0.2%"), combined odds, 10 credits, the potential return.

**Summary block:**
* Allocated: 100 credits (30 + 30 + 30 + 10)
* Chance of getting 100 back (modelled)
* Expected return, e.g. "52.5 credits (−47.5 net)"
* Best case if everything wins: "1,163 credits"

**Potential vs expected:**
* Potential returns are labelled "if it wins".
* The expected return is labelled "average over all outcomes, according to the
  model".
* No 30% figure is ever shown next to a probability, so the allocation cannot be
  read as a chance.

### 4.3 "Your Payout Probability" (second chart, in the details panel)

**Purpose:** "What could this grouping actually pay, and how likely is each
amount?" The frontier compares groupings; this chart explains the one you picked.
It sits below the bucket cards, as the panel's "Your Payout Probability" section.

**Worked example** (real numbers):
* Phase 5B slate R1, recommended grouping `024|158|367`, at 30/30/30/10.
* Bucket payouts: C 100.70, A 116.58, B 176.83. Nine-fold 768.81.

| Buckets that win | Gross payout | Chance of exactly this | Chance of at least this |
|---|---:|---:|---:|
| none | 0.00 | 62.9% | 100% |
| C | 100.70 | 16.5% | 37.1% |
| A | 116.58 | 10.3% | 20.6% |
| B | 176.83 | 5.2% | 10.3% |
| A + C | 217.28 | 2.7% | 5.1% |
| B + C | 277.52 | 1.4% | 2.4% |
| A + B | 293.41 | 0.8% | 1.1% |
| all three + nine-fold | 1,162.91 | 0.2% | 0.2% |

The 100-credit line falls inside the flat step that runs up to 100.70, so
"at least 100 credits" = 37.1%: the same figure as this grouping's point on the
frontier.

#### Main view: "Chance of at least…"

```
Your Payout Probability                         [At least ▾ | Exactly]   [Full range | Focus on buckets]
Chance of getting at least this much back (modelled)
100% ┤█
     │█
 37% ┤╞════╗ ◀ 100 credits back: 37.1%
 21% ┤│    ╚═╗
 10% ┤│      ╚════╗
  5% ┤│           ╚═══╗
0.2% ┤│               ╚════════════════════════════════════════════╗ all nine win: 1,162.91 cr · 0.2%
   0 ┼┴──────┬──────────────┬─────────────────────────────────────┴──▶
      0    100           300                                   1,163   Gross payout (credits)
Figures assume Goal Model 1.0 probabilities and reference odds frozen on Thu 19 Nov.
```

(This is a schematic. The real chart draws all seven drops, at 100.70, 116.58,
176.83, 217.28, 277.52, 293.41 and 1,162.91 credits.)

| Element | Specification |
|---|---|
| Shape | A step line through explicit vertices: (0, 100%) → (0, S₁) → (r₁, S₁) → (r₁, S₂) → … → (r_max, S_max) → (r_max, 0). For x in (r_{k−1}, r_k] the level is P(R ≥ r_k). Vertical drops at each payout. No smoothing, no interpolation. |
| X axis | 0 to the maximum payout, padded 3%, in credits. **Full range is the default.** The optional "Focus on buckets" toggle limits the axis to 1.1 × the largest payout without the nine-fold, and shows an off-scale label for the all-win point. |
| Y axis | 0–100%, linear, ticks in %. Values below 0.1% are printed "<0.1%". |
| 100-credit marker | Dashed vertical line at 100, plus a dot where it meets the curve, labelled "100 credits back: 37.1%". Always shown, even if it lies inside a flat step. |
| Maximum marker | Dot at the right end: "All nine win: 1,162.91 credits · 0.2%". |
| Hover / tap on a step | "At least 176.83 credits: 10.3% · happens if Bucket B wins (with or without others)". |
| Update | The figure is rebuilt from the selected grouping on every selection change. |
| Caption | "Chance of getting at least this much back, according to Goal Model 1.0. It is not a promise: real results can differ." |

#### Secondary view: "Chance of exactly…"

* A toggle switches to thin vertical stems (not wide bars, which would imply
  ranges) at each distinct payout. Height = probability of exactly that payout.
* Each stem is labelled with which buckets win.
* A note says that 0 credits ("no bucket wins") is the most likely single outcome
  when it is.
* Stem probabilities sum to 100%, stated in the caption.
* "Show as table" opens the eight-row table above. This is also the accessible
  form of both views.

**Wording rules (cumulative vs exact):**
* **Cumulative:** "Chance of getting **at least** X credits".
* **Exact:** "Chance of getting **exactly** X credits".
* The two views never share a heading. Each axis title repeats "at least" or
  "exactly".
* "Chance of 100 credits" on its own is never used.

### Mobile

* Chart on top: full width, 300 px high.
* Below it, the selected-grouping summary, then collapsible bucket cards, then the
  "Your Payout Probability" section (240 px high, with the view toggles as
  segmented buttons), then the efficient list.
* A sticky bottom bar: "Review entry ▸".
* Dominated taps show a toast.

## 5. Step 3: Review and submit

```
┌ ③ Review & submit ──────────────────────────────────────────────────────┐
│ Your entry for Weekend 20–23 Nov            Locks Fri 20 Nov, 20:45 SAST │
│ Grouping 024|158|367 ★ recommended                                       │
│ Bucket A (30) · Bucket B (30) · Bucket C (30) · Nine-fold (10)           │
│ Chance of getting 100 back 37.1% · Expected return 52.5 credits          │
│                                                                          │
│ Before you submit                                                        │
│ • These are Goal Model 1.0 estimates, not guarantees.                    │
│ • Prices are reference odds frozen on Thu 19 Nov, not bookmaker offers.  │
│ • Credits are virtual and have no cash value.                            │
│ ☐ I understand                                       [Back] [Submit ▸]   │
└──────────────────────────────────────────────────────────────────────────┘
```

* **Submit** is enabled only when the box is ticked. It sends the draft with an
  idempotency key.
* **Success** shows a receipt: "Entry submitted · version 1 · Thu 19 Nov 18:02 ·
  you can change it until Fri 20:45." Links: My Challenge, Leaderboards.
* **Resubmission** shows "This replaces your entry submitted at 18:02".

## 6. My Challenge (`/challenge/me`)

```
This week · Weekend 20–23 Nov · LOCKED · settling (5 of 9 picks settled)
  Bucket A  ✓ ✓ ●   pending      Bucket B  ✓ ✗ –  lost      Bucket C ✓ ✓ ✓  won  +116.6
  Nine-fold lost
  Returned so far 116.6 credits · net +16.6 (provisional)
Season 2026/27 · 7 rounds entered · average net −4.2 · rank 18 of 140 (qualified)
History ▸  Weekend 13–16 Nov  net −100.0   ·   Weekend 6–9 Nov  net +212.4 …
```

* Selection states: ✓ won · ✗ lost · ● pending · "void" pill with its reason
  (postponed, cancelled, …).
* Before the deadline: "Edit entry" reopens the builder with the current
  submission.

## 7. Leaderboards (`/leaderboards`)

**This week:**
* rank, display name, net credits, buckets won (0–3), status (provisional or
  final);
* ties share a rank, shown as "=4";
* your own row is highlighted.

**Season:**
* rank, name, rounds entered, average net, total net;
* the qualification rule is printed above the table;
* non-qualifiers are listed below, without a rank.

Explanations: "Net = credits returned − 100". "Provisional until all matches are
settled".

## 8. User-facing terminology and educational copy

| Concept | UI term | Avoid |
|---|---|---|
| P(R ≥ 100) | Chance of getting your 100 credits back | "recovery probability" in headings (help text only) |
| E[R] | Expected return (average over all outcomes) | "projected profit", "EV" in headings |
| Potential payout | Returns … if it wins | "will return" |
| Pareto-efficient | Efficient grouping | "optimal", "best" |
| P(R ≥ x) | Chance of getting at least x credits | "chance of x", "odds of x" |
| P(R = x) | Chance of getting exactly x credits | "chance of x" |
| Dominated | Another grouping is at least as good on both counts | "bad", "losing" |
| Consensus odds | Reference odds (median of bookmakers) | "odds you can get" |
| Model probability | Modelled chance (Goal Model 1.0) | "real chance" |
| Bucket | Bucket (three-pick accumulator) | — |

**Fixed copy blocks:**
* **Efficient.** "Efficient groupings offer combinations of recovery probability
  and expected return that are not jointly improved upon by another grouping,
  based on Diski 9's current model."
* **Recommendation.** "Recommended because it has the highest modelled probability
  of recovering your 100 weekly credits." Followed by: "Expected return:
  52.5 credits. These are estimates; real results can differ."
* **Uncertainty** (explorer and review). "Goal Model 1.0 probabilities are
  estimates. Small changes in them can change which groupings are efficient. A
  high chance of getting your credits back is not a guarantee."
* **Expected return.** "The average result the model expects over many weeks like
  this one. In a single week you will usually get much more or much less."
* **Reference odds.** "Median prices from at least three independent bookmakers,
  frozen when the round opened. Not offers you can bet on."
* **Virtual.** "Credits are virtual and have no cash value. Diski 9 is an
  educational game."

**Banned words:** guaranteed, safe bet, sure win, risk-free, lock, banker, free
money, can't lose.

**Market-implied probability:**
* Shown per pick in tooltips and on the review step ("Model 55% · Market 67%").
* It adds transparency (it shows where the model and the market differ) at low
  cost.
* It is not on the chart, so the central view stays two-dimensional.

## 9. Error and empty states

| State | Message |
|---|---|
| No open round | "The next round opens on Thursday. Meanwhile, explore fixtures in the Screener." |
| Round not published (< 9 eligible fixtures) | "This week doesn't have enough fixtures with reliable reference odds for a round." |
| Not signed in | Builder usable as a preview; Submit shows "Sign in to enter" |
| Deadline passed | Builder read-only: "Entries closed at Fri 20:45" |
| A pick became unavailable (kickoff moved) | Banner on the slip: "Man City v Fulham was moved earlier and is no longer available. Replace it to continue." |
| Submit conflict (another tab saved first) | "Your entry was updated elsewhere. Reload to see the latest version." |
| Submit after deadline (race) | "Entries closed at 20:45:00. Your entry from 18:02 stands." |
| Duplicate click | Same receipt; no second version |
| Calculation error | "We couldn't calculate groupings for these picks. Your picks are kept; try again." (logged) |
| Settlement delayed | Pick shows "Waiting for official result" |

## 10. Mobile and accessibility checklist

* 390 px: no horizontal page scroll. Chart, list and bucket cards stack.
* Tap targets at least 40 px. Chips wrap.
* Colour plus shape plus text for every state (★ recommended, ring selected,
  ✓/✗ results).
* Keyboard: the stepper, chips (buttons), the efficient list and Submit are all
  focusable in order.
* Times: browser time zone detected client-side and stored for the session, with
  the app's time zone as fallback. Labels show the zone abbreviation.
* Contrast: the existing token palette meets WCAG AA in both themes.
