"""Reading a pasted recipe, in code.

A recipe link already skips the model: the bot fetches the page and drafts
it from the site's structured data. A pasted recipe used to depend on the
model deciding to call draft_recipe, and a small model often didn't. It
checked the ingredients against the fridge instead, or wrote the recipe back
as chat text. This reads the paste itself, so both routes end at the same
Save and Cancel preview.

The words are kept exactly as pasted. Only bullet marks, step numbers,
section headings and wrapping quotes are removed. Nothing is reworded.

Strict on purpose: a multi-line grocery list with quantities must not turn
into a recipe draft. A recipe needs a title line that is not itself an
ingredient, at least three ingredient lines, most of them with a quantity or
a unit, and either an ingredients heading or at least one step.

Pure functions only.
"""

import re

_QUOTES = "\"'“”‘’"
_FRACTIONS = "¼½¾⅓⅔⅛⅜⅝⅞"

_INGREDIENTS_HEAD = re.compile(r"^ingredients?\s*:?$", re.I)
_STEPS_HEAD = re.compile(
    r"^(instructions?|directions?|method|steps?|preparation)\s*:?$", re.I)
_BULLET = re.compile(r"^\s*[-*•·]\s*")
_NUMBERED = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):]\s*", re.I)
_QUANTITY = re.compile(r"^\s*(\d|[%s])" % _FRACTIONS)
_UNIT = re.compile(
    r"\b(cups?|tablespoons?|tbsps?|teaspoons?|tsps?|pounds?|lbs?|ounces?|oz|"
    r"grams?|kg|ml|liters?|litres?|cloves?|cans?|pinch|dash|slices?|"
    r"sticks?|scoops?|bunch(es)?|sprigs?|handful)\b", re.I)

_SAVE_REQUEST = re.compile(
    r"^\s*(please\s+)?(save|add|keep|put)\s+(it|this|that|the recipe|this recipe|"
    r"that recipe|it as a recipe|as a recipe|to notes|it to notes|this to notes|"
    r"that to notes|to my notes|in notes)(\s+(to|in)\s+(my\s+)?notes)?"
    r"(\s+please)?\s*[.!]*\s*$", re.I)

MIN_INGREDIENTS = 3
MAX_TITLE_CHARS = 100
STEP_MIN_CHARS = 60


def _lines(text):
    text = text.strip().strip(_QUOTES).strip()
    return [l.strip() for l in text.splitlines() if l.strip()]


def _measured(line):
    return bool(_QUANTITY.match(line) or _UNIT.search(line))


def _is_step(line):
    """A numbered line, or a long sentence. Short unnumbered lines are
    ingredients ("Coarse salt and fresh ground pepper")."""
    return bool(_NUMBERED.match(line)) or (
        len(line) >= STEP_MIN_CHARS and line.rstrip().endswith("."))


def _clean(line, step=False):
    line = _BULLET.sub("", line)
    if step:
        line = _NUMBERED.sub("", line)
    return line.strip()


def parse(text):
    """{"title", "ingredients", "steps"} for a pasted recipe, or None."""
    lines = _lines(text or "")
    if len(lines) < MIN_INGREDIENTS + 1:
        return None
    title = _clean(lines[0])
    if (len(title) > MAX_TITLE_CHARS or _measured(title)
            or _INGREDIENTS_HEAD.match(title) or _STEPS_HEAD.match(title)):
        return None

    ingredients, steps, headed, section = [], [], False, "ingredients"
    for line in lines[1:]:
        if _INGREDIENTS_HEAD.match(line):
            headed, section = True, "ingredients"
            continue
        if _STEPS_HEAD.match(line):
            headed, section = True, "steps"
            continue
        if section == "ingredients" and _is_step(line):
            section = "steps"
        if section == "steps":
            steps.append(_clean(line, step=True))
        else:
            ingredients.append(_clean(line))

    measured = sum(1 for i in ingredients if _measured(i))
    if (len(ingredients) < MIN_INGREDIENTS or measured * 2 < len(ingredients)
            or not (headed or steps)):
        return None
    return {"title": title, "ingredients": ingredients, "steps": steps}


def is_save_request(text):
    """"Save to notes", "add as a recipe", "save it": a request to save the
    recipe just sent, with no recipe in the message itself."""
    return bool(_SAVE_REQUEST.match(text or ""))
