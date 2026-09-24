"""Renders the messages the bot would send, for given dates. No network, no token.

    python3 preview.py              # today
    python3 preview.py 2026-09-25   # any date
"""
import json, os, sys, tempfile
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fridge, shelf_life as sl

day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
con = fridge.connect(tempfile.mktemp(suffix=".db"))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json")) as f:
    for it in json.load(f)["items"]:
        con.execute("INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
                    " VALUES (1,?,?,?,0,?, 'open')",
                    (it["name"], it["use_by"], it["risk"], day.isoformat()))
con.commit()

bar = "─" * 52
print("\n%s\n  NUDGE AS IT WOULD ARRIVE ON %s\n%s\n" % (bar, day.strftime("%a %b %d %Y"), bar))
items = fridge.at_risk(con, 1, day)
body = fridge.compose_nudge(items, day)
print(body if body else "(silent — nothing at risk)")
if items:
    print("\nthen one tappable line each:\n")
    for i in items:
        print("   %s — %s" % (i["name"], sl.when(i["use_by_date"], day)))
        print("   [ ✅ Used it ]  [ ❄ Froze it ]  [ \U0001f5d1 Tossed it ]\n")
print("%s\n  /fridge\n%s\n" % (bar, bar))
print(fridge.compose_inventory(fridge.open_items(con, 1), day))
print()
