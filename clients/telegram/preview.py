"""Renders the messages the bot would send, for given dates. No network, no token.

    python3 preview.py              # today
    python3 preview.py 2026-09-25   # any date

Shows the nudge card as it arrives, the same card after the first item is
tapped, the /fridge card, and the /freezer card. Falls back to seed.example.json when there is
no seed.json.
"""
import html, json, os, re, sys, tempfile
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, fridge


class PrintTG:
    """Prints what bot.py would send or edit, roughly as a phone shows it."""

    def _show(self, text, buttons):
        text = re.sub(r"</?pre>", "", text)
        text = re.sub(r"<b>(.*?)</b>", lambda m: m.group(1).upper(), text)
        print(html.unescape(text))
        for row in buttons or ():
            print("  ".join("[ %s ]" % b["text"] for b in row))
        print()

    def send(self, chat_id, text, buttons=None, html=False):
        self._show(text, buttons)
        return {"ok": True, "result": {"message_id": 1}}

    def edit(self, chat_id, message_id, text, buttons=None, html=False):
        self._show(text, buttons)

    def set_buttons(self, chat_id, message_id, buttons):
        for row in buttons or ():
            print("  ".join("[ %s ]" % b["text"] for b in row))
        print()

    def answer(self, callback_id, text=None):
        print("  (popup: %s)\n" % text)


day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
con = fridge.connect(tempfile.mktemp(suffix=".db"))
here = os.path.dirname(os.path.abspath(__file__))
seed = os.path.join(here, "seed.json")
if not os.path.exists(seed):
    seed = os.path.join(here, "seed.example.json")
with open(seed) as f:
    for it in json.load(f)["items"]:
        con.execute("INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
                    " VALUES (1,?,?,?,0,?, 'open')",
                    (it["name"], it["use_by"], it["risk"], day.isoformat()))
con.commit()

tg = PrintTG()
bar = "─" * 52
print("\n%s\n  NUDGE AS IT WOULD ARRIVE ON %s\n%s\n" % (bar, day.strftime("%a %b %d %Y"), bar))
items = fridge.at_risk(con, 1, day)
if bot.send_nudge(tg, con, 1, day):
    print("%s\n  AFTER TAPPING ✅ ON ITEM 1\n%s\n" % (bar, bar))
    bot.handle_callback(tg, con, {
        "id": "cb", "data": "used:%d" % items[0]["id"],
        "message": {"chat": {"id": 1, "type": "private"}, "message_id": 1}},
        {"allowed_chat_ids": []})
else:
    print("(silent — nothing at risk)\n")
print("%s\n  /fridge\n%s\n" % (bar, bar))
bot.send_fridge(tg, con, 1, day)

print("%s\n  /freezer (after freezing everything open)\n%s\n" % (bar, bar))
for i in fridge.open_items(con, 1):
    fridge.close_item(con, 1, i["id"], "frozen", day)
frozen = fridge.frozen_items(con, 1)
if bot.send_freezer(tg, con, 1, day):
    print("%s\n  AFTER TAPPING 🗑 ON ITEM 1\n%s\n" % (bar, bar))
    bot.handle_callback(tg, con, {
        "id": "cb", "data": "frz:tossed:%d" % frozen[0]["id"],
        "message": {"chat": {"id": 1, "type": "private"}, "message_id": 1}},
        {"allowed_chat_ids": []})
