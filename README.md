# Fridge Loop

A system for using food before it goes bad.

It watches what's in your fridge, works out roughly when each thing turns, and
sends one reminder a day naming what to do about it — with a recipe from your own
collection where one fits. Reminders persist until you tick them off as used,
frozen or tossed, then stop cleanly instead of nagging.

This is one person's working system, published as a reference rather than a
product. The specifics in it — a Puerto Rican / Cuban / Peruvian and Asian
stir-fry repertoire, three particular supermarkets, a pantry where all the cooking
wine happens to be salted — are what make it useful, and are also what you'll want
to replace. Fork it and let it learn yours.

## The two failure modes it's built around

Systems like this die in one of two ways, and both are design problems rather than
willpower problems.

**Pull-based capture.** A tool for forgetful people that requires remembering to
open it has the failure built in. So capture is pushed: a scheduled prompt, and a
geofence that asks for your receipt as you leave the shop.

**No decay.** The system assumes you'll report eating the chicken. You won't. The
inventory fills with food that's been gone for weeks, the reminders start being
wrong, you dismiss them reflexively, and it's dead. So there's a weekly
reconciliation, and every claim carries how old it is.

## What's here

| | |
|---|---|
| `skill/SKILL.md` | The doctrine — what to do and why. This is the main artifact |
| `ops/` | How to drive the apps. Reference, read when needed |
| `clients/telegram/` | A chat client for people without the Mac stack |
| `docs/` | Why it's built this way, and what was rejected |
| `examples/` | Starting shapes for the four data files |

## The two clients

**Apple Reminders** is v1 and canonical. Real checkboxes, subtasks, geofences,
native phone sync. It needs a Mac that stays awake, because a sweep drives the
Reminders UI directly.

**Telegram** (`clients/telegram/`) is the same logic with a chat UI, standard
library only, no dependencies. It runs anywhere, which is the point — no Mac, no
iCloud account, no device bridge. It loses geofences, and with them the duplicate
check and receipt capture.

They do not share an inventory and are not meant to.

## Setting it up

1. Fill in the four `{{PLACEHOLDERS}}` in `skill/SKILL.md` — your device, your
   iCloud account, your recipe folder, your timezone.
2. Copy `ops/` into your recipe folder as `_ops/`.
3. Create the lists: `Fridge`, `Freezer`, `Groceries`, `Just Shopped`, and a
   `Use First` smart list filtered to Fridge + next 2 days, **Include Past Due
   checked** — that checkbox is load-bearing.
4. Copy the files in `examples/` into your recipe folder, minus the `.example`.
5. Set up the four scheduled tasks in §16. Declare the recipe folder on every one;
   they do not inherit it, and a task that can't read your recipes will run
   happily and silently skip half its job.

For the Telegram client, see `clients/telegram/README.md`.

## What it deliberately doesn't do

Quantity tracking. A static dashboard. Unbounded reminders. Prices inside a nudge.
Budgets or targets. Cross-store price comparison. Each of those is explained in
`docs/design-decisions.md`, because the reasons are more useful than the rules.

## Keeping it in sync

The skill is the thing that changes; everything else describes it. When it changes,
`skill/SKILL.md` here needs re-templating from the installed version and committing.

The weekly check-in does this automatically and says nothing unless something is off.
If you're running this yourself, the discipline is worth copying: **one copy of the
reasoning, and a scheduled job that checks it.** Two copies of the same argument in two
documents is how both end up wrong, which is exactly what happened here before the split.

## Your data stays yours

`Pantry.md`, `Patterns.md`, `CookLog.md` and `Restock.md` are your kitchen, your
habits and your shopping — they're in `.gitignore` and should stay there.
`Restock.md` in particular accumulates what you buy and what it costs. The repo is
the system; your instance is not.

## Safety

This gives quality estimates, not food-safety guarantees. Raw meat and seafood past
their date get thrown out, not cooked. Smell, look, texture — and when in doubt,
bin it.
