"""Talk to the bot in a terminal, through the real handlers, without Telegram.

Uses a throwaway fridge seeded from seed.json, or seed.example.json, so your
real fridge.db is never touched. Reads config.json if there is one, for
llm_mode and its provider; no token needed. Without llm_mode on, plain
messages go to the rule-based parser, exactly as they would in Telegram.

    python3 try_chat.py                 # a scripted conversation
    python3 try_chat.py -i              # type your own, blank line to stop
    python3 try_chat.py "ate the kale"  # just these messages

Cards show their buttons. Press one by typing, for the most recent card:

    tap 2 used          (or frozen, tossed)

Ported from claude/pull-latest-reo66c, where it drove llm.py; on main the
conversational mode is llm_agent.py, switched on by llm_mode.
"""
import html, json, os, re, sys, tempfile
from datetime import date
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot, fridge, onboarding as onb

SCRIPT = [
    "milk, spinach, rice, a bag of onions",
    "/fridge",
    "tap 1 used",
    "those are pantry",
    "/nudge",
    "/pantry",
]

CHAT = {"id": 1, "type": "private"}
TAP = re.compile(r"^tap\s+(\d+)\s+(used|frozen|tossed)$", re.I)


class PrintTG:
    """Prints what bot.py would send or edit, roughly as a phone shows it,
    and remembers the latest card's buttons so `tap` can press one."""

    def __init__(self):
        self.next_id = 0
        self.last_card = None   # (message_id, buttons)

    def _show(self, verb, text, buttons):
        text = re.sub(r"</?pre>", "", text)
        text = html.unescape(re.sub(r"</?(b|i|code)>", "", text))
        print("bot %s " % verb + text.replace("\n", "\n      "))
        for row in buttons or ():
            print("      " + "  ".join("[ %s ]" % b["text"] for b in row))

    def send(self, chat_id, text, buttons=None, html=False):
        self.next_id += 1
        self._show(">", text, buttons)
        if buttons:
            self.last_card = (self.next_id, buttons)
        return {"ok": True, "result": {"message_id": self.next_id}}

    def edit(self, chat_id, message_id, text, buttons=None, html=False):
        self._show("~", text, buttons)
        if self.last_card and self.last_card[0] == message_id:
            self.last_card = (message_id, buttons)

    def answer(self, callback_id, text=None):
        if text:
            print("      (popup: %s)" % text)

    def call(self, method, **params):
        return None

    def download_photo(self, file_id):
        return None


def tap(tg, con, cfg, n, state):
    """Press button `state` on line `n` of the latest card."""
    if not tg.last_card or not tg.last_card[1]:
        print("      (no card with buttons to tap)")
        return
    message_id, buttons = tg.last_card
    for row in buttons:
        for b in row:
            if b["text"].split()[0] == n and state in b["callback_data"].split(":"):
                bot.handle_callback(tg, con, {
                    "id": "tap", "data": b["callback_data"],
                    "message": {"chat": CHAT, "message_id": message_id}}, cfg)
                return
    print("      (no %s button on line %s)" % (state, n))


def main():
    cfg = {}
    path = os.path.join(HERE, "config.json")
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    cfg = bot.with_defaults(cfg)
    cfg["allowed_chat_ids"] = []          # this throwaway chat is always allowed

    con = fridge.connect(tempfile.mktemp(suffix=".db"))
    onb.set_step(con, 1, onb.DONE)
    seed = os.path.join(HERE, "seed.json")
    if not os.path.exists(seed):
        seed = os.path.join(HERE, "seed.example.json")
    with open(seed) as f:
        for it in json.load(f)["items"]:
            con.execute("INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
                        " VALUES (1,?,?,?,0,?, 'open')",
                        (it["name"], it["use_by"], it["risk"], date.today().isoformat()))
    con.commit()

    if cfg["llm_mode"]:
        model = (cfg["ollama_model"] if cfg["llm_provider"] == "ollama"
                 else cfg["llm_model"])
        print("plain messages: %s via %s\n" % (model, cfg["llm_provider"]))
    else:
        print("plain messages: rule-based parser (llm_mode is off)\n")

    args = sys.argv[1:]
    interactive = args == ["-i"]
    msgs = iter(lambda: input("you > ").strip(), "") if interactive else (args or SCRIPT)
    tg = PrintTG()
    for text in msgs:
        if not interactive:
            print("you > " + text)
        m = TAP.match(text)
        if m:
            tap(tg, con, cfg, m.group(1), m.group(2).lower())
        else:
            bot.handle_message(tg, con, {"chat": CHAT, "text": text}, cfg)
        print()


if __name__ == "__main__":
    main()
