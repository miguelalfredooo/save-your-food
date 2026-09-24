"""Delight: small ASCII drawings at the moments that deserve one.

Where this can and cannot go
----------------------------
The whole point of this system is that it does not nag. Art is the easiest way
to undo that, so it lives under rules rather than taste:

  NEVER in a nudge that needs a decision. The nudge has to scan on a lock
  screen in one glance. A drawing above it pushes the item name down and buys
  nothing. Same reasoning as keeping money out of a nudge.

  NEVER celebrating a toss. Food was wasted. A confetti burst over it reads as
  mockery, and a toss is already the moment someone feels worst about using
  this. Tosses get one quiet line and no drawing.

  NEVER twice running. Delight is a surprise; the same picture three times is
  furniture. The last frame shown is remembered per chat and excluded.

  RARELY for the big ones. Milestone art is held back for milestones. If the
  crown shows up every Tuesday it stops being a crown.

So art appears on: using something (the win), freezing it (a save), an empty
at-risk list (silence, made visible), finishing setup, and the monthly
scorecard.

Why the art matches the food
----------------------------
A generic tick is acknowledgement. A little carton when you finish the milk is
recognition, which is a different feeling and a much cheaper one to produce:
the category machinery already exists for shelf life, so it is reused here.

Why this is a library and not a generator
-----------------------------------------
The bot is stdlib-only with no model behind it, so it cannot draw anything at
runtime. Every frame is authored and vetted ahead of time by the art-curator
agent, against the rules above and a width limit. Anything wider than MAX_WIDTH
breaks into a scrolling mess on a phone, which is the opposite of delight.
"""

MAX_WIDTH = 16
MAX_LINES = 6


def _f(*lines):
    return "\n".join(lines)


# --- frames keyed to the food -----------------------------------------------

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

LEAF = _f(
    "    ,/|",
    "   / /",
    "  / /",
    " (_/")

PAN = _f(
    "   ___",
    "  (___)====")

POT = _f(
    "   ~  ~  ~",
    "  /-------\\",
    "  \\_______/")

JAR = _f(
    "  [=====]",
    "  |     |",
    "  |     |",
    "  |_____|")

WEDGE = _f(
    "   /|",
    "  /o|",
    " /__|")

# Keyword to frame. First match wins, so specific goes before general.
ITEM_ART = (
    (("milk", "cream", "yogurt", "yoghurt", "half and half"), CARTON),
    (("egg",), EGG),
    (("spinach", "lettuce", "arugula", "kale", "greens", "salad", "herb",
      "cilantro", "parsley", "culantro", "basil", "mint"), LEAF),
    (("beef", "chicken", "pork", "lamb", "turkey", "bacon", "steak", "fish",
      "salmon", "shrimp", "tilapia", "chops"), PAN),
    (("leftover", "soup", "stew", "guiso", "cooked rice"), POT),
    (("cheese", "parmesan", "cheddar", "manchego", "brie"), WEDGE),
    (("hummus", "olives", "pickle", "capers", "sauce"), JAR),
)


# --- frames keyed to the moment ---------------------------------------------

PLATE = _f(
    "  .-~~~~~~-.",
    " /          \\",
    " \\          /",
    "  '-......-'")

CUTLERY = _f(
    "  | |   /\\",
    "  |_|  |__|")

FLAKE = _f(
    "   \\ | /",
    "  -- * --",
    "   / | \\")

ICEBOX = _f(
    "  .------.",
    "  | *  * |",
    "  |  **  |",
    "  '------'")

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

DOOR = _f(
    "  .------.",
    "  |      |o",
    "  |      |o",
    "  '------'")

# Common frames rotate freely. Rare ones are held for milestones.
MOMENT_ART = {
    "used":     (PLATE, CUTLERY),
    "frozen":   (FLAKE, ICEBOX),
    "allclear": (SHELVES, SUN),
    "welcome":  (DOOR,),
    "milestone": (STARS, CROWN),
    "scorecard": (CROWN,),
}

# Moments that must never carry a drawing, and why.
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
    for _, f in ITEM_ART:
        if f not in seen:
            seen.append(f)
    for frames in MOMENT_ART.values():
        for f in frames:
            if f not in seen:
                seen.append(f)
    return seen


# --- choosing ---------------------------------------------------------------

def for_item(name):
    """The frame that matches this food, or None."""
    n = (name or "").lower()
    for keys, frame in ITEM_ART:
        if any(k in n for k in keys):
            return frame
    return None


def choose(moment, item=None, avoid=None):
    """A frame for this moment, or None if the moment must not carry one.

    Prefers a frame that matches the food, because recognition beats
    acknowledgement. Falls back to the moment's own frames, skipping whatever
    was shown last so the same picture never lands twice running.
    """
    if moment in FORBIDDEN:
        return None

    if item and moment in ("used", "frozen"):
        match = for_item(item)
        if match and match != avoid:
            return match

    options = [f for f in MOMENT_ART.get(moment, ()) if f != avoid]
    if not options:
        options = list(MOMENT_ART.get(moment, ()))
    if not options:
        return None
    # Rotate rather than randomise: with two frames, alternating IS the
    # rotation, and a deterministic pick is testable.
    return options[0]


def render(frame, caption=None):
    """A frame as a Telegram HTML pre block, with an optional line under it.

    Telegram sets a proportional font by default, which turns every drawing
    into rubble. A pre block is the only thing that holds the columns, and
    inside one the three HTML entities have to be escaped by hand.
    """
    if not frame:
        return caption or ""
    body = (frame.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))
    out = "<pre>" + body + "</pre>"
    if caption:
        out += "\n" + caption
    return out
