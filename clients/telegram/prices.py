"""Reference prices, for costing a toss or a rescue.

Where the numbers come from
---------------------------
`ops/reference-prices-west.md` is the source of truth. ROWS below is generated
from it, so the bot needs no file at runtime, and a test parses the markdown
again and fails if the two ever disagree. After a BLS refresh, regenerate:

    python3 prices.py --regenerate

What this client can and cannot reach
-------------------------------------
The skill's source order is: the exact `bought` line this item joins to, then
the median of your own receipts, then BLS West, then BLS US, then unpriced.

The first two are not available in this client at all. Both need receipt
capture, which needs vision and an API key, and this bot has no `Restock.md` --
it keeps its own SQLite store and cannot read the Mac side. So every figure it
produces comes from BLS, and every report has to say so. `price_for` takes a
`receipts` mapping anyway, so the day receipts exist the order is already right
and outranks BLS without further surgery.

Why there is no fallback to a similar item
------------------------------------------
A cilantro price guessed from romaine is the kind of number this system exists
to avoid. An item that is not in the table is unpriced, and unpriced is a
correct answer that gets reported as one. ALIASES only ever map a name to the
SAME item under another wording: "ground beef" to "Ground beef, 100%" is fine,
"naan" to "Bread, white pan" is not.

BLS tracks almost none of what is most likely to be tossed -- no fresh herbs,
greens, mushrooms, berries other than strawberries, yogurt, butter, tofu, fish
or leftovers. Thin coverage is the honest state of this table, not a bug in it.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# Only the test and the regenerator read the markdown; the bot runs off ROWS.
SOURCE_MD = os.path.join(HERE, "..", "..", "ops", "reference-prices-west.md")

UNPRICED = (None, None)


def parse_markdown(path=None):
    """Pull the BLS rows out of the ops table.

    Returns {item name: (pack_price, source)}. Only the BLS tables, which are
    the ones carrying a "BLS series" column. The "Your receipts" table has a
    different shape and is derived from Restock.md, never from here.
    """
    path = path or SOURCE_MD
    rows = {}
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    in_bls = False
    for line in lines:
        if line.startswith("|") and "BLS series" in line:
            in_bls = True
            continue
        if line.startswith("#"):
            in_bls = False
            continue
        if not in_bls or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or set(cells[0]) <= set("-: "):
            continue
        try:
            price = float(cells[4])
        except ValueError:
            continue
        rows[cells[0]] = (price, cells[2])
    return rows


# Same item, other wording. Never a neighbouring item: see the docstring.
ALIASES = {
    "ground beef": "Ground beef, 100%",
    "minced beef": "Ground beef, 100%",
    "beef mince": "Ground beef, 100%",
    "chicken breast": "Chicken breast, boneless",
    "chicken breasts": "Chicken breast, boneless",
    "boneless chicken breast": "Chicken breast, boneless",
    "whole chicken": "Chicken, whole",
    "chicken legs": "Chicken legs, bone-in",
    "drumsticks": "Chicken legs, bone-in",
    "sirloin": "Steak, sirloin, Choice boneless",
    "sirloin steak": "Steak, sirloin, Choice boneless",
    "chuck roast": "Chuck roast, Choice boneless",
    "pork chops": "Pork chops, boneless",
    "bacon": "Bacon, sliced",
    "ham": "Ham, boneless",
    "milk": "Milk, whole",
    "whole milk": "Milk, whole",
    "cheddar": "Cheddar, natural",
    "cheddar cheese": "Cheddar, natural",
    "eggs": "Eggs, grade A large",
    "egg": "Eggs, grade A large",
    "ice cream": "Ice cream, bulk",
    "banana": "Bananas",
    "lemon": "Lemons",
    "navel oranges": "Oranges, navel",
    "romaine": "Lettuce, romaine",
    "romaine lettuce": "Lettuce, romaine",
    "iceberg lettuce": "Lettuce, iceberg",
    "tomatoes": "Tomatoes, field grown",
    "white bread": "Bread, white pan",
    "whole wheat bread": "Bread, whole wheat pan",
    "white rice": "Rice, white long grain",
    "spaghetti": "Spaghetti and macaroni",
    "macaroni": "Spaghetti and macaroni",
    "flour": "Flour, all purpose",
    "dried beans": "Beans, dried",
    "sugar": "Sugar, white",
    "ground coffee": "Coffee, ground",
}


def _norm(name):
    n = (name or "").lower().strip()
    n = re.sub(r"\s*\([^)]*\)", "", n)        # "chicken (fridge)" -> "chicken"
    n = re.sub(r"[^a-z0-9% ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def price_for(name, receipts=None):
    """(pack_price, source) for a food name, or (None, None) if unpriced.

    `receipts` is {normalised name: (price, source)} and outranks everything
    here, per the skill's source order. This client never has any yet.
    """
    n = _norm(name)
    if not n:
        return UNPRICED
    if receipts and n in receipts:
        return receipts[n]
    exact = ALIASES.get(n)
    if exact and exact in ROWS:
        return ROWS[exact]
    for item, priced in ROWS.items():
        if _norm(item) == n:
            return priced
    return UNPRICED


def source_label(src):
    """How a source reads to a person: 'your receipts' or 'BLS'."""
    if not src:
        return None
    return "your receipts" if src.startswith("R") else "BLS"


ROWS = {
    'American processed cheese': (3.56, 'US Aug 2026'),
    'Bacon, sliced': (5.19, 'W'),
    'Bananas': (1.43, 'W'),
    'Beans, dried': (1.39, 'W'),
    'Beef roasts, all uncooked': (24.54, 'W'),
    'Bread, white pan': (2.54, 'W'),
    'Bread, whole wheat pan': (3.52, 'US May 2026'),
    'Cheddar, natural': (3.66, 'W'),
    'Chicken breast, boneless': (7.08, 'W'),
    'Chicken legs, bone-in': (3.43, 'W Apr 2026'),
    'Chicken, whole': (9.02, 'W'),
    'Chuck roast, Choice boneless': (26.18, 'W'),
    'Coffee, ground': (6.97, 'US Aug 2026'),
    'Eggs, grade A large': (2.27, 'US Aug 2026'),
    'Flour, all purpose': (2.74, 'US Aug 2026'),
    'Grapefruit': (1.60, 'US Aug 2026'),
    'Ground beef, 100%': (7.44, 'W'),
    'Ground beef, all uncooked': (7.21, 'W'),
    'Ham, boneless': (5.22, 'W'),
    'Ice cream, bulk': (7.38, 'W'),
    'Lemons': (0.50, 'W'),
    'Lettuce, iceberg': (1.84, 'US Aug 2026'),
    'Lettuce, romaine': (5.17, 'W May 2026'),
    'Milk, whole': (2.42, 'W'),
    'Orange juice, frozen conc.': (3.61, 'US Jul 2026'),
    'Oranges, navel': (0.73, 'W May 2026'),
    'Pork chops, all': (6.29, 'W'),
    'Pork chops, boneless': (6.87, 'W'),
    'Potatoes, white': (5.02, 'W'),
    'Rice, white long grain': (2.22, 'US Aug 2026'),
    'Spaghetti and macaroni': (1.37, 'US Aug 2026'),
    'Steak, sirloin, Choice boneless': (18.77, 'W'),
    'Steaks, all uncooked beef': (13.81, 'W'),
    'Strawberries': (3.44, 'US Aug 2026'),
    'Sugar, white': (4.04, 'W'),
    'Tomatoes, field grown': (1.98, 'US Aug 2026'),
}


def _regenerate():
    """Rewrite this file's ROWS from the markdown. Run after a BLS refresh."""
    import sys
    fresh = parse_markdown()
    path = os.path.join(HERE, "prices.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    start = src.index("ROWS = {")
    end = src.index("\n}", start) + 2
    block = ["ROWS = {"]
    for item in sorted(fresh):
        price, s = fresh[item]
        block.append("    %r: (%.2f, %r)," % (item, price, s))
    block.append("}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(src[:start] + "\n".join(block) + src[end:])
    sys.stdout.write("rewrote %d rows\n" % len(fresh))


if __name__ == "__main__":
    import sys
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        sys.stdout.write("%d rows\n" % len(ROWS))
