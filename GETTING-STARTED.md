# Getting started with Save Your Food

You have the bot running (if not, start with [INSTALL.md](./INSTALL.md)). This page
is the first day: what setup does, how to add food, and what the daily reminder
asks of you. Five minutes.

**Agents:** this page is for the person. Walk them through it in order, and send
them the Telegram messages to try. You can check what the bot will say without
Telegram (see the end of this page).

---

## 1. Setup: send `/start`

The bot walks you through four short steps, each one on your own food rather than a
description:

1. **Tell it one thing in your fridge.** It works out roughly when it turns, and
   says when that's a guess.
2. **Tell it something that doesn't go off**, like a spice. You'll watch it land in
   the pantry, which is never nagged about.
3. **Pick when the daily reminder arrives**, with buttons.
4. **See how to undo or correct it**, before you need to.

Any step takes `/skip`, and `/setup` runs it again later.

## 2. Add food: just type it

Send a list, the way you'd write it down:

    milk, spinach, chicken thighs, oregano

It sorts each thing into one of three places:

| Place | What goes there | Reminded about? |
|---|---|---|
| **Fridge** | Things that go off: meat, dairy, greens, leftovers | Yes |
| **Pantry** | Things that keep: spices, cans, oil, rice | Never |
| **Counter** | Onions, garlic, potatoes and the like | No |

Quantities are dropped (`2 bunches cilantro` becomes `cilantro`). If it sorted
something wrong, say `those are pantry` or `those are fridge`, or send `/undo` to
take the whole list back.

## 3. The daily reminder

Once a day, at the time you picked, it sends **one card** listing what to use soon,
with three buttons per item:

| Button | Means |
|---|---|
| ✅ | Used it |
| ❄️ | Froze it (it moves to the freezer list) |
| 🗑 | Tossed it |

Each tap updates the same card. When every line is done the card closes. **If
nothing needs using, nothing arrives**: silence means you're fine.

Raw meat and fish that sit past their date get flagged `long gone, toss it?`.
These are quality estimates, not food-safety guarantees: when in doubt, throw it out.

## 4. Look things up

| Send | You get |
|---|---|
| `/fridge` | Everything tracked, soonest first |
| `/nudge` | The reminder now, instead of waiting |
| `/pantry` | What's remembered but never reminded about |
| `/freezer` | What you froze, with buttons for finished or binned |
| `/month` | What you used in time, and what went in the bin |
| `/help` | The commands |

## 5. Optional extras

- **Start with what's already in your fridge (owner only).** In
  `clients/telegram`, copy `seed.example.json` to `seed.json`, replace the items
  with yours (name, use-by date, risk), then send `/seed`. It only works once, on an
  empty fridge.
- **Share it with your household (owner only).** `/invite` makes a one-time link
  that works for 7 days. `/members` lists who joined, with a button to remove them.
  Everyone shares one fridge.
- **AI mode** (INSTALL step 9): type normal sentences ("put the butter chicken in
  the fridge as leftovers") and send photos of your fridge or a receipt. On a Mac,
  the owner can also send a recipe or a recipe link and save it to the Recipes folder
  in Apple Notes.

## 6. Your data

- `/privacy`: what's kept, where, and who can see it.
- `/clear`: wipe the food, keep your settings.
- `/deleteme`: erase everything about you, after a confirm button.

All of it lives on the computer running the bot, in `fridge.db`.

---

## For agents: checking the bot without Telegram

From `clients/telegram`, none of these needs a token or the network:

    python3 try_chat.py -i          # chat with the real bot logic in the terminal;
                                    # `tap 2 used` presses a card button
    python3 preview.py 2026-11-01   # the messages it would send on that date
    python3 test_logic.py           # the 548 tests; exit code 0 means they pass

Use `try_chat.py` to show the person what a message will do before they send it, or
to reproduce something odd they saw. If the bot logged something strange, have them
send `/fridge` to see what it thinks it holds. A date marked `(est.)` was guessed
because the item isn't in `shelf_life.py`; add it there.

The full command list, invites, AI mode and security notes are in
`clients/telegram/README.md`. The reasoning behind the design is in
`docs/design-decisions.md`.
