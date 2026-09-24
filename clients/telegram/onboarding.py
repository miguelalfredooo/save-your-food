"""Onboarding: four steps, each demonstrated on the user's own food.

Why it works this way
---------------------
The old opening was a paragraph describing what the bot does. Descriptions do
not earn trust. The user cannot tell whether the thing works, what it will do
tomorrow, or how to get out of it if it gets something wrong. So nothing here
explains a feature before the user has seen it act on something of theirs.

Four steps, in this order for a reason:

  1  ONE item, not a list. A list is a chore before any trust exists, and one
     item is enough to show the dating and to admit the date is a guess.
  2  The sort, taught by doing. The user is asked for something that does not
     go off, so they watch their own spice land in the pantry instead of
     reading a rule about it.
  3  The nudge time, chosen with buttons. "Once a day" is not a promise anyone
     can hold you to. "08:00" is.
  4  The way out, before it is needed. Undo and a plain-language correction,
     shown while nothing is at stake.

Then the last line says what silence means, which is the part that makes a
daily message tolerable: if nothing needs using, nothing arrives.

State lives in the meta table, so a restart mid-onboarding resumes rather than
starting over. Every step takes /skip.

Copy style follows the rest of the bot: plain words, short sentences, no dashes.
"""

from datetime import date

import fridge
import shelf_life as sl

BULLET = "•"
B = BULLET

KEY = "onboarding"
DONE = "done"
STEPS = ("1", "2", "3", "4")


# --- state -----------------------------------------------------------------

def step(con, chat_id):
    row = con.execute("SELECT value FROM meta WHERE chat_id=? AND key=?",
                      (chat_id, KEY)).fetchone()
    return row["value"] if row else None


def set_step(con, chat_id, value):
    con.execute("INSERT OR REPLACE INTO meta (chat_id,key,value) VALUES (?,?,?)",
                (chat_id, KEY, value))
    con.commit()


def active(con, chat_id):
    return step(con, chat_id) in STEPS


def started(con, chat_id):
    return step(con, chat_id) is not None


# --- copy ------------------------------------------------------------------

STEP1 = (
    "I help you use food before it goes bad. One message a day, and only when "
    "something needs using.\n\n"
    "Let's set it up on your real food, so you can see what you're getting.\n\n"
    "Name one thing in your fridge right now. Just one."
)

STEP2 = (
    "Now the part that matters.\n\n"
    "Send me three or four more things. Put something in there that does NOT "
    "go off. A spice, a can, a bottle of oil. Anything."
)

STEP3 = (
    "That's the whole idea. Perishables get a date. Everything else I just "
    "remember.\n\n"
    "When do you want your one message a day?"
)

STEP4_HEAD = (
    "Set. One last thing, and it's the one people need most.\n\n"
    "I will get things wrong. When I do, you don't have to learn a command. "
    "Just tell me:\n\n"
    "    “those are pantry”   moves the last list out of tracking\n"
    "    “those are fridge”   moves them back\n"
    "    /undo                takes back the last list entirely\n\n"
    "Here is what a nudge looks like. Tap one and it stops asking."
)

TIME_BUTTONS = [
    [{"text": "07:00", "callback_data": "onb:time:7"},
     {"text": "08:00", "callback_data": "onb:time:8"},
     {"text": "09:00", "callback_data": "onb:time:9"}],
    [{"text": "12:00", "callback_data": "onb:time:12"},
     {"text": "17:00", "callback_data": "onb:time:17"},
     {"text": "19:00", "callback_data": "onb:time:19"}],
]


def finished(hour):
    return (
        "You're done. Here is what happens from here.\n\n"
        "  %s Every day at %02d:00 I message you, but only if something needs "
        "using. If nothing does, you hear nothing from me. Silence means "
        "you're fine.\n"
        "  %s Bought something? Send it as a list, with commas between things.\n"
        "  %s /fridge shows what's tracked. /pantry shows what I remember. "
        "/help shows the rest.\n\n"
        "That's it. No app, no login, nothing to keep open."
        % (B, hour, B, B)
    )


# --- steps -----------------------------------------------------------------

def begin(con, chat_id):
    set_step(con, chat_id, "1")
    return STEP1


def skip(con, chat_id, hour):
    set_step(con, chat_id, DONE)
    return ("Skipped. Send a list whenever you like, with commas between "
            "things. I'll message you at %02d:00 if anything needs using. "
            "/help shows the rest." % hour)


def handle_item(con, chat_id, text, today=None):
    """Step 1: one item. Returns (reply, next_prompt or None)."""
    today = today or date.today()
    names, too_long = fridge.parse_list(text, report=True)
    if not names:
        if too_long:
            return ("That didn't look like a food name, so I left it out "
                    "rather than guessing. Just one thing, plainly: milk, or "
                    "chicken thighs, or spinach."), None
        return ("I couldn't read a thing in that. Just one, plainly. "
                "Like milk, or chicken thighs, or spinach."), None

    name = names[0]
    skip_it, reason = sl.not_tracked(name)
    if skip_it:
        where = ("on the counter, where it keeps better than in the fridge"
                 if reason == "outside" else "in your pantry")
        fridge.add_items(con, chat_id, [name], today)
        set_step(con, chat_id, "2")
        return ("%s doesn't go off on a clock. I put it %s rather than making "
                "up a date for it. Nothing to nudge you about.\n\n"
                "Send a perishable and you'll see the difference."
                % (name, where)), None

    tracked, _, _, _ = fridge.add_items(con, chat_id, [name], today)
    if tracked:
        _, use_by_date, _, estimated = tracked[0]
    else:
        # Re-running /setup on a name already tracked: add_items just moved
        # its date rather than inserting, so read the refreshed row instead.
        match = next((i for i in fridge.open_items(con, chat_id)
                      if i["name"].lower() == name.lower()), None)
        use_by_date = match["use_by_date"] if match else sl.use_by(name, today)[0]
        estimated = match["estimated"] if match else False
    guess = (" I guessed that from the type of thing it is, not from a date I "
             "read. Move it if you know better."
             if estimated else
             " That's the usual life for %s once it's open." % name)
    set_step(con, chat_id, "2")
    return ("%s: %s.%s" % (name, sl.when(use_by_date, today),
                           guess)), STEP2


def handle_list(con, chat_id, text, today=None):
    """Step 2: the sort, shown on their own list."""
    today = today or date.today()
    names, too_long = fridge.parse_list(text, report=True)
    if not names:
        if too_long:
            return ("Those didn't look like food names, so I left them "
                    "out rather than guessing: " + "; ".join(too_long) +
                    "\n\nPut commas between things, like: milk, cumin, "
                    "spinach"), None
        return ("I couldn't pick anything out of that. Put commas between "
                "things, like: milk, cumin, spinach"), None

    tracked, stable, outside, again = fridge.add_items(con, chat_id, names, today)
    lines = []
    if too_long:
        lines.append("These didn't look like food names, so I left them "
                     "out rather than guessing: " + "; ".join(too_long))
    if tracked:
        if lines:
            lines.append("")
        lines.append("On a clock, so I'll watch these:")
        for name, ub, risk, est in tracked:
            lines.append("  %s %s: %s%s" % (B, name, sl.when(ub, today),
                                            " (guess)" if est else ""))
    if again:
        if lines:
            lines.append("")
        lines.append("Already had %s, so I moved the date instead of adding "
                     "a second one:" % ("this" if len(again) == 1 else "these"))
        for name in again:
            lines.append("  %s %s" % (B, name))
    if stable or outside:
        if lines:
            lines.append("")
        lines.append("No clock, so I'll stay quiet about these:")
        for name in stable + outside:
            lines.append("  %s %s" % (B, name))
    if not stable and not outside and not again:
        if lines:
            lines.append("")
        lines.append("All of those were perishable, so nothing went to the "
                     "pantry this time. Send a spice or a can any time and it "
                     "will land there instead.")
    set_step(con, chat_id, "3")
    return "\n".join(lines), STEP3
