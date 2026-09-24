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

MAX_WIDTH = 16
MAX_LINES = 6


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

MOMENT_ART = {
    "used": (PLATE, CUTLERY),
    "frozen": (FLAKE,),
    "allclear": (SHELVES, SUN),
    "welcome": (ICEBOX,),
    "milestone": (STARS, CROWN),
    "scorecard": (CROWN,),
}

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

def category(name):
    """The category a food name belongs to, or None."""
    n = (name or "").lower()
    for keys, cat in ITEM_CATEGORY:
        if any(k in n for k in keys):
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


def render(frame, caption=None):
    """A drawing as a Telegram HTML pre block, with an optional line under it.

    Telegram sets a proportional font by default, which turns every drawing into
    rubble. A pre block is the only thing that holds the columns, and inside one
    the three HTML entities have to be escaped by hand.
    """
    if not frame:
        # No pre block means no HTML, so the caption goes out as plain text and
        # must NOT be escaped. Escaping here would show "&amp;" to the user.
        return caption or ""
    body = (frame.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))
    out = "<pre>" + body + "</pre>"
    if caption:
        out += "\n" + esc(caption)
    return out
