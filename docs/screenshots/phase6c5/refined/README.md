# Phase 6C.5 Stage E: owner-requested refinements (screenshots)

These were captured from the real app with the local Supabase Auth harness on the
seeded showcase database, `diski9_e2e_6c5`. That database was built by
`tools/e2e_6c5/seed.py` through the real services, with 60 participants. None of it
is owner data.

The script is `tools/e2e_6c5/refined.js`. Its run gave 108 element-level page checks
at 1360, 768, 430, 390, 360 and 320 px, with 0 problems.

Desktop captures are full page. Tablet and phone captures keep the top 2,400 px, and
component captures are cropped to the component. The original Stage E captures in the
parent folder are kept as the "before" set.

## Before and after
| File | Shows |
|---|---|
| `compare_desktop_weekly_alignment_podium.png` | Points column aligned with its header (it sat left of it); compact column; compact podium with one bright "Returned" label per card; grouped controls; friendly round title |
| `compare_desktop_championship.png` | Larger progress; "Completed with 9 valid rounds" (D-30a) instead of an empty tenth segment |
| `compare_desktop_history_stats_cards.png` | Coloured-header statistics cards; methodology behind a disclosure; chart placeholder below three rounds |
| `compare_mobile_weekly_cards.png` | Navigation no longer clipped ("Leaderboards"); compact cards: position, larger name and points on one line |
| `compare_mobile_championship_cards.png` | The same for championship cards |
| `compare_mobile_history.png` | Statistics cards and compact history cards on a phone |

## Reference: Build Portfolio (unchanged)
| File | Shows |
|---|---|
| `reference_build_portfolio_cards.png` | Foundation, Balanced and Challenger prediction cards: coloured left edge and tinted tag. This is the pattern the statistics cards reuse |
| `reference_build_portfolio_tracker.png` | The bucket tracker with the same tags |

## Statistics cards
| File | Shows |
|---|---|
| `desktop_stats_cards_positive_net.png` | Six cards with category headers; positive Net and return on allocation in green |
| `desktop_stats_cards_negative_net.png` | Second viewer, one championship: negative Net in red |
| `desktop_stats_cards_zero_net_specimen.png` | **Styling specimen:** the real cards with the values set in the page to +0.00 / 0.0% (neutral). The showcase data has no zero-net participant |
| `mobile_stats_cards.png` | Two per row on a 390 px phone |

## Leaderboards
| File | Shows |
|---|---|
| `desktop_weekly_final.png`, `tablet_…`, `mobile_…`, `mobile320_…` | Final competitive round |
| `desktop_weekly_table_alignment.png` | The aligned table (rank centred, name left, numbers right, coloured Net) |
| `desktop_podium_shared_ranks.png` | Compact podium: 1st shared by two, 3rd shared by three, no 2nd |
| `desktop_weekly_provisional.png`, `mobile_weekly_provisional.png` | Provisional round (settled and pending counts) |
| `desktop_weekly_corrected.png`, `desktop_weekly_practice.png` | Corrected (version 2); practice (no points column) |
| `mobile_weekly_cards_rank_name.png`, `mobile_championship_cards_rank_name.png` | Mobile cards: compact position area, name, points; the viewer's card highlighted |
| `desktop_championship_in_progress.png`, `tablet_…`, `mobile_…`, `mobile320_…` | Championship in progress |
| `desktop_championship_corrected_under_review.png`, `tablet_…`, `mobile_…`, `mobile320_…` | Completed championship: D-30a disclosure, joint champions, Under review and Corrected |

## My Challenge
| File | Shows |
|---|---|
| `desktop_my_challenge_current.png`, `mobile_my_challenge_current.png` | Current tab with the championship progress |
| `desktop_history.png`, `tablet_history.png`, `mobile_history.png`, `mobile320_history.png` | History (all championships): chart 1 shown (10 rounds); chart 2's championship has one round, so its placeholder appears |
| `desktop_charts_one_eligible.png` | One chart eligible, the other not |
| `desktop_charts_both_eligible.png` | One championship (9 rounds played): both charts, rounds numbered 1–9 |
| `desktop_charts_locked.png` | Second viewer, one round: both placeholders ("1 of 3 eligible rounds completed") |
| `desktop_history_championship_scope.png` | History for one championship |
| `desktop_history_detail_under_review.png`, `tablet_…`, `mobile_…`, `mobile320_…` | Entry details of a reopened round |

## Narrow phones and long names
| File | Shows |
|---|---|
| `mobile320_navigation.png`, `mobile320_navigation_guest.png` | 2 × 2 navigation at 320 px, signed in and guest |
| `mobile320_navigation_long_name.png` | A real 24-character account name (truncated, full name as tooltip) |
| `mobile320_history_long_name_negative.png` | That viewer's History at 320 px |
| `mobile320_long_name_weekly_stress.png`, `mobile320_long_name_championship_stress.png` | **Stress pass:** 24-character names, seven-figure returns and maximum points injected into the rendered page; nothing clipped or overlapping. Names locked into entries cannot be changed in the database |
