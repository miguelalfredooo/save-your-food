"""The calendar file the Claude app skill hands out. Run: python3 test_make_ics.py"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "save-your-food", "scripts"))
import make_ics

# 2026-10-14 is a Wednesday. The default check-ins after it fall on
# Sun Oct 18, Wed Oct 21, Sun Oct 25, Wed Oct 28, Sun Nov 1, Wed Nov 4.
TODAY = "2026-10-14"


def plan(items, **kw):
    return dict({"today": TODAY, "items": items}, **kw)


def item(name, use_by, **kw):
    return dict({"name": name, "use_by": use_by}, **kw)


def by_date(events):
    return {e[0].isoformat(): e for e in events}


class Schedule(unittest.TestCase):

    def test_food_due_before_the_first_checkin_gets_its_own_event(self):
        ev = by_date(make_ics.plan_events(plan([
            item("Chicken thighs", "2026-10-16")])))
        self.assertEqual(ev["2026-10-15"][2], "Use the chicken thighs by tomorrow")

    def test_due_tomorrow_lands_on_its_own_day_not_today(self):
        # Today's evening may already be gone, so nothing is scheduled today.
        ev = by_date(make_ics.plan_events(plan([item("Ground beef", "2026-10-15")])))
        self.assertEqual(ev["2026-10-15"][2], "Use the ground beef today")
        self.assertNotIn(TODAY, ev)

    def test_due_on_the_first_checkin_counts_as_urgent(self):
        ev = by_date(make_ics.plan_events(plan([item("Fish", "2026-10-18")])))
        self.assertEqual(ev["2026-10-17"][2], "Use the fish by tomorrow")

    def test_later_food_goes_to_the_last_checkin_before_its_date(self):
        ev = by_date(make_ics.plan_events(plan([
            item("Spinach", "2026-10-19", guess=True),
            item("Yogurt", "2026-10-21"),
            item("Eggs", "2026-11-04")])))
        sun = "\n".join(ev["2026-10-18"][3])
        self.assertIn("Spinach (Mon Oct 19, guess)", sun)
        self.assertIn("Yogurt (Wed Oct 21)", sun)
        self.assertNotIn("Eggs", sun)
        self.assertIn("Eggs (Wed Nov 4)", "\n".join(ev["2026-11-01"][3]))

    def test_empty_checkins_are_skipped_and_the_list_closes(self):
        events = make_ics.plan_events(plan([
            item("Spinach", "2026-10-19"), item("Eggs", "2026-11-04")]))
        self.assertEqual([e[0].isoformat() for e in events],
                         ["2026-10-18", "2026-11-01", "2026-11-08"])
        self.assertEqual(events[-1][2], "Save Your Food: time for a new list")
        self.assertIn("Wed Oct 14 receipt", events[-1][3][0])

    def test_the_idea_for_the_most_urgent_food_comes_along(self):
        ev = by_date(make_ics.plan_events(plan([
            item("Yogurt", "2026-10-21", idea="Overnight oats."),
            item("Mushrooms", "2026-10-19", idea="Wilt them into eggs.")])))
        self.assertIn("Idea: Wilt them into eggs.", ev["2026-10-18"][3])
        self.assertNotIn("Idea: Overnight oats.", ev["2026-10-18"][3])

    def test_past_today_and_far_off_food_stay_out(self):
        self.assertEqual(make_ics.plan_events(plan([
            item("Old milk", "2026-10-10"), item("Lettuce", TODAY),
            item("Honey", "2027-06-01")])), [])

    def test_other_days_and_hour(self):
        events = make_ics.plan_events(plan(
            [item("Spinach", "2026-10-20")], days=["MO", "TH"], hour=8))
        self.assertEqual(events[0][0].isoformat(), "2026-10-19")   # a Monday
        self.assertEqual(events[0][1], 8)


class FileFormat(unittest.TestCase):

    P = plan([item("Chicken, boneless; thighs", "2026-10-16"),
              item("Crème fraîche " * 8, "2026-10-19", guess=True,
                   idea="Stir it into soup, tonight.")])

    def test_lines_are_crlf_and_at_most_75_octets(self):
        ics = make_ics.to_ics(self.P)
        self.assertTrue(ics.endswith("\r\n"))
        self.assertNotIn("\n", ics.replace("\r\n", ""))
        for l in ics.split("\r\n"):
            self.assertLessEqual(len(l.encode("utf-8")), 75, l)

    def test_blocks_balance_and_every_event_alerts(self):
        ics = make_ics.to_ics(self.P)
        n = ics.count("BEGIN:VEVENT")
        self.assertEqual(n, ics.count("END:VEVENT"))
        self.assertEqual(n, ics.count("BEGIN:VALARM"))
        self.assertEqual(n, len(make_ics.plan_events(self.P)))

    def test_text_is_escaped(self):
        unfolded = make_ics.to_ics(self.P).replace("\r\n ", "")
        self.assertIn("Use the chicken\\, boneless\\; thighs by tomorrow", unfolded)
        self.assertIn("\\nIdea: Stir it into soup\\, tonight.", unfolded)

    def test_same_plan_same_uids_different_plan_different_uids(self):
        uids = lambda p: [l for l in make_ics.to_ics(p).split("\r\n")
                          if l.startswith("UID:")]
        self.assertEqual(uids(self.P), uids(self.P))
        self.assertEqual(len(set(uids(self.P))), len(uids(self.P)))
        other = plan([item("Chicken, boneless; thighs", "2026-10-17")])
        self.assertFalse(set(uids(self.P)) & set(uids(other)))

    def test_times_are_floating(self):
        starts = [l for l in make_ics.to_ics(self.P).split("\r\n")
                  if l.startswith("DTSTART")]
        self.assertTrue(starts)
        for l in starts:
            self.assertRegex(l, r"^DTSTART:\d{8}T170000$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
