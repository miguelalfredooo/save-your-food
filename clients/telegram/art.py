"""Small ASCII drawings. Two kinds, doing two different jobs.

GLYPHS are evergreen. One drawing per category, the same one every time: a can
always means pantry, a hen always means raw poultry, an onion always means the
counter. Repetition is the whole point. Used consistently, they stop being
decoration and become a vocabulary, so someone can see which bucket a thing
landed in instead of reading that it did. That matters here because "pantry" and
"fridge" are the distinction people get wrong.

FRAMES rotate. They mark a moment that has no food behind it: an empty at-risk
list, the end of setup, a milestone. Those are supposed to feel like a small
surprise, so the same one twice running makes it furniture.

The two rules are opposites, and that is deliberate:

  a glyph MUST repeat    or it is not a vocabulary
  a frame MUST NOT       or it is not a surprise

Where none of it may go
-----------------------
  NEVER in a nudge that needs a decision. It has to scan on a lock screen in
  one glance. A drawing pushes the item name down and buys nothing. Same
  reasoning as keeping money out of a nudge.

  NEVER celebrating a toss. Food was wasted, and a toss is already the moment
  someone feels worst about using this. A picture over it reads as mockery.
  A toss gets one quiet line.

  NEVER on a question. Art marks an outcome; a disposal prompt is still open.

Why a library and not a generator
---------------------------------
The client is stdlib-only with no model behind it, so it cannot draw at runtime,
and evergreen art would not want it to: a can that came out slightly different
each time would be worse than no can. Frames are authored and vetted ahead of
time by the ascii-art-curator agent, against these rules and the size limits
below. Anything wider than MAX_WIDTH scrolls sideways on a phone, which is the
opposite of delight.
"""

import re
import textwrap

# 24x8 is the largest canvas that still holds still on a phone. Telegram's
# <pre> block keeps the monospace column width, but the bubble itself is
# still proportional to screen width: on the narrowest phones still in use
# (roughly 320 logical pixels wide) a pre block has room for about 28
# monospace columns before it wraps and scrolls sideways, which is the exact
# failure MAX_WIDTH exists to prevent. 24 keeps a safety margin under that
# for older/smaller phones and larger system fonts, while still being half
# again as wide as the old 16 - enough for a bigger, single-scene frame
# instead of another small icon. 8 lines gives those bigger scenes room to
# read as a scene rather than a cropped fragment, without turning into a
# wall of text under a one-line nudge. The small evergreen glyphs below do
# not need the extra room and are left exactly as they were: nobody should
# have to relearn one.
MAX_WIDTH = 24
MAX_LINES = 8


def _f(*lines):
    return "\n".join(lines)


# --- evergreen glyphs -------------------------------------------------------
# One per category. These never rotate and never change: the whole value is
# that the same drawing means the same thing every single time.

CAN = _f(
    "  ,-----.",
    "  |=====|",
    "  | ### |",
    "  | ### |",
    "  '-----'")

ONION = _f(
    "    \\|/",
    "   .-'-.",
    "  ( ( ) )",
    "   '---'")

ICEBOX = _f(
    "  .------.",
    "  |      |o",
    "  |      |o",
    "  '------'")

HEN = _f(
    "    ,",
    "   (o)",
    "  (   )>",
    "   ^ ^")

CHOP = _f(
    "    ,-.",
    "   (   )--",
    "   (___)")

FISH = _f(
    "    ,-.",
    "  ><(o  )",
    "    `-'")

LEAF = _f(
    "    ,/|",
    "   / /",
    "  / /",
    " (_/")

CARTON = _f(
    "  ____",
    " |\\  /|",
    " | \\/ |",
    " |    |",
    " |____|")

EGG = _f(
    "   .--.",
    "  /    \\",
    "  \\    /",
    "   '--'")

WEDGE = _f(
    "    /|",
    "   /o|",
    "  /__|")

POT = _f(
    "   ~  ~  ~",
    "  /-------\\",
    "  \\_______/")

LOAF = _f(
    "   .-----.",
    "  /       \\",
    " |_________|")

APPLE = _f(
    "    .|",
    "   (   )",
    "   (___)")

FLAKE = _f(
    "   \\ | /",
    "  -- * --",
    "   / | \\")

GLYPHS = {
    "pantry": CAN,
    "counter": ONION,
    "fridge": ICEBOX,
    "poultry": HEN,
    "meat": CHOP,
    "fish": FISH,
    "greens": LEAF,
    "dairy": CARTON,
    "egg": EGG,
    "cheese": WEDGE,
    "leftovers": POT,
    "bread": LOAF,
    "fruit": APPLE,
    "frozen": FLAKE,
}

# Keyword to category. First match wins, so specific before general, exactly as
# in the shelf-life table. Order here is checked against that table on purpose:
# a name must never reach a drawing that contradicts the bucket it landed in.
ITEM_CATEGORY = (
    (("leftover", "soup", "stew", "guiso", "cooked rice"), "leftovers"),
    (("chicken", "turkey", "hen", "poultry", "duck"), "poultry"),
    (("fish", "salmon", "tilapia", "shrimp", "prawn", "scallop", "shellfish"), "fish"),
    (("beef", "pork", "lamb", "bacon", "steak", "chops", "ham", "deli meat",
      "sausage", "chorizo"), "meat"),
    (("egg",), "egg"),
    (("cheese", "parmesan", "cheddar", "manchego", "brie", "ricotta"), "cheese"),
    (("milk", "cream", "yogurt", "yoghurt", "half and half", "butter"), "dairy"),
    (("spinach", "lettuce", "arugula", "kale", "greens", "salad", "herb",
      "cilantro", "parsley", "culantro", "basil", "mint", "broccoli",
      "asparagus", "zucchini", "mushroom"), "greens"),
    (("bread", "tortilla", "bagel", "roll", "bun", "pita"), "bread"),
    (("berry", "berries", "strawberr", "blueberr", "raspberr", "apple",
      "orange", "grape", "melon", "pineapple", "cut fruit", "lemon",
      "lime", "banana"), "fruit"),
)


# --- rotating frames --------------------------------------------------------
# For moments with no food behind them. These are meant to surprise, so the
# last one shown is remembered per person and excluded.

PLATE = _f(
    "  .-~~~~~~-.",
    " /          \\",
    " \\          /",
    "  '-......-'")

CUTLERY = _f(
    "  | |   /\\",
    "  |_|  |__|")

SHELVES = _f(
    "  .-------.",
    "  |  ---  |",
    "  |  ---  |",
    "  '-------'")

SUN = _f(
    "   \\  |  /",
    "    .---.",
    "  - (   ) -",
    "    '---'",
    "   /  |  \\")

STARS = _f(
    "   .  *  .",
    "  *  \\|/  *",
    "   -- * --",
    "  *  /|\\  *")

CROWN = _f(
    "  \\  /\\  /",
    "   \\/  \\/",
    "  [======]")

# General-purpose frames. Bigger scenes, sized for the wider canvas above,
# and deliberately not owned by a single moment: each is wired into every
# moment its scene actually fits, so the shared "no repeat" rule against
# `avoid` does real work across moments instead of only within one. A cake
# after a milestone and a cake on the scorecard a week later still reads as
# two different surprises; a cake twice in the same breath would not.
CUPBOARD = _f(
    "  .-----------------.",
    "  |  ------------   |",
    "  |                 |",
    "  |  ------------   |",
    "  |                 |",
    "  |  ------------   |",
    "  '-----------------'")

BASKET = _f(
    "     o   o   o   o",
    "   .-----------------.",
    "  / v v v v v v v v \\",
    "  \\_________________/")

CAKE = _f(
    "        *",
    "        |",
    "     .-------.",
    "    |:::::::::|",
    "    |_________|",
    "   |:::::::::::|",
    "   |_____________|")

MUG = _f(
    "      (  (  (",
    "     .----------.",
    "    |            |",
    "    |            |_",
    "    |            | )",
    "    |____________|_)",
    "     '----------'")

# A fourth occasion marker, distinct from CAKE (a dessert), CROWN (regalia)
# and STARS (a burst): bunting, the thing you actually string up for an
# event. Shares milestone and scorecard with those three so the rotation
# pool for "something worth marking" is wider, which is what keeps any one
# of them from turning into furniture.
BANNER = _f(
    "  *      o      *",
    " /\\  /\\  /\\  /\\ ",
    "/  \\/  \\/  \\/  \\")

MOMENT_ART = {
    "used": (PLATE, CUTLERY),
    "frozen": (FLAKE,),
    "allclear": (SHELVES, SUN, CUPBOARD, BASKET),
    "welcome": (ICEBOX, MUG, CUPBOARD),
    "milestone": (STARS, CROWN, CAKE, BANNER),
    "scorecard": (CROWN, BASKET, CAKE, BANNER),
}

# Deliberately no coins/wallet/piggy-bank frame anywhere above. This system
# has no "money saved" figure to draw honestly: the only dollar amount it
# ever produces is what tossed food cost, reported loosely and never
# measured against a target, because it is meant to read as information,
# not a verdict. A cheerful currency drawing next to that number would
# either look like it is celebrating waste or like the app is grading a
# figure it is supposed to stay neutral about - exactly what keeping money
# out of a nudge already guards against. The honest version of "money
# saved" here is food used instead of tossed, one item at a time, and that
# is already drawn: PLATE and CUTLERY mark the moment it happens, CUPBOARD
# and BASKET echo a kitchen that is provisioned rather than bare. A second
# icon chasing the same idea would be vanity, not vocabulary.

# Moments that must never carry a drawing, and why. A rule without a reason
# gets deleted by the next person who reads it.
FORBIDDEN = {
    "tossed": "food was wasted; a drawing over it reads as mockery",
    "nudge": "has to scan on a lock screen in one glance",
    "toss_prompt": "it is asking a question, not marking an outcome",
}


# --- validation -------------------------------------------------------------

def measure(frame):
    lines = frame.split("\n")
    return len(lines), max(len(l) for l in lines)


def fits(frame):
    n, w = measure(frame)
    return n <= MAX_LINES and w <= MAX_WIDTH


def all_frames():
    seen = []
    for f in list(GLYPHS.values()):
        if f not in seen:
            seen.append(f)
    for frames in MOMENT_ART.values():
        for f in frames:
            if f not in seen:
                seen.append(f)
    return seen


# --- choosing ---------------------------------------------------------------

# Keywords short enough to appear inside an unrelated word ("egg" in
# "eggplant") get whole-word matching. Everything else, including the
# deliberately truncated stems ("strawberr" for strawberry/strawberries),
# stays on substring matching, or a prefix match would break them.
_EXACT_WORD_KEYS = {"egg"}


def category(name):
    """The category a food name belongs to, or None."""
    n = (name or "").lower()
    for keys, cat in ITEM_CATEGORY:
        for k in keys:
            if k in _EXACT_WORD_KEYS:
                if re.search(r"\b%ss?\b" % re.escape(k), n):
                    return cat
            elif k in n:
                return cat
    return None


def glyph(key):
    """The evergreen drawing for a category or a bucket. Always the same one.

    Takes either a category name ("poultry") or a bucket name ("pantry"), since
    both are looked up the same way and callers have one or the other.
    """
    return GLYPHS.get(key)


def for_item(name):
    """The evergreen drawing that matches this food, or None."""
    return GLYPHS.get(category(name))


def choose(moment, item=None, avoid=None):
    """A drawing for this moment, or None if the moment must not carry one.

    A food match wins, and wins even against `avoid`: the glyph is a label, so
    two chickens in a row is correct rather than repetitive. Only the rotating
    frames honour `avoid`.
    """
    if moment in FORBIDDEN:
        return None

    if item and moment in ("used", "frozen"):
        match = for_item(item)
        if match:
            return match

    options = [f for f in MOMENT_ART.get(moment, ()) if f != avoid]
    if not options:
        options = list(MOMENT_ART.get(moment, ()))
    return options[0] if options else None


def esc(text):
    """Escape a caption for HTML parse mode.

    Captions carry food names, and food names come from users. One stray angle
    bracket in "<3 cilantro" and Telegram reads the rest of the message as a
    tag, silently dropping it. Any caption in an HTML message goes through here.
    """
    return (str(text).replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))


def _wrap_caption(caption, width=MAX_WIDTH):
    """A caption's lines, word-wrapped to `width` so it can share the frame's
    <pre> block without forcing a phone to scroll sideways.

    A caption is prose, not a drawing, so it has none of a frame's width
    discipline baked in: a milestone line or a comma-joined pantry list can
    run well past MAX_WIDTH as a single line. `<pre>` does not wrap on its
    own, so without this a long caption inside the box would hit the exact
    failure MAX_WIDTH exists to prevent, just moved into the caption instead
    of the frame.

    Existing newlines are kept as hard breaks, since a caption sometimes
    carries its own short header ("Pantry (3)") over a longer line, and each
    of those is wrapped on its own so the header does not bleed into the
    text under it.
    """
    lines = []
    for para in caption.split("\n"):
        if not para.strip():
            lines.append(para)
            continue
        lines.extend(textwrap.wrap(para, width=width, break_long_words=True,
                                    break_on_hyphens=False) or [para])
    return lines


def render(frame, caption=None):
    """A drawing and its caption as one Telegram HTML pre block.

    Telegram sets a proportional font by default, which turns every drawing
    into rubble. A pre block is the only thing that holds the columns, and
    inside one the three HTML entities have to be escaped by hand.

    The caption lives inside the same pre block as the frame, the way a
    fridge or pantry list is one block rather than a box with a stray line
    of plain text bolted on after it. Wrapping happens on the raw caption
    before escaping, so the wrap width matches what actually shows on
    screen: an escaped "&amp;" is five characters in the string but one on
    the phone, and wrapping after escaping would cut lines short for no
    visible reason.
    """
    if not frame:
        # No pre block means no HTML, so the caption goes out as plain text and
        # must NOT be escaped. Escaping here would show "&amp;" to the user.
        return caption or ""
    body = esc(frame)
    if caption:
        wrapped = "\n".join(esc(line) for line in _wrap_caption(caption))
        body += "\n\n" + wrapped
    return "<pre>" + body + "</pre>"
