#!/usr/bin/env python3
"""Turn one receipt's tracked food into a calendar file of check-ins.

Two check-ins a week (Sunday and Wednesday at 17:00 unless asked otherwise).
Each lists the food to use before the next one. Food due before the first
check-in gets its own event the day before. One last event says the list has
run out and asks for the next receipt. Standard library only.

    python3 make_ics.py plan.json save-your-food.ics

plan.json:

    {
      "today": "2026-10-14",
      "days": ["SU", "WE"],              optional, two-letter weekdays
      "hour": 17,                        optional, 0 to 23
      "items": [
        {"name": "Spinach", "use_by": "2026-10-17", "guess": true,
         "idea": "Wilt it into eggs."}   idea optional
      ]
    }

Times are floating (no time zone), so they land at 17:00 wherever the
calendar is. The UIDs come from the plan's contents: importing the same file
twice updates the events instead of doubling them where the calendar app
supports that, and two different receipts never overwrite each other.
"""
import datetime as dt
import hashlib
import json
import sys

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
HORIZON_DAYS = 35   # anything later is left out; it keeps for weeks
MINUTES = 15


def checkin_dates(today, days, until):
    """Every chosen weekday after today, up to and including until."""
    wanted = {WEEKDAYS.index(d.upper()[:2]) for d in days}
    out, d = [], today + dt.timedelta(days=1)
    while d <= until:
        if d.weekday() in wanted:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def short(d):
    return d.strftime("%a %b ") + str(d.day)


def line(item):
    return "%s (%s%s)" % (item["name"], short(item["use_by"]),
                          ", guess" if item.get("guess") else "")


def plan_events(plan):
    """[(date, hour, title, description)] in date order."""
    today = dt.date.fromisoformat(plan["today"])
    hour = int(plan.get("hour", 17))
    days = plan.get("days") or ["SU", "WE"]
    items = []
    for it in plan["items"]:
        it = dict(it, use_by=dt.date.fromisoformat(it["use_by"]))
        if today < it["use_by"] <= today + dt.timedelta(days=HORIZON_DAYS):
            items.append(it)
    items.sort(key=lambda i: (i["use_by"], i["name"]))
    if not items:
        return []

    last = items[-1]["use_by"]
    # One spare slot past the last item, for the closing event.
    dates = checkin_dates(today, days, last + dt.timedelta(days=7))
    events = []

    # Due on or before the first check-in: its own event the day before.
    first = dates[0]
    for it in [i for i in items if i["use_by"] <= first]:
        day = it["use_by"] - dt.timedelta(days=1)
        if day <= today:
            day = it["use_by"]
        when = "today" if day == it["use_by"] else "by tomorrow"
        desc = [line(it)]
        if it.get("idea"):
            desc.append("Idea: " + it["idea"])
        events.append((day, hour, "Use the %s %s" % (it["name"].lower(), when),
                       desc))

    # Each later item goes to the last check-in strictly before its date.
    for n, d in enumerate(dates):
        nxt = dates[n + 1] if n + 1 < len(dates) else None
        group = [i for i in items
                 if d < i["use_by"] and (nxt is None or i["use_by"] <= nxt)]
        if not group:
            continue
        desc = ["Use soon:"] + ["  " + line(i) for i in group]
        idea = next((i["idea"] for i in group if i.get("idea")), None)
        if idea:
            desc.append("Idea: " + idea)
        desc.append("Bought more? Send the receipt to Claude for a new list.")
        events.append((d, hour, "Save Your Food: use soon", desc))

    # The closing event: the first slot after the last food's date. The dates
    # run a week past it, so there always is one.
    end = next(d for d in dates if d > last)
    events.append((end, hour, "Save Your Food: time for a new list",
                   ["Everything from your %s receipt is past its window."
                    % short(today),
                    "Send your next receipt to Claude to start again."]))
    events.sort(key=lambda e: e[0])
    return events


def esc(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\n", "\\n"))


def fold(s):
    """RFC 5545: lines of at most 75 octets, continued with a space."""
    out, b = [], s.encode("utf-8")
    while len(b) > 75:
        cut = 75 if not out else 74
        while (b[cut] & 0xC0) == 0x80:   # don't split a UTF-8 character
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n ".join(out)


def to_ics(plan):
    seed = hashlib.sha1(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:12]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Save Your Food//Check-ins//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:Save Your Food"]
    for n, (day, hour, title, desc) in enumerate(plan_events(plan)):
        start = dt.datetime.combine(day, dt.time(hour))
        end = start + dt.timedelta(minutes=MINUTES)
        lines += ["BEGIN:VEVENT",
                  "UID:syf-%s-%d@save-your-food" % (seed, n),
                  "DTSTAMP:" + stamp,
                  "DTSTART:" + start.strftime("%Y%m%dT%H%M%S"),
                  "DTEND:" + end.strftime("%Y%m%dT%H%M%S"),
                  "SUMMARY:" + esc(title),
                  "DESCRIPTION:" + esc("\n".join(desc)),
                  "BEGIN:VALARM", "ACTION:DISPLAY",
                  "DESCRIPTION:" + esc(title), "TRIGGER:PT0M", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: make_ics.py plan.json out.ics")
    plan = json.load(open(argv[1]))
    events = plan_events(plan)
    if not events:
        sys.exit("Nothing to put in a calendar: no tracked food due in the "
                 "next %d days." % HORIZON_DAYS)
    with open(argv[2], "w", newline="") as f:
        f.write(to_ics(plan))
    for day, hour, title, desc in events:
        print("%s %02d:00  %s" % (short(day), hour, title))


if __name__ == "__main__":
    main(sys.argv)
