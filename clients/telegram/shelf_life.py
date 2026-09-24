"""Shelf life and risk classes — the fridge-loop skill's section 4 and 6, as code.

Deliberately free of any Telegram or storage code so it can be tested on its own.
Days are the LOW end of each range: it is better to nudge a day early than a day late.
"""

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
BETTER_OUTSIDE = ("onion", "potato", "garlic", "winter squash", "butternut")

DEFAULT_DAYS, DEFAULT_CLASS = 5, YELLOW


def lookup(name):
    """(days, risk_class, estimated) for an item name."""
    n = name.lower().strip()
    for keys, days, cls in SHELF_LIFE:
        if any(k in n for k in keys):
            return days, cls, False
    return DEFAULT_DAYS, DEFAULT_CLASS, True


def better_outside(name):
    n = name.lower().strip()
    return any(k in n for k in BETTER_OUTSIDE)


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
