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
    batch     TEXT,                     -- one capture's stamp, for /undo
    state     TEXT    NOT NULL DEFAULT 'open',  -- open | used | frozen | tossed
    closed    TEXT
);
CREATE TABLE IF NOT EXISTS pantry (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    name      TEXT    NOT NULL,
    kind      TEXT    NOT NULL,   -- stable | outside
    added     TEXT    NOT NULL,
    batch     TEXT,
    UNIQUE (chat_id, name)
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
    # A db made before /undo existed has no batch column. Add it rather than
    # asking anyone to delete their fridge to get an upgrade.
    for table in ("items", "pantry"):
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
        if "batch" not in cols:
            con.execute("ALTER TABLE %s ADD COLUMN batch TEXT" % table)
    con.commit()
    return con


# --- capture ---------------------------------------------------------------

# "2 bunches cilantro", "milk x2", "- spinach"
_LEADING_QTY = re.compile(r"^\s*[-*•]?\s*(\d+\s*(x|bunches|bunch|bags?|packs?|lbs?|cans?)?\s+)?", re.I)
_TRAILING_QTY = re.compile(r"\s*[x×]\s*\d+\s*$", re.I)


MAX_NAME = 60

# Answers to me, not food. Each of these used to become a five-day guess and
# show up in the next morning's nudge.
CHATTER = {
    "ok", "okay", "k", "kk", "thanks", "thank you", "thx", "ty", "yes", "yep",
    "yeah", "no", "nope", "sure", "cool", "nice", "great", "got it", "done",
    "hi", "hey", "hello", "yo", "sup", "good morning", "good night", "night",
    "please", "sorry", "what", "huh", "why", "test", "testing",
}


def is_chatter(text):
    """True for a whole message that is talking to me rather than listing food."""
    n = text.lower().strip().strip("!?. ")
    return n in CHATTER


# --- sentences, not lists --------------------------------------------------
#
# A list is "milk, spinach, chicken". A sentence is "these items are all from
# the pantry". Both arrive as text in the same box, and until this existed the
# second one became a 38-character fridge item with a five-day date on it.
#
# Two things have to happen. A sentence must never be logged as food. And when
# the sentence is a CORRECTION — the user telling me I sorted their list wrong —
# it has to actually work, because that is the whole point of letting people
# answer in their own words.

# Words that do not appear in food names but hold sentences together.
FUNCTION_WORDS = {
    "a", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be",
    "been", "but", "by", "can", "did", "do", "does", "for", "from", "had",
    "has", "have", "how", "i", "if", "in", "is", "it", "its", "just", "me",
    "my", "no", "not", "of", "on", "only", "or", "should", "so", "some",
    "that", "thats", "the", "their", "them", "then", "these", "they", "this",
    "those", "to", "was", "were", "what", "when", "which", "will", "with",
    "would", "you", "your", "dont", "doesnt", "isnt", "arent", "im", "ive",
    "none", "nothing", "here", "there", "already", "most", "why", "please",
    "remove", "add", "about", "think", "need", "want", "get", "put", "keep",
}

PANTRY_WORDS = ("pantry", "cupboard", "cabinet", "shelf", "shelves",
                "shelf stable", "shelf-stable", "spice rack", "dry goods",
                "not perishable", "dont go bad", "do not go bad",
                "wont go bad", "never go bad", "no expiry", "no expiration")

FRIDGE_WORDS = ("fridge", "refrigerator", "perishable", "goes bad", "go bad",
                "goes off", "go off", "track these", "track them", "track it")

# "none of these go bad" means the opposite of "these go bad", and a person
# correcting me is quite likely to phrase it that way. Bare "no" is deliberately
# absent: in "no, those go off quickly" it is a discourse marker, not a negation.
NEGATORS = ("none", "not", "never", "nothing", "dont", "doesnt", "wont",
            "cant", "isnt", "arent", "without")


def _words(text):
    return [w for w in re.split(r"[^a-z]+", text.lower()) if w]


def looks_like_sentence(text):
    """True for prose. A list has commas or few function words; prose has both
    several words and the small words that glue them together."""
    if "\n" in text:
        return False
    words = _words(text)
    if len(words) < 4:
        return False
    fn = sum(1 for w in words if w in FUNCTION_WORDS)
    if "," in text:
        # "milk, spinach, and some yogurt" is still a list.
        return fn >= 3 and fn / float(len(words)) > 0.4
    return fn >= 2


def correction(text):
    """'pantry', 'fridge' or None — which way the user says I sorted it wrong."""
    n = text.lower()
    # A comma or a newline means someone is listing food, even if a keyword
    # happens to be in there ("pantry staples, milk"). Anything else is prose
    # short enough to be a correction, so let the keywords decide.
    if "," in text or "\n" in text:
        return None
    hits_pantry = any(k in n for k in PANTRY_WORDS)
    hits_fridge = any(k in n for k in FRIDGE_WORDS)
    negated = any(w in NEGATORS for w in _words(n))
    if negated:
        # A negated claim means the other bucket.
        hits_pantry, hits_fridge = hits_fridge, hits_pantry
    if hits_pantry and not hits_fridge:
        return "pantry"
    if hits_fridge and not hits_pantry:
        return "fridge"
    return None


def last_batch(con, chat_id):
    stamps = [r[0] for r in con.execute(
        "SELECT MAX(batch) FROM items WHERE chat_id=? AND batch IS NOT NULL"
        " UNION ALL"
        " SELECT MAX(batch) FROM pantry WHERE chat_id=? AND batch IS NOT NULL",
        (chat_id, chat_id)) if r[0]]
    return max(stamps) if stamps else None


def _join(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def reclassify_last(con, chat_id, target, today=None):
    """Move the last captured list into the other bucket. Returns (names, message).

    This is the escape hatch for my own guess being wrong, in either direction,
    and it has to work on the words a person would actually use rather than a
    command they have to learn.
    """
    today = today or date.today()
    stamp = last_batch(con, chat_id)
    if not stamp:
        return [], "I don't have a recent list to move."

    if target == "pantry":
        rows = con.execute(
            "SELECT name, risk FROM items WHERE chat_id=? AND batch=? AND state='open'",
            (chat_id, stamp)).fetchall()
        if not rows:
            return [], "Nothing in that list was being tracked, so there is nothing to move."

        # Raw meat and fish are the one thing not moved on a vague instruction.
        # A pantry item is never nudged again, so obeying here would quietly stop
        # watching raw chicken — and the cost of being wrong is not a wasted
        # bunch of parsley. Everything else moves; these get named and kept, with
        # a way to remove them outright.
        held = [r["name"] for r in rows if r["risk"] == sl.RED]
        names = [r["name"] for r in rows if r["risk"] != sl.RED]

        for name in names:
            remember(con, chat_id, name, "stable", today, stamp)
        if names:
            marks = ",".join("?" * len(names))
            con.execute(
                "DELETE FROM items WHERE chat_id=? AND batch=? AND state='open'"
                " AND name IN (%s)" % marks, [chat_id, stamp] + names)
        con.commit()

        if not names:
            return [], ("That list is raw %s, so I have kept it tracked rather "
                        "than moving it on a maybe. /undo removes it outright if "
                        "it should not be there." % _join(held))
        msg = ("Moved %d to your pantry, no dates and no nudges: %s"
               % (len(names), ", ".join(names)))
        if held:
            msg += ("\n\nI kept %s tracked. Raw meat and fish are the one thing I "
                    "won't quietly stop watching. /undo if it should not be "
                    "there at all." % _join(held))
        return names, msg

    rows = con.execute("SELECT name FROM pantry WHERE chat_id=? AND batch=?",
                       (chat_id, stamp)).fetchall()
    names = [r["name"] for r in rows]
    if not names:
        return [], "Nothing in that list went to your pantry, so there is nothing to move."
    moved = []
    for name in names:
        ub, risk, est = sl.use_by(name, today)
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,batch,state)"
            " VALUES (?,?,?,?,?,?,?, 'open')",
            (chat_id, name, ub.isoformat(), risk, 1 if est else 0,
             today.isoformat(), stamp))
        moved.append((name, ub, est))
    con.execute("DELETE FROM pantry WHERE chat_id=? AND batch=?", (chat_id, stamp))
    con.commit()
    lines = ["Tracking %d now:" % len(moved), ""]
    for name, ub, est in moved:
        lines.append("  \u2022 %s \u2014 %s%s" % (name, sl.when(ub, today),
                                            " (est.)" if est else ""))
    return names, "\n".join(lines)


def parse_list(text, report=False):
    """A free-typed list into clean item names. Commas, newlines and bullets all work.

    With report=True, also returns the fragments that were too long to be item
    names. They used to vanish without a word, which broke the one promise
    capture has to keep: never drop anything silently.
    """
    parts = re.split(r"[,\n;]+", text)
    out, too_long = [], []
    for p in parts:
        p = _LEADING_QTY.sub("", p)
        p = _TRAILING_QTY.sub("", p)
        p = p.strip(" .\t").strip()
        if not p:
            continue
        if len(p) >= MAX_NAME:
            too_long.append(p[:40].rstrip() + "...")
            continue
        out.append(p)
    return (out, too_long) if report else out


def add_items(con, chat_id, names, today=None):
    """Sort a list into buckets. Returns (tracked, stable, outside, again).

    Nobody answers "what's in your fridge" the way you meant it. People send
    their whole kitchen. That is not a wrong answer to correct \u2014 it is a list
    that belongs in more than one place, so it gets sorted:

      tracked  perishable, dated, nudged until it is closed out
      stable   spices, cans, oil, rice. Kept as reference, never nudged.
      outside  onions, potatoes, garlic. Perishable but not fridge food.

    The last two are still worth keeping: they are what makes "can I cook X
    tonight" answerable. They just have no clock on them.
    """
    today = today or date.today()
    batch = datetime.now().isoformat(timespec="microseconds")
    tracked, stable, outside, again = [], [], [], []
    open_names = {i["name"].lower(): i["id"] for i in open_items(con, chat_id)}
    for name in names:
        skip, reason = sl.not_tracked(name)
        if skip:
            remember(con, chat_id, name, reason, today, batch)
            (outside if reason == "outside" else stable).append(name)
            continue
        ub, risk, est = sl.use_by(name, today)
        existing = open_names.get(name.lower())
        if existing is not None:
            # You bought more milk. That is one milk with a later date, not two
            # milks — and two would mean two nudges for one carton.
            con.execute("UPDATE items SET use_by=?, added=?, estimated=? WHERE id=?",
                        (ub.isoformat(), today.isoformat(), 1 if est else 0, existing))
            again.append(name)
            continue
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,batch,state)"
            " VALUES (?,?,?,?,?,?,?, 'open')",
            (chat_id, name, ub.isoformat(), risk, 1 if est else 0,
             today.isoformat(), batch),
        )
        tracked.append((name, ub, risk, est))
        open_names[name.lower()] = None
    con.commit()
    return tracked, stable, outside, again


def remember(con, chat_id, name, kind, today=None, batch=None):
    """File a non-perishable as reference data. Idempotent \u2014 re-sending a list
    must not stack duplicates, because people re-send lists."""
    con.execute(
        "INSERT OR IGNORE INTO pantry (chat_id,name,kind,added,batch)"
        " VALUES (?,?,?,?,?)",
        (chat_id, name, kind, (today or date.today()).isoformat(), batch),
    )


def pantry_items(con, chat_id):
    rows = con.execute(
        "SELECT name, kind FROM pantry WHERE chat_id=? ORDER BY kind, name",
        (chat_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def compose_pantry(items):
    if not items:
        return ("Nothing in your pantry yet. Anything you send me that has no "
                "clock on it \u2014 spices, cans, oil, rice \u2014 lands here.")
    stable = [i["name"] for i in items if i["kind"] == "stable"]
    outside = [i["name"] for i in items if i["kind"] == "outside"]
    out = ["Not tracked, but I remember you have it.", ""]
    if stable:
        out += ["Pantry (%d)" % len(stable), "  " + ", ".join(stable), ""]
    if outside:
        out += ["On the counter (%d)" % len(outside), "  " + ", ".join(outside)]
    return "\n".join(out).strip()


def clear_chat(con, chat_id):
    """Everything for this chat. Returns (items, pantry) counts."""
    n_items = con.execute("SELECT COUNT(*) FROM items WHERE chat_id=?",
                          (chat_id,)).fetchone()[0]
    n_pantry = con.execute("SELECT COUNT(*) FROM pantry WHERE chat_id=?",
                           (chat_id,)).fetchone()[0]
    con.execute("DELETE FROM items WHERE chat_id=?", (chat_id,))
    con.execute("DELETE FROM pantry WHERE chat_id=?", (chat_id,))
    # The chosen nudge hour is a preference, not data. Wiping the fridge should
    # not silently move someone's morning message back to the default.
    con.execute("DELETE FROM meta WHERE chat_id=? AND key NOT IN "
                "('nudge_hour','onboarding')", (chat_id,))
    con.commit()
    return n_items, n_pantry


def undo_last(con, chat_id):
    """Remove everything captured in the most recent capture batch.

    Keyed on the batch stamp every row in one capture shares. This is
    the escape hatch for a list that went in wrong — without it the only fix is
    /clear, which throws away the good with the bad.
    """
    stamps = [r[0] for r in con.execute(
        "SELECT MAX(batch) FROM items WHERE chat_id=? AND batch IS NOT NULL"
        " UNION ALL"
        " SELECT MAX(batch) FROM pantry WHERE chat_id=? AND batch IS NOT NULL",
        (chat_id, chat_id)) if r[0]]
    if not stamps:
        return "Nothing to undo."
    stamp = max(stamps)
    n_i = con.execute("DELETE FROM items WHERE chat_id=? AND batch=?",
                      (chat_id, stamp)).rowcount
    n_p = con.execute("DELETE FROM pantry WHERE chat_id=? AND batch=?",
                      (chat_id, stamp)).rowcount
    con.commit()
    if not (n_i or n_p):
        return "Nothing to undo."
    bits = []
    if n_i:
        bits.append("%d tracked item%s" % (n_i, "" if n_i == 1 else "s"))
    if n_p:
        bits.append("%d pantry entr%s" % (n_p, "y" if n_p == 1 else "ies"))
    return "Took back " + " and ".join(bits) + "."


def last_art(con, chat_id):
    return get_pref(con, chat_id, "last_art")


def note_art(con, chat_id, frame):
    """Remember the frame just shown, so the next one differs.

    The same drawing twice running stops being a surprise and becomes
    furniture, which is the failure mode for anything meant as delight.
    """
    if frame:
        set_pref(con, chat_id, "last_art", frame)


def set_pref(con, chat_id, key, value):
    con.execute("INSERT OR REPLACE INTO meta (chat_id,key,value) VALUES (?,?,?)",
                (chat_id, key, str(value)))
    con.commit()


def get_pref(con, chat_id, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE chat_id=? AND key=?",
                      (chat_id, key)).fetchone()
    return row["value"] if row else default


def nudge_hour(con, chat_id, default):
    """The hour this chat chose at onboarding, falling back to the config.

    Per chat rather than per process: the bot is one instance serving several
    people, and 08:00 is not everyone's morning.
    """
    raw = get_pref(con, chat_id, "nudge_hour")
    try:
        h = int(raw)
    except (TypeError, ValueError):
        return default
    return h if 0 <= h <= 23 else default


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

def count_closed(con, chat_id, state):
    return con.execute("SELECT COUNT(*) FROM items WHERE chat_id=? AND state=?",
                       (chat_id, state)).fetchone()[0]


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
        head = ("1 item past its date: check before eating" if len(t0) == 1
                else "%d items past their date: check before eating" % len(t0))
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
            note = ": raw, throw it out" if i["risk"] == sl.RED else ""
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
