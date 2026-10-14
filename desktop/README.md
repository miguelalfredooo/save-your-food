# Options 1 and 2: no install

| File | What it is |
|---|---|
| `paste-this.md` | Option 1: the prompt people paste into any Claude chat |
| `save-your-food/SKILL.md` | Option 2: the Claude app skill |
| `save-your-food/scripts/make_ics.py` | Writes the calendar file of check-ins. Standard library only |
| `save-your-food.zip` | What people download and upload to the Claude app |
| `test_make_ics.py` | Tests for the calendar file. Run: `python3 test_make_ics.py` |

Setup steps for people are in the [README](../README.md).

**After changing the skill**, rebuild the zip from this folder, leaving out
Python caches:

    zip -X -r save-your-food.zip save-your-food -x '*/__pycache__/*' '*.DS_Store'

Keep `paste-this.md` in step with the skill's sorting, use-by table and safety
lines. It can't make a calendar file, so it ends with a list to paste instead.
