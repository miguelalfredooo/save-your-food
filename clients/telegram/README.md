# Fridge Loop — Telegram client

The Mac version is v1. This is the same system with a chat UI, for people who
don't have a Mac Mini, an iCloud account set up for it, or the patience for a
seven-step setup.

Standard library only. Nothing to install.

## Running it

**1. Make a bot.** In Telegram, message **@BotFather** and send `/newbot`.
Give it a name. It replies with a token that looks like
`8123456789:AAF...`. That token is a password — don't paste it into a chat,
including a chat with Claude.

**2. Put the token in a config file.** In Terminal:

    cd ~/Recipes/_fridge-bot
    cp config.example.json config.json
    open -e config.json

Replace `PUT_YOUR_BOTFATHER_TOKEN_HERE` with the token. Save and close.

Where there is no file to edit, such as a cloud session holding the token as
a secret, set `TELEGRAM_BOT_TOKEN` instead. A real token in `config.json`
still wins over it. The launchd service below doesn't see your shell's
environment, so it still needs `config.json`.

**3. Start it.**

    python3 bot.py

Leave that Terminal window open. It prints one line and then waits. Ctrl-C stops it.

**4. Message your bot** in Telegram. Send `/start`, then `/seed` to load the
fridge contents as of Sep 23.

## Run it on startup

Running it by hand (above) is fine for trying it out, but a Terminal window
you have to leave open does not survive a reboot or a closed laptop lid. For
a Mac mini that stays on, install it as a per-user launchd service instead:
it starts at login and restarts itself if it ever crashes.

    cd clients/telegram/service
    ./install.sh

Safe to run more than once — it stops any `bot.py` you started by hand first,
and boots out any earlier copy of the service before installing fresh.

    ./status.sh      # running or not, pid, last exit code, and the last
                      # 20 lines of each log
    ./uninstall.sh    # stops it and removes the plist; config.json and
                      # fridge.db are untouched

Logs live in `~/Library/Logs/fridge-loop/bot.log` and `bot.err.log`, rotated
to `.old` by `install.sh` once either passes 5 MB.

The service runs the bot under `caffeinate -i`, so the Mac doesn't idle-sleep
while it's up and the daily nudge still goes out. The display can still sleep.

**Two Mac settings launchd can't handle, both needed for this to survive a
power cut:**

- **Automatic login.** A LaunchAgent only starts once someone is logged in.
  Turn on automatic login for this user (System Settings > Users & Groups >
  Login Options), or the bot stays off after a restart until someone logs in
  by hand.
- **Start up after a power failure.** System Settings > Energy: turn on
  "Start up automatically after a power failure". `caffeinate` keeps a
  running Mac awake, but it can't turn a Mac back on.

## Who can use it

By default the bot answers anyone who finds it. Lock it to yourself by adding
your chat id to `config.json`:

    "allowed_chat_ids": [123456789]

Message **@userinfobot** in Telegram to get your own numeric chat id, add it
to the list, and restart the bot. A chat that is not on the list gets no
reply at all, not even an error, since a reply would confirm the bot exists.

Leave the list empty and the bot prints a warning on startup that it is open
to anyone.

The bot only ever replies in a private chat. In a group, anyone in it could
wipe the shared fridge with `/clear`, and the daily nudge would go out to
everyone in the group.

## Limits

A message over 2,000 characters is refused with a note to send it in a few
smaller messages. A single capture keeps only the first 50 items and says how
many it left out, rather than growing without bound on a huge paste. Each
chat is capped at 20 messages a minute, in memory only; past that, messages
are ignored quietly until the minute rolls over.

`seed.json` is your real fridge, so `/seed` only ever works for the first id
in `allowed_chat_ids`. Anyone else gets the normal help text instead, and if
the list is empty, `/seed` refuses everyone.

## Conversational mode (opt-in)

The default bot understands commands and typed lists via regex and a
keyword table: fast, free, and exact, but it can't read "put butter chicken
in the fridge as leftovers" as an add. `llm_agent.py` is a separate,
self-contained mode that hands every typed message (and now photos too) to a
model instead, so it can read natural phrasing and correct itself in
conversation. Off by default.

**Two providers, same code path.** Pick one with `llm_provider`:

    "llm_mode": true,
    "llm_provider": "openrouter",
    "openrouter_api_key": "sk-or-...",
    "llm_model": "anthropic/claude-haiku-4.5"

or, to run entirely on your own machine with [Ollama](https://ollama.com)
instead, free and offline once the model is pulled:

    "llm_mode": true,
    "llm_provider": "ollama",
    "ollama_base_url": "http://localhost:11434/v1",
    "ollama_model": "llama3.2-vision"

`ollama pull llama3.2-vision` first (needs Ollama running locally). Every
message on OpenRouter costs money on your account; Ollama costs nothing per
message but needs a machine that can actually run the model — a vision
model wants real RAM (roughly 8GB+ free for an 11B model in Q4). The bot
refuses to start with `llm_mode` on and OpenRouter selected with no key set,
rather than silently falling back to a different path.

**Photos work in this mode too.** Send a photo of your fridge or a receipt,
with or without a caption, and it goes to the model as an image alongside
any text you typed — provided the model you picked actually supports vision
("Capabilities: vision" in `ollama show <model>`, or a vision-capable
OpenRouter model). A text-only model just never mentions the photo. Outside
this mode, a photo gets a plain "I can't read photos yet."

This mode is a genuinely different front end, not a layer over the regular
one: a message never reaches onboarding, the sentence/correction logic, or
`parse_list` while it's on. It shares the same `items`/`pantry` tables, so
`/fridge` and the rest still show what it captured, but it does not read
slash commands as commands — the model itself decides what a message like
`/start` means, and its four tools (`add_items`, `update_item`, `remove_item`,
`list_items`) are how it reads and writes your fridge. The daily nudge and
the used/frozen/tossed buttons are unchanged in both modes: they're not an
understanding problem, so the model never touches them.

## What it does

| You send | It does |
|---|---|
| `milk, spinach, chicken thighs` | Logs them, works out roughly when each turns, tells you which to watch |
| `/fridge` | Everything open, soonest first, grouped by urgency, as a card you can tap |
| `/nudge` | The at-risk message on demand, rather than waiting for the daily one |
| `/seed` | Loads `seed.json` once. Refuses if you already have things logged |
| `/help` | The above |

Once a day at 16:30 (change `nudge_hour` in `config.json`) it sends **one**
message, a card, with a numbered line per item and a row of buttons for each:

    1 TO USE TONIGHT, 1 TO CHECK
    ────────────────────────
    CHECK BEFORE EATING
    1 cilantro       1d past

    TONIGHT OR FREEZE IT
    2 chicken thighs   today
    ────────────────────────
    0 of 2 handled
    [ 1 ✅ ] [ 1 ❄️ ] [ 1 🗑 ]
    [ 2 ✅ ] [ 2 ❄️ ] [ 2 🗑 ]

A tap edits the same card: the line becomes `✓ cilantro  used`, its buttons
go, the footer counts up. When every line is handled the card closes with one
drawing (none if everything was tossed). No extra messages arrive.

The card body is a monospace block padded to exactly 24 columns, the same
canvas the drawings use, so every card is the same width on a phone instead of
each bubble sizing itself to its longest line. A long list shows the soonest
15 and says how many it left out. `card.py` has the reasoning.

`/freezer` is a card too, with two buttons per item: ✅ when it is finished,
🗑 if it ended up in the bin. Binning something that had counted as used in
time marks its line `off this month's count`.

`/month` is a card with no buttons: what was used before it went off, then
what was thrown away, each with how much of it could be priced and from
where. Never a net figure between the two, and no dollar amount on a side
where nothing was priced. A month with nothing closed yet stays a plain
line.

Items that sit past their date longer than their risk class allows — 1 day for
raw meat, 3 for dairy and greens, 7 for hard cheese and root veg — are marked
`long gone, toss it?` on their line. They used to get a separate message too.

## What it deliberately doesn't do

No recipe matching, no pantry, no cook log, no scorecard, no geofences. This is
the thinnest loop that can prove whether a Telegram nudge gets answered more
often than a Reminders alert. Everything else is in the `fridge-loop` skill and
can come across once that question is settled.

Photo capture needs a vision model and an API key, so it's not here either —
typed lists only for now.

## Files

| File | |
|---|---|
| `bot.py` | Telegram transport and conversation. The only file that touches the network |
| `fridge.py` | Storage, list parsing, composing messages |
| `card.py` | The fixed-width card the nudge, `/fridge` and `/freezer` are drawn as |
| `shelf_life.py` | The use-by table and risk classes, ported from the skill |
| `test_logic.py` | 331 tests. `python3 test_logic.py` |
| `preview.py` | Renders the messages for any date, no token needed. `python3 preview.py 2026-09-26` |
| `try_chat.py` | Chat with the real handlers in a terminal, no token. `tap 2 used` presses a card button. `python3 try_chat.py -i` |
| `seed.json` | Real fridge contents as of Sep 23, so the test runs against real food |
| `fridge.db` | Created on first run. Your data. Not synced anywhere |

`test_logic.py` and `preview.py` need no token and no network — the logic is
checkable on its own, which is how it was built, since `api.telegram.org` is
unreachable from the environment Claude runs in.

## If something breaks

**"Couldn't reach Telegram"** — the token is wrong, or you're offline.

**Nothing arrives at 16:30** — the Terminal window has to still be open and the
Mac awake. Check the window for errors.

**It logged something odd** — send `/fridge` to see what it thinks it has. The
parser splits on commas and newlines and strips quantities, so
`2 bunches cilantro` becomes `cilantro`.

**Dates look wrong** — anything marked `(est.)` was guessed because the item
isn't in `shelf_life.py`. Add it to the table there.

## Commands

The bot registers these with Telegram on startup, so they show in the `/` menu.

| | |
|---|---|
| a typed list | capture. Sorted into tracked / pantry / counter |
| `/start` | first run walks four onboarding steps; later runs just say hello |
| `/setup` | run the onboarding again |
| `/skip` | leave onboarding at any step |
| `/fridge` | what is tracked, soonest first |
| `/pantry` | what is remembered but never nudged |
| `/freezer` | what you froze, as a card: finished or binned |
| `/month` | what you used in time, and what went in the bin, as a card |
| `/nudge` | what is at risk right now |
| `/undo` | take back the last captured list, whole |
| `/clear` | wipe everything, with a confirmation |
| `/seed` | load `seed.json`, refused if the chat is not empty |
| "those are pantry" | move the last list out of tracking |
| "those are fridge" | move it back |

## What it refuses to do

- **Track a shelf-stable item.** Spices, cans, oil and rice go to the pantry, which is never nudged. A nudge asking whether you used your oregano is the noise that kills these systems.
- **Log a sentence as food.** Prose is either a correction or a miss, never an item.
- **Move raw meat or fish out of tracking on a vague instruction.** Everything else in the list moves; the meat is named and kept.
- **Drop anything silently.** An over-long fragment is named back to you.
- **Stack duplicates.** Re-sending a list moves the date instead.
- **Invent a demo.** The onboarding nudge is a real item of yours with live buttons, or it says there isn't one yet.

## Tests

    python3 test_logic.py

331 tests, no network needed. The interesting ones are the bucket collisions
(`ground beef` vs `ground ginger`, `coconut milk` vs `oat milk`, `butternut
squash` vs `peanut butter`) and the correction phrasings, including negation.

## Delight

`art.py` holds two kinds of drawing, with opposite rules.

**Glyphs are evergreen.** One per category, the same one every time. A can means
pantry, an onion means the counter, a hen means raw poultry, a carton means
dairy. Repetition is the point: used consistently they become a vocabulary, so
you can see which bucket something landed in rather than read that it did.

    pantry      counter      poultry      dairy       greens
    ,-----.       \|/          ,          ____         ,/|
    |=====|      .-'-.        (o)        |\  /|        / /
    | ### |     ( ( ) )      (   )>      | \/ |       / /
    | ### |      '---'        ^ ^        |    |      (_/
    '-----'                              |____|

Full set: pantry, counter, fridge, poultry, meat, fish, greens, dairy, egg,
cheese, leftovers, bread, fruit, frozen.

The can heads the pantry list and the onion heads the counter list in `/pantry`,
which is the most useful thing the set does: it makes the sort visible.

**Frames rotate.** They mark a moment with no food behind it: an empty at-risk
list, the end of setup, a milestone (10, 25, 50, 100, 250, 500 uses).

| | |
|---|---|
| A glyph **must** repeat | or it is not a vocabulary |
| A frame **must not** | or it is not a surprise |

Two cartons in a row is correct: it means two dairy items.

A card gets at most one drawing, when its last line is handled, edited into
the same message. Drawing after every tap turned a three-item nudge back into
six messages.

Where drawings never appear, and why:

| Never | Why |
|---|---|
| A nudge needing a decision | It has to scan on a lock screen. A drawing pushes the item name down. |
| A toss | Food was wasted. A picture over it reads as mockery. One quiet line instead. |
| A question | Art marks an outcome; a disposal prompt is still open. |

Limits: pure ASCII (a Cyrillic `o` renders as an empty box on some phones), 16
characters wide, 6 lines tall, and a `<pre>` block with HTML parse mode, because
Telegram's default font is proportional and destroys columns. Captions carry
food names, so they go through `art.esc`.

The `ascii-art-curator` agent in `.claude/agents/` authors and vets the set.
Nothing is drawn at runtime: the bot is stdlib-only with no model behind it, and
evergreen art would not want it to. A can that came out slightly different each
time would be worse than no can.
