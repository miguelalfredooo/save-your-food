# Reference prices — BLS West region

**Lives at `FOLDER/_ops/reference-prices-west.md`. Never top-level** — §1: every top-level `.md` in `FOLDER` is a recipe.

**As of:** BLS Average Price Data, **August 2026** release · fetched **2026-10-08** · next refresh due **2027-01** (quarterly).

**What this is for:** pricing a toss or a rescue that has no `bought` line in `Restock.md` to join to (§15). There are two layers: **your own receipt prices**, which build up with every receipt, and **BLS West**, which fills in until they do. Every dollar figure built from this table is an estimate and is reported as one.

**What it is not:** a California price. BLS publishes no state figure. "West" is 13 states — AK, AZ, CA, CO, HI, ID, MT, NV, NM, OR, UT, WA, WY. Bay Area and LA shelf prices usually run higher, so treat every West figure as a **floor**, not a midpoint.

## Source rule — which price a toss or rescue uses

| Order | Use | Marked |
|---|---|---|
| 1 | The `bought` line this item joins to in `Restock.md` | exact |
| 2 | **Your receipts:** median of your `bought` prices for this item, last 12 months | `R` + count |
| 3 | BLS West, Aug 2026 | `W` |
| 4 | BLS West, latest month within 6 months | `W` + month |
| 5 | BLS US city average, latest within 6 months | `US` + month |
| 6 | Nothing | not covered (see below) |

**Your receipts outrank BLS as soon as there is one.** They're your stores and your pack sizes, which is the thing BLS can't know. Before a toss can be costed, a receipt price has to be a **pack** price. `GV WHL MLK 1G 4.99` covers a gallon. If you threw out half of it, count half.

## Your receipts

**Derived from `Restock.md`. Never a second source.** Rebuild this section from the `bought` lines whenever a receipt is captured. If the two ever disagree, `Restock.md` wins and this section gets regenerated. Only add a row once a receipt line can be matched to a named item. Don't add a row for an OCR string you couldn't read.

| Item | Pack | Median pack $ | Receipts | Range | Last bought | Stores |
|---|---|---|---|---|---|---|
| _no receipts captured yet_ | | | | | | |

`Receipts` is the count behind the median. One receipt is a price; three is a fair price. Show the count every time.

**This section fills the gaps BLS left.** Cilantro, yogurt, butter and tofu get a real price from the second receipt they appear on. Until then they stay unpriced (see below) rather than getting a borrowed figure.

**US figures are NOT scaled up to West.** Across the 28 items that have both, West ÷ US had a median of **1.05**, but ranged from **0.85 (dried beans) to 1.31 (sirloin)**. One multiplier would be a precise-looking guess. A US row is a national price, labelled as one.

## BLS West — the fallback

`Pack` is a typical supermarket pack. **The pack sizes are estimates, not BLS data. Edit them to match what you actually buy.** `Pack $` = price × pack.

### Meat and poultry — red class (§6)

| Item | $ / unit | Src | Pack (est.) | Pack $ | BLS series |
|---|---|---|---|---|---|
| Chicken breast, boneless | 4.72 / lb | W | 1.5 lb | 7.08 | APU0400FF1101 |
| Chicken, whole | 2.00 / lb | W | 4.5 lb | 9.02 | APU0400706111 |
| Chicken legs, bone-in | 1.71 / lb | W Apr 2026 | 2 lb | 3.43 | APU0400706212 |
| Ground beef, 100% | 7.44 / lb | W | 1 lb | 7.44 | APU0400703112 |
| Ground beef, all uncooked | 7.21 / lb | W | 1 lb | 7.21 | APU0400FC1101 |
| Steak, sirloin, Choice boneless | 18.77 / lb | W | 1 lb | 18.77 | APU0400703613 |
| Steaks, all uncooked beef | 13.81 / lb | W | 1 lb | 13.81 | APU0400FC3101 |
| Chuck roast, Choice boneless | 10.47 / lb | W | 2.5 lb | 26.18 | APU0400703213 |
| Beef roasts, all uncooked | 9.81 / lb | W | 2.5 lb | 24.54 | APU0400FC2101 |
| Pork chops, boneless | 4.58 / lb | W | 1.5 lb | 6.87 | APU0400704212 |
| Pork chops, all | 4.20 / lb | W | 1.5 lb | 6.29 | APU0400FD3101 |
| Bacon, sliced | 6.92 / lb | W | 12 oz | 5.19 | APU0400704111 |
| Ham, boneless | 5.22 / lb | W | 1 lb | 5.22 | APU0400704312 |

### Dairy and eggs — yellow/green

| Item | $ / unit | Src | Pack (est.) | Pack $ | BLS series |
|---|---|---|---|---|---|
| Milk, whole | 4.83 / gal | W | ½ gal | 2.42 | APU0400709112 |
| Cheddar, natural | 7.32 / lb | W | 8 oz | 3.66 | APU0400710212 |
| American processed cheese | 4.75 / lb | US Aug 2026 | 12 oz | 3.56 | APU0000710211 |
| Eggs, grade A large | 2.27 / doz | US Aug 2026 | 1 doz | 2.27 | APU0000708111 |
| Ice cream, bulk | 7.38 / ½ gal | W | ½ gal | 7.38 | APU0400710411 |

### Produce

| Item | $ / unit | Src | Pack (est.) | Pack $ | BLS series |
|---|---|---|---|---|---|
| Bananas | 0.71 / lb | W | bunch, 2 lb | 1.43 | APU0400711211 |
| Lemons | 2.01 / lb | W | 1 lemon, ¼ lb | 0.50 | APU0400711412 |
| Oranges, navel | 1.45 / lb | W May 2026 | 1 orange, ½ lb | 0.73 | APU0400711311 |
| Grapefruit | 1.60 / lb | US Aug 2026 | 1 fruit, 1 lb | 1.60 | APU0000711411 |
| Strawberries | 2.58 / 12 oz | US Aug 2026 | 1 lb clamshell | 3.44 | APU0000711415 |
| Potatoes, white | 1.00 / lb | W | 5 lb bag | 5.02 | APU0400712112 |
| Lettuce, romaine | 4.14 / lb | W May 2026 | 3 hearts, 1.25 lb | 5.17 | APU0400FL2101 |
| Lettuce, iceberg | 1.47 / lb | US Aug 2026 | 1 head, 1.25 lb | 1.84 | APU0000712211 |
| Tomatoes, field grown | 1.98 / lb | US Aug 2026 | 1 lb | 1.98 | APU0000712311 |

### Bread and pantry — rarely tossed, here for completeness

| Item | $ / unit | Src | Pack (est.) | Pack $ | BLS series |
|---|---|---|---|---|---|
| Bread, white pan | 2.04 / lb | W | 20 oz loaf | 2.54 | APU0400702111 |
| Bread, whole wheat pan | 2.81 / lb | US May 2026 | 20 oz loaf | 3.52 | APU0000702212 |
| Rice, white long grain | 1.11 / lb | US Aug 2026 | 2 lb | 2.22 | APU0000701312 |
| Spaghetti and macaroni | 1.37 / lb | US Aug 2026 | 1 lb | 1.37 | APU0000701322 |
| Flour, all purpose | 0.55 / lb | US Aug 2026 | 5 lb | 2.74 | APU0000701111 |
| Beans, dried | 1.39 / lb | W | 1 lb | 1.39 | APU0400714233 |
| Sugar, white | 1.01 / lb | W | 4 lb | 4.04 | APU0400715211 |
| Coffee, ground | 9.30 / lb | US Aug 2026 | 12 oz | 6.97 | APU0000717311 |
| Orange juice, frozen conc. | 4.82 / 16 oz | US Jul 2026 | 12 oz can | 3.61 | APU0000713111 |

## Not covered — and why

**BLS stopped publishing most produce.** These series returned no data for 2025–26 at either West or US level. Broccoli and sweet peppers last published in **March 2020**. Butter, carrots, apples and peanut butter had nothing at all from 2020 onward:

> butter · broccoli · carrots · celery · cabbage · sweet peppers · apples · grapes · peaches · pears · cherries · Valencia oranges · bone-in chicken breast · peanut butter

**BLS never tracked these:** fresh herbs (cilantro, parsley), spinach and bagged greens, mushrooms, berries other than strawberries, avocados, yogurt, sour cream, tofu, oat and nut milk, deli meat, fish and shellfish, cooked leftovers.

**The awkward part is that these are the items most likely to be tossed.** Cilantro is the example `fridge-loop` itself uses (§15). So this table prices the meat, which is the costly part of most tosses, and leaves most of the produce unpriced.

**Your receipts close this gap.** Every receipt with cilantro on it gives cilantro a real price. Coverage grows with use and doesn't depend on BLS.

Until an item's first receipt arrives: count it in the toss or rescue tally, but leave it out of the dollar figure. The skill already does this, as the "N of M priced" line in the scorecard (§17). **Never estimate a price from a similar item.** A cilantro price guessed from romaine is the kind of number this system exists to avoid.

## Refreshing

The BLS bulk files (`download.bls.gov/pub/time.series/ap/`) refuse requests that don't carry a contact email. Two things work without one:

1. The rendered table, scraped with Firecrawl:
   `https://www.bls.gov/regions/mid-atlantic/data/averageretailfoodandenergyprices_usandwest_table.htm`
   It shows US and West, for the latest month, the month before and a year earlier. West cells are blank when BLS didn't publish that month.
2. The public API, which needs no key: up to 25 series per call and 25 calls a day.
   `POST https://api.bls.gov/publicAPI/v1/timeseries/data/` with `{"seriesid":[...],"startyear":"2025","endyear":"2026"}`.
   It returns `-` for a month that wasn't published. October 2025 is `-` across almost every series.

Re-apply the source rule on every refresh, because a row can change from `W` to `US` or back. Update **As of**, and leave the pack-size column alone. That column is yours.
