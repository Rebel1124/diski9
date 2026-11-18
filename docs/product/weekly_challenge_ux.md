# Diski 9 Weekly Challenge — UX Specification (revised, Phase 6A.2)

Status: **revised specification for review**. It supersedes the Phase 5C UX
(`2e079ba`).
* **Removed:** the 280-grouping explorer, the efficient-frontier chart and the
  recommended grouping.
* **Kept, with changes:** "Your Payout Probability".
* **New:** the bucket builder, the bucket tracker, Explore Your Bucket Risk, and
  championships.

## 1. Principles

1. **Two goals, said plainly.** "Get your 100 credits back" and "finish in the top
   ten *and* get your 100 back". Winning the week is never promoted as a goal.
2. **The buckets teach the lesson.** Each pick lands in its bucket automatically.
   The tracker shows what's still needed.
3. **Individual ≠ combined.** Wherever a bucket appears, its combined chance sits
   next to the individual chances.
4. **Plain words first, detail on demand.** Advanced calculations are in
   expanders.
5. **Honest numbers.** Everything is labelled as an estimate:
   * market estimate vs Diski 9 model estimate;
   * reference odds, not offers;
   * virtual credits with no value.

## 2. Navigation and screens

```
Diski 9  Screener | Weekly Challenge | Leaderboards          Times in SAST · Sign in / Thandi ▾
```

| Route | Screen | Contains |
|---|---|---|
| `/` | Screener and Match Lab | Unchanged |
| `/challenge` | **Weekly Challenge** | Builder (pool + tracker) → Review (portfolio analytics) → Submit → Receipt |
| `/challenge/learn` | **Explore Your Bucket Risk** | Permanent educational explorer (illustrative only) |
| `/challenge/me` | **My Challenge** | Current entry, settlement progress, history, championship summary |
| `/leaderboards` | **Leaderboards** | This week · Championship |

## 3. The builder

### Desktop

```
┌ Weekly Challenge · Weekend 20–23 Nov ─────────────────────── Deadline Fri 20 Nov 20:45 SAST ┐
│ Goal: get your 100 credits back. Bonus: finish top ten and get your 100 back.  [How it works]│
├──────────────────────────────────────────────────────────────┬─────────────────────────────────┤
│ League [All 6 ▾]  Day [All ▾]  Market [All ▾]  🔍            │ YOUR BUCKETS                    │
│                                                              │ Foundation  ███░  3/4  (40 cr)  │
│ Sat 21 Nov · EPL · Man City v Fulham              14:00      │ Balanced    ██░   2/3  (30 cr)  │
│  Result  Home  Mkt 67% · D9 55% · 1.41  [Foundation]  [+]    │ Challenger  ░░    0/2  (20 cr)  │
│          Draw  Mkt 19% · D9 24% · 5.20  not eligible <20%    │ The Diski 9 ─ all nine (10 cr)  │
│          Away  Mkt 14% · D9 21% · 7.60  not eligible <20%    │ Total       █████░░░░  5/9      │
│  BTTS    Yes   Mkt 47% · D9 52% · 2.05  [Balanced]    [+]    │                                 │
│          No    Mkt 53% · D9 48% · 1.84  [Balanced]    [+]    │ 1 Man City v Fulham · Home  F ✕ │
│  Goals   Over  Mkt 64% · D9 58% · 1.53  [Foundation]  [+]    │ 2 Millwall v QPR · BTTS Yes B ✕ │
│          Under Mkt 36% · D9 42% · 2.70  [Challenger]  [+]    │ …                               │
│ …                                                            │ [Review portfolio ▸]  (at 9/9)  │
└──────────────────────────────────────────────────────────────┴─────────────────────────────────┘
```

The values in this wireframe are illustrative.

**Behaviour:**
* Every outcome shows:
  * the **market** probability ("Mkt"), which decides the bucket;
  * the **Diski 9** model probability ("D9");
  * the reference odds;
  * a bucket chip (Foundation, Balanced or Challenger), or "not eligible" with the
    reason.
* **[+] adds the pick to its bucket automatically:**
  * the tracker animates the new count;
  * picking another outcome on the same fixture replaces the earlier one, with a
    toast naming the change;
  * if that bucket is full, [+] is disabled with the tooltip "Foundation is full
    (4/4) — remove a Foundation pick to add this".
* **The tracker always shows** Foundation X/4, Balanced X/3, Challenger X/2 and
  Total X/9.
  * It shows completion ticks per bucket.
  * Colour is never the only signal (text counts, plus ✓).
* **Pool shape:** fixtures with no eligible outcome are hidden, with a count note.
  A filter "Show only outcomes for buckets I still need" helps finish the
  portfolio.
* **Market vs model:** the copy explains that "Mkt" decides the bucket, and "D9"
  is Diski 9's independent estimate. A big gap is highlighted neutrally ("Diski 9
  rates this higher"), never as advice.

### Mobile (390 px)

* The fixture list is full width.
* The tracker is a sticky bar: "F 3/4 · B 2/3 · C 0/2 · 5/9 ▸". It expands to the
  pick list.
* Outcome rows wrap; the bucket chip sits below the probabilities.

## 4. Review: portfolio analytics (complete portfolios only)

**Before 9/9:**
* The Review button stays disabled.
* Only completed buckets show their own combined probability, odds and payout,
  labelled "Bucket complete".
* No portfolio recovery, expected return or chart is shown. The message reads
  "Complete all three buckets to see your portfolio's chances."

**At 9/9:**

```
┌ Your portfolio ───────────────────────────── Estimate: [ Market ▾ | Diski 9 model ] ──────────┐
│ Chance of getting 100 credits back  34.8%        Chance of getting nothing  65.1%           │
│ Expected return 79.6 credits (−20.4 net)        Maximum if all nine win  3,812.40 credits   │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Foundation · 40 credits    4 picks, each 60–95%                                              │
│   Man City Home 67% · Bayern Home 87% · Over 2.5 64% · Como Home 73%                         │
│   Combined chance 27.6%  ·  combined odds 3.86  ·  pays 154.40 if all four win  ✓ alone ≥ 100 │
│ Balanced · 30 credits    3 picks, each 40–60%     combined 11.9% · odds 7.70 · pays 231.00   │
│ Challenger · 20 credits  2 picks, each 20–40%     combined 9.6% · odds 9.18 · pays 183.60    │
│ The Diski 9 · 10 credits all nine                 combined 0.3% · pays 2,729.60               │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Your Payout Probability  [ At least this payout | Exactly this payout ]  (Phase 5C §4.3)     │
│ ▸ How these numbers are calculated   ▸ Explore Your Bucket Risk                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

Illustrative numbers.

* **Estimate toggle:** Market (default) or Diski 9 model. Each view uses one
  source throughout; the label always names the source.
* **Per-bucket line:**
  * the individual probabilities;
  * **the combined chance** (product, assuming independence);
  * combined odds and payout "if it wins";
  * "✓ alone ≥ 100" when that bucket alone would recover your credits.
* **Callout** when a high-probability bucket has a low combined chance: "Four
  likely outcomes together: about 1 in 4."
* **Your Payout Probability** (as in Phase 5C, §4.3 there):
  * the cumulative step chart, with the 100-credit marker;
  * an exact-payout bar view;
  * the 100-credit value equals the summary figure;
  * the maximum includes The Diski 9;
  * the eight-state table is hidden behind "All possible outcomes".
* **Caption:** "Modelled estimates from [market prices / Goal Model 1.0], assuming
  matches are independent. Not a guarantee. Credits are virtual and have no cash
  value."

## 5. Explore Your Bucket Risk (`/challenge/learn`, also linked from Review)

```
┌ Explore Your Bucket Risk ───────────────────────────────────── ILLUSTRATION ONLY ┐
│ Change these made-up chances to see how combining picks works.                    │
│ Pick 1 [ 75% ]  Pick 2 [ 70% ]  Pick 3 [ 80% ]  Pick 4 [ 65% ]   (+ add / − remove) │
│ Combined chance all four win: 27.3%   ← each pick looks likely; together, ~1 in 4 │
│ Fair odds (1 ÷ chance): 3.66 · 40 credits would pay 146.40 if all win             │
│ Expected return at fair odds: 40.00 credits — potential payout is not the average │
│ Chance this bucket returns nothing: 72.7%                                         │
│ ▸ Why combined chances shrink  ▸ Potential payout vs expected return              │
│ ▸ What "getting your 100 back" means  ▸ Assumptions and limits                    │
└───────────────────────────────────────────────────────────────────────────────────┘
```

* The inputs are hypothetical probabilities. The odds are **fair** (no margin) and
  labelled as such.
* **Never** linked to the participant's portfolio, the reference odds or the fixed
  credits. Nothing typed here is saved or submitted.
* **Short, expandable explanations:**
  * individual vs combined probability;
  * why four 60–95% picks can still give a low combined chance;
  * potential payout vs expected return (fair odds give an expected return equal
    to the stake; real reference odds include a margin, so less);
  * the recovery and zero-payout probabilities;
  * the independence assumption;
  * estimates vs true probabilities.

## 6. Leaderboards

**This week:**

| Pos | Name | Gross returned | Net | Points |
|---|---|---:|---:|---:|
| 1 | Thandi | 412.80 cr | +312.80 | 150 |
| =2 | Sipho / Lee | 231.00 cr | +131.00 | 127.50 each |
| … | | | | |
| 23 | Ana | 88.20 cr | −11.80 | 0 (not recovered) |

* Gross and net are labelled with units.
* The points column explains a 0 when a participant didn't recover.
* Ties show "=" with the shared points.

**Championship (10 rounds):**

| Rank | Name | Rounds entered | Recoveries | Points |
|---|---|---:|---:|---:|
| 1 | Lee | 7 | 5 | 612.50 |

* A header line reads: "Championship 3 · round 7 of 10 · No recovery, no points".
* The tie rules are printed under the table.
* Fractional points show to 2 decimals.
* There is **no** interactive championship or season explorer.

## 7. Terminology and copy

| Concept | UI term | Avoid |
|---|---|---|
| Bucket A / B / C | Foundation / Balanced / Challenger (outcome categories) | "safe bucket", "risky bucket" as accumulator claims |
| Nine-fold | The Diski 9 | "jackpot" |
| P(gross ≥ 100) | Chance of getting your 100 credits back | "win chance" |
| E[gross] | Expected return (average over all outcomes) | "projected profit" |
| Potential payout | Pays … if it wins | "you will get" |
| Market probability | Market estimate (decides the bucket) | "true chance" |
| Model probability | Diski 9 estimate (Goal Model 1.0) | "real chance" |

**Banned words:** safe, guaranteed, risk-free, sure, lock, banker, free money,
can't lose.

## 8. Error and empty states

| State | Message |
|---|---|
| Round postponed (opening checks failed) | "This week's round is postponed: not enough eligible fixtures to build a full portfolio. The championship continues with the next completed round." |
| Bucket full | "Foundation is full (4/4). Remove a Foundation pick to add this." |
| Not enough fixtures left for a bucket (after other picks) | "Only 1 Challenger outcome left on unused fixtures — swap a pick to free a fixture." |
| Incomplete portfolio | "Complete all three buckets to see your portfolio's chances." |
| Deadline passed / submit race / duplicate click | As in Phase 5C (the entry from before the deadline stands; idempotent receipt) |

## 9. Accessibility and mobile

* The tracker uses text counts plus ✓, never colour alone, and `aria-live`
  announces count changes.
* Every chart has a table alternative.
* Toggles are segmented buttons with `aria-pressed`.
* At 390 px there is no horizontal page scroll. Tap targets are at least 40 px.
