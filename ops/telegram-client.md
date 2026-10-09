# The Telegram client

Operational reference for the `fridge-loop` skill. Read before touching
`_fridge-bot/`.

The same spec with a chat UI, for people without the Mac stack. Standard library
only, nothing to install. Its own SQLite store; it cannot read Apple Reminders and
is not meant to.

## Scope is deliberately thin

Typed capture, one daily nudge, three inline buttons (Used it / Froze it /
Tossed it), per-class disposal prompts. Recipe search reads Notes live, and a recipe sent
as text or a link can be added to Notes after a Save tap (create-only; see
SKILL.md §8a). No cook log, scorecard or geofences. The only question this client exists to answer is whether a chat nudge
gets answered more often than a Reminders alert.

## What ports and what doesn't

| Feature | Ports? | Why |
|---|---|---|
| Capture, tiers, budgets, nudge | yes | pure logic |
| Cadence (§15) | yes | the `items` table already records added, closed and state |
| Restock notes | yes | ride the daily message |
| Duplicate check | **no** | no geofence means no arriving moment to attach it to; degrades to an on-demand question |
| Receipt diff | **no** | reading a receipt needs vision and an API key |
| Recipe matching | yes | reads Apple Notes live, falls back to the last snapshot |
| Recipe adding | yes | text or https link → draft → Save button → new note in Recipes. Never edits a note. Photos not yet |

## Constraints

**`api.telegram.org` is unreachable** from both the device VM and the cloud
container — blocked by egress while other HTTPS works fine. The bot cannot be run
or tested from a Claude session. Build against `test_logic.py` and `preview.py`,
which need no network, and hand the user one command to run it themselves. Say
plainly that the transport is untested rather than implying it works end to end.

**Never ask for the bot token**, and never accept one pasted into chat. It belongs
in `config.json` on their machine.

**Photo capture needs a vision call and an API key.** Until that exists it is typed
lists only — don't imply otherwise in the bot's own copy.

## Running as a service

For a Mac mini that stays on, `clients/telegram/service/` has a launchd
LaunchAgent (`install.sh`, `uninstall.sh`, `status.sh`) instead of a Terminal
window left open. It enforces single-instance itself (bot.py's own
`.bot.lock`) since two copies polling `getUpdates` at once get HTTP 409s and
lose messages. Full instructions are in `clients/telegram/README.md` under
"Run it on startup".
