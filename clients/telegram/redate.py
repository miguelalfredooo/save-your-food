"""One-time fix: re-date open items whose date was a guess the table can now make.

Before the shelf-life table came first (PR #23), AI mode saved every date as
the model's guess, even for food the table knows. Raw chicken thighs came out
"fine for a week" when the table says one day. Items keep the date they were
saved with, so those guesses stay until this runs.

What it changes: open items marked a guess (estimated = 1) whose food the
table knows. The new date is the day the item was added plus the table's
days, and the risk class is corrected with it. Nothing else is touched:
not a date someone gave, not a closed item, not a food the table doesn't
know.

    python3 redate.py            # dry run: lists every change, writes nothing
    python3 redate.py --apply    # backs up fridge.db first, then writes

Safe to run more than once: a second run finds nothing left to change.
Chat ids are never printed; rows say "you" for the owner and "member N".
"""

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fridge            # noqa: E402
import shelf_life as sl  # noqa: E402


def redate(con, apply=False):
    """The changes to make, as dicts, and makes them if `apply`."""
    changes = []
    for row in con.execute(
            "SELECT * FROM items WHERE state='open' AND estimated=1 ORDER BY chat_id, id"):
        days, risk, unknown = sl.lookup(row["name"])
        if unknown:
            continue
        new = date.fromisoformat(row["added"]) + timedelta(days=days)
        if new.isoformat() == row["use_by"] and risk == row["risk"]:
            continue
        changes.append({"id": row["id"], "chat_id": row["chat_id"],
                        "name": row["name"], "old": row["use_by"],
                        "new": new.isoformat(), "old_risk": row["risk"],
                        "new_risk": risk})
    if apply:
        for c in changes:
            con.execute("UPDATE items SET use_by=?, risk=?, estimated=0 WHERE id=?",
                        (c["new"], c["new_risk"], c["id"]))
        # A date marked a guess but already matching the table is no longer
        # a guess either.
        for row in con.execute("SELECT id, name FROM items WHERE state='open'"
                               " AND estimated=1").fetchall():
            if not sl.lookup(row["name"])[2]:
                con.execute("UPDATE items SET estimated=0 WHERE id=?", (row["id"],))
        con.commit()
    return changes


def _labels(changes, owner):
    """"you" for the owner, "member N" for everyone else, in a stable order."""
    others = sorted({c["chat_id"] for c in changes} - {owner})
    names = {cid: "member %d" % n for n, cid in enumerate(others, 1)}
    names[owner] = "you"
    return names


def _owner():
    try:
        with open(os.path.join(HERE, "config.json")) as f:
            ids = json.load(f).get("allowed_chat_ids") or []
        return ids[0] if ids else None
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (backs up the database first)")
    ap.add_argument("--db", default=fridge.DB_PATH, help="path to fridge.db")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit("! No database at %s" % args.db)
    con = fridge.connect(args.db)
    changes = redate(con, apply=False)
    if not changes:
        print("Nothing to change: no open item has a guessed date the table can fix.")
        return

    who = _labels(changes, _owner())
    for c in changes:
        risk = ("" if c["old_risk"] == c["new_risk"]
                else "  (risk %s -> %s)" % (c["old_risk"], c["new_risk"]))
        print("%-9s %-28s %s -> %s%s" % (who[c["chat_id"]], c["name"][:28],
                                         c["old"], c["new"], risk))
    print("\n%d item%s." % (len(changes), "" if len(changes) == 1 else "s"))

    if not args.apply:
        print("Dry run: nothing written. Run with --apply to make these changes.")
        return
    con.close()
    backup = "%s.bak-%s" % (args.db, datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(args.db, backup)
    con = fridge.connect(args.db)
    redate(con, apply=True)
    print("Done. Backup of the old database: %s" % backup)


if __name__ == "__main__":
    main()
