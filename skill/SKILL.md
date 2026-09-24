---
name: "fridge-loop"
description: "Log fridge, freezer and pantry items into Apple Reminders and drive timed nudges that persist until you tick them off as used, frozen or tossed, with recipe matches from your Apple Notes recipes. Learns what you re-buy, flags what you already have, prices what you waste, and answers questions about your own kitchen."
---

# Fridge Loop

Goal: use food before it goes bad. Turn fridge and freezer contents into timed reminders that name what to do, persist until ticked, and stop cleanly instead of nagging forever.

This file is doctrine — what to do and why. Operational detail lives beside the recipes and is read when needed, not before:

| Read before | File |
|---|---|
| any `computer_app_*` work | `FOLDER/_ops/reminders-ui.md` |
| touching the Telegram client | `FOLDER/_ops/telegram-client.md` |

## 0. Config

| Key | Value |
|---|---|
| `DEVICE` | `{{DEVICE}}` (a desktop that stays awake) |
| `STORE` | Apple Reminders, iCloud `{{ICLOUD_ACCOUNT}}` |
| `FRIDGE_LIST` | `Fridge` · `FREEZER_LIST` `Freezer` · `GROCERY_LIST` `Groceries` |
| `CAPTURE_LIST` | `Just Shopped` — exit-geofence prompts only |
| `AT_RISK_VIEW` | `Use First` smart list: Fridge + next 2 days + Include Past Due |
| `RECIPE_CANON` | Apple Notes, Recipes folder — **the source of truth** |
| `FOLDER` | `{{FOLDER}}` |
| `TZ` | `{{TZ}}` |
| `COOK_ALERT` 4:30 PM · `MORNING_ALERT` 9:00 AM · `NIGHT_BEFORE_ALERT` 8:00 PM |

**More than one client.** Reminders is v1 and canonical; a Telegram client lives in `FOLDER/_fridge-bot/`. They do not share an inventory. If both run, say which one an answer is about.

## 1. Data model

| Store | Holds | Written by |
|---|---|---|
| `FRIDGE_LIST` | Perishables. **This is the inventory** | capture + sweep |
| `FREEZER_LIST` | Frozen items, 90-day quality checks | capture + "froze X" |
| `GROCERY_LIST` | Things to buy, plus arrive triggers in an `At the store` section | recipe gaps, `(low)`/`(out)`, restock |
| `CAPTURE_LIST` | Exit triggers only. Never food | setup, rarely |
| `Pantry.md` | Shelf-stable reference. No dates | user statements |
| `Patterns.md` | Observed defaults, so questions aren't re-asked | Claude, from what happens |
| `CookLog.md` | Append-only: suggested / cooked / ignored | sweep + reconciliation |
| `Restock.md` | Append-only: purchases and closes, with prices (§15) | receipt capture + sweep |
| mirror `.md` files | Derived copy of the Notes recipes | sync |

**Only top-level `.md` files in `FOLDER` are recipes.** Subfolders hold clients, ops docs and their data — `_fridge-bot/`, `_ops/`. Never sync into them, never clean them up, and never grep them for ingredients: source code and reference docs are full of food words, and an unconstrained grep will offer a test file as a recipe. This has already happened once.

**One list, one job.** `GROCERY_LIST` answers *what do I buy*; `CAPTURE_LIST` answers *what did I just bring home*. Keep scaffolding that must live in `GROCERY_LIST` inside a single `At the store` section so auto-categorization can't scatter it.

**Structure lives in lists and sections, not tags.** A tag adds a colored word to every title, costs a filter click to see, and has to be kept consistent by hand; a section is visible without doing anything.

**Two invariants:** store only the use-by date, never urgency — tiers compute against today. And reminders are dumb renderings of state; the sweep owns all logic.

## 2. Lead time — when the nudge must come early

A 4:30 PM reminder assumes cooking can start at 4:30. Often it can't, and then it is worse than useless because it looks like the system worked.

| Blocking step | Lead | Nudge |
|---|---|---|
| Fridge-thaw a protein over ~1 lb | 12–24h | `NIGHT_BEFORE_ALERT`, previous day |
| Cold-water thaw, or thin/small frozen items | 1–3h | `MORNING_ALERT` |
| Marinade under 12h | 1–12h | `MORNING_ALERT` |
| Overnight marinade | 12h+ | `NIGHT_BEFORE_ALERT`, previous day |
| Day-old / cold rice required | 3h+ | `MORNING_ALERT` — cook and chill it |
| Dough rise or proof | 2–5h | `MORNING_ALERT` |
| Braise or simmer over 2h | — | `MORNING_ALERT`, state a start-by time |
| Shopping is the only gap | — | `MORNING_ALERT` + store geofences |
| None | — | `COOK_ALERT` |

1. **The title names the action for the EARLIEST moment, not the dish.** One title must work at both alerts, so the step with the deadline wins: `Thaw beef this morning — Picadillo tonight`.
2. **Night-before cases get their own reminder on the previous day** — the one deliberate exception to the one-per-day cap.

**Check whether a required item lives in `FREEZER_LIST`,** not just whether it exists. A perfect match needing frozen protein that fires at 4:30 PM is a failed reminder.

## 3. Capture

**Read `Patterns.md` first.** Don't re-ask a question it already answers.

**The best capture moment is leaving a shop, not standing at the fridge.** A fridge photo shows everything including what's already tracked, and says nothing about age. A receipt says exactly what's new, what's sealed, when it was bought — and what it cost.

**Exit geofences make that automatic.** One reminder per regular store in `CAPTURE_LIST`, location **Leaving**, titled `Snap the receipt — <store>`, noting that bags on the counter work too. Arrive triggers stay in `GROCERY_LIST` under `At the store` and do the opposite job — surfacing the buy-list on the way in, and carrying the duplicate check (§15) in their notes.

Arrive and exit triggers for the same store must point at the **same branch**. Different branches means one never fires, and nothing reports the mismatch.

Accept: photo, typed list, or receipt. Record per item: name, **quantity and container state**, date added, printed date if visible. "Cilantro (loose bunch, crisper drawer)", not "greens" — the reminder has to match the physical object.

### Sort what arrives. Never reject it.

**Nobody answers "what's in your fridge" the way you meant it.** Asked that question, people send their whole kitchen — spices, cans, oil, rice. That is not a wrong answer to correct. It is a list that belongs in more than one place, so put it in the right places and say what went where.

| Bucket | What lands there | Gets a date? | Gets nudged? |
|---|---|---|---|
| **Tracked** | perishables | yes | yes, until closed out |
| **Pantry** | spices, cans, oil, vinegar, rice, flour, sugar, frozen things | no | never |
| **Counter** | onions, potatoes, garlic, winter squash | no | never |

The last two are still worth keeping — they are what makes "can I cook X tonight" answerable. They just have no clock on them.

**Never reply with a count of zero.** Someone who sent their spice rack must not read "Logged 0 items" as a failure. Lead with whatever the list actually turned out to be.

**Match on whole words, not substrings.** Every one of these broke a real capture:

| Pantry | Tracked | The trap |
|---|---|---|
| ground ginger | ground **beef** | `ground` is a pantry modifier |
| dried parsley | parsley | `dried` is too |
| coconut milk | oat milk | `milk` matched a can |
| black pepper | bell pepper | bare `pepper` is produce |
| black beans | green beans | bare `bean` is produce |
| Calrose rice | cooked rice | a leftover, not a grain |
| garlic powder, garlic paste | garlic | counter rules need whole words |
| peanut butter, butter | butternut squash, buttermilk | `butter` is a substring of both |
| minced garlic | minced beef | `minced` is a pantry modifier |

### A sentence is not an item, and it is usually a correction

**Prose must never be logged as food.** "these items are all from the pantry" is a 35-character sentence, and logging it produces a dated fridge item with a clause for a name that then turns up in a nudge. A list has commas or few function words; prose has several words and the small words that glue them together.

**When the sentence is a correction, act on it.** The user telling you the sort was wrong is the single most important thing to get right, because it is the only way they can fix your guess without learning a command.

- "those are pantry" / "that's all in my cupboard" / "none of these go bad" → move the last captured list out of tracking
- "those are fridge" / "those are perishable" / "track these" → move them back
- **Negation flips the bucket.** "none of these go bad" means the opposite of "these go bad". A bare leading "no" does not — in "no, those go off quickly" it is a discourse marker.
- A comma or a newline means they are listing food, not correcting you, even if a keyword is in there.

**One exception, and it is a safety one: never move raw meat or fish out of tracking on a vague instruction.** A pantry item is never nudged again, so obeying would quietly stop watching raw chicken, and the cost of being wrong there is not a wasted bunch of parsley. Move everything else in the list, name what you held back, and offer to remove it outright.

### Nothing is lost silently

- A fragment too long to be an item name gets **named back to the user**, not dropped.
- "ok", "thanks", "yes" are answers to you, not food. Logged, each becomes a five-day guess in tomorrow's nudge.
- Re-sending a list **moves the date, it does not add a second copy**. Two cartons of milk mean one item with a later date, or you nudge twice for one carton.
- Every capture is one **batch**, so the last one can be taken back whole.

### A receipt is a diff, not just a capture

| On the receipt | On the list | Means | Do |
|---|---|---|---|
| no | yes | **missed** | leave it on the list |
| yes | no | **unplanned** | feeds cadence (§15) |
| yes | yes | **bought** | tick it off |

The third row is the quiet win nobody asks for: the grocery list clears itself, with no inference and no way to be annoyingly wrong.

**Tick confidently, flag missing timidly.** Receipts read `GV WHL MLK 1G`, not "whole milk". A skipped auto-tick is invisible; saying he forgot the milk while he is holding the milk is the confidently-wrong failure this system exists to prevent.

**Timing decides whether a missing item is worth naming.** Still in the shop, say so. Once he has left, don't — "you forgot the milk" at the exit is a message to turn around in the car park.

### What to take off a receipt, and what to leave

Every food line becomes a `bought` line in `Restock.md` with its price and the store (§15).

**Food lines only.** Never the card digits, never the receipt total, never non-food lines — pharmacy, household, anything else in the basket. A receipt is a financial document; only the part that is about food belongs in the log.

Reading a receipt needs vision. Fine on this client; not available to the Telegram client without an API key.

**In the fridge ≠ tracked.** Condiments that live in the fridge but keep for months go in `Pantry.md` marked `(fridge)`. Tracking them generates reminders that get dismissed, and dismissal is the habit that kills the system.

**When a capture reveals a new default**, append it to `Patterns.md` so the question dies.

## 4. Use-by date

Printed or stated date always wins. Otherwise the **low end**:

| Item | Days |
|---|---|
| Raw chicken, ground meat, fish, shellfish | 1–2 |
| Raw steaks, chops, roasts | 3–5 |
| Cooked leftovers, cooked grains, soups | 3–4 |
| Opened deli meat, opened tofu, cut fruit | 3–5 |
| Leafy greens, berries, fresh herbs, mushrooms | 3–5 |
| Broccoli, asparagus, green beans, zucchini | 3–5 |
| Opened bacon, opened hummus, opened dairy milk | 7 |
| Opened oat/nut milk | 7–10 |
| Soft cheese, opened | 7 |
| Yogurt | 7–14 |
| Peppers, cucumbers, grapes | 7 |
| Hard cheese, opened | 21 |
| Carrots, cabbage, citrus, apples | 21+ |
| Eggs | 21+ |

Not in the table: estimate from similar foods, mark *(est.)*.

**Sealed vs opened is a 5x difference on tofu and dairy.** Ask unless `Patterns.md` answers it. If the answer never comes, don't quietly pick one and bury the item in a group — give it its own reminder whose title asks the question.

Whole onions, potatoes, garlic and winter squash keep better OUT of the fridge — say so rather than tracking them.

## 5. Urgency tiers — computed, never stored

| Tier | Days left | Label | Action |
|---|---|---|---|
| 0 | past date | **Check before eating** | Inspect. Raw meat or seafood: toss |
| 1 | 0–1 | **Tonight or freeze it** | Both options, always named |
| 2 | 2–4 | **Plan this week** | A plan, not a panic |
| 3 | 5+ | **Fine for now** | Logged, not his problem |

Tier 0 stays separate from tier 1 — the action is *inspect*, not *cook*. `Use First` is a filtered VIEW, not a second home; its Include Past Due flag is load-bearing.

## 6. Risk class — drives priority AND persistence

| Class | Items | Priority | Rolls forward | Then |
|---|---|---|---|---|
| **Red** | Raw meat, poultry, fish, shellfish | High | use-by + 1 day | Toss prompt, no recipe |
| **Yellow** | Leftovers, opened dairy, cut fruit, greens | Medium | use-by + 3 days | "Check it, then decide" |
| **Green** | Hard cheese, carrots, citrus, eggs | Low or none | use-by + 7 days | Low-key nudge |

Priority encodes **how bad it is to miss**, not when.

## 7. Reminder anatomy

One parent per day, one subtask per expiring item. Title carries the action for the earliest moment; subtasks carry one item each; notes carry the ingredient split, alternates, sync date and caveats; URL carries the recipe link; priority carries risk class.

**Every grouped reminder needs notes.** A title listing four items can't say which expires when, and the next sweep can't re-date the survivors from a title alone.

**Never overstate readiness.** `Ready` and `Need N` are claims about the whole ingredient list. If any ingredient is `?` in `Pantry.md`, the honest title is `check pantry`, and the notes name the unverified items.

**Never put money in a nudge.** No prices, no "that cost $2.49", no running total. A use-it-tonight reminder carrying a price tag is guilt with a number attached. Dollars live in the scorecard (§17) and in answers he asked for (§19).

**Keep parseable dates out of titles.** Reminders reads them and silently attaches a due date.

Dates always `Ddd Mon D`, with `(today)` / `(tomorrow)` / `(2 days past)` computed at read time. Plurals agree with the count.

## 8. Recipe sync

Notes is canon; the folder is a mirror. In the daily sweep: open Notes, Recipes folder, sorted by **Date Edited**; pull anything edited since `.last-sync`; update it. Sorting by edited date, not filename, catches **edits**, not just new notes.

Never write to Notes. A vanished note does not delete its file — mention it at reconciliation.

**Staleness is visible:** every reminder built on a recipe carries `recipes last synced <Ddd Mon D>`. Do not drop it.

## 9. Recipe matching

Grep **only the top-level `.md` files** in `FOLDER` — `find FOLDER -maxdepth 1 -name '*.md'`. A recursive grep reaches into `_ops/` and `_fridge-bot/` and matches food words in code and docs.

Rank by: items rescued (desc), ingredients to buy (asc), lead time (asc), cook time (asc), then **cook history**.

**Cook history matters.** Read `CookLog.md`. A recipe cooked before ranks above one never cooked; suggested three times and never cooked drops below everything. Sixty recipes on file does not mean sixty in rotation.

Cross-check against `Pantry.md` — anything `?` is unconfirmed, not present. Check `Patterns.md` for never-stocked items and count those as buys.

**Weight base builders heavier than single spices** — in this kitchen, sofrito, achiote, sazón, Maggi Jugo. Some never appear in recipe files at all.

**Fallback:** nothing matches → a weeknight idea from expiring items plus `Pantry.md` staples, labelled *(suggested, not from your notes)*.

## 10. Confirmation, and the leftovers loop

**Ticking the checkbox is the confirmation.** Parent ticked → whole group; one subtask → that item. Said in chat → same effect. Every close appends a line to `Restock.md` (§15).

**Cooking creates food. Catch it.** When a cook-reminder is ticked, the next sweep asks one question: *leftovers?* If yes, log them as cooked leftovers — 3–4 days, yellow. Cooked leftovers are where most household waste happens and they enter the system nowhere else. Append the outcome to `CookLog.md`.

**A ticked `Snap the receipt` with no photo means nothing was bought, or the prompt was dismissed.** Don't assume a shop happened.

**Freezing is a win, not a fallback.** Two minutes versus forty.

## 11. Daily sweep

1. Recipe sync (§8).
2. Read `FRIDGE_LIST`, including items completed in the last 7 days.
3. Ticked → handled. Drop them, append each to `Restock.md`. **If it was a cook-reminder, ask about leftovers (§10).**
4. Compute `days_left`. Bucket into tiers.
5. Tier 0 and 1 belong in **today's** parent.
6. Past class budget → toss prompt, then remove.
7. Re-match recipes. Check lead time (§2) and frozen dependencies before choosing the time.
8. Rewrite today's parent. Delete any parent left empty.
9. Append to `CookLog.md`. Run §15: add anything due to `GROCERY_LIST`, refresh the arrive triggers' duplicate notes.

**Degradation:** needs the machine awake. If unreachable, existing reminders still fire from iCloud — they just don't roll, re-match or re-sync. Never claim a fresh match that didn't happen.

## 12. Weekly reconciliation

List everything open, grouped by tier, and ask for one batched reply. Without it the list fills with food long gone and he stops trusting the reminders.

Also: ask whether he's shopped (§3), surface overdue items, mention recipe files whose Notes source vanished, carry restock notes (§15), append anything learned to `Patterns.md`.

Never delete a reminder just because its date passed.

## 13. Freezer

On "froze X": remove from `FRIDGE_LIST`, add to `FREEZER_LIST` due 90 days out, no priority.

**Batch, don't itemize.** A freezer inventory logged at once gets ONE reminder with items in the notes. Fourteen reminders on one day is the wall this system prevents.

When freeze dates are unknown write `logged <date>`, never `frozen <date>`, and say in the notes that it's a logging date.

Never escalates, never gets a toss prompt — frozen food stays safe indefinitely at 0°F. Say that in the notes, or a December reminder about September meat reads as an alarm.

## 14. Pantry

`Pantry.md` is reference data. No dates, no tracking.

- plain = has it · `(low)` = last of it · `(out)` = gone · `?` = unverified · `(fridge)` = in the fridge but keeps for months
- `(low)` and `(out)` become reminders in `GROCERY_LIST`
- Update only when he mentions it. Never audit unprompted.
- **Restructuring loses entries.** Diff before and after, or use targeted edits.

When asking him to confirm `?` items, **show the items, not the count**. Ask for what he does NOT have — always the shorter list.

Do **not** build a quantity-tracked pantry. Only useful if accurate, accuracy needs logging every partial consumption, wrong within a week. The duplicate check (§15) needs presence, not count.

## 15. Recurrence: restock, duplicates and cost

A purchase, plus the next purchase of the same thing, is one cycle; three is a cadence. **One cadence answers two questions** — when something is due, and when it very much isn't. The same log, with prices on it, answers a third: what the waste cost.

### The log

`Restock.md`, append-only, two event kinds:

    2026-09-28 | milk     | bought | 4.99 | Safeway
    2026-09-28 | cilantro | bought | 2.49 | Safeway
    2026-10-05 | milk     | used   |      |
    2026-10-02 | cilantro | tossed |      |

`bought` lines come from the receipt (§3). `used` / `frozen` / `tossed` come from a tick. **Price rides the `bought` line only** — a toss gets its cost by joining back to the most recent `bought` of that item. When there is no match, the item still counts toward the toss count but not the dollar figure, and any report says how many were priced.

This cannot be reconstructed afterwards — Reminders doesn't keep completed items indefinitely and the sweep only looks back 7 days. Append only; never rewrite history.

| Signal | Reads | Produces |
|---|---|---|
| **Cadence** — how often it returns | "milk, ~8 days, 3 cycles" | A restock suggestion |
| **Outcome** — how it ended | "cilantro, tossed 3 of 4" | Buy smaller, or stop buying |
| **Cost** — what the tossed ones cost | "~$20 binned last month" | The toss count with teeth |

**Only `used` counts toward cadence. `tossed` is an anti-signal.** A detector counting every reappearance will help him re-buy the cilantro he bins every time — the system working against its own purpose.

**The bar is three completed cycles with intervals that agree.** Two points is a line, not a pattern. Require gaps within roughly a third of their mean, and state the cycle count when reporting one.

### Direction one: due

**Stay silent until there's evidence.** Milk takes about a month, slower items a season. Say one line at setup — *over time I'll notice what you re-buy and ask about it* — and nothing else.

**Ask at evidence, never at onboarding.** An onboarding toggle takes consent at the moment of least information, for something that won't act for a month. Ask once, per item, with the finding in hand:

> Milk's come back about every 8 days, three times running. Want me to mention it when you've been out a couple of days?
> Yes · Not milk · Don't do this at all

The third option is a global off without a settings screen. The answer becomes a `Patterns.md` line — keeping the record of what the system watches in a file he can open and edit is a better answer to "is this creepy" than any reassurance.

**Report a state, never a failure.** `Milk's been on your list since Tue Sep 22`, not `you forgot the milk`. A state has no timing dependency; a reprimand works only in a narrow window and, if wrong, is an accusation to argue with.

### Direction two: not due — the duplicate check

**It fires on ARRIVING, never on the receipt.** Post-purchase, "you already had milk" is guilt with no remedy. It belongs in the notes of the `At the store` trigger.

**Purchase recency beats inventory.** `Restock.md` saying he bought milk two days ago is a logged fact; `FRIDGE_LIST` saying he *has* milk is an inference that decays the moment he drinks it without ticking. Lead with recency.

**It's a cupboard problem more than a fridge problem.** He opens the fridge twice a day. He cannot see that he already owns three cans of tomato paste. Weight `Pantry.md` above `FRIDGE_LIST`.

**Never instruct. Report, and let him overrule.**

> Already here: milk (bought Mon, usually lasts 8 days), tomato paste, berbere

The inverse failure is worse than the duplicate it prevents: a wrong "you already have it" costs the item, the trip and every future line's credibility. Cap it at a handful of items.

### Cost — what prices are for, and what they are not

**The point is not spend.** A bank totals groceries better than this ever will. What this system uniquely knows is **what the food he threw away cost**, which turns the toss count from an abstraction into a number that stings appropriately.

**Report it loosely, never to the cent.** OCR is fuzzy, promotions and weight-pricing distort line prices, and a half-drunk $4.99 carton binned was not $4.99 of waste. Round hard, say "about", give a range if it helps.

**The long payoff is drift, not budgeting.** The same basket six months apart says what his actual groceries cost now versus then — something no bank app can compute, because it doesn't know a basket from a basket.

**Rejected: cross-store price comparison as a nudge.** Noisy across different sizes, promos and products, and it turns a waste system into a shopping optimizer. If he asks directly, answer with the caveat; never volunteer it.

**Backfill is impossible.** Prices start accumulating from the next receipt. Say so rather than showing a low first month as progress.

### Volume

Restock notes ride the weekly check-in or an existing daily nudge. Duplicate notes ride the arrive trigger's **notes**, never its title. Cost appears only in the monthly scorecard and in answers he asked for. None of the three is ever its own push.

## 16. Scheduled tasks

Use `create_trigger`. Never the local cron tools.

| Task | Cadence | Does |
|---|---|---|
| Daily sweep | Daily 8:00 AM | §11 |
| Weekly capture + reconciliation | Sun 10:00 AM | §3 and §12 |
| Monthly scorecard | 1st, 10:00 AM | §17 |
| Annual pantry audit | Yearly | §14 |

**Declare the recipe folder on every task.** Tasks do NOT inherit folders connected to the chat — `folders_state` returns `NONE` and the run silently can't read recipes. Pass `folders` explicitly and verify `FOLDERS_STATE_PRESENT`.

**Turn notifications on while the system is unproven.** A sweep that says nothing on a quiet day and a sweep that failed look identical from the outside.

**Hard cap: one parent reminder per day, one check-in per week.** Only exception is a night-before prep reminder (§2). Geofenced triggers don't count — they fire on place, not time.

## 17. Monthly scorecard

Count: items logged, items ticked, **items that reached a toss prompt and roughly what they cost**, recipes suggested vs cooked, own-notes matches vs fallbacks, restock suggestions vs bought, duplicates flagged vs bought anyway.

The toss figure is the number that matters. Lead with it, in dollars when enough lines are priced, and say how many were — *"about $20 across 9 items, 6 of them priced"*. One table, one sentence, nothing more.

If ticks fall or tosses climb, name the likeliest cause: wrong reminder time, notifications not landing, reconciliation skipped. Restock suggestions that go unbought mean the cadence is wrong. Duplicate flags he buys through mean the inventory is stale, and the flag should go quiet rather than louder.

Never compare the waste figure to a budget or a target. It is a measurement, not a verdict.

## 18. Onboarding — orient by demonstrating, not describing

A description of what the system does earns nothing. The user cannot tell whether it works, what it will do tomorrow, or how to get out of it when it gets something wrong. **Nothing is explained before the user has watched it act on food of theirs.**

Four steps, in this order for a reason:

1. **One item, not a list.** A list is a chore before any trust exists. One item is enough to show the dating — and to admit the date is a guess when it is one. If the first thing they name is a spice, say so and invent no date; a fake demo costs more than a slow one.
2. **The sort, taught by doing.** Ask for something that does *not* go off. They watch their own spice land in the pantry instead of reading a rule about it.
3. **The time, as a number.** "Once a day" is not a promise anyone can hold you to; "08:00" is. Buttons, not typing, and store it **per person** — 08:00 is not everyone's morning.
4. **The way out, before it is needed.** Undo and the plain-language corrections, shown while nothing is at stake, on a **real nudge with live buttons** — not a mock-up.

Then **say what silence means**: if nothing needs using, nothing arrives. This is the line that makes a daily message tolerable, and it is the one people are never told.

Rules that hold throughout:

- Buttons over typing wherever a question has a fixed set of answers.
- **Plain words, short sentences, no dashes** in anything the user reads. The doctrine here uses them; the product does not.
- **Every step takes a skip**, and skipping leaves no half-finished state.
- Resume, never restart: state survives a restart, and a second `/start` must not cost someone their fridge.
- No scheduled nudge fires at someone mid-onboarding.
- An unreadable answer re-asks the same question. It does not advance.

## 19. Tone

Flat and factual. "Chicken, 2 days past. Check it." Never urgent, never scolding, no guilt. A month of waste is information, not a failing — and that holds double once it has a dollar sign on it.

## 20. Answering questions

**This is the only channel he opens.** The one-per-day cap exists to stop unsolicited noise; a question he asked carries no such cost, so everything the cap suppresses can live here.

**Every answer names its source and its age.** These files decay at different rates — `Restock.md` is a log of facts, `FRIDGE_LIST` is an inference that rots the moment he eats something without ticking it. "From `Pantry.md`, last touched Sep 23" costs four words and is the difference between an answer and a guess.

**From the fridge and freezer**

- *"What's in my fridge?"* — sorted by use-by, tier labels as headers, overdue flagged. **Say when the list was last updated.** If nothing has been captured or ticked in over a week, lead with that, not with the list.
- *"What can I cook right now?"* — cross with `Pantry.md`; recipes needing nothing bought AND no lead time (§2).
- *"What can I make in 20 minutes?"* — recipe notes carry cook times unevenly. Answer from the ones that state a time, and say how many you couldn't judge.

**From `Pantry.md`**

- *"What am I out of?"* — `(out)` first, then `(low)`.
- *"Do I already have X?"* — recency from `Restock.md` first, presence second (§15).
- *"What can I make from the cupboard alone?"* — no fridge, no shopping. The bad-day question.

**From `Patterns.md`**

- *"Can I use X instead of Y?"* — the substitutions section is built for this.
- *"Why is this so salty?"* — kitchen quirks. In this one, all three cooking wines are salted.
- *"What do I always have?"* — the always-on-hand list, so he can plan against it.

**From `CookLog.md`**

- *"What haven't I made in ages?"* — recipes with no cooked line. Early on that is nearly all of them because the log just started — say so rather than implying neglect.
- *"Why do you keep suggesting that?"* — the declines and their reasons are logged. Read them back.

**From `Restock.md`, once it has data**

- *"What do I always run out of?"* — 3+ `used` cycles, shortest cadence first, count shown.
- *"How long does X last me?"* — the mean interval, with the count.
- *"What do I throw away most?"* — `tossed` by frequency, with rough cost. **The most important question in the system**, answerable on demand rather than only monthly.
- *"What did I waste this month?"* — approximate dollars, with how many lines were priced.
- *"Is X getting more expensive?"* — same item, earliest vs latest `bought` price, with dates and a caveat about sizes and promos.

**Answer honestly, or not at all**

| Asked | Answer |
|---|---|
| "How many cans of tomato paste?" | Presence, not count — deliberately (§14). Don't guess a number. |
| "How much did I spend on groceries?" | Only food lines from receipts he sent are logged — an undercount, not a total. Point at his bank. |
| "Is this still safe to eat?" | Senses, then Safety below. Never a confident yes. |
| "What's the healthiest thing here?" | No nutrition data. Don't infer it from ingredient names. |

- *"Add this recipe"* — he adds it in Notes. Never write to Notes.

## Safety

Quality estimates, not food-safety guarantees. If asked whether something is safe: smell, look, texture, and throw out raw meat or seafood past its date. Red-class items get one roll then a toss prompt — a safety line, and it does not bend.
