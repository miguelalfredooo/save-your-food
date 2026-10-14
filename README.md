# Save Your Food

Use your food before it goes bad. Send a photo of your grocery receipt; it sorts
what you bought, works out roughly when each thing turns, and reminds you what to
use first.

There are four ways to run it. Start at the top; move down only when you want
what the next one adds. Every option runs on your own account, so you pay for
your own use and nobody else's.

| | What it is | What it takes | What you get | What it doesn't do |
|---|---|---|---|---|
| **1 · Paste** | A prompt you paste into any Claude chat | Copy, paste, send a photo. No settings | Food sorted, use-by guesses, what to use first, a list to paste into your reminders | Remind you later, or remember anything |
| **2 · Claude app skill** *(start here)* | A skill you add to the Claude app | About 2 minutes, any Claude plan including Free | Everything in 1, plus a **calendar file with two check-ins a week** | Update the calendar when you eat something, or remember between chats |
| **3 · Your own Telegram bot** | Your bot, with your own AI key | 30 to 60 minutes (less with an AI agent following the guide), a computer that stays on, an AI key billed to you | Reminders that know what's left, "I used the spinach" updates the list, a daily card, sharing with your household | Location reminders, real checkboxes |
| **4 · Apple Reminders** | The original setup, on a Mac | A Mac that stays awake, iCloud Reminders lists, four scheduled tasks | Real checkboxes, reminders at the store, phone sync, "you already have this" checks | Run without a Mac. This one is for tinkerers |

## 2 · Start here: the Claude app skill

1. [Download the skill](https://github.com/miguelalfredooo/save-your-food/raw/main/desktop/save-your-food.zip) (one zip file).
2. In the Claude app, open **Settings → Capabilities** and turn on **Code
   execution and file creation**.
3. Go to **Customize → Skills**, click **+**, then **Create skill → Upload a
   skill**, and choose the zip. (Older versions of the app have this under
   **Settings → Capabilities → Skills**.)
4. Start a chat and send a photo of a grocery receipt.

**You'll know it worked** when Claude replies with your food sorted by when to use
it, and a file called `save-your-food.ics`. Open the file to add your check-ins:
Sundays and Wednesdays at 5pm, and a heads-up the day before anything urgent.
Want other days? Say "make it Mondays and Thursdays".

**Good to know:** the calendar is a snapshot. If you eat the spinach on Monday,
Wednesday's check-in still lists it. Send your next receipt and you get a fresh
file. If that gets old, option 3 keeps track for you.

## 1 · No settings at all: paste a prompt

If you'd rather not touch settings, open [the prompt](desktop/paste-this.md),
copy it into any Claude chat, then send your receipt. It ends with a list you can
paste into your reminders app instead of a calendar file.

**Next step up:** option 2 adds the calendar check-ins.

## 3 · Your own Telegram bot

A bot that lives in Telegram, keeps your fridge list, and sends one card a day
with what to use soon. You make the bot, it runs on your computer, and photo
reading uses your own AI key (OpenRouter, Claude or ChatGPT), usually a cent or
less per receipt. Nothing goes through anyone else's account.

**What you need:** a computer that stays on (a Mac can run it as a service),
Python 3, Telegram, and an AI key if you want photo reading. You can skip the key
and type your food in instead.

**Steps:** [INSTALL.md](./INSTALL.md), written so an AI agent like Claude Code can
follow it end to end and stop only for what you have to do yourself. Then
[GETTING-STARTED.md](./GETTING-STARTED.md) for the first week.

**You'll know it worked** when you send `/start` to your bot and it asks for a
photo of your next receipt.

**Next step up:** option 4, if you're on a Mac and want reminders that know
which shop you're in.

## 4 · Apple Reminders

The original setup, and the most complete: real checkboxes, location reminders,
phone sync and a weekly clean-up, driven by scheduled tasks on a Mac that stays
awake. It takes real setup and some comfort editing files. See
[docs/apple-reminders.md](docs/apple-reminders.md).

---

## The two failure modes it's built around

Systems like this die in one of two ways, and both are design problems rather than
willpower problems.

**Pull-based capture.** A tool for forgetful people that requires remembering to
open it has the failure built in. So capture is pushed: a scheduled check-in, and
in the full setup a geofence that asks for your receipt as you leave the shop.

**No decay.** The system assumes you'll report eating the chicken. You won't. The
inventory fills with food that's been gone for weeks, the reminders start being
wrong, you dismiss them reflexively, and it's dead. So there's a weekly
reconciliation, and every claim carries how old it is.

## What's here

| | |
|---|---|
| `desktop/` | Options 1 and 2: the paste-in prompt and the Claude app skill |
| `clients/telegram/` | Option 3: the Telegram bot |
| `skill/SKILL.md` | Option 4: the doctrine, what to do and why. The main artifact |
| `ops/` | How option 4 drives the apps. Reference, read when needed |
| `docs/` | Why it's built this way, what was rejected, and the option 4 setup |
| `examples/` | Starting shapes for option 4's four data files |

## What it deliberately doesn't do

Quantity tracking. A static dashboard. Unbounded reminders. Prices inside a nudge.
Budgets or targets. Cross-store price comparison. Each of those is explained in
`docs/design-decisions.md`, because the reasons are more useful than the rules.

## Your data stays yours

Options 1 and 2 keep nothing outside your Claude chat and your calendar. Options 3
and 4 keep everything on your own computer. `Pantry.md`, `Patterns.md`,
`CookLog.md` and `Restock.md` are your kitchen, your habits and your shopping;
they're in `.gitignore` and should stay there.

## Safety

This gives quality estimates, not food-safety guarantees. Raw meat and seafood past
their date get thrown out, not cooked. Smell, look, texture, and when in doubt,
bin it.
