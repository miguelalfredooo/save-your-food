# Getting started with Save Your Food

You have the bot running (if not, start with [INSTALL.md](./INSTALL.md)).

**You only need to do one thing to start: next time you go grocery shopping, send
the bot a photo of your receipt.** Everything else on this page can wait until you
want it.

**Agents:** this page is for the person. Give them step 1 and stop there. Bring up
the rest only when they ask, or when the bot's daily card arrives. Don't walk them
through all of it on the first day; that is what makes people give up on a system
like this.

---

## Step 1 · Send a photo of your next receipt

After you shop, open your bot in Telegram and send a photo of the receipt. No
caption needed. You can even do it before `/start`.

The bot reads the food lines (never the card number, the total or anything that
isn't food), logs each item, and works out roughly when each one turns. It replies
with what it added.

Why a receipt rather than a photo of your fridge: a receipt says exactly what's new
and when you bought it. A fridge photo shows everything, including what it already
knows about, and nothing about how old any of it is.

**No receipt handy, or photo reading not turned on?** Type what you bought, with
commas between things:

    milk, spinach, chicken thighs

A photo gets `I can't read photos yet` when photo reading is off. Turning it on is
step 7 of INSTALL.md.

## Step 2 · When the daily card arrives, tap one button per item

Once a day it sends **one card** listing what to use soon, with three buttons per
item:

| Button | Means |
|---|---|
| ✅ | Used it |
| ❄️ | Froze it |
| 🗑 | Tossed it |

Each tap updates the same card. When every line is done, the card closes. **If
nothing needs using, nothing arrives**: silence means you're fine.

That's the whole habit: a receipt photo after you shop, a few taps when the card
comes. Keep doing just that for a week or two.

These are quality estimates, not food-safety guarantees. Raw meat and fish past
their date get flagged `long gone, toss it?`. When in doubt, throw it out.

---

## Later, when you're ready

None of this is needed to get value from the bot. Pick things up one at a time.

**Choose when the card arrives.** It comes at 16:30 unless you picked a time in
`/start`. Send
`/setup` for a short walkthrough on your own food: when the card arrives, how
pantry items work, and how to undo.

**Fix how something was sorted.** Food goes to one of three places: the **fridge**
(reminded about), the **pantry** (spices, cans, oil, rice; never reminded about) or
the **counter** (onions, garlic, potatoes). If something landed wrong, say
`those are pantry` or `those are fridge`. `/undo` takes back the last thing you
added.

**Look things up.**

| Send | You get |
|---|---|
| `/fridge` | Everything tracked, soonest first |
| `/nudge` | The card now, instead of waiting |
| `/pantry` | What's remembered but never reminded about |
| `/freezer` | What you froze, with buttons for finished or binned |
| `/month` | What you used in time, and what went in the bin |
| `/help` | The commands |

**Talk to it normally** (photo reading on): "put the butter chicken in the fridge as
leftovers" works, and so does a photo of your fridge.

**Share it with your household** (the owner only). `/invite` makes a one-time link
that works for 7 days. `/members` lists who joined, with a button to remove them.
Everyone shares one fridge.

**Save recipes** (the owner, on a Mac). Send a recipe or a recipe link and tap Save
to add it to the Recipes folder in Apple Notes.

**Start from what's already in your fridge** (the owner only). In `clients/telegram`,
copy `seed.example.json` to `seed.json`, replace the items with yours, then send
`/seed`. It only works once, on an empty fridge. Most people skip this: the next
receipt fills the fridge on its own.

**Your data.** `/privacy` says what's kept, where and who can see it. `/clear` wipes
the food and keeps your settings. `/deleteme` erases everything about you, after a
confirm button. All of it lives on the computer running the bot.

---

## For agents: checking the bot without Telegram

From `clients/telegram`, none of these needs a token or the network:

    python3 try_chat.py -i          # chat with the real bot logic in the terminal;
                                    # `tap 2 used` presses a card button
    python3 preview.py 2026-11-01   # the messages it would send on that date
    python3 test_logic.py           # the test suite; exit code 0 means it passes

Use `try_chat.py` to show the person what a typed message will do, or to reproduce
something odd they saw. Photos need AI mode and the network, so they can't be tried
here. If the bot logged something strange, have them send `/fridge` to see what it
thinks it holds. A date marked `(est.)` was guessed because the item isn't in
`shelf_life.py`; add it there.

The full command list, invites, AI mode and security notes are in
`clients/telegram/README.md`. The reasoning behind the design is in
`docs/design-decisions.md`.
