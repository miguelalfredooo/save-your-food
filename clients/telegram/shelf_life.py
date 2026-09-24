"""Shelf life and risk classes — the fridge-loop skill's section 4 and 6, as code.

Deliberately free of any Telegram or storage code so it can be tested on its own.
Days are the LOW end of each range: it is better to nudge a day early than a day late.
"""

import re
from datetime import date, timedelta

RED, YELLOW, GREEN = "red", "yellow", "green"

# (match substrings, days, risk class)
# Order matters — the first match wins, so put specific before general.
SHELF_LIFE = [
    (("ground beef", "ground chicken", "ground turkey", "ground pork"), 1, RED),
    (("chicken breast", "chicken thigh", "chicken", "turkey"), 1, RED),
    (("fish", "salmon", "tilapia", "shrimp", "prawn", "shellfish", "scallop"), 1, RED),
    (("steak", "chops", "roast", "pork belly", "beef", "pork", "lamb"), 3, RED),
    (("bacon",), 7, RED),
    (("leftover", "cooked rice", "soup", "stew", "guiso"), 3, YELLOW),
    (("deli meat", "ham", "turkey slices"), 3, YELLOW),
    (("tofu",), 3, YELLOW),
    (("cut fruit", "melon", "pineapple"), 3, YELLOW),
    (("spinach", "lettuce", "arugula", "salad", "greens", "kale"), 3, YELLOW),
    (("berry", "berries", "strawberr", "blueberr", "raspberr"), 3, YELLOW),
    (("cilantro", "parsley", "culantro", "basil", "herb", "mint"), 3, YELLOW),
    (("mushroom",), 3, YELLOW),
    (("broccoli", "asparagus", "green bean", "zucchini"), 3, YELLOW),
    (("hummus",), 7, YELLOW),
    (("oat milk", "oatmilk", "almond milk", "soy milk", "nut milk"), 7, YELLOW),
    (("chocolate milk", "milk", "cream", "half and half"), 7, YELLOW),
    (("soft cheese", "brie", "ricotta", "cottage cheese"), 7, YELLOW),
    (("yogurt", "yoghurt"), 7, YELLOW),
    (("pepper", "cucumber", "grape"), 7, GREEN),
    (("hard cheese", "parmesan", "cheddar", "manchego"), 21, GREEN),
    (("carrot", "cabbage", "orange", "lemon", "lime", "apple", "citrus"), 21, GREEN),
    (("egg",), 21, GREEN),
]

# Keeps better OUT of the fridge — worth saying rather than tracking.
#
# Matched on whole words, not substrings: "garlic powder" and "Campbell's French
# onion" are pantry items, and a bare substring match put both on the counter.
# A name qualifies only if every word in it is either the produce itself or a
# harmless qualifier.
BETTER_OUTSIDE = ("onion", "onions", "potato", "potatoes", "garlic", "shallot",
                  "shallots", "butternut", "squash")

OUTSIDE_QUALIFIERS = {
    "a", "and", "of", "the", "bulb", "bulbs", "head", "heads", "whole", "some",
    "fresh", "raw", "red", "white", "yellow", "sweet", "russet", "yukon",
    "gold", "golden", "purple", "baby", "new", "winter", "spanish", "vidalia",
    "cloves", "clove", "bag", "lb", "lbs",
}

# --- shelf-stable guard ----------------------------------------------------
#
# The first question people answer is "what's in your fridge", and a lot of
# them answer with the whole kitchen — soy sauce, cumin, canned beans. Those
# have no clock on them. Tracked, they produce a nudge asking whether you used
# or tossed your oregano, which is the exact noise that kills these systems.
# So: refuse them at capture, and say why.
#
# Checked BEFORE the shelf-life table, so the collisions below are handled
# first or they would swallow real perishables.

# Never shelf-stable, whatever else matches. "ground beef" contains "ground ",
# "cooked rice" contains "rice", "fresh ginger" contains "ginger".
NEVER_STABLE = (
    "ground beef", "ground chicken", "ground turkey", "ground pork",
    "ground lamb", "ground meat", "cooked", "leftover", "fresh ",
    # "butter" is a pantry keyword, and these are not butter.
    "butter lettuce", "butterhead", "buttermilk", "butternut",
    # "minced" is a pantry modifier; minced meat is a one-day red item.
    "minced beef", "minced meat", "minced pork", "minced lamb",
    "minced chicken", "minced turkey",
)

# A modifier is enough on its own: dried, ground, powdered, canned, jarred.
# Matched as whole words so "jarred" at the end of a name still counts —
# "minced garlic, jarred" was slipping through when these needed a trailing space.
MODIFIER_TOKENS = {
    "dried", "ground", "powdered", "canned", "jarred", "tinned", "instant",
    "minced", "bottled", "granulated",
}

# Substring modifiers, for the ones that are not a separate word.
STABLE_MODIFIERS = (" powder", "can of ", "cans of ", "jar of ", "tin of ")

STABLE = (
    # oils, vinegars, cooking wines
    "oil", "vinegar", "cooking wine", "mirin", "shaoxing", "ghee",
    # sauces and condiments
    "soy sauce", "fish sauce", "oyster sauce", "hoisin", "worcestershire",
    "sriracha", "bbq sauce", "barbecue sauce", "ketchup", "mustard", "mayo",
    "mayonnaise", "stir fry sauce", "soyaki", "maggi", "liquid smoke",
    "hot sauce", "tahini", "peanut butter", "sofrito", "achiote",
    # salt, spices, blends. Note the pepper keys are specific on purpose —
    # bare "pepper" is a bell pepper and belongs in the fridge.
    "salt", "black pepper", "white pepper", "peppercorn", "lemon pepper",
    "pepper flakes", "seasoning", "adobo", "sazon", "sazón", "berbere",
    "cumin", "oregano", "paprika", "turmeric", "cinnamon", "nutmeg", "thyme",
    "rosemary", "sage", "tarragon", "coriander", "allspice", "bay leaf",
    "bay leaves", "five spice", "herbes de provence", "old bay", "curry",
    "chili powder", "msg", "vanilla extract", "cocoa",
    # canned, jarred, bouillon
    "bouillon", "broth", "consomm", "stock cube", "paste",
    "crushed tomato", "coconut milk", "evaporated milk", "condensed milk",
    "powdered milk", "pimiento", "olives", "capers", "vienna sausage",
    "soup mix", "seasoning mix", "cake mix", "pancake mix",
    "black bean", "pink bean", "kidney bean", "refried", "pinto",
    "garbanzo", "chickpea", "gandule", "pigeon pea", "lentil",
    "kernel corn", "canned corn",
    # grains, pasta, flour, baking
    "rice", "spaghetti", "macaroni", "pasta", "noodle", "udon", "flour",
    "cornstarch", "breadcrumb", "panko", "yeast", "baking soda", "sesame seed",
    "cream of", "campbell", "consomme", "butter", "frozen",
    "baking powder", "sugar", "honey", "maple syrup", "syrup",
    "chocolate chip", "oats", "chia", "flax", "raisin",
)


def shelf_stable(name):
    """True for things with no clock on them. Checked before the shelf-life table."""
    n = name.lower().strip()
    if any(k in n for k in NEVER_STABLE):
        return False
    if any(w in MODIFIER_TOKENS for w in _tokens(n)):
        return True
    if any(k in n for k in STABLE_MODIFIERS):
        return True
    return any(k in n for k in STABLE)


def not_tracked(name):
    """(True, reason) for anything that should be refused at capture.

    Two different reasons, and the difference is worth saying out loud: an onion
    is perishable but belongs on the counter, whereas cumin is simply not on a
    clock.
    """
    if better_outside(name):
        return True, "outside"
    if shelf_stable(name):
        return True, "stable"
    return False, None

DEFAULT_DAYS, DEFAULT_CLASS = 5, YELLOW


def lookup(name):
    """(days, risk_class, estimated) for an item name."""
    n = name.lower().strip()
    for keys, days, cls in SHELF_LIFE:
        if any(k in n for k in keys):
            return days, cls, False
    return DEFAULT_DAYS, DEFAULT_CLASS, True


def _tokens(name):
    return [w for w in re.split(r"[^a-z]+", name.lower()) if w]


def better_outside(name):
    words = _tokens(name)
    if not words:
        return False
    if not any(w in BETTER_OUTSIDE for w in words):
        return False
    # Every other word has to be a qualifier. "garlic powder" fails on "powder",
    # "sweet potatoes" passes, "onion soup" fails on "soup".
    return all(w in BETTER_OUTSIDE or w in OUTSIDE_QUALIFIERS for w in words)


def use_by(name, added=None):
    added = added or date.today()
    days, cls, est = lookup(name)
    return added + timedelta(days=days), cls, est


# --- urgency: computed against today, never stored -------------------------

TIERS = {
    0: "Check before eating",
    1: "Tonight or freeze it",
    2: "Plan this week",
    3: "Fine for now",
}

# How long an item keeps rolling past its date before it becomes a toss prompt.
BUDGET = {RED: 1, YELLOW: 3, GREEN: 7}


def tier(use_by_date, today=None):
    days_left = (use_by_date - (today or date.today())).days
    if days_left < 0:
        return 0
    if days_left <= 1:
        return 1
    if days_left <= 4:
        return 2
    return 3


def past_budget(use_by_date, risk_class, today=None):
    """True once an item has rolled longer than its class allows."""
    over = ((today or date.today()) - use_by_date).days
    return over > BUDGET.get(risk_class, 3)


def when(use_by_date, today=None):
    """Human phrasing. Weekday always present — 'Fri Sep 25' scans, '09-25' needs arithmetic."""
    today = today or date.today()
    days_left = (use_by_date - today).days
    stamp = use_by_date.strftime("%a %b ") + str(use_by_date.day)
    if days_left == 0:
        return stamp + " (today)"
    if days_left == 1:
        return stamp + " (tomorrow)"
    if days_left < 0:
        n = -days_left
        return stamp + (" (1 day past)" if n == 1 else " (%d days past)" % n)
    return stamp
