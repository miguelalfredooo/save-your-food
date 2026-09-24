"""The fridge itself: storage, capture parsing, and composing the daily nudge.

No Telegram in here either. Everything in this file can be run and checked
without a network, which matters because the transport can't be tested offline.
"""

import os
import re
import sqlite3
from datetime import date, datetime

import shelf_life as sl

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fridge.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    name      TEXT    NOT NULL,
    use_by    TEXT    NOT NULL,   -- ISO date
    risk      TEXT    NOT NULL,   -- red | yellow | green
    estimated INTEGER NOT NULL,   -- 1 if the date was guessed, not stated
    added     TEXT    NOT NULL,
    state     TEXT    NOT NULL DEFAULT 'open',  -- open | used | frozen | tossed
    closed    TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    chat_id   INTEGER NOT NULL,
    key       TEXT    NOT NULL,
    value     TEXT,
    PRIMARY KEY (chat_id, key)
);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# --- capture ---------------------------------------------------------------

# "2 bunches cilantro", "milk x2", "- spinach"
_LEADING_QTY = re.compile(r"^\s*[-*•]?\s*(\d+\s*(x|bunches|bunch|bags?|packs?|lbs?|cans?)?\s+)?", re.I)
_TRAILING_QTY = re.compile(r"\s*[x×]\s*\d+\s*$", re.I)


def parse_list(text):
    """A free-typed list into clean item names. Commas, newlines and bullets all work."""
    parts = re.split(r"[,\n;]+", text)
    out = []
    for p in parts:
        p = _LEADING_QTY.sub("", p)
        p = _TRAILING_QTY.sub("", p)
        p = p.strip(" .\t").strip()
        if p and len(p) < 60:
            out.append(p)
    return out


def add_items(con, chat_id, names, today=None):
    """Returns (added, skipped_outside). Never silently drops anything."""
    today = today or date.today()
    added, outside = [], []
    for name in names:
        if sl.better_outside(name):
            outside.append(name)
            continue
        ub, risk, est = sl.use_by(name, today)
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
            " VALUES (?,?,?,?,?,?, 'open')",
            (chat_id, name, ub.isoformat(), risk, 1 if est else 0, today.isoformat()),
        )
        added.append((name, ub, risk, est))
    con.commit()
    return added, outside


def open_items(con, chat_id):
    rows = con.execute(
        "SELECT * FROM items WHERE chat_id=? AND state='open' ORDER BY use_by ASC",
        (chat_id,),
    ).fetchall()
    return [dict(r, use_by_date=date.fromisoformat(r["use_by"])) for r in rows]


def close_item(con, chat_id, item_id, state):
    con.execute(
        "UPDATE items SET state=?, closed=? WHERE id=? AND chat_id=?",
        (state, datetime.now().isoformat(timespec="seconds"), item_id, chat_id),
    )
    con.commit()


# --- the nudge -------------------------------------------------------------

def at_risk(con, chat_id, today=None):
    """Tier 0 and 1 only — what actually needs a decision today."""
    today = today or date.today()
    return [i for i in open_items(con, chat_id) if sl.tier(i["use_by_date"], today) <= 1]


def expired_past_budget(con, chat_id, today=None):
    today = today or date.today()
    return [
        i for i in open_items(con, chat_id)
        if sl.past_budget(i["use_by_date"], i["risk"], today)
    ]


def compose_nudge(items, today=None):
    """The message body. The title line has to work on a lock screen by itself."""
    today = today or date.today()
    if not items:
        return None

    t0 = [i for i in items if sl.tier(i["use_by_date"], today) == 0]
    t1 = [i for i in items if sl.tier(i["use_by_date"], today) == 1]

    if t1 and not t0:
        hero = t1[0]["name"]
        head = ("Use the %s tonight, or freeze it" % hero if len(t1) == 1
                else "%s and %d more to use tonight or freeze" % (hero, len(t1) - 1))
    elif t0 and not t1:
        head = ("1 item past its date. Check before eating" if len(t0) == 1
                else "%d items past their date. Check before eating" % len(t0))
    else:
        head = "%d to use tonight, %d to check" % (len(t1), len(t0))

    lines = [head, ""]
    if t1:
        lines.append(sl.TIERS[1])
        for i in t1:
            lines.append("  • %s: %s%s" % (
                i["name"], sl.when(i["use_by_date"], today),
                " (est.)" if i["estimated"] else ""))
        lines.append("")
    if t0:
        lines.append(sl.TIERS[0])
        for i in t0:
            note = ". Raw, throw it out" if i["risk"] == sl.RED else ""
            lines.append("  • %s: %s%s" % (
                i["name"], sl.when(i["use_by_date"], today), note))
    return "\n".join(lines).strip()


def compose_inventory(items, today=None):
    today = today or date.today()
    if not items:
        return "Nothing logged. Send me a list and I'll start tracking it."
    out, seen = [], None
    for i in items:
        t = sl.tier(i["use_by_date"], today)
        if t != seen:
            out.append("" if seen is not None else None)
            out.append(sl.TIERS[t])
            seen = t
        out.append("  • %s: %s%s" % (
            i["name"], sl.when(i["use_by_date"], today),
            " (est.)" if i["estimated"] else ""))
    return "\n".join(x for x in out if x is not None).strip()
