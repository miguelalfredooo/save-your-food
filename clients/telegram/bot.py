#!/usr/bin/env python3
"""Fridge Loop — Telegram client.

Standard library only. Nothing to install: if you can run python3, you can run this.

  python3 bot.py

Reads config.json for the bot token. The token is never logged or echoed.
"""

import base64
import fcntl
import json
import os
import re
import socket
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# Prefer IPv4 for outbound calls. Measured on this project: a getUpdates or
# sendMessage socket that picks an IPv6 route can sit in SYN_SENT for minutes
# before connecting, or time out and silently drop a reply, while IPv4 to the
# same host connects instantly. Falls back to whatever getaddrinfo returned if
# there is no IPv4 route at all, so an IPv6-only network still works.
_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(*args, **kwargs):
    results = _getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in results if r[0] == socket.AF_INET]
    return ipv4 or results


socket.getaddrinfo = _ipv4_first_getaddrinfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fridge          # noqa: E402
import shelf_life as sl  # noqa: E402
import onboarding as onb  # noqa: E402
import art  # noqa: E402
import card  # noqa: E402
import llm_agent  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "config.json")
LOCK_PATH = os.path.join(HERE, ".bot.lock")
API = "https://api.telegram.org/bot%s/%s"
FILE_API = "https://api.telegram.org/file/bot%s/%s"

POLL_TIMEOUT = 50      # long-poll seconds
REQUEST_DOWNLOAD_TIMEOUT = 30
STATE_LABELS = {"used": "Used it", "frozen": "Froze it", "tossed": "Tossed it"}

MAX_MESSAGE_LENGTH = 2000
MAX_ITEMS_PER_CAPTURE = 50
MAX_CAPTION_LIST_CHARS = 1500
RATE_LIMIT_PER_MINUTE = 20
RATE_LIMIT_WINDOW = 60   # seconds

# In-memory only, not persisted: a burst is a right-now problem, not a
# things-to-remember one, and it resets on restart along with everything else
# process-local. Keyed by chat_id, each value a list of recent message times.
_MSG_TIMES = {}


def _rate_limited(chat_id, now=None):
    """True, and records nothing, once a chat is over budget for this
    window. Under budget, records the hit and returns False."""
    now = now if now is not None else time.time()
    times = _MSG_TIMES.setdefault(chat_id, [])
    cutoff = now - RATE_LIMIT_WINDOW
    while times and times[0] < cutoff:
        times.pop(0)
    if len(times) >= RATE_LIMIT_PER_MINUTE:
        return True
    times.append(now)
    return False


def reset_rate_limits():
    """Test hook. The limiter is deliberately process-global state, which a
    test suite reusing the same chat ids across many tests should not
    inherit from an earlier test."""
    _MSG_TIMES.clear()

CLOSE_LINES = {
    "used": "That one did not go to waste.",
    "frozen": "Frozen. Good for months.",
}

# Held back deliberately. A milestone that arrives every Tuesday is not one.
MILESTONES = (10, 25, 50, 100, 250, 500)


def milestone_line(n):
    return "%d things used before they turned. That is the whole idea." % n


# --- config ----------------------------------------------------------------

def acquire_lock():
    """Refuse to start if another copy is already running. Two copies polling
    getUpdates at once get HTTP 409 errors from Telegram and lose messages.

    Returns the open file handle. It has to stay referenced for the life of
    the process: closing it, or letting it get garbage collected, releases
    the lock.
    """
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Another copy of this bot is already running (%s is locked)." % LOCK_PATH)
    return lock_file


def with_defaults(cfg):
    """Fill in every setting a config can leave out. No token needed, so
    try_chat.py can build a working config without one."""
    cfg.setdefault("nudge_hour", 16)
    cfg.setdefault("nudge_minute", 30)
    cfg.setdefault("allowed_chat_ids", [])
    cfg.setdefault("llm_mode", False)
    cfg.setdefault("llm_provider", "openrouter")   # "openrouter" or "ollama"
    cfg.setdefault("openrouter_api_key", "")
    cfg.setdefault("llm_model", "anthropic/claude-haiku-4.5")
    cfg.setdefault("ollama_base_url", "http://localhost:11434/v1")
    cfg.setdefault("ollama_model", "llama3.2-vision")
    return cfg


def _placeholder(token):
    return not token or "PUT_YOUR" in token


def load_config():
    # A single, clearly marked line, not a paragraph: under a launchd
    # crash loop this repeats every ThrottleInterval seconds, and status.sh
    # only shows the tail of the log, so the reason it keeps restarting has
    # to be readable in one line, not buried mid-paragraph.
    #
    # TELEGRAM_BOT_TOKEN stands in for the token where there is no file to
    # edit, such as a cloud session with the token stored as a secret. A real
    # token in config.json still wins.
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    elif not env_token:
        sys.exit("! No config.json found. Copy config.example.json to "
                 "config.json and put your bot token in it (from @BotFather "
                 "in Telegram: /newbot), or set TELEGRAM_BOT_TOKEN.")
    if env_token and _placeholder(cfg.get("token")):
        cfg["token"] = env_token
    if _placeholder(cfg.get("token")):
        sys.exit("! config.json has no real token in it yet.")
    with_defaults(cfg)
    if cfg["llm_mode"] and cfg["llm_provider"] == "openrouter" and (
            not cfg["openrouter_api_key"] or "PUT_YOUR" in cfg["openrouter_api_key"]):
        sys.exit("! llm_mode is on with llm_provider openrouter, but "
                 "openrouter_api_key is not set in config.json.")
    return cfg


# --- telegram --------------------------------------------------------------

class Telegram:
    def __init__(self, token):
        self._token = token

    def _redact(self, text):
        """The token is never logged. Some urllib exceptions embed the
        request URL in their own message, and the URL carries the token."""
        return text.replace(self._token, "<token>") if self._token in text else text

    def call(self, method, **params):
        url = API % (self._token, method)
        data = json.dumps(params).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 15) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            print("! telegram %s failed: %s %s" % (method, e.code, self._redact(body)))
        except Exception as e:                     # network blips are expected
            print("! telegram %s failed: %s" % (method, self._redact(str(e))))
        return None

    def send(self, chat_id, text, buttons=None, html=False):
        """html=True is only for messages carrying a pre block.

        Telegram uses a proportional font unless told otherwise, which turns
        every ASCII drawing into rubble. Nothing else asks for HTML, because
        turning it on means hand-escaping any stray angle bracket in a food
        name, and food names come from users.
        """
        params = {"chat_id": chat_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def answer(self, callback_id, text=None):
        self.call("answerCallbackQuery", callback_query_id=callback_id,
                  **({"text": text} if text else {}))

    def edit(self, chat_id, message_id, text, buttons=None, html=False):
        """Leaving buttons out removes the keyboard, which is how a closed
        item loses its row."""
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        self.call("editMessageText", **params)

    def download_photo(self, file_id, timeout=REQUEST_DOWNLOAD_TIMEOUT):
        """The actual image bytes for a photo, or None on any failure.
        Two calls: getFile resolves file_id to a path, then the file itself
        lives on a different host entirely (api.telegram.org/file/..., not
        the regular bot API endpoint call() uses)."""
        info = self.call("getFile", file_id=file_id)
        if not info or not info.get("ok"):
            return None
        file_path = info["result"]["file_path"]
        url = FILE_API % (self._token, file_path)
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            print("! telegram file download failed: %s" % self._redact(str(e)))
            return None


# --- conversation ----------------------------------------------------------

WELCOME = (
    "I help you use food before it goes bad.\n\n"
    "What did you just buy? Type it, commas between things:\n\n"
    "    milk, spinach, chicken thighs\n\n"
    "Send whatever you like: I sort it. Things with a clock on them get "
    "tracked, and I message you once a day when one needs using. Spices, cans and "
    "rice go to your pantry instead, where I remember them but never nag you."
)

HELP = (
    "Type a list any time. I sort it: perishables get tracked, everything "
    "else goes to your pantry.\n\n"
    "/fridge: what's tracked, soonest first\n"
    "/pantry: what I remember but don't track\n"
    "/nudge: what's at risk right now\n"
    "/freezer: what you froze, and how it ended up\n"
    "/month: what you used in time, and what went in the bin\n"
    "/undo: take back the last list I added\n"
    "\"those are pantry\": move the last list out of tracking\n"
    "/clear: wipe everything and start over\n"
    "/help: this"
)

CLEAR_ASK = ("This wipes everything: what's tracked and what's in your pantry. "
             "There is no getting it back.")


def handle_seed(tg, con, chat_id):
    """Load seed.json into this chat. Refuses if the chat already has anything,
    so a stray /seed can't quietly duplicate a real fridge.

    Sorted the same way a typed capture is: this used to insert every entry
    straight into the tracked table with no pantry or outside check at all,
    so a seed file full of real pantry contents (salt, spices, canned soup,
    bouillon) tracked all of it with a fake fridge date and put it in the
    daily nudge. A trailing "?" some import left on an uncertain name is
    stripped too, rather than shown to the user as-is.
    """
    path = os.path.join(HERE, "seed.json")
    if not os.path.exists(path):
        tg.send(chat_id, "No seed.json here.")
        return
    if fridge.open_items(con, chat_id):
        tg.send(chat_id, "You already have things tracked. I won't seed over them.")
        return
    with open(path) as f:
        data = json.load(f)
    today = date.today().isoformat()
    n_pantry = 0
    for it in data.get("items", []):
        name = it["name"].strip().rstrip(" ?").strip()
        if not name:
            continue
        skip, reason = sl.not_tracked(name)
        if skip:
            fridge.remember(con, chat_id, name, reason, date.today())
            n_pantry += 1
            continue
        con.execute(
            "INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)"
            " VALUES (?,?,?,?,0,?, 'open')",
            (chat_id, name, it["use_by"], it["risk"], today))
    con.commit()
    tail = ("\n\n%d went straight to your pantry, no dates: /pantry to see "
            "them." % n_pantry) if n_pantry else ""
    tg.send(chat_id, "Loaded your current fridge.\n\n"
            + fridge.compose_inventory(fridge.open_items(con, chat_id)) + tail)


COMMANDS = [
    ("fridge", "What's tracked, soonest first"),
    ("nudge", "What needs using right now"),
    ("pantry", "What I remember but don't track"),
    ("freezer", "What you froze, and how it ended up"),
    ("month", "What you used in time, and what got tossed"),
    ("undo", "Take back the last list"),
    ("setup", "Run the setup again"),
    ("clear", "Wipe everything"),
    ("help", "What I can do"),
]


def send_card(tg, con, chat_id, kind, head, items, today):
    """One card for these items, remembered so a tap can redraw it.

    This used to be one summary plus one buttoned message per item: three
    things at risk was four notifications. See card.py for the shape.
    """
    shown, more = items[:card.MAX_ITEMS], max(0, len(items) - card.MAX_ITEMS)
    spec = {"kind": kind, "head": head, "day": today.isoformat(),
            "ids": [i["id"] for i in shown], "more": more,
            "used_before": fridge.count_closed(con, chat_id, "used")}
    html, buttons = _render(kind, head, shown, today, more)
    res = tg.send(chat_id, html, buttons=buttons, html=True)
    msg_id = ((res or {}).get("result") or {}).get("message_id")
    if msg_id is not None:
        fridge.save_card(con, chat_id, msg_id, spec)
    return len(shown)


def close_card(con, chat_id, spec, items):
    """The drawing that closes a finished card, or None.

    One per card, not one per tap: a drawing after every button turned a
    three-item nudge back into six messages. A card that ends all tossed
    gets none, for the same reason a toss never did.
    """
    states = {i["state"] for i in items}
    if states == {"tossed"}:
        return None
    used_now = fridge.count_closed(con, chat_id, "used")
    crossed = [m for m in MILESTONES if spec["used_before"] < m <= used_now]
    if crossed:
        moment, caption = "milestone", milestone_line(crossed[-1])
    else:
        moment = "used" if "used" in states else "frozen"
        caption = CLOSE_LINES[moment]
    frame = art.choose(moment, avoid=fridge.last_art(con, chat_id))
    if not frame:
        return None
    fridge.note_art(con, chat_id, frame)
    return art.render(frame, caption)


def _render(kind, head, items, today, more, closing=None):
    footer = card.tally(kind, items, more)
    if kind == "freezer":
        return card.render_freezer(head, items, footer)
    return card.render(head, items, today, footer, closing,
                       label_one_tier=(kind != "nudge"))


def refresh_card(tg, con, chat_id, message_id, spec):
    """Redraw a card after a tap: the line flips, its buttons go."""
    items = fridge.items_by_ids(con, chat_id, spec["ids"])
    today = date.fromisoformat(spec["day"])
    closing = None
    # The freezer gets no closing drawing: it never drew on a settle before
    # cards either, and its last tap is as likely to be a toss as not.
    if (spec["kind"] != "freezer" and items
            and all(card.settled(spec["kind"], i) for i in items)):
        closing = close_card(con, chat_id, spec, items)
    html, buttons = _render(spec["kind"], spec["head"], items, today,
                            spec["more"], closing)
    tg.edit(chat_id, message_id, html, buttons=buttons, html=True)


def send_nudge(tg, con, chat_id, today=None):
    """What's at risk, as one card. Returns how many items it shows."""
    today = today or date.today()
    items = fridge.at_risk(con, chat_id, today)
    if not items:
        return 0
    return send_card(tg, con, chat_id, "nudge",
                     fridge.nudge_head(items, today), items, today)


def send_fridge(tg, con, chat_id, today=None):
    today = today or date.today()
    items = fridge.open_items(con, chat_id)
    if not items:
        tg.send(chat_id, fridge.compose_inventory(items))
        return
    send_card(tg, con, chat_id, "fridge", "In your fridge", items, today)


def _capped_item_list(names, max_chars=MAX_CAPTION_LIST_CHARS):
    """A comma-joined list, capped so a pantry can't grow a caption past
    Telegram's hard message length limit. Truncating the finished HTML at
    send time would risk cutting a message off mid-tag; capping the list
    itself, while it is still plain names, can't ever produce a broken
    <pre> block."""
    joined = ", ".join(names)
    if len(joined) <= max_chars:
        return joined
    kept, total = [], 0
    for name in names:
        add = len(name) + (2 if kept else 0)  # ", " between items
        if total + add > max_chars:
            break
        kept.append(name)
        total += add
    return "%s, and %d more" % (", ".join(kept), len(names) - len(kept))


def send_freezer(tg, con, chat_id, today=None):
    """What is in the freezer, as one card with ✅ and 🗑 per item.

    This exists because freezing was a dead end: the item left every view and
    could never be answered for again, so a frozen rescue could never be
    reversed and the rescued figure could only drift upward.
    """
    today = today or date.today()
    items = fridge.frozen_items(con, chat_id)
    if not items:
        tg.send(chat_id, "Nothing in the freezer that I know about. Freezing "
                         "something from a nudge puts it here.")
        return 0
    return send_card(tg, con, chat_id, "freezer", "In the freezer", items, today)


def compose_pantry_html(items):
    """The pantry, with a can over the pantry and an onion over the counter.

    This is where the evergreen glyphs earn their keep. "Pantry" and "counter"
    are the distinction people get wrong, and two drawings make the split
    visible instead of leaving it to be read. Same can every time, on purpose.
    """
    if not items:
        return fridge.compose_pantry(items)

    stable = [i["name"] for i in items if i["kind"] == "stable"]
    outside = [i["name"] for i in items if i["kind"] == "outside"]
    parts = []
    if stable:
        parts.append(art.render(art.glyph("pantry"),
                                "Pantry (%d)\n%s" % (len(stable), _capped_item_list(stable))))
    if outside:
        parts.append(art.render(art.glyph("counter"),
                                "On the counter (%d)\n%s"
                                % (len(outside), _capped_item_list(outside))))
    head = "Not tracked, but I remember you have it."
    return art.esc(head) + "\n\n" + "\n\n".join(parts)


FRIDGE_LISTING_PHRASES = ("in my fridge", "in the fridge")
PANTRY_LISTING_PHRASES = ("in my pantry", "in the pantry", "in my cupboard",
                          "in the cupboard")


def answer_question(tg, con, chat_id, text):
    """A genuine question about contents gets the real listing, not a
    definition. "Is there anything in my fridge" asks what's there, not what
    "fridge" means, and answering with the actual list is strictly more
    useful than the glossary line for the word itself."""
    n = text.lower()
    if any(p in n for p in FRIDGE_LISTING_PHRASES):
        send_fridge(tg, con, chat_id)
        return
    if any(p in n for p in PANTRY_LISTING_PHRASES):
        items = fridge.pantry_items(con, chat_id)
        tg.send(chat_id, compose_pantry_html(items), html=bool(items))
        return
    tg.send(chat_id, fridge.answer_question(text))


def send_delight(tg, con, chat_id, moment, item=None, caption=None):
    """One place every drawing goes through, so the rules hold everywhere.

    Returns True if something was drawn. A forbidden moment sends the caption
    on its own rather than nothing: the outcome still needs acknowledging, it
    just does not get a picture over it.
    """
    frame = art.choose(moment, item=item, avoid=fridge.last_art(con, chat_id))
    if not frame:
        if caption:
            tg.send(chat_id, caption)
        return False
    tg.send(chat_id, art.render(frame, caption), html=True)
    fridge.note_art(con, chat_id, frame)
    return True


def run_onboarding(tg, con, chat_id, text, cfg):
    stage = onb.step(con, chat_id)

    if stage == "1":
        reply, nxt = onb.handle_item(con, chat_id, text)
        tg.send(chat_id, reply)
        if nxt:
            tg.send(chat_id, nxt)
        return

    if stage == "2":
        reply, nxt = onb.handle_list(con, chat_id, text)
        tg.send(chat_id, reply)
        if nxt:
            tg.send(chat_id, nxt, buttons=onb.TIME_BUTTONS)
        return

    if stage == "3":
        # Only a button answers this step; there is no reliable time to parse
        # from free text. Taking any typed text as a grocery list used to
        # force-end onboarding on it: "ignored, buttons only" got tracked as
        # two fake fridge items and setup silently stopped.
        tg.send(chat_id, "Tap one of the times above, or /skip.",
                buttons=onb.TIME_BUTTONS)
        return

    # No other step is left waiting on a message (step 4 resolves inside the
    # same callback that sets it), so this is unexpected. End onboarding
    # defensively rather than leaving the chat stuck, and handle the text
    # normally.
    onb.set_step(con, chat_id, onb.DONE)
    handle_message(tg, con, {"chat": {"id": chat_id}, "text": text}, cfg)


def send_sample_nudge(tg, con, chat_id, today=None):
    """Step 4: a real nudge, on a real item of theirs, with live buttons.

    Deliberately not a mock-up. The user needs to see the message that will
    arrive tomorrow, and to find out that one tap ends it, while nothing is at
    stake. If they have nothing perishable yet, say so rather than inventing an
    item — a fake nudge is exactly the thing that costs trust.
    """
    items = fridge.open_items(con, chat_id)
    if not items:
        tg.send(chat_id, "Nothing of yours is on a clock yet, so there is no "
                         "nudge to show you. Send a perishable and you will get "
                         "one tomorrow.")
        return
    today = today or date.today()
    send_card(tg, con, chat_id, "nudge", fridge.nudge_head(items[:1], today),
              items[:1], today)


# --- rendering an LLM reply -------------------------------------------------
#
# The model writes plain markdown (**bold**, *italic*, `code`) and, when
# asked to list more than one thing, "- " bulleted lines (the system prompt
# asks for exactly this). Telegram needs HTML to render any of it: a run of
# bulleted lines goes in a <pre> block so a phone's proportional font can't
# scramble the alignment, and everything else gets ordinary inline markdown.

_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s+(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


_TAG_RE = re.compile(r"</?(b|i|code)>")


def _tags_are_balanced(html):
    """Whether every open tag this line introduced closes in the right order.

    Bold and italic are converted independently, so markdown that crosses
    its own boundaries ("**bold *italic** more*") can produce tags that
    interleave instead of nest: <b>bold <i>italic</b> more</i>. Telegram's
    parser rejects that outright and fails the whole message, not just the
    one line, so this has to be caught before it ever reaches send().
    """
    stack = []
    for m in _TAG_RE.finditer(html):
        tag = m.group(1)
        if m.group(0)[1] == "/":
            if not stack or stack.pop() != tag:
                return False
        else:
            stack.append(tag)
    return not stack


def _inline_markdown(escaped_line):
    line = re.sub(r"(\*\*|__)(.+?)\1", r"<b>\2</b>", escaped_line)
    line = re.sub(r"`([^`]+?)`", r"<code>\1</code>", line)
    line = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", line)
    line = re.sub(r"(?<!_)_(?!_)([^_\n]+?)_(?!_)", r"<i>\1</i>", line)
    # Overlapping emphasis markers can produce cross-nested tags (see
    # _tags_are_balanced). A line that can't be formatted safely is still
    # better sent plain, asterisks and all, than not sent at all.
    return line if _tags_are_balanced(line) else escaped_line


def _markdown_to_html(text):
    lines = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Telegram has no heading or rule support at all: a "### Title" or a
        # standalone "---" line would otherwise show up as literal hash
        # marks or dashes rather than doing anything. A heading becomes
        # bold text instead; a rule is dropped outright, since a blank line
        # already does the separating job in a chat.
        if _HR_RE.match(line):
            i += 1
            continue
        header = _HEADER_RE.match(line)
        if header:
            blocks.append("<b>%s</b>" % _inline_markdown(art.esc(header.group(1))))
            i += 1
            continue
        if _BULLET_RE.match(line):
            j = i
            list_lines = []
            while j < len(lines) and (_BULLET_RE.match(lines[j]) or not lines[j].strip()):
                list_lines.append(lines[j])
                j += 1
            while list_lines and not list_lines[-1].strip():
                list_lines.pop()
            blocks.append("<pre>%s</pre>" % art.esc("\n".join(list_lines)))
            i = j
        else:
            blocks.append(_inline_markdown(art.esc(line)))
            i += 1
    return "\n".join(blocks)


def send_llm_reply(tg, chat_id, text):
    """Falls back to the original, unformatted plain text if the converted
    HTML ever fails to send: a malformed tag from an imperfect conversion of
    free-form model text must never mean the user gets nothing back."""
    if tg.send(chat_id, _markdown_to_html(text), html=True) is None:
        tg.send(chat_id, text)


MAX_PHOTO_BYTES = 10 * 1024 * 1024


def _pick_photo(sizes):
    """Telegram sends several sizes of the same photo, smallest first. The
    largest one at or under the cap, rather than always the biggest: a huge
    photo still gets something sent instead of a flat refusal, and the model
    doesn't need more resolution than that to read a fridge or a receipt."""
    under_cap = [s for s in sizes if s.get("file_size", 0) <= MAX_PHOTO_BYTES]
    return (under_cap[-1] if under_cap else sizes[0])["file_id"]


def handle_photo(tg, con, chat_id, msg, cfg):
    """A photo only means something in llm_mode: there is no way for the
    regex pipeline to read an image, and pretending otherwise would be the
    exact kind of silent guess this bot is built to avoid."""
    if not cfg["llm_mode"]:
        tg.send(chat_id, "I can't read photos yet, only typed lists: "
                         "commas between things.")
        return
    caption = (msg.get("caption") or "").strip()
    file_id = _pick_photo(msg["photo"])
    photo_bytes = tg.download_photo(file_id)
    if photo_bytes is None:
        tg.send(chat_id, "Couldn't get that photo from Telegram. Try sending it again.")
        return
    image_b64 = base64.b64encode(photo_bytes).decode()
    send_llm_reply(tg, chat_id, llm_agent.run_agent(con, chat_id, caption, cfg, image_b64=image_b64))


def handle_message(tg, con, msg, cfg):
    chat_id = msg["chat"]["id"]
    # A flood gets nothing back, quietly, before any other work runs.
    if _rate_limited(chat_id):
        return
    # In a group, anyone in it could /clear the shared fridge, and the daily
    # nudge would go out to everyone in the group.
    if msg["chat"].get("type") != "private":
        return
    # A reply confirms the bot exists, so a chat that isn't on the allow
    # list gets nothing at all, not even an error.
    if cfg["allowed_chat_ids"] and chat_id not in cfg["allowed_chat_ids"]:
        return
    if "photo" in msg:
        handle_photo(tg, con, chat_id, msg, cfg)
        return
    text = (msg.get("text") or "").strip()
    if not text:
        tg.send(chat_id, "I can only read typed lists for now: "
                         "commas between things.")
        return
    if len(text) > MAX_MESSAGE_LENGTH:
        tg.send(chat_id, "That is too long for me to read in one go. Send it "
                         "in a few smaller messages.")
        return

    # llm_mode is a separate, self-contained conversational front end: a
    # message here never reaches onboarding, is_chatter, correction or
    # parse_list. It replaces how a typed message is understood, not the
    # daily nudge or the used/frozen/tossed buttons, which are unchanged in
    # both modes since they are not an understanding problem.
    if cfg["llm_mode"]:
        send_llm_reply(tg, chat_id, llm_agent.run_agent(con, chat_id, text, cfg))
        return

    # A reply to me or a genuine question can arrive at any point, onboarding
    # included, and answering it must never look like a captured fridge item.
    # Before this existed, "what's toss?" became a tracked item with a fake
    # date on it, which is the exact confusion the bot exists to prevent.
    if not text.startswith("/"):
        if fridge.is_chatter(text):
            tg.send(chat_id, "Noted. Send a list whenever you want to add "
                             "something, or /help for what I can do.")
            return
        if fridge.is_question(text):
            answer_question(tg, con, chat_id, text)
            return

    # While onboarding is running it owns plain text, because each step is a
    # question and the answer means something different at each one.
    if onb.active(con, chat_id) and not text.startswith("/"):
        run_onboarding(tg, con, chat_id, text, cfg)
        return

    low = text.lower()
    if low.startswith("/start"):
        # A first /start onboards. A later one does not restart it: someone
        # tapping /start out of curiosity should not lose their fridge.
        if not onb.started(con, chat_id):
            tg.send(chat_id, onb.begin(con, chat_id))
        else:
            tg.send(chat_id, WELCOME)
        return
    if low.startswith("/setup"):
        tg.send(chat_id, onb.begin(con, chat_id))
        return
    if low.startswith("/skip"):
        tg.send(chat_id, onb.skip(con, chat_id, cfg["nudge_hour"]))
        return
    if low.startswith("/help"):
        tg.send(chat_id, HELP)
        return
    if low.startswith("/fridge"):
        send_fridge(tg, con, chat_id)
        return
    if low.startswith("/month"):
        tg.send(chat_id, fridge.month_summary(con, chat_id))
        return
    if low.startswith("/freezer"):
        send_freezer(tg, con, chat_id)
        return
    if low.startswith("/pantry"):
        items = fridge.pantry_items(con, chat_id)
        body = compose_pantry_html(items)
        tg.send(chat_id, body, html=bool(items))
        return
    if low.startswith("/undo"):
        tg.send(chat_id, fridge.undo_last(con, chat_id))
        return
    if low.startswith("/clear"):
        tg.send(chat_id, CLEAR_ASK, buttons=[[
            {"text": "Yes, wipe it", "callback_data": "clear:yes"},
            {"text": "No, keep it", "callback_data": "clear:no"},
        ]])
        return
    if low.startswith("/seed"):
        # seed.json is the owner's real fridge. Anyone with nothing logged
        # could otherwise load it, which leaks personal data.
        owner = cfg["allowed_chat_ids"][0] if cfg["allowed_chat_ids"] else None
        if chat_id == owner:
            handle_seed(tg, con, chat_id)
        else:
            tg.send(chat_id, HELP)
        return
    if low.startswith("/nudge"):
        if send_nudge(tg, con, chat_id) == 0:
            # The one place a drawing earns its keep on an empty result: this is
            # the state the whole system is trying to produce, and it otherwise
            # looks identical to the bot being broken.
            send_delight(tg, con, chat_id, "allclear",
                         caption="Nothing needs using today.")
        return
    if low.startswith("/"):
        tg.send(chat_id, HELP)
        return

    # "I put butter chicken in the fridge as leftovers" is a capture written
    # as a sentence. It has to be read before the correction check, which
    # would otherwise see "fridge" and move the previous list.
    put = fridge.put_away(text)
    if put:
        names, too_long = [put], []
    else:
        # "these items are all from the pantry" is a correction, not an item.
        # Act on it rather than logging the sentence, which is what used to
        # happen.
        fix = fridge.correction(text)
        if fix:
            _, reply = fridge.reclassify_last(con, chat_id, fix)
            tg.send(chat_id, reply)
            return

        # Any other sentence is prose. Logging it produces a dated fridge item
        # with a whole clause for a name, which then turns up in a nudge.
        if fridge.looks_like_sentence(text):
            tg.send(chat_id, "That reads like a sentence rather than a list, "
                             "so I haven't tracked it.\n\nFood goes in with "
                             "commas between: milk, spinach, chicken thighs. "
                             "If I sorted your last list wrong, say \"those are "
                             "pantry\" or \"those are fridge\" and I'll move "
                             "them.")
            return

        # "milk eggs bread" has no comma to split on, so without this it
        # becomes one tracked item named "milk eggs bread" with a fake date.
        if fridge.looks_like_an_unseparated_list(text):
            tg.send(chat_id, "Looks like a few different things with nothing "
                             "between them. Put commas between them and send "
                             "it again: milk, eggs, bread.")
            return

        names, too_long = fridge.parse_list(text, report=True)
    names, n_dropped = fridge.cap_names(names)

    if too_long:
        tg.send(chat_id, "These didn't look like food names, so I left them "
                         "out rather than guessing: " + "; ".join(too_long))

    if n_dropped:
        tg.send(chat_id, "That is more than I can take in one go, so I kept "
                         "the first %d and left out %d. Send the rest in a "
                         "second message." % (fridge.MAX_ITEMS, n_dropped))

    if not names:
        tg.send(chat_id, "I couldn't pick anything out of that. "
                         "Try: milk, spinach, chicken thighs")
        return

    tracked, stable, outside, again = fridge.add_items(con, chat_id, names)

    # Lead with what the list actually turned out to be. Someone who sent their
    # spice rack must not read "Logged 0 things" as a failure — the list went
    # somewhere useful, it just was not the tracked pile.
    lines = []
    if tracked:
        lines += ["Tracking %d thing%s:" % (
            len(tracked), "" if len(tracked) == 1 else "s"), ""]
        for name, ub, risk, est in tracked:
            lines.append("  • %s: %s%s" % (
                name, sl.when(ub), " (a guess)" if est else ""))
    if again:
        if lines:
            lines.append("")
        lines += ["Already had %s, so I moved the date instead of adding a second one:"
                  % ("this" if len(again) == 1 else "these"),
                  "  " + ", ".join(again)]
    if stable:
        if lines:
            lines.append("")
        lines += ["Put %d in your pantry: no clock on %s, so no nudges:" % (
            len(stable), "it" if len(stable) == 1 else "them"),
            "  " + ", ".join(stable)]
    if outside:
        if lines:
            lines.append("")
        lines += ["These keep better on the counter than in the fridge, so I am "
                  "remembering them without tracking them:",
                  "  " + ", ".join(outside)]
    if stable or outside:
        lines += ["", "/pantry any time to see that list."]
    soonest = min((a[1] for a in tracked), default=None)
    if soonest:
        lines += ["", "First one to watch: %s." % sl.when(soonest)]
    tg.send(chat_id, "\n".join(lines))


def handle_callback(tg, con, cb, cfg):
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if ":" not in data or chat_id is None:
        tg.answer(cb["id"])
        return
    if msg.get("chat", {}).get("type") != "private":
        return
    if cfg["allowed_chat_ids"] and chat_id not in cfg["allowed_chat_ids"]:
        return
    state, _, raw_id = data.partition(":")

    if state == "frz":
        outcome, _, raw = raw_id.partition(":")
        if outcome not in ("used", "tossed"):
            tg.answer(cb["id"])
            return
        try:
            item_id = int(raw)
        except ValueError:
            tg.answer(cb["id"])
            return
        row = con.execute("SELECT name, tier FROM items WHERE id=? AND chat_id=?"
                          " AND state='frozen' AND freezer_outcome IS NULL",
                          (item_id, chat_id)).fetchone()
        if not row:
            tg.answer(cb["id"], "Already handled.")
            return
        fridge.settle_freezer_item(con, chat_id, item_id, outcome)
        tg.answer(cb["id"], "Used it" if outcome == "used" else "Tossed it")

        spec = fridge.load_card(con, chat_id, msg["message_id"])
        if spec and item_id in spec["ids"]:
            refresh_card(tg, con, chat_id, msg["message_id"], spec)
            return

        # A message sent before the freezer was a card: one item, its own
        # buttons, and the reversal said as a separate line.
        if outcome == "used":
            tg.edit(chat_id, msg["message_id"],
                    "%s: used out of the freezer." % row["name"])
            return
        # A reversal. No drawing: the food was wasted in the end (§19,
        # art.FORBIDDEN). And no verdict on it either: "freezing only to bin it
        # later is not a save" is doctrine written for the model, not a line to
        # say to the person, and as a message it is guilt, which §20 forbids
        # outright. State what happened to the figure and stop.
        tg.edit(chat_id, msg["message_id"],
                "%s: tossed out of the freezer." % row["name"])
        if fridge.is_rescue("frozen", row["tier"]):
            tg.send(chat_id, "Noted. That one had counted as used in time, so "
                             "it comes off this month's figure.")
        else:
            tg.send(chat_id, "Noted. Logged so the monthly count is honest.")
        return

    if state == "onb":
        kind, _, val = raw_id.partition(":")
        if kind != "time":
            tg.answer(cb["id"])
            return
        try:
            hour = int(val)
        except ValueError:
            tg.answer(cb["id"])
            return
        if not (0 <= hour <= 23):
            tg.answer(cb["id"])
            return
        fridge.set_pref(con, chat_id, "nudge_hour", hour)
        tg.answer(cb["id"], "%02d:00 it is." % hour)
        tg.edit(chat_id, msg["message_id"], "Your message arrives at %02d:00." % hour)
        onb.set_step(con, chat_id, "4")
        tg.send(chat_id, onb.STEP4_HEAD)
        send_sample_nudge(tg, con, chat_id)
        onb.set_step(con, chat_id, onb.DONE)
        send_delight(tg, con, chat_id, "welcome", caption=onb.finished(hour))
        return

    if state == "clear":
        if raw_id != "yes":
            tg.answer(cb["id"], "Left it alone.")
            tg.edit(chat_id, msg["message_id"], "Nothing wiped.")
            return
        n_items, n_pantry = fridge.clear_chat(con, chat_id)
        tg.answer(cb["id"], "Wiped.")
        tg.edit(chat_id, msg["message_id"],
                "Wiped %d tracked thing%s and %d pantry entr%s. Send a list when "
                "you are ready." % (n_items, "" if n_items == 1 else "s",
                                    n_pantry, "y" if n_pantry == 1 else "ies"))
        return

    if state not in STATE_LABELS:
        tg.answer(cb["id"])
        return
    try:
        item_id = int(raw_id)
    except ValueError:
        tg.answer(cb["id"])
        return

    row = con.execute(
        "SELECT name FROM items WHERE id=? AND chat_id=? AND state='open'",
        (item_id, chat_id)).fetchone()
    if not row:
        tg.answer(cb["id"], "Already handled.")
        return

    fridge.close_item(con, chat_id, item_id, state)
    tg.answer(cb["id"], STATE_LABELS[state])

    spec = fridge.load_card(con, chat_id, msg["message_id"])
    if spec and item_id in spec["ids"]:
        refresh_card(tg, con, chat_id, msg["message_id"], spec)
        return

    # A message sent before cards existed: one item, its own buttons.
    tg.edit(chat_id, msg["message_id"], "%s: %s" % (row["name"], STATE_LABELS[state].lower()))

    # Used or froze: a small drawing, matched to the food where there is one.
    # Tossed gets a line and no picture, on purpose (see art.FORBIDDEN).
    if state == "tossed":
        tg.send(chat_id, "Noted.")
        return
    n = fridge.count_closed(con, chat_id, "used")
    if state == "used" and n in MILESTONES:
        send_delight(tg, con, chat_id, "milestone", caption=milestone_line(n))
        return
    send_delight(tg, con, chat_id, state, item=row["name"],
                 caption=CLOSE_LINES[state])


# --- daily nudge -----------------------------------------------------------

def due_today(con, chat_id, cfg, now):
    """Fire once per day, at or after the configured time. Survives restarts."""
    row = con.execute("SELECT value FROM meta WHERE chat_id=? AND key='last_nudge'",
                      (chat_id,)).fetchone()
    if row and row["value"] == now.date().isoformat():
        return False
    target = now.replace(hour=fridge.nudge_hour(con, chat_id, cfg["nudge_hour"]),
                         minute=cfg["nudge_minute"], second=0, microsecond=0)
    return now >= target


def mark_nudged(con, chat_id, day):
    con.execute("INSERT OR REPLACE INTO meta (chat_id,key,value) VALUES (?,'last_nudge',?)",
                (chat_id, day.isoformat()))
    con.commit()


def sweep(tg, con, cfg, now=None):
    """Roll past-budget items into a disposal prompt, then nudge whoever is due."""
    now = now or datetime.now()
    today = now.date()
    chats = [r["chat_id"] for r in
             con.execute("SELECT DISTINCT chat_id FROM items").fetchall()]
    for chat_id in chats:
        # Someone halfway through onboarding must not get a scheduled nudge on
        # top of the step they are answering.
        if onb.active(con, chat_id):
            continue
        if not due_today(con, chat_id, cfg, now):
            continue
        # Anything past its budget is past its date too, so it is already a
        # line on the nudge card, marked "long gone". It used to get its own
        # message as well, on top of its line in the nudge.
        send_nudge(tg, con, chat_id, today)
        mark_nudged(con, chat_id, today)


# --- main ------------------------------------------------------------------

def main():
    _lock = acquire_lock()   # noqa: F841 (held for the life of the process)
    cfg = load_config()
    if not cfg["allowed_chat_ids"]:
        print("! No allowed_chat_ids set in config.json. This bot will "
              "respond to anyone who finds it.")
    tg = Telegram(cfg["token"])
    con = fridge.connect()

    me = tg.call("getMe")
    if not me or not me.get("ok"):
        sys.exit("! Couldn't reach Telegram. Check the token and your connection.")
    tg.call("setMyCommands", commands=[
        {"command": c, "description": d} for c, d in COMMANDS])
    print("Fridge Loop running as @%s. Nudging at %02d:%02d. Ctrl-C to stop."
          % (me["result"]["username"], cfg["nudge_hour"], cfg["nudge_minute"]))

    offset = None
    while True:
        try:
            res = tg.call("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                          allowed_updates=["message", "callback_query"])
            if res and res.get("ok"):
                for upd in res["result"]:
                    offset = upd["update_id"] + 1
                    if "message" in upd:
                        handle_message(tg, con, upd["message"], cfg)
                    elif "callback_query" in upd:
                        handle_callback(tg, con, upd["callback_query"], cfg)
            sweep(tg, con, cfg)
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
