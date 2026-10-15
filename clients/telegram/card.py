"""The card: one message that holds a whole list and edits itself.

The nudge used to be one summary plus one buttoned message per item, so three
things at risk meant four notifications and twelve meant thirteen. A card is
one message instead. Each item is a numbered line, each open item gets one
row of buttons, and a tap edits the same message in place: the line flips to
its outcome, its buttons go, the footer counts up.

Plain text, not a code block
----------------------------
Cards used to sit in a <pre> block padded to a fixed width, so dates lined
up in a column. That broke for the people who most need it to work: large
text wrapped every padded line, a screen reader read the padding and the
ruled lines, and a tap on a code block copies it. Now each item is one
sentence-like line, "1. Spinach, tomorrow", with any warning in italics on
the line under it and a blank line before the next item. It wraps wherever
the phone likes and reads in order. Headings are bold, in sentence case,
rather than in capitals.

Names, not buttons, carry the item
----------------------------------
A Telegram button label is one line and gets truncated, so the item's name,
date and warning live in the text, and the buttons carry its number and a
word: "1 Used", not "1 ✅", which a screen reader reads as "check mark".

Pure functions only. Nothing here touches the network or the database.
"""

from datetime import date

import fridge
import shelf_life as sl

MAX_ITEMS = 15            # 3 buttons each stays well under Telegram's 100

# What a closed line starts with.
MARK = {"used": "✓", "frozen": "✓", "tossed": "✗"}
OUTCOME = {"used": "used", "frozen": "frozen", "tossed": "tossed"}
STATES = ("used", "frozen", "tossed")
# Something already frozen has no "froze it": only finished, or binned.
FREEZER_STATES = ("used", "tossed")
WORDS = {"used": "Used", "frozen": "Froze", "tossed": "Tossed"}

# Past this many items with buttons, a card shows one row of numbers instead
# of a row of three buttons per item: tap a number, then choose. Fifteen rows
# of [1 Used] [1 Froze] [1 Tossed] is a wall to read before you can answer
# anything.
DIRECT_MAX = 4
PICKER_ROW = 6


# --- keyboards --------------------------------------------------------------

def _data(state, item, freezer):
    return ("frz:%s:%d" if freezer else "%s:%d") % (state, item["id"])


def keyboard(numbered, freezer=False, others=False, pick=None):
    """Buttons for these (n, item) pairs, or None.

    Up to DIRECT_MAX get a direct row each, one tap to answer. More get a
    single row of numbers. `others` adds "Mark another item" for items on the
    card that have no buttons of their own, so nothing is out of reach.
    `pick` fixes the layout: a card keeps the one it was sent with, or it
    would switch from numbers to rows under someone's thumb as they answer.
    """
    if not numbered and not others:
        return None
    states = FREEZER_STATES if freezer else STATES
    if pick is None:
        pick = len(numbered) > DIRECT_MAX
    if not pick:
        rows = [[{"text": "%d %s" % (n, WORDS[st]), "callback_data": _data(st, item, freezer)}
                 for st in states] for n, item in numbered]
    else:
        nums = [{"text": str(n), "callback_data": "pick:%d" % item["id"]}
                for n, item in numbered]
        rows = [nums[i:i + PICKER_ROW] for i in range(0, len(nums), PICKER_ROW)]
    if others:
        # Says what it does and which items: "another" when some already
        # have buttons above it, "an" when it is the only way in.
        label = "Mark another item" if numbered else "Mark an item"
        rows.append([{"text": label + " \u203a", "callback_data": "pickall:0"}])
    return rows


def picker(numbered):
    """A row of numbers for every one of these, for "Mark another item"."""
    nums = [{"text": str(n), "callback_data": "pick:%d" % item["id"]}
            for n, item in numbered]
    rows = [nums[i:i + PICKER_ROW] for i in range(0, len(nums), PICKER_ROW)]
    return rows + [[{"text": "\u2039 Back", "callback_data": "unpick:0"}]]


def actions(n, item, freezer=False):
    """The choices for one picked item, and the way back to the numbers."""
    states = FREEZER_STATES if freezer else STATES
    return [[{"text": "%d %s" % (n, WORDS[st]),
              "callback_data": _data(st, item, freezer)} for st in states],
            [{"text": "\u2039 Back", "callback_data": "unpick:0"}]]


def rel(use_by, today):
    """When it's due, in words: "today", "in 3 days", "2 days past", "Oct 14"."""
    days = (use_by - today).days
    if days < 0:
        return "%d day%s past" % (-days, "" if days == -1 else "s")
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 7:
        return "in %d days" % days
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


def _row(left, right):
    """One line: "3 items, about $12". The phone wraps it, not us."""
    return ["%s, %s" % (left, right) if right else left]


def lines_for(n, item, today):
    if item["state"] == "open":
        line = "%d. %s, %s" % (n, item["name"], rel(item["use_by_date"], today))
    else:
        line = "%s %s, %s" % (MARK[item["state"]], item["name"], OUTCOME[item["state"]])
    extra = note(item, today)
    return [line, Italic(extra)] if extra else [line]


def nudge_title(items, today):
    """The nudge card's heading. With one tier, the heading is that tier,
    which is also the label the card then drops; the count is already in
    the footer. With two, a short count, and the sections keep labels."""
    tiers = [sl.tier(i["use_by_date"], today) for i in items]
    if len(set(tiers)) == 1:
        return sl.TIERS[tiers[0]]
    tonight, check = tiers.count(1), tiers.count(0)
    if tonight + check == len(tiers):
        return "%d tonight, %d to check" % (tonight, check)
    return "%d things to check" % len(tiers)


def esc(text):
    """Escape text for HTML parse mode.

    Food names come from users. One stray angle bracket in "<3 cilantro" and
    Telegram reads the rest of the message as a tag, silently dropping it.
    Anything in an HTML message goes through here.
    """
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


class Bold(str):
    """A body line shown in bold: a section heading."""


class Italic(str):
    """A body line shown in italics: a note about the item above it."""


def _line_html(line):
    if isinstance(line, Bold):
        return "<b>%s</b>" % esc(line)
    if isinstance(line, Italic):
        return "<i>%s</i>" % esc(line)
    return esc(line)


def _html(head, body, closing):
    lines = [_line_html(l) for l in body]
    # Two bold lines in a row read as one heading: space them apart.
    gap = "\n" if body and isinstance(body[0], Bold) else ""
    html = "<b>%s</b>\n%s%s" % (esc(head), gap, "\n".join(lines))
    return html + ("\n" + closing if closing else "")


def render(head, items, today, footer, closing=None, label_one_tier=True,
           notes=None, actionable=None, pick=None):
    """(html, buttons) for a card.

    `items` keep their order for the life of the card, closed or not, so an
    item's number never changes under someone's thumb. Sections follow the
    tier each item was in on the day the card went out, not today, for the
    same reason. `closing` is an already-escaped line under the card, or None.
    `notes` are short sentences under the footer, wrapped to the card.
    `actionable` picks which open items get buttons (all, by default); the
    rest are reachable through "Mark another item".

    A nudge's heading already names its tier when there is only one ("2
    things past their best: check before eating"), so label_one_tier=False
    drops the section label that would repeat it right underneath.
    """
    tiers = {sl.tier(i["use_by_date"], today) for i in items}
    labelled = label_one_tier or len(tiers) > 1
    body, seen = [], None
    for n, item in enumerate(items, 1):
        t = sl.tier(item["use_by_date"], today)
        if t != seen:
            if seen is not None:
                body.append("")
            if labelled:
                body += [Bold(sl.TIERS[t]), ""]
            seen = t
        elif n > 1:
            # A blank line between items: a name, its date and its warning
            # read as one unit, and the eye finds item 7 without counting.
            body.append("")
        body.extend(lines_for(n, item, today))
    body += ["", footer]
    for note in notes or ():
        body += ["", note]
    html = _html(head, body, closing)
    is_open = [(n, i) for n, i in enumerate(items, 1) if i["state"] == "open"]
    act = actionable or (lambda i: True)
    numbered = [(n, i) for n, i in is_open if act(i)]
    return html, keyboard(numbered, others=len(numbered) < len(is_open), pick=pick)


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


def render_freezer(head, items, footer, pick=None):
    """(html, buttons) for /freezer. No tier sections: once frozen, a use-by
    date stops meaning anything, so each line says when it went in."""
    body = []
    for n, item in enumerate(items, 1):
        if n > 1:
            body.append("")
        outcome = item.get("freezer_outcome")
        if outcome:
            body.append("%s %s, %s" % (MARK[outcome], item["name"], OUTCOME[outcome]))
            # A binned rescue comes back off the month. Said once, under its
            # line, as a fact about the figure: no verdict (SKILL §20).
            if outcome == "tossed" and fridge.is_rescue("frozen", item["tier"]):
                body.append(Italic("off this month's count"))
        else:
            when = frozen_on(item)
            body.append("%d. %s%s" % (n, item["name"], ", frozen " + when if when else ""))
    body += ["", footer]
    numbered = [(n, i) for n, i in enumerate(items, 1)
                if not i.get("freezer_outcome")]
    return _html(head, body, None), keyboard(numbered, freezer=True, pick=pick)


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


# --- /month -----------------------------------------------------------------

def _month_side(label, items):
    """One side of the ledger: count and money on a line, then how much of it
    was priced and from where. No dollar figure when nothing is priced, for
    the same reason compose_month gives none: "$0" would claim it cost
    nothing, from no data."""
    total, n, by_source = fridge._price_side(items)
    out = [Bold(label)]
    if not n:
        return out + ["Nothing yet"]
    count = "%d item%s" % (n, "" if n == 1 else "s")
    n_priced = sum(by_source.values())
    out += _row(count, "about $%d" % total if n_priced else "unpriced")
    if n_priced:
        priced = "All priced" if n_priced == n else "%d of %d priced" % (n_priced, n)
        split = ", ".join("%d %s" % (k, src.replace("your ", ""))
                          for src, k in sorted(by_source.items()))
        out.append("%s: %s" % (priced, split))
    return out


def render_month(fig):
    """The monthly report as a card, or None for a month with nothing in it.

    The same ledger compose_month writes as prose, and the same rules (SKILL
    §17): two figures side by side, used first, and never a net between them
    or a claim about what was "saved". No buttons: nothing here needs an
    answer.
    """
    if not fig["rescued"] and not fig["tossed"]:
        return None
    body = _month_side("Used before it went off", fig["rescued"])
    if fig["reversals"]:
        total, n, by_source = fridge._price_side(fig["reversals"])
        money = " (about $%d)" % total if sum(by_source.values()) else ""
        body.append("%d frozen earlier %s tossed this month%s."
                    % (n, "was" if n == 1 else "were", money))
    body.append("")
    body += _month_side("Thrown away", fig["tossed"])

    notes = []
    priced = any(fridge._price_side(fig[k])[2] for k in ("rescued", "tossed"))
    if priced:
        notes.append("Prices are rough estimates, not what you paid.")
    if fig["reconstructed"]:
        k = fig["reconstructed"]
        notes.append("%d tier%s reconstructed from before I recorded %s."
                     % (k, "" if k == 1 else "s", "it" if k == 1 else "them"))
    notes.append("Counts only what you've told me here.")
    for note in notes:
        body += ["", note]
    return _html(fridge._month_name(fig["month"]), body, None)


# --- /pantry ----------------------------------------------------------------

def _names(names):
    """Names on one line, comma-separated: the phone wraps between words."""
    return ", ".join(names)


def render_list(head, sections, footer, notes=None):
    """A card of plain names, no buttons: what was moved, taken back, or is
    remembered. `sections` is [(label, names)]; empty ones are skipped."""
    body = []
    for label, names in sections:
        if not names:
            continue
        if body:
            body.append("")
        body += [Bold("%s (%d)" % (label, len(names))), _names(names)]
    body += ["", footer]
    for note in notes or ():
        body += ["", note]
    return _html(head, body, None)


def render_pantry(head, stable, outside, notes=None):
    """What is remembered but never nudged. Two sections, because pantry and
    counter are the split people get wrong. Names already capped."""
    return render_list(head, [("Pantry", stable), ("On the counter", outside)],
                       "Remembered, never nudged", notes)
