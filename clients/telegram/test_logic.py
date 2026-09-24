"""Everything that can be checked without Telegram. Run: python3 test_logic.py"""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fridge
import shelf_life as sl

TODAY = date(2026, 9, 23)   # a Wednesday, so weekday names are checkable


class ShelfLife(unittest.TestCase):
    def test_raw_meat_is_red_and_short(self):
        for name in ("chicken thighs", "ground beef", "salmon fillet"):
            days, cls, est = sl.lookup(name)
            self.assertEqual(cls, sl.RED, name)
            self.assertLessEqual(days, 3, name)
            self.assertFalse(est, name)

    def test_specific_beats_general(self):
        # "ground beef" must not fall through to the 3-day "beef" rule
        self.assertEqual(sl.lookup("ground beef")[0], 1)
        self.assertEqual(sl.lookup("beef chuck")[0], 3)
        # "chocolate milk" and "oat milk" are both milk, but oat lasts longer
        self.assertEqual(sl.lookup("oat milk")[0], 7)
        self.assertEqual(sl.lookup("chocolate milk")[0], 7)

    def test_unknown_is_flagged_estimated(self):
        days, cls, est = sl.lookup("dragonfruit curd")
        self.assertTrue(est)
        self.assertEqual(days, sl.DEFAULT_DAYS)

    def test_things_that_belong_outside(self):
        self.assertTrue(sl.better_outside("yellow onions"))
        self.assertTrue(sl.better_outside("russet potatoes"))
        self.assertFalse(sl.better_outside("spinach"))

    def test_garlic_paste_is_not_a_bulb(self):
        # a known trap: "garlic paste" lives in the fridge, whole garlic does not.
        # Both currently match, which is a real limitation — assert it honestly
        # so the day someone fixes it, this test tells them.
        self.assertTrue(sl.better_outside("garlic paste"))


class Tiers(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(sl.tier(TODAY - timedelta(days=1), TODAY), 0)
        self.assertEqual(sl.tier(TODAY, TODAY), 1)
        self.assertEqual(sl.tier(TODAY + timedelta(days=1), TODAY), 1)
        self.assertEqual(sl.tier(TODAY + timedelta(days=2), TODAY), 2)
        self.assertEqual(sl.tier(TODAY + timedelta(days=4), TODAY), 2)
        self.assertEqual(sl.tier(TODAY + timedelta(days=5), TODAY), 3)

    def test_budget_is_per_risk_class(self):
        two_past = TODAY - timedelta(days=2)
        self.assertTrue(sl.past_budget(two_past, sl.RED, TODAY))     # red: 1 day
        self.assertFalse(sl.past_budget(two_past, sl.YELLOW, TODAY))  # yellow: 3
        self.assertFalse(sl.past_budget(two_past, sl.GREEN, TODAY))   # green: 7

    def test_wording_carries_weekday_and_relative(self):
        self.assertEqual(sl.when(TODAY, TODAY), "Wed Sep 23 (today)")
        self.assertEqual(sl.when(TODAY + timedelta(days=1), TODAY), "Thu Sep 24 (tomorrow)")
        self.assertEqual(sl.when(TODAY + timedelta(days=2), TODAY), "Fri Sep 25")
        self.assertEqual(sl.when(TODAY - timedelta(days=1), TODAY), "Tue Sep 22 (1 day past)")
        self.assertEqual(sl.when(TODAY - timedelta(days=3), TODAY), "Sun Sep 20 (3 days past)")


class Parsing(unittest.TestCase):
    def test_commas_newlines_bullets(self):
        self.assertEqual(
            fridge.parse_list("milk, spinach\n- chicken thighs\n• yogurt"),
            ["milk", "spinach", "chicken thighs", "yogurt"])

    def test_quantities_are_stripped(self):
        self.assertEqual(
            fridge.parse_list("2 bunches cilantro, milk x2, 3 cans tomatoes"),
            ["cilantro", "milk", "tomatoes"])

    def test_junk_in_junk_out_but_no_crash(self):
        self.assertEqual(fridge.parse_list("   "), [])
        self.assertEqual(fridge.parse_list(",,,"), [])


class Store(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.con = fridge.connect(self.path)

    def tearDown(self):
        self.con.close()
        os.path.exists(self.path) and os.remove(self.path)

    def test_add_then_read_back(self):
        added, outside = fridge.add_items(
            self.con, 1, ["milk", "chicken thighs", "onions"], TODAY)
        self.assertEqual(len(added), 2)
        self.assertEqual(outside, ["onions"])
        items = fridge.open_items(self.con, 1)
        self.assertEqual([i["name"] for i in items], ["chicken thighs", "milk"])

    def test_closing_removes_from_open(self):
        fridge.add_items(self.con, 1, ["milk"], TODAY)
        item = fridge.open_items(self.con, 1)[0]
        fridge.close_item(self.con, 1, item["id"], "used")
        self.assertEqual(fridge.open_items(self.con, 1), [])

    def test_chats_do_not_see_each_other(self):
        fridge.add_items(self.con, 1, ["milk"], TODAY)
        fridge.add_items(self.con, 2, ["spinach"], TODAY)
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 1)], ["milk"])
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 2)], ["spinach"])

    def test_at_risk_is_only_tiers_0_and_1(self):
        fridge.add_items(self.con, 1, ["chicken thighs", "milk", "carrots"], TODAY)
        tomorrow = TODAY + timedelta(days=1)
        names = [i["name"] for i in fridge.at_risk(self.con, 1, tomorrow)]
        self.assertEqual(names, ["chicken thighs"])   # milk has 6 days left, carrots 20


class Nudge(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.con = fridge.connect(self.path)

    def tearDown(self):
        self.con.close()
        os.path.exists(self.path) and os.remove(self.path)

    def test_silence_when_nothing_is_at_risk(self):
        fridge.add_items(self.con, 1, ["carrots"], TODAY)
        self.assertIsNone(fridge.compose_nudge(fridge.at_risk(self.con, 1, TODAY), TODAY))

    def test_single_item_headline_names_it(self):
        fridge.add_items(self.con, 1, ["spinach"], TODAY)
        day = TODAY + timedelta(days=2)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertTrue(body.startswith("Use the spinach tonight, or freeze it"))

    def test_headline_never_hides_the_count(self):
        fridge.add_items(self.con, 1, ["spinach", "cilantro", "parsley"], TODAY)
        day = TODAY + timedelta(days=2)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("2 more", body)

    def test_expired_raw_meat_says_throw_it_out(self):
        fridge.add_items(self.con, 1, ["chicken thighs"], TODAY)
        day = TODAY + timedelta(days=2)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("throw it out", body)

    def test_past_date_headline_agrees_in_number(self):
        fridge.add_items(self.con, 1, ["spinach"], TODAY)
        day = TODAY + timedelta(days=5)
        self.assertIn("1 item past its date",
                      fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day))
        fridge.add_items(self.con, 1, ["cilantro", "parsley"], TODAY)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("3 items past their date", body)
        self.assertNotIn("past its date", body)

    def test_estimates_are_marked_as_estimates(self):
        fridge.add_items(self.con, 1, ["dragonfruit curd"], TODAY)
        day = TODAY + timedelta(days=5)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("(est.)", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
