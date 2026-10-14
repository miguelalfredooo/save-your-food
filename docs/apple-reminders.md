# Option 4 · Apple Reminders

The original Save Your Food, and the most complete. It watches what's in your
fridge, works out roughly when each thing turns, and sends one reminder a day
naming what to do about it, with a recipe from your own collection where one
fits. Reminders persist until you tick them off as used, frozen or tossed, then
stop cleanly instead of nagging. Send it a recipe as text, a link or a photo of
a cookbook page, and it adds it to your Notes once you say yes. It never edits a
recipe that's already there.

**What you need:** a Mac that stays awake (a sweep drives the Reminders UI
directly), iCloud Reminders, Claude with scheduled tasks, and some comfort
editing files. If that's more than you want, the [Telegram bot](../INSTALL.md)
does most of this with far less setup.

This is one person's working system, published as a reference rather than a
product. The specifics in it (a Puerto Rican / Cuban / Peruvian and Asian
stir-fry repertoire, three particular supermarkets, a pantry where all the
cooking wine happens to be salted) are what make it useful, and are also what
you'll want to replace. Fork it and let it learn yours.

## How it differs from the Telegram bot

**Apple Reminders** has real checkboxes, subtasks, geofences and native phone
sync, and with geofences a receipt prompt as you leave the shop and a check for
food you already have.

**Telegram** (`clients/telegram/`) is the same logic with a chat UI, standard
library only, no dependencies. It runs anywhere: no Mac, no iCloud account, no
device bridge. It loses geofences, and with them the duplicate check and receipt
capture.

They do not share an inventory and are not meant to.

## Setting it up

1. Fill in the four `{{PLACEHOLDERS}}` in `skill/SKILL.md`: your device, your
   iCloud account, your recipe folder, your timezone.
2. Copy `ops/` into your recipe folder as `_ops/`.
3. Create the lists: `Fridge`, `Freezer`, `Groceries`, `Just Shopped`, and a
   `Use First` smart list filtered to Fridge + next 2 days, **Include Past Due
   checked**. That checkbox is load-bearing.
4. Copy the files in `examples/` into your recipe folder, minus the `.example`.
5. Set up the four scheduled tasks in §16. Declare the recipe folder on every one;
   they do not inherit it, and a task that can't read your recipes will run
   happily and silently skip half its job.

**You'll know it worked** when the first scheduled sweep fills `Use First` and a
reminder arrives on your phone naming what to use.

## Keeping it in sync

The skill is the thing that changes; everything else describes it. When it
changes, `skill/SKILL.md` needs re-templating from the installed version and
committing.

A weekly check-in can do this automatically and say nothing unless something is
off. The discipline is worth copying: **one copy of the reasoning, and a scheduled
job that checks it.** Two copies of the same argument in two documents is how both
end up wrong, which is exactly what happened here before the split.
