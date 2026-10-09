"""The fridge itself: storage, capture parsing, and composing the daily nudge.

No Telegram in here either. Everything in this file can be run and checked
without a network, which matters because the transport can't be tested offline.
"""

import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

import prices
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
    closed    TEXT,
    tier      INTEGER,                  -- urgency tier at the moment it closed
    tier_source TEXT,                   -- recorded | reconstructed
    freezer_outcome TEXT,               -- used | tossed, once it leaves the freezer
    freezer_at TEXT                     -- when that happened
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
CREATE TABLE IF NOT EXISTS invites (
    code      TEXT    PRIMARY KEY,
    created   TEXT    NOT NULL,
    expires   TEXT    NOT NULL,
    used_by   INTEGER,                  -- the chat that redeemed it
    used_at   TEXT
);
CREATE TABLE IF NOT EXISTS members (
    chat_id   INTEGER PRIMARY KEY,      -- let in by an invite, not config.json
    name      TEXT,
    joined    TEXT    NOT NULL,
    invite    TEXT
);
CREATE TABLE IF NOT EXISTS ai_usage (
    chat_id   INTEGER NOT NULL,
    day       TEXT    NOT NULL,         -- ISO date
    calls     INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost      REAL,                     -- dollars, when the provider says; NULL if never
    PRIMARY KEY (chat_id, day)
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
    # Deleted rows are overwritten, not left in free pages of the file, so
    # /deleteme leaves nothing behind for a file-level reader to recover.
    con.execute("PRAGMA secure_delete=ON")
    con.executescript(SCHEMA)
    # A db made before a feature existed is missing its columns. Add them
    # rather than asking anyone to delete their fridge to get an upgrade.
    for table, column, decl in (
        ("items", "batch", "TEXT"),
        ("pantry", "batch", "TEXT"),
        ("items", "tier", "INTEGER"),
        ("items", "tier_source", "TEXT"),
        ("items", "freezer_outcome", "TEXT"),
        ("items", "freezer_at", "TEXT"),
    ):
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
        if column not in cols:
            con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))
    con.commit()
    backfill_tiers(con)
    return con


def backfill_tiers(con):
    """Reconstruct the tier for closes that happened before the column existed.

    Exact, not a guess. A closed row keeps the use_by it had, the dedupe in
    add_items only touches open rows, and sl.tier's thresholds have never
    changed since they were written, so sl.tier(use_by, close date) returns
    what it would have returned on the day. The date part of the timestamp is
    what counts, so an item closed just after midnight gets that day's tier.

    Marked `reconstructed` all the same, because a report that mixes the two
    silently is claiming more than it knows. Idempotent: only NULL tiers.
    """
    rows = con.execute(
        "SELECT id, use_by, closed FROM items"
        " WHERE state != 'open' AND tier IS NULL AND closed IS NOT NULL"
    ).fetchall()
    for r in rows:
        closed_day = date.fromisoformat(r["closed"][:10])
        t = sl.tier(date.fromisoformat(r["use_by"]), closed_day)
        con.execute("UPDATE items SET tier=?, tier_source='reconstructed'"
                    " WHERE id=?", (t, r["id"]))
    if rows:
        con.commit()
    return len(rows)


# --- capture ---------------------------------------------------------------

# "2 bunches cilantro", "milk x2", "- spinach"
_LEADING_QTY = re.compile(r"^\s*[-*•]?\s*(\d+\s*(x|bunches|bunch|bags?|packs?|lbs?|cans?)?\s+)?", re.I)
_TRAILING_QTY = re.compile(r"\s*[x×]\s*\d+\s*$", re.I)


MAX_NAME = 60
MAX_ITEMS = 50

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


# --- questions, not lists or corrections ------------------------------------
#
# Someone who does not follow "a guess" or "past its best" is not going to
# type a command, they are going to ask in plain words: "what's toss?",
# "why did you say past its best". Before this existed, a short question fell
# through to capture and became a fridge item with a fake date on it — the
# exact confusion the bot exists to prevent.

QUESTION_STARTS = ("what", "whats", "why", "how", "when", "which", "who")

# Whole-phrase openers, for the natural phrasings that do not start with a
# bare wh-word. Without these, "do I have anything in my pantry" read as a
# correction and silently moved real tracked items to the pantry.
QUESTION_PHRASES = ("can you", "could you", "would you", "will you",
                     "is there", "are there", "do i", "does it", "did you",
                     "should i", "am i")

GLOSSARY = (
    (("guess",), "A guess means I did not know exactly how long that keeps, "
                 "so I estimated from what kind of food it is. Tell me a "
                 "better date and I will use that instead."),
    (("past its best", "past due", "past its date"),
     "Past its best means the date I had for it has gone by. It might "
     "still be fine, so check it: smell, look, texture."),
    (("toss",), "Toss just means throw it out."),
    (("use up", "use it"), "Use up means eat or cook it before it turns."),
    (("freeze",), "Freeze it means put it in the freezer. That stops the "
                  "clock, so it keeps for months."),
    (("tonight",), "Tonight means it needs using today, or it will likely "
                   "turn by tomorrow."),
    (("tracked", "tracking"), "Tracked means I am watching it and will "
                              "message you before it goes bad."),
    (("pantry",), "Pantry means things with no clock on them, like spices, "
                  "cans, oil or rice. I remember them but never message you "
                  "about them."),
    (("counter",), "Counter means food that keeps better outside the "
                   "fridge, like onions, potatoes or garlic."),
    (("nudge",), "A nudge is the one message a day I send, and only when "
                 "something needs using."),
    (("clock",), "Clock just means the countdown to when something turns."),
    (("date", "day"), "The day and date is when I think it turns, like "
                      "\"Wed Sep 30\". \"(today)\", \"(tomorrow)\" or "
                      "\"(2 days past)\" says how soon."),
)


def is_question(text):
    """True for a genuine question about a word or a date, not a list or a
    correction. Checked before capture and before chatter has already been
    ruled out by the caller, so a bare reaction like "why" or "what" stays
    chatter rather than becoming a half-answered question."""
    if "," in text or "\n" in text:
        return False
    if "?" in text:
        return True
    n = text.lower().strip("!?. ")
    words = n.split()
    if words and words[0] in QUESTION_STARTS and len(words) > 1:
        return True
    return n.startswith(QUESTION_PHRASES)


def answer_question(text):
    """A short, plain answer for a recognised term, or a fallback that still
    answers rather than leaving the question ignored."""
    n = text.lower()
    for keys, answer in GLOSSARY:
        if any(k in n for k in keys):
            return answer
    return ("Not sure which word you mean. Ask about one I used, like "
            "\"what's a guess\", or send /help to see everything I can do.")


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
                "no expiry", "no expiration")

# Pre-negated idioms like "wont go bad" or "not perishable" used to live here
# too, but each one contains a FRIDGE_WORDS substring ("go bad", "perishable"),
# so both buckets hit before the flip below ever runs and the flip just swaps
# two Trues, falling through to None — "this wont go bad" was silently
# tracked as a literal fridge item instead of moved to the pantry. The
# negation flip already covers every one of these on its own: "not
# perishable" hits FRIDGE_WORDS' "perishable" and NEGATORS' "not", flips to
# pantry, no separate entry needed.

FRIDGE_WORDS = ("fridge", "refrigerator", "perishable", "goes bad", "go bad",
                "goes off", "go off", "track these", "track them", "track it")

# "none of these go bad" means the opposite of "these go bad", and a person
# correcting me is quite likely to phrase it that way. Bare "no" is deliberately
# absent: in "no, those go off quickly" it is a discourse marker, not a negation.
# A correction is about the list I just sorted, so it points back at it:
# "those are pantry", "none of these go bad", "they are all dry goods".
# Without one of these, "I put butter chicken in the fridge" read as a
# correction on the word "fridge" and moved the previous list, or answered
# "I don't have a recent list to move" to someone adding leftovers.
REFERENTS = {"these", "those", "they", "them", "this", "that", "it",
             "everything", "none", "nothing"}

NEGATORS = ("none", "not", "never", "nothing", "dont", "doesnt", "wont",
            "cant", "isnt", "arent", "without")


def _words(text):
    # Apostrophes (straight or curly) drop before splitting, so "don't" and
    # "don’t" both tokenize as "dont" and match the apostrophe-free
    # NEGATORS/FUNCTION_WORDS entries — otherwise every real contraction
    # misses and a negated correction flips to the wrong bucket.
    n = text.lower().replace("'", "").replace("’", "")
    return [w for w in re.split(r"[^a-z]+", n) if w]


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


# "half and half" is the one perishable in shelf_life.SHELF_LIFE three words
# or longer. Pantry and outside names of the same shape ("herbes de
# provence", "bag of onions") are already caught generally, below, by
# sl.not_tracked() — this is the single exception that needed listing by hand.
_LOW_GLUE_PERISHABLE_NAMES = frozenset(("half and half",))


def looks_like_an_unseparated_list(text):
    """True for several foods typed with no separator at all: "milk eggs
    bread". Without this, parse_list finds no comma to split on and the
    whole string becomes one garbled tracked item.

    The complement of looks_like_sentence: enough words to be more than one
    thing, but too few function words to be prose. A real single pantry or
    outside name of the same shape ("herbes de provence", "bag of onions")
    is ruled out first — by better_outside(), which already requires every
    word to be accounted for, and by an EXACT match against STABLE, not
    shelf_stable()'s substring check: shelf_stable("chicken breast rice
    beans") is true on "rice" alone, which is exactly the false negative
    this function exists to avoid.
    """
    if "," in text or "\n" in text or ";" in text:
        return False
    n = text.lower().strip()
    if n in _LOW_GLUE_PERISHABLE_NAMES or sl.better_outside(n) or n in sl.STABLE:
        return False
    words = _words(text)
    if len(words) < 3:
        return False
    fn = sum(1 for w in words if w in FUNCTION_WORDS)
    return fn <= 1


def correction(text):
    """'pantry', 'fridge' or None — which way the user says I sorted it wrong."""
    n = text.lower()
    # A comma or a newline means someone is listing food, even if a keyword
    # happens to be in there ("pantry staples, milk"). Anything else is prose
    # short enough to be a correction, so let the keywords decide.
    if "," in text or "\n" in text:
        return None
    if not any(w in REFERENTS for w in _words(n)):
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


# "I put butter chicken in the fridge as leftovers". The one sentence shape
# that is plainly a capture: a put-away verb, a food, and the fridge.
_PUT_AWAY = re.compile(
    r"^(?:i\s+)?(?:just\s+)?(?:put|stuck|popped|placed|stored|added|threw)\s+"
    r"(?:some\s+|the\s+|my\s+|a\s+)?(?P<food>.+?)\s+(?:in|into|to)\s+"
    r"(?:the|my)\s+(?:fridge|refrigerator)"
    r"(?:\s+as\s+(?:a\s+)?(?P<left>leftovers?))?\s*[.!]*$", re.I)


def put_away(text):
    """The food name from a put-away sentence, or None.

    "as leftovers" becomes part of the name, so it gets the short cooked-food
    window rather than whatever the raw ingredient would get. "put them in
    the fridge" is not a capture: it points back at the last list, so it is
    left for correction() to read.
    """
    m = _PUT_AWAY.match(text.strip())
    if not m:
        return None
    food = m.group("food").strip()
    if not food or all(w in REFERENTS or w in FUNCTION_WORDS for w in _words(food)):
        return None
    if m.group("left") and "leftover" not in food.lower():
        food += " (leftovers)"
    return food


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
    r = reclassify(con, chat_id, target, today)
    return r["moved"], r["message"]


def reclassify(con, chat_id, target, today=None):
    """reclassify_last, with its parts kept apart so the bot can draw a card:
    {"moved": names, "held": raw meat kept tracked, "message": prose}."""
    r = _reclassify(con, chat_id, target, today)
    if isinstance(r, tuple):
        names, message = r
        return {"moved": names, "held": [], "message": message}
    return r


def _reclassify(con, chat_id, target, today=None):
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
        return {"moved": names, "held": held, "message": msg}

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
        lines.append("  \u2022 %s: %s%s" % (name, sl.when(ub, today),
                                            " (a guess)" if est else ""))
    return names, "\n".join(lines)


_HAS_LETTER_OR_DIGIT = re.compile(r"[a-zA-Z0-9]")


def parse_list(text, report=False):
    """A free-typed list into clean item names. Commas, newlines and bullets all work.

    With report=True, also returns the fragments rejected as not real food
    names: too long, or made of no letters or digits at all ("!!!???",
    emoji). They used to vanish without a word, or worse, get tracked as a
    literal item with a fake date, which broke the one promise capture has to
    keep: never drop or mistrack anything silently.
    """
    parts = re.split(r"[,\n;]+", text)
    out, rejected = [], []
    for p in parts:
        p = _LEADING_QTY.sub("", p)
        p = _TRAILING_QTY.sub("", p)
        p = p.strip(" .\t").strip()
        if not p:
            continue
        if len(p) >= MAX_NAME:
            rejected.append(p[:40].rstrip() + "...")
            continue
        if not _HAS_LETTER_OR_DIGIT.search(p):
            rejected.append(p)
            continue
        out.append(p)
    return (out, rejected) if report else out


def cap_names(names):
    """Keep a single capture from growing without bound on a huge paste.
    Returns (kept, n_dropped) rather than silently truncating, since nothing
    is lost silently is the one promise capture has to keep."""
    if len(names) <= MAX_ITEMS:
        return names, 0
    return names[:MAX_ITEMS], len(names) - MAX_ITEMS


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
            # milks, and two would mean two nudges for one carton. The batch
            # still moves to today's, so /undo and a correction on this
            # message act on it rather than whichever day first captured it.
            con.execute("UPDATE items SET use_by=?, added=?, estimated=?, batch=? WHERE id=?",
                        (ub.isoformat(), today.isoformat(), 1 if est else 0, batch, existing))
            again.append(name)
            continue
        cur = con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,batch,state)"
            " VALUES (?,?,?,?,?,?,?, 'open')",
            (chat_id, name, ub.isoformat(), risk, 1 if est else 0,
             today.isoformat(), batch),
        )
        tracked.append((name, ub, risk, est))
        # The row's real id, not None, so a repeat of this name later in the
        # same list hits the "again" branch above instead of inserting twice.
        open_names[name.lower()] = cur.lastrowid
    con.commit()
    return tracked, stable, outside, again


def remember(con, chat_id, name, kind, today=None, batch=None):
    """File a non-perishable as reference data. Idempotent \u2014 re-sending a list
    must not stack duplicates, because people re-send lists. The batch always
    moves to this call's, even for a name already on file, so /undo and a
    correction target today's message rather than whichever day first saw it."""
    con.execute(
        "INSERT OR IGNORE INTO pantry (chat_id,name,kind,added,batch)"
        " VALUES (?,?,?,?,?)",
        (chat_id, name, kind, (today or date.today()).isoformat(), batch),
    )
    con.execute(
        "UPDATE pantry SET batch=? WHERE chat_id=? AND name=?",
        (batch, chat_id, name),
    )


def pantry_items(con, chat_id):
    rows = con.execute(
        "SELECT name, kind FROM pantry WHERE chat_id=? ORDER BY kind, name",
        (chat_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def compose_pantry(items):
    if not items:
        return ("Nothing in your pantry yet. Anything you send me with no clock "
                "on it, like spices, cans, oil or rice, lands here.")
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


def delete_person(con, chat_id):
    """Everything this chat ever left here, for /deleteme. Returns (items,
    pantry) counts.

    Wider than clear_chat on purpose: that one wipes the food and keeps the
    settings, for starting over. This one is for leaving, so it also takes
    the settings, saved cards, AI usage and membership. The invite code they
    used stays spent, so it cannot let anyone else in.
    """
    n_items = con.execute("SELECT COUNT(*) FROM items WHERE chat_id=?",
                          (chat_id,)).fetchone()[0]
    n_pantry = con.execute("SELECT COUNT(*) FROM pantry WHERE chat_id=?",
                           (chat_id,)).fetchone()[0]
    for table in ("items", "pantry", "meta", "ai_usage", "members"):
        con.execute("DELETE FROM %s WHERE chat_id=?" % table, (chat_id,))
    # The invite they used no longer names them. 0, not NULL: a NULL would
    # make the code redeemable again.
    con.execute("UPDATE invites SET used_by=0 WHERE used_by=?", (chat_id,))
    con.commit()
    return n_items, n_pantry


def undo_last(con, chat_id):
    """Remove everything captured in the most recent capture batch.

    Keyed on the batch stamp every row in one capture shares. This is
    the escape hatch for a list that went in wrong — without it the only fix is
    /clear, which throws away the good with the bad.
    """
    return undo(con, chat_id)["message"]


def undo(con, chat_id):
    """undo_last with the names kept, so the bot can show what went:
    {"tracked": names, "pantry": names, "message": prose}."""
    stamp = last_batch(con, chat_id)
    if not stamp:
        return {"tracked": [], "pantry": [], "message": "Nothing to undo."}
    tracked = [r["name"] for r in con.execute(
        "SELECT name FROM items WHERE chat_id=? AND batch=?", (chat_id, stamp))]
    pantry = [r["name"] for r in con.execute(
        "SELECT name FROM pantry WHERE chat_id=? AND batch=?", (chat_id, stamp))]
    n_i = con.execute("DELETE FROM items WHERE chat_id=? AND batch=?",
                      (chat_id, stamp)).rowcount
    n_p = con.execute("DELETE FROM pantry WHERE chat_id=? AND batch=?",
                      (chat_id, stamp)).rowcount
    con.commit()
    return {"tracked": tracked, "pantry": pantry,
            "message": _undo_message(n_i, n_p)}


def _undo_message(n_i, n_p):
    if not (n_i or n_p):
        return "Nothing to undo."
    bits = []
    if n_i:
        bits.append("%d tracked thing%s" % (n_i, "" if n_i == 1 else "s"))
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


# A drawing everywhere stops being delight and turns into furniture, so each
# person gets a few a day. Milestones don't count: they're rare by design.
ART_DAILY_CAP = 3


def art_left(con, chat_id, today=None):
    """Drawings this chat may still get today."""
    today = (today or date.today()).isoformat()
    day, _, n = (get_pref(con, chat_id, "art_day") or "").partition(" ")
    used = int(n) if day == today and n.isdigit() else 0
    return max(0, ART_DAILY_CAP - used)


def spend_art(con, chat_id, today=None):
    today = (today or date.today()).isoformat()
    used = ART_DAILY_CAP - art_left(con, chat_id, date.fromisoformat(today))
    set_pref(con, chat_id, "art_day", "%s %d" % (today, used + 1))


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


# --- invites ---------------------------------------------------------------
#
# Friends get in through a link from the owner instead of their numeric chat
# id in config.json. One person per link, and links go stale, so a link
# forwarded on, or found in an old chat, lets nobody else in.

INVITE_DAYS = 7


def create_invite(con, now=None, days=INVITE_DAYS):
    """A fresh one-use code. URL-safe, so it can ride a t.me ?start= link."""
    now = now or datetime.now()
    code = secrets.token_urlsafe(9)
    con.execute("INSERT INTO invites (code, created, expires) VALUES (?,?,?)",
                (code, now.isoformat(timespec="seconds"),
                 (now + timedelta(days=days)).isoformat(timespec="seconds")))
    con.commit()
    return code


def redeem_invite(con, code, chat_id, name=None, now=None):
    """Let this chat in on this code. False if the code is unknown, used or
    expired. A chat already in redeems nothing and stays in."""
    now = now or datetime.now()
    if is_member(con, chat_id):
        return True
    cur = con.execute(
        "UPDATE invites SET used_by=?, used_at=? WHERE code=? AND used_by IS NULL"
        " AND expires > ?",
        (chat_id, now.isoformat(timespec="seconds"), code,
         now.isoformat(timespec="seconds")))
    if cur.rowcount != 1:
        return False
    con.execute("INSERT OR REPLACE INTO members (chat_id, name, joined, invite)"
                " VALUES (?,?,?,?)",
                (chat_id, name, now.isoformat(timespec="seconds"), code))
    con.commit()
    return True


def is_member(con, chat_id):
    return con.execute("SELECT 1 FROM members WHERE chat_id=?",
                       (chat_id,)).fetchone() is not None


def members(con):
    return [dict(r) for r in
            con.execute("SELECT * FROM members ORDER BY joined")]


def remove_member(con, chat_id):
    """Ends access only. Their fridge stays in the store until it is deleted
    on purpose; losing someone's data on a mis-tap would be worse."""
    con.execute("DELETE FROM members WHERE chat_id=?", (chat_id,))
    # A re-invite starts from scratch: AI is the owner's money, so it is
    # never carried over from an earlier membership.
    con.execute("DELETE FROM meta WHERE chat_id=? AND key='ai'", (chat_id,))
    con.commit()


# --- AI usage --------------------------------------------------------------
#
# One row per person per day. Counts what the provider reports for each model
# call, so "is this worth optimising" is answered from the bill, not a guess.

def record_usage(con, chat_id, usage, day=None):
    """Add one model call. `usage` is the provider's usage object, or None
    when it sent none: the call still counts, with no tokens and no cost."""
    usage = usage or {}
    cost = usage.get("cost")
    con.execute(
        "INSERT INTO ai_usage (chat_id, day, calls, prompt_tokens,"
        " completion_tokens, cost) VALUES (?,?,1,?,?,?)"
        " ON CONFLICT (chat_id, day) DO UPDATE SET calls=calls+1,"
        " prompt_tokens=prompt_tokens+excluded.prompt_tokens,"
        " completion_tokens=completion_tokens+excluded.completion_tokens,"
        " cost=CASE WHEN excluded.cost IS NULL THEN cost"
        "      ELSE COALESCE(cost, 0) + excluded.cost END",
        (chat_id, (day or date.today()).isoformat(),
         int(usage.get("prompt_tokens") or 0),
         int(usage.get("completion_tokens") or 0),
         float(cost) if cost is not None else None))
    con.commit()


def calls_today(con, chat_id, day=None):
    row = con.execute("SELECT calls FROM ai_usage WHERE chat_id=? AND day=?",
                      (chat_id, (day or date.today()).isoformat())).fetchone()
    return row["calls"] if row else 0


def has_data(con, chat_id):
    """Whether anything about this chat is stored, so /deleteme has work."""
    return any(con.execute("SELECT 1 FROM %s WHERE chat_id=? LIMIT 1" % t,
                           (chat_id,)).fetchone()
               for t in ("items", "pantry", "meta", "ai_usage", "members"))


def usage_since(con, day):
    """Totals per chat from `day` on, busiest first."""
    return [dict(r) for r in con.execute(
        "SELECT chat_id, SUM(calls) calls, SUM(prompt_tokens) prompt_tokens,"
        " SUM(completion_tokens) completion_tokens, SUM(cost) cost"
        " FROM ai_usage WHERE day >= ? GROUP BY chat_id ORDER BY calls DESC",
        (day.isoformat(),))]


# Open items per chat. Far past any real fridge, and it keeps one chat from
# growing the store, and every AI prompt that lists the fridge, without end.
MAX_OPEN_ITEMS = 300


def room_left(con, chat_id):
    n = con.execute("SELECT COUNT(*) FROM items WHERE chat_id=? AND state='open'",
                    (chat_id,)).fetchone()[0]
    return MAX_OPEN_ITEMS - n


CARD_KEEP_DAYS = 30


def prune_cards(con, chat_id, today=None):
    """Forget cards older than CARD_KEEP_DAYS. One meta row is saved per card
    sent, so without this the table grows with every nudge forever. A tap on
    a card this old says it is out of date."""
    cutoff = ((today or date.today()) - timedelta(days=CARD_KEEP_DAYS)).isoformat()
    stale = []
    for r in con.execute("SELECT key, value FROM meta WHERE chat_id=? AND key LIKE 'card:%'",
                         (chat_id,)):
        try:
            day = json.loads(r["value"]).get("day", "")
        except ValueError:
            day = ""
        if day < cutoff:
            stale.append(r["key"])
    for key in stale:
        con.execute("DELETE FROM meta WHERE chat_id=? AND key=?", (chat_id, key))
    con.commit()
    return len(stale)


def items_by_ids(con, chat_id, ids):
    """These items in this order, open or closed. A card keeps showing a
    closed item as its outcome, so it needs rows open_items would drop."""
    if not ids:
        return []
    rows = con.execute(
        "SELECT * FROM items WHERE chat_id=? AND id IN (%s)" % ",".join("?" * len(ids)),
        [chat_id] + list(ids)).fetchall()
    by_id = {r["id"]: dict(r, use_by_date=date.fromisoformat(r["use_by"])) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


# --- cards -----------------------------------------------------------------
#
# What a sent card holds, keyed by its Telegram message id, so a tap can
# redraw the same message. Lives in meta: one small JSON blob per card.

def save_card(con, chat_id, message_id, spec):
    set_pref(con, chat_id, "card:%d" % message_id, json.dumps(spec))


def load_card(con, chat_id, message_id):
    raw = get_pref(con, chat_id, "card:%d" % message_id)
    return json.loads(raw) if raw else None


def close_item(con, chat_id, item_id, state, today=None):
    """Close an item out, recording the tier it was in at that moment.

    Returns True if it closed, False if there was no open item to close.

    Tiers are computed and never stored (SKILL §1, §5), so this row is the only
    place that moment survives, and it is what makes a rescue countable later.

    Every close goes through here, including the LLM's update_item, so there is
    one place the tier can be missed and it is this one.
    """
    now = datetime.now()
    row = con.execute("SELECT use_by FROM items WHERE id=? AND chat_id=?"
                      " AND state='open'",
                      (item_id, chat_id)).fetchone()
    if not row:
        return False
    t = sl.tier(date.fromisoformat(row["use_by"]), today or now.date())
    # Only an open item closes. Without this an inline button tapped twice, or
    # a stale one tapped weeks later, would overwrite the close date and the
    # tier of a close that already happened, moving a rescue into the wrong
    # month or out of being a rescue at all.
    con.execute(
        "UPDATE items SET state=?, closed=?, tier=?, tier_source='recorded'"
        " WHERE id=? AND chat_id=? AND state='open'",
        (state, now.isoformat(timespec="seconds"), t, item_id, chat_id),
    )
    con.commit()
    return True


RESCUE_TIERS = (0, 1)


def is_rescue(state, tier):
    """A rescue is a used or frozen close at t0 or t1 (SKILL §15).

    Nothing earlier counts. Milk drunk on day 2 of 8 was never at risk, so
    counting it would credit the system for breakfast.
    """
    return state in ("used", "frozen") and tier in RESCUE_TIERS


def tier_counts(con, chat_id):
    """How many closed rows carry a recorded tier versus a reconstructed one.

    A report built from these has to be able to say "N reconstructed".
    """
    out = {"recorded": 0, "reconstructed": 0, "none": 0}
    for r in con.execute(
            "SELECT tier_source, COUNT(*) n FROM items"
            " WHERE chat_id=? AND state != 'open' GROUP BY tier_source",
            (chat_id,)):
        out[r["tier_source"] or "none"] = r["n"]
    return out


# --- the freezer -----------------------------------------------------------
#
# Freezing used to be a dead end: the item left open_items and had no buttons
# ever again, so a frozen rescue could never be reversed and the rescued figure
# could only ever drift upward. These two columns give it somewhere to go.
#
# A frozen item keeps state='frozen' and its original close date and tier. That
# close really happened and the rescue was really earned, so it stays attributed
# to the month it happened in. What comes later is a separate event with its own
# date, which is what lets a reversal land in the month of the toss (SKILL §15)
# rather than silently rewriting an earlier month.

def frozen_items(con, chat_id):
    """What is in the freezer and still undecided."""
    rows = con.execute(
        "SELECT * FROM items WHERE chat_id=? AND state='frozen'"
        " AND freezer_outcome IS NULL ORDER BY closed DESC",
        (chat_id,),
    ).fetchall()
    return [dict(r, use_by_date=date.fromisoformat(r["use_by"])) for r in rows]


def settle_freezer_item(con, chat_id, item_id, outcome):
    """Record what finally happened to something frozen: used or tossed.

    'tossed' is the reversal. Freezing only to delay the bin is not a save, so
    the rescue comes back off in the month the bin happened.
    """
    if outcome not in ("used", "tossed"):
        raise ValueError("outcome must be used or tossed")
    # First answer wins. Telegram keeps inline buttons tappable forever, so a
    # stale message could otherwise overwrite "used" with "tossed" and reverse
    # a rescue that was never reversed. The bot checks this too; the guard
    # belongs here as well, because the button is the untrusted side.
    con.execute(
        "UPDATE items SET freezer_outcome=?, freezer_at=?"
        " WHERE id=? AND chat_id=? AND state='frozen'"
        " AND freezer_outcome IS NULL",
        (outcome, datetime.now().isoformat(timespec="seconds"), item_id, chat_id),
    )
    con.commit()


def reversed_rescues(con, chat_id):
    """Frozen rescues that later went in the bin, with the date they did."""
    rows = con.execute(
        "SELECT * FROM items WHERE chat_id=? AND state='frozen'"
        " AND freezer_outcome='tossed' ORDER BY freezer_at DESC",
        (chat_id,),
    ).fetchall()
    return [dict(r) for r in rows if is_rescue("frozen", r["tier"])]


# --- the monthly figures ---------------------------------------------------
#
# Two numbers, side by side, rescued first because it is the one the system
# affects (SKILL §17). Everything here is counted from this bot's own SQLite
# store and nothing else: it cannot read Apple Reminders or Restock.md, so the
# text says where the numbers come from rather than letting them be mistaken
# for the Mac side's.
#
# A reversal is the awkward case. A frozen rescue that later goes in the bin
# counts in the month of the toss, on both sides: the toss goes onto thrown
# away, and the rescue reverses. But the month the rescue was earned keeps it,
# because the freeze and the toss are two events with their own dates. So the
# reversal is shown as its own clause and never subtracted into a smaller
# rescued figure, which would be a negative number wearing a disguise.

def _month_of(stamp):
    return (stamp or "")[:7]


def month_figures(con, chat_id, today=None):
    """The raw counts behind a monthly report. All from this bot's store."""
    today = today or date.today()
    month = today.isoformat()[:7]
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM items WHERE chat_id=? AND state != 'open'", (chat_id,))]

    rescued, tossed, reversals = [], [], []
    for r in rows:
        if _month_of(r["closed"]) == month and is_rescue(r["state"], r["tier"]):
            rescued.append(r)
        if _month_of(r["closed"]) == month and r["state"] == "tossed":
            tossed.append(r)
        # A frozen rescue binned this month: a toss here, and a reversal here,
        # whichever month the freeze happened in.
        if (r["state"] == "frozen" and r["freezer_outcome"] == "tossed"
                and _month_of(r["freezer_at"]) == month):
            if is_rescue("frozen", r["tier"]):
                reversals.append(r)
            tossed.append(r)

    # Scoped to the rows this month's figures are built from, not the whole
    # store. An all-time count sitting under a monthly figure reads as a claim
    # about that month: September said "6 tiers reconstructed" when only 5 of
    # its rows were in September at all.
    counted = {}
    for r in rescued + tossed + reversals:
        counted[r["id"]] = r
    reconstructed = sum(1 for r in counted.values()
                        if r["tier_source"] == "reconstructed")
    return {
        "month": month,
        "rescued": rescued,
        "tossed": tossed,
        "reversals": reversals,
        "reconstructed": reconstructed,
    }


def _price_side(items):
    """(rounded total, n_items, {source label: count}) for one side of the ledger.

    Unpriced items still count in the tally and stay out of the money, which is
    the whole reason the report says how many were priced.
    """
    total, by_source = 0.0, {}
    for i in items:
        amount, src = prices.price_for(i["name"])
        if amount is None:
            continue
        total += amount
        label = prices.source_label(src)
        by_source[label] = by_source.get(label, 0) + 1
    return int(round(total)), len(items), by_source


def _side_clause(total, n, by_source):
    """One side of the ledger as a sentence.

    With nothing priced there is no dollar figure at all. "about $0 across 1
    item" reads as "it cost nothing", which is a confident claim built from no
    data -- the item counts in the tally and stays out of the money, which is
    the whole reason the priced count is printed next to it.
    """
    if not n:
        return "nothing yet."
    plural = "" if n == 1 else "s"
    if not sum(by_source.values()):
        return "%d item%s, none of them priced." % (n, plural)
    return "about $%d across %d item%s (%s)." % (
        total, n, plural, _priced_clause(by_source, n))


def _priced_clause(by_source, n_total):
    n_priced = sum(by_source.values())
    if not n_priced:
        return "none of them priced"
    split = ", ".join("%d %s" % (n, label)
                      for label, n in sorted(by_source.items()))
    if n_priced == n_total:
        return "all %d priced: %s" % (n_priced, split)
    return "%d of %d priced: %s" % (n_priced, n_total, split)


def _month_name(month):
    y, m = month.split("-")
    return date(int(y), int(m), 1).strftime("%B %Y")


def compose_month(fig):
    """The monthly text. One shape, used by /month and by the LLM tool alike.

    No net figure, ever: rescued minus thrown away would present a ledger as a
    verdict, and the two are not the same kind of number (SKILL §17). And never
    "saved you" -- rescued means it reached the edge and got used, not that it
    would otherwise have been binned.
    """
    r_total, r_n, r_src = _price_side(fig["rescued"])
    t_total, t_n, t_src = _price_side(fig["tossed"])
    name = _month_name(fig["month"])

    if not r_n and not t_n:
        return ("Nothing closed out in %s yet, so there is no figure to give. "
                "This counts only what you have told me here." % name)

    lines = ["%s, from what you have told me here." % name, ""]

    used = "Used before it went off: " + _side_clause(r_total, r_n, r_src)
    if fig["reversals"]:
        rev_total, rev_n, rev_src = _price_side(fig["reversals"])
        # Same rule for the reversal clause: no figure when nothing is priced.
        money = (" (about $%d)" % rev_total
                 if sum(rev_src.values()) else "")
        used += (" %d item%s frozen earlier %s tossed this month%s."
                 % (rev_n, "" if rev_n == 1 else "s",
                    "was" if rev_n == 1 else "were", money))
    lines.append(used)

    lines.append("Thrown away: " + _side_clause(t_total, t_n, t_src))

    notes = []
    # Only caveat a figure that was actually shown.
    if sum(r_src.values()) or sum(t_src.values()):
        notes.append("Every price is a rough estimate, not what you actually "
                     "paid.")
    if fig["reconstructed"]:
        n = fig["reconstructed"]
        notes.append("%d tier%s reconstructed from before I recorded %s."
                     % (n, "" if n == 1 else "s", "it" if n == 1 else "them"))
    if notes:
        lines += ["", " ".join(notes)]
    return "\n".join(lines)


def month_summary(con, chat_id, today=None):
    return compose_month(month_figures(con, chat_id, today))


def all_time_figures(con, chat_id):
    """Totals, where a reversed rescue is not a rescue.

    It counts once, as a toss. A month reports what happened in it; a total
    reports how things ended, so the two disagree on purpose (SKILL §15).
    """
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM items WHERE chat_id=? AND state != 'open'", (chat_id,))]
    rescued, tossed = [], []
    for r in rows:
        binned = (r["state"] == "tossed"
                  or (r["state"] == "frozen" and r["freezer_outcome"] == "tossed"))
        if binned:
            tossed.append(r)
        elif is_rescue(r["state"], r["tier"]):
            rescued.append(r)
    return {"rescued": rescued, "tossed": tossed}


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


def nudge_head(items, today=None):
    """The title line. It has to work on a lock screen by itself."""
    today = today or date.today()
    t0 = [i for i in items if sl.tier(i["use_by_date"], today) == 0]
    t1 = [i for i in items if sl.tier(i["use_by_date"], today) == 1]
    if t1 and not t0:
        hero = t1[0]["name"]
        return ("Use the %s tonight, or freeze it" % hero if len(t1) == 1
                else "%s and %d more to use tonight or freeze" % (hero, len(t1) - 1))
    if t0 and not t1:
        return ("1 thing past its best: check before eating" if len(t0) == 1
                else "%d things past their best: check before eating" % len(t0))
    if t0 and t1:
        return "%d to use tonight, %d to check" % (len(t1), len(t0))
    return "Coming up: %s" % _join([i["name"] for i in items])


def compose_nudge(items, today=None):
    """The message body. The title line has to work on a lock screen by itself."""
    today = today or date.today()
    if not items:
        return None

    t0 = [i for i in items if sl.tier(i["use_by_date"], today) == 0]
    t1 = [i for i in items if sl.tier(i["use_by_date"], today) == 1]

    lines = [nudge_head(items, today), ""]
    if t1:
        lines.append(sl.TIERS[1])
        for i in t1:
            lines.append("  • %s: %s%s" % (
                i["name"], sl.when(i["use_by_date"], today),
                " (a guess)" if i["estimated"] else ""))
        lines.append("")
    if t0:
        lines.append(sl.TIERS[0])
        for i in t0:
            note = ": raw, toss it" if i["risk"] == sl.RED else ""
            lines.append("  • %s: %s%s" % (
                i["name"], sl.when(i["use_by_date"], today), note))
    return "\n".join(lines).strip()


def compose_inventory(items, today=None):
    today = today or date.today()
    if not items:
        return "Nothing tracked yet. Send me a list and I'll start."
    out, seen = [], None
    for i in items:
        t = sl.tier(i["use_by_date"], today)
        if t != seen:
            out.append("" if seen is not None else None)
            out.append(sl.TIERS[t])
            seen = t
        out.append("  • %s: %s%s" % (
            i["name"], sl.when(i["use_by_date"], today),
            " (a guess)" if i["estimated"] else ""))
    return "\n".join(x for x in out if x is not None).strip()
