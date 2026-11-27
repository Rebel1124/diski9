# Diski 9 Stage F3 — monthly infrastructure cost log (amounts only)

Approved by the owner on 23 Nov 2026 (S-2). Amounts only: no account numbers, card
details, addresses or credentials. **USD**, as invoiced.

**Thresholds (F3-D3, unchanged):**
* **$65/month: warning.** Review the cause and record it below.
* **$75/month: ceiling.** New discretionary spending stops until the owner approves it.
* The ceiling is enforced **per provider and by procedure** (S-1). It is **not** an
  absolute technical hard cap: no provider enforces the combined total.

**Labels:** **actual** = on a paid invoice; **estimated** = forecast, not invoiced;
**uninvoiced** = usage accruing that has not been billed yet.

**Procedure (on the 1st of each month, and whenever an invoice arrives):**
1. Enter each new invoice: provider, invoice date, period, subtotal, tax, total.
2. Check the provider notifications: Supabase usage emails, Backblaze cap alerts (75 %
   and 100 %).
3. Compare the month's total, actual plus estimated, with $65 and $75.
4. At ≥ $65, record the cause. At ≥ $75, or for any new add-on, project, plan change or
   cap increase, get the owner's approval first.
5. Commit the update (documentation only).

## Month 1: 22 Nov – 21 Dec 2026

| Provider | Item | Invoice / period | Subtotal | Tax | Total | Status |
|---|---|---|---|---|---|---|
| Hostinger | KVM 2, first month (discounted) | 22 Nov 2026 | 10.99 | 1.65 | **12.64** | **actual** (paid) |
| Supabase | Pro subscription | EGXGMN-00001, 22 Nov–21 Dec 2026 | 25.00 | 0.00 | **25.00** | **actual** (paid). Billing page 23 Nov: current $25.00, projected $25.00 |
| Supabase | – | EGXGMN-00002 | 0.00 | 0.00 | 0.00 | **actual** (paid) |
| Backblaze B2 | storage, downloads | Nov 2026 usage: ≈ 0 GB average storage, 0 GB downloaded, 25 transactions (A 4, B 1, C 20; free) | – | – | ≈ 0.00 | **uninvoiced** (below the free 10 GB; capped) |
| **Month 1 total** | | | | | **37.64** actual + ≈ 0 uninvoiced | below $65 |

The Hostinger subtotal is derived as total minus tax.

## Forecast: month 2 onwards (estimated)

| Provider | Basis | Monthly | Status |
|---|---|---|---|
| Hostinger KVM 2 | renewal price $24.49 + ≈ 15 % tax (tax evidenced on the first invoice) | ≈ 28.16 | **estimated** |
| Supabase Pro | verified subscription charge (tax $0.00 on the invoice; reverse charge unassessed) | 25.00 | **estimated** (invoice-based) |
| Backblaze B2 | at most storage $0.10/day plus downloads $0.05/day (caps); transactions free; Class D unused | ≤ 4.65 (≤ 5.35 with 15 % tax); expected ≈ 0 | **estimated** (maximum under caps) |
| **Normal-month maximum** | | **≈ 58.51** | below $65 |
| + Supabase IPv4 add-on, only if needed (not purchased; needs approval) | ≈ 4.00 | ≈ 62.51 | estimated |
| + drill-month temporary Supabase project (estimate; needs approval) | ≈ 5.00 | ≈ 67.51 | estimated: **expected warning**, below $75 |
| Conservative: Supabase charged 15 % VAT | | ≈ 71.86 | estimated: below $75 |

## Uncapped charges (accepted residual risk, S-1 and S-3)
* taxes, including any reverse-charge obligation (unassessed);
* provider price changes and the Hostinger renewal price;
* Supabase add-ons, compute changes and extra projects (the spend cap covers only usage
  beyond the included quotas);
* Backblaze Class D (Event Notifications only): uncapped, unused, and **must not be
  enabled without separate approval**;
* stored Backblaze data keeps being billed while Object Lock retains it (the storage cap
  only blocks new uploads).

## Notification status
| Provider | Notification | Status |
|---|---|---|
| Backblaze | cap alerts at 75 % and 100 % (storage, downloads) | **verified** (owner, 23 Nov 2026) |
| Supabase | spend cap enabled; billing email recipient configured; quota notifications automatic (provider-documented); **no custom dollar-threshold alert is offered** | **verified with qualification** (owner, Billing page, 23 Nov 2026). Delivery not tested; no custom $65 alert exists. The $65 warning relies on this log |
| Hostinger | renewal reminder | owner calendar: refund decision 17 Dec 2026 |

## Recurring cost register (owner-confirmed 27 Nov 2026; Phase 8 OD-5)

Infrastructure costs and data-provider costs are recorded separately.

| Category | Provider | Plan | Monthly (USD) | Basis |
|---|---|---|---|---|
| Infrastructure | Hostinger VPS | KVM 2 | **12.64** (owner figure, the current invoiced month); **≈ 28.16** forecast from renewal (above) | actual / estimated |
| Infrastructure | Supabase | Pro | 25.00 | actual |
| Infrastructure | Backblaze B2 | usage-based, capped | ≈ 0 (subject to usage) | uninvoiced |
| Data provider | API-Football | Pro (7,500 requests/day) | **16.00** | owner-confirmed. Expires 14 Dec 2026; **no automatic renewal**; reverts to the Free plan on expiry; a manual renewal extends the remaining period; reminder 12 Dec |
| **Combined recurring** | | | **53.64** at the current Hostinger figure; **≈ 69.16** at the Hostinger renewal forecast | before variable charges and future AI or LiveKit spend |

**Threshold scope (unchanged; clarified, not altered):**
- The **$65 warning and $75 ceiling (F3-D3)** apply to the **infrastructure** total (Hostinger, Supabase, Backblaze), as approved for this log.
- **API-Football is tracked separately as data-provider spend.** It is outside those thresholds unless the owner decides otherwise.
- **Open owner decision:** whether the thresholds should cover the combined total. At the renewal forecast, the combined total (≈ 69.16) would exceed the $65 warning.
- Any API-Football plan change or longer-term purchase is an owner decision.

## Log of warnings and approvals
| Date | Event | Decision |
|---|---|---|
| – | none yet | – |
