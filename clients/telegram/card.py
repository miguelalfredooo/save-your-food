"""The card: one fixed-width message that holds a whole list and edits itself.

The nudge used to be one summary plus one buttoned message per item, so three
things at risk meant four notifications and twelve meant thirteen, and every
bubble was a different width because Telegram sizes a bubble to its longest
line. A card is one message instead. Each item is a numbered line, each open
item gets one row of buttons, and a tap edits the same message in place: the
line flips to its outcome, its buttons go, the footer counts up.

Why monospace and a fixed width
-------------------------------
The body sits in a <pre> block padded to exactly WIDTH columns, framed by a
rule of the same width. Monospace makes every character the same width, so
every card is the same width on a given phone, and the rule pins it even when
every line is short. WIDTH is art.MAX_WIDTH on purpose: the drawings are drawn
to the same canvas, so a card and the frame that closes it line up.

Names, not buttons, carry the item
----------------------------------
A Telegram button label is one line and gets truncated, so the item's name,
date and warning live in the text, and the buttons only carry its number.

Pure functions only. Nothing here touches the network or the database.
"""

from datetime import date

import art
import fridge
import shelf_life as sl

WIDTH = art.MAX_WIDTH
RULE = "─" * WIDTH
RIGHT = 8                 # the date column: "14d past", "tomorrow", "Oct 14"
MAX_ITEMS = 15            # 3 buttons each stays well under Telegram's 100

# Plain marks, not emoji: an emoji is two columns wide on some phones and one
# on others, which breaks the one guarantee this file makes.
MARK = {"used": "✓", "frozen": "✓", "tossed": "·"}
OUTCOME = {"used": "used", "frozen": "frozen", "tossed": "tossed"}
BUTTONS = (("used", "✅"), ("frozen", "❄️"), ("tossed", "\U0001f5d1"))
# Something already frozen has no "froze it": only finished, or binned.
FREEZER_BUTTONS = (("used", "✅"), ("tossed", "\U0001f5d1"))


def rel(use_by, today):
    """The right-hand column. Short enough to fit RIGHT, relative when near."""
    days = (use_by - today).days
    if days < 0:
        return "%dd past" % -days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 7:
        return "in %dd" % days
    return use_by.strftime("%b ") + str(use_by.day)


def note(item, today):
    """The one warning a line can carry, most urgent first, or None."""
    if item["state"] != "open":
        return None
    if sl.past_budget(item["use_by_date"], item["risk"], today):
        return "long gone, toss it?"
    if item["risk"] == sl.RED and sl.tier(item["use_by_date"], today) == 0:
        return "raw, toss it"
    if item["estimated"]:
        return "date is a guess"
    return None


def _clip(text, width):
    return text if len(text) <= width else text[:width - 1] + "…"


def _row(left, right):
    """left and right on one WIDTH line, or two lines if they will not fit."""
    room = WIDTH - len(right) - 1
    if len(left) <= room:
        return [left + " " * (WIDTH - len(left) - len(right)) + right]
    return [_clip(left, WIDTH), right.rjust(WIDTH)]


def lines_for(n, item, today):
    if item["state"] == "open":
        left = "%d %s" % (n, item["name"])
        right = rel(item["use_by_date"], today)
    else:
        left = "%s %s" % (MARK[item["state"]], item["name"])
        right = OUTCOME[item["state"]]
    out = _row(left, right)
    extra = note(item, today)
    if extra:
        out.append(_clip("  " + extra, WIDTH))
    return out


def _html(head, body, closing):
    html = "<b>%s</b>\n<pre>%s</pre>" % (art.esc(head),
                                        "\n".join(art.esc(l) for l in body))
    return html + ("\n" + closing if closing else "")


def render(head, items, today, footer, closing=None):
    """(html, buttons) for a card.

    `items` keep their order for the life of the card, closed or not, so an
    item's number never changes under someone's thumb. Sections follow the
    tier each item was in on the day the card went out, not today, for the
    same reason. `closing` is an already-rendered art block, or None.
    """
    body, seen = [RULE], None
    for n, item in enumerate(items, 1):
        t = sl.tier(item["use_by_date"], today)
        if t != seen:
            if seen is not None:
                body.append("")
            body.append(sl.TIERS[t].upper())
            seen = t
        body.extend(lines_for(n, item, today))
    body += [RULE, footer]
    html = _html(head, body, closing)
    buttons = [[{"text": "%d %s" % (n, icon),
                 "callback_data": "%s:%d" % (state, item["id"])}
                for state, icon in BUTTONS]
               for n, item in enumerate(items, 1) if item["state"] == "open"]
    return html, (buttons or None)


def frozen_on(item):
    """The day it went in the freezer, as "Oct 3", or "" if unrecorded."""
    stamp = (item["closed"] or "")[:10]
    if not stamp:
        return ""
    d = date.fromisoformat(stamp)
    return d.strftime("%b ") + str(d.day)


def settled(kind, item):
    """Whether a line on this kind of card is finished.

    Depends on the card: freezing milk from a nudge finishes its nudge line,
    while the same milk is still an open line on the freezer card until it is
    used or binned out of the freezer.
    """
    if kind == "freezer":
        return item.get("freezer_outcome") is not None
    return item["state"] != "open"


def render_freezer(head, items, footer):
    """(html, buttons) for /freezer. No tier sections: once frozen, a use-by
    date stops meaning anything, so the right column is when it went in."""
    body = [RULE, "FROZEN ON".rjust(WIDTH)]
    for n, item in enumerate(items, 1):
        outcome = item.get("freezer_outcome")
        if outcome:
            body.extend(_row("%s %s" % (MARK[outcome], item["name"]),
                             OUTCOME[outcome]))
            # A binned rescue comes back off the month. Said once, on its
            # line, as a fact about the figure: no verdict (SKILL §20).
            if outcome == "tossed" and fridge.is_rescue("frozen", item["tier"]):
                body.append("  off this month's count")
        else:
            body.extend(_row("%d %s" % (n, item["name"]), frozen_on(item)))
    body += [RULE, footer]
    buttons = [[{"text": "%d %s" % (n, icon),
                 "callback_data": "frz:%s:%d" % (state, item["id"])}
                for state, icon in FREEZER_BUTTONS]
               for n, item in enumerate(items, 1)
               if not item.get("freezer_outcome")]
    return _html(head, body, None), (buttons or None)


def tally(kind, items, more=0):
    """The footer. A nudge counts what's handled; /fridge and /freezer count
    what's left."""
    total = len(items)
    done = sum(1 for i in items if settled(kind, i))
    if kind == "nudge":
        line = ("All %d handled" % total if done == total
                else "%d of %d handled" % (done, total))
    elif kind == "freezer":
        line = ("%d in the freezer" % total if not done
                else "%d settled, %d left" % (done, total - done))
    else:
        line = ("%d tracked" % total if not done
                else "%d closed, %d left" % (done, total - done))
    if more:
        line += ("\n+%d more, see /fridge" % more if kind == "nudge"
                 else "\n+%d more not shown" % more)
    return line
