"""Everything that can be checked without Telegram. Run: python3 test_logic.py"""

import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fridge
import shelf_life as sl
import onboarding as onb
import art

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
        # This used to assert the limitation rather than the behaviour: both
        # "garlic paste" and "garlic" matched the counter rule, because it was a
        # bare substring match. It is whole-word now, so the paste is a pantry
        # item and only the bulb goes on the counter.
        self.assertFalse(sl.better_outside("garlic paste"))
        self.assertTrue(sl.shelf_stable("garlic paste"))
        self.assertTrue(sl.better_outside("garlic"))


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
        added, stable, outside, again = fridge.add_items(
            self.con, 1, ["milk", "chicken thighs", "onions"], TODAY)
        self.assertEqual(len(added), 2)
        self.assertEqual(outside, ["onions"])
        self.assertEqual((stable, again), ([], []))
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
        self.assertIn("toss it", body)

    def test_past_date_headline_agrees_in_number(self):
        fridge.add_items(self.con, 1, ["spinach"], TODAY)
        day = TODAY + timedelta(days=5)
        self.assertIn("1 thing past its best",
                      fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day))
        fridge.add_items(self.con, 1, ["cilantro", "parsley"], TODAY)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("3 things past their best", body)
        self.assertNotIn("past its date", body)

    def test_estimates_are_marked_as_estimates(self):
        fridge.add_items(self.con, 1, ["dragonfruit curd"], TODAY)
        day = TODAY + timedelta(days=5)
        body = fridge.compose_nudge(fridge.at_risk(self.con, 1, day), day)
        self.assertIn("(a guess)", body)


# ---------------------------------------------------------------------------
# Wrong answers land in the right bucket.
#
# Every case below is a real thing a person typed, or would type, into a bot
# that opens by asking what is in their fridge. None of them is a mistake to
# reject — each one is a list that belongs somewhere, and the job is to put it
# there and say so.
# ---------------------------------------------------------------------------

class Buckets(unittest.TestCase):
    """sl.not_tracked: which of the three piles does a name belong to?"""

    def assertBucket(self, name, expected):
        skip, reason = sl.not_tracked(name)
        got = reason if skip else "tracked"
        self.assertEqual(got, expected, "%s — expected %s, got %s"
                         % (name, expected, got))

    def test_a_whole_spice_rack_goes_to_the_pantry(self):
        for name in ("cumin", "oregano", "paprika", "turmeric", "bay leaves",
                     "Old Bay seasoning", "Goya adobo", "berbere seasoning",
                     "chili powder", "Chinese five spice", "kosher salt",
                     "black pepper", "MSG", "curry powder"):
            self.assertBucket(name, "stable")

    def test_sauces_oils_and_vinegars_go_to_the_pantry(self):
        for name in ("olive oil", "sesame oil", "rice vinegar", "dark soy sauce",
                     "fish sauce", "hoisin sauce", "oyster sauce", "sriracha",
                     "Worcestershire sauce", "mirin", "Shaoxing wine",
                     "Maggi Jugo", "tahini", "peanut butter", "liquid smoke"):
            self.assertBucket(name, "stable")

    def test_cans_and_dry_goods_go_to_the_pantry(self):
        for name in ("chicken bouillon", "beef broth", "tomato paste",
                     "crushed tomatoes", "black beans", "pink beans",
                     "red lentils", "whole kernel corn", "Calrose rice",
                     "spaghetti", "elbow macaroni", "all-purpose flour",
                     "cornstarch", "panko", "baking powder", "brown sugar",
                     "honey", "maple syrup", "chia seeds", "raisins",
                     "Vienna sausages", "capers", "sliced pimientos"):
            self.assertBucket(name, "stable")

    def test_counter_produce_is_its_own_bucket(self):
        # Perishable, but the fridge is the wrong place for it, and that is a
        # different thing to say than "this has no clock on it".
        for name in ("onions", "potatoes", "garlic", "butternut squash"):
            self.assertBucket(name, "outside")

    def test_real_perishables_still_get_tracked(self):
        for name in ("milk", "spinach", "chicken thighs", "yogurt", "cilantro",
                     "oat milk", "ground beef", "salmon", "strawberries",
                     "tofu", "mushrooms", "leftover guiso", "parmesan", "eggs"):
            self.assertBucket(name, "tracked")


class BucketCollisions(unittest.TestCase):
    """The pantry keywords are substrings, so each of these is a trap: one name
    contains another name that belongs in a different bucket. Every pair below
    broke at least once while the guard was being written."""

    def assertBucket(self, name, expected):
        skip, reason = sl.not_tracked(name)
        got = reason if skip else "tracked"
        self.assertEqual(got, expected, "%s — expected %s, got %s"
                         % (name, expected, got))

    def test_ground_meat_is_not_a_ground_spice(self):
        # "ground " is a pantry modifier. Ground beef is a one-day red item.
        self.assertBucket("ground ginger", "stable")
        self.assertBucket("ground cinnamon", "stable")
        self.assertBucket("ground beef", "tracked")
        self.assertBucket("ground turkey", "tracked")
        self.assertBucket("ground pork", "tracked")

    def test_fresh_beats_the_dried_version(self):
        self.assertBucket("dried parsley", "stable")
        self.assertBucket("parsley", "tracked")
        self.assertBucket("fresh ginger", "tracked")

    def test_coconut_milk_is_not_a_dairy_run(self):
        # This one was a live bug: canned coconut milk was tracked as a
        # seven-day perishable because "milk" matched.
        self.assertBucket("coconut milk", "stable")
        self.assertBucket("evaporated milk", "stable")
        self.assertBucket("oat milk", "tracked")
        self.assertBucket("chocolate milk", "tracked")
        self.assertBucket("milk", "tracked")

    def test_black_pepper_is_not_a_bell_pepper(self):
        self.assertBucket("black pepper", "stable")
        self.assertBucket("lemon pepper", "stable")
        self.assertBucket("bell pepper", "tracked")
        self.assertBucket("red peppers", "tracked")

    def test_canned_beans_are_not_green_beans(self):
        self.assertBucket("black beans", "stable")
        self.assertBucket("canned beans", "stable")
        self.assertBucket("green beans", "tracked")

    def test_cooked_rice_is_a_leftover_not_a_grain(self):
        self.assertBucket("Calrose rice", "stable")
        self.assertBucket("cooked rice", "tracked")
        self.assertBucket("leftover rice", "tracked")

    def test_the_counter_bucket_is_whole_word_not_substring(self):
        # Every one of these was going to the counter because "garlic" or
        # "onion" appeared somewhere inside the name.
        for name in ("garlic powder", "garlic salt", "onion powder",
                     "minced garlic, jarred", "garlic paste",
                     "Campbell's French onion", "onion soup mix"):
            self.assertBucket(name, "stable")
        for name in ("onions", "sweet potatoes", "russet potatoes",
                     "garlic", "3 cloves garlic", "butternut squash",
                     "shallots", "winter squash"):
            self.assertBucket(name, "outside")

    def test_butter_does_not_swallow_its_lookalikes(self):
        self.assertBucket("butter", "stable")
        self.assertBucket("peanut butter", "stable")
        self.assertBucket("butternut squash", "outside")
        self.assertBucket("butter lettuce", "tracked")
        self.assertBucket("buttermilk", "tracked")

    def test_canned_soup_is_not_cream(self):
        self.assertBucket("cream of chicken", "stable")
        self.assertBucket("Campbell's beef consomme", "stable")
        self.assertBucket("heavy cream", "tracked")

    def test_frozen_things_are_not_on_a_fridge_clock(self):
        self.assertBucket("frozen sofrito", "stable")
        self.assertBucket("frozen peas", "stable")

    def test_a_modifier_alone_is_enough(self):
        # Things not in any keyword list, carried by the modifier only.
        self.assertBucket("dried porcini", "stable")
        self.assertBucket("canned jackfruit", "stable")
        self.assertBucket("ground sumac", "stable")


class SortedCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.con = fridge.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()
        os.unlink(self.tmp.name)

    def test_a_pantry_list_is_sorted_not_rejected(self):
        # The actual failure that started this: asked what was in his fridge, he
        # sent his pantry. Nothing should be tracked, nothing should be lost.
        sent = ["cumin", "olive oil", "black beans", "onions", "milk"]
        tracked, stable, outside, again = fridge.add_items(self.con, 1, sent, TODAY)
        self.assertEqual([t[0] for t in tracked], ["milk"])
        self.assertEqual(stable, ["cumin", "olive oil", "black beans"])
        self.assertEqual(outside, ["onions"])
        self.assertEqual(len(tracked) + len(stable) + len(outside), len(sent))

    def test_pantry_items_are_remembered_not_discarded(self):
        fridge.add_items(self.con, 1, ["cumin", "olive oil", "onions"], TODAY)
        names = [i["name"] for i in fridge.pantry_items(self.con, 1)]
        self.assertEqual(sorted(names), ["cumin", "olive oil", "onions"])
        body = fridge.compose_pantry(fridge.pantry_items(self.con, 1))
        self.assertIn("cumin", body)
        self.assertIn("counter", body.lower())

    def test_nothing_untracked_ever_reaches_a_nudge(self):
        # The symptom he hit: buttons asking whether he used or tossed his
        # soy sauce. Nothing in the pantry may appear in the at-risk list, ever.
        fridge.add_items(self.con, 1, ["cumin", "soy sauce", "rice", "onions"], TODAY)
        for offset in range(0, 40):
            day = TODAY + timedelta(days=offset)
            self.assertEqual(fridge.at_risk(self.con, 1, day), [],
                             "pantry item surfaced on day %d" % offset)
        self.assertIsNone(fridge.compose_nudge(fridge.at_risk(self.con, 1, TODAY)))

    def test_resending_a_list_does_not_stack_duplicates(self):
        fridge.add_items(self.con, 1, ["milk", "cumin"], TODAY)
        tracked, stable, outside, again = fridge.add_items(
            self.con, 1, ["milk", "cumin"], TODAY + timedelta(days=2))
        self.assertEqual(tracked, [])
        self.assertEqual(again, ["milk"])          # date moved, not duplicated
        self.assertEqual(len(fridge.open_items(self.con, 1)), 1)
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 1)

    def test_buying_more_moves_the_date_forward(self):
        fridge.add_items(self.con, 1, ["milk"], TODAY)
        later = TODAY + timedelta(days=5)
        fridge.add_items(self.con, 1, ["milk"], later)
        item = fridge.open_items(self.con, 1)[0]
        self.assertEqual(item["use_by_date"], later + timedelta(days=7))

    def test_case_does_not_create_a_second_copy(self):
        fridge.add_items(self.con, 1, ["Milk"], TODAY)
        tracked, _, _, again = fridge.add_items(self.con, 1, ["milk"], TODAY)
        self.assertEqual(again, ["milk"])
        self.assertEqual(len(fridge.open_items(self.con, 1)), 1)

    def test_undo_takes_back_only_the_last_list(self):
        fridge.add_items(self.con, 1, ["milk", "cumin"], TODAY)
        fridge.add_items(self.con, 1, ["spinach", "oregano"], TODAY)
        msg = fridge.undo_last(self.con, 1)
        self.assertIn("Took back", msg)
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 1)], ["milk"])
        self.assertEqual([i["name"] for i in fridge.pantry_items(self.con, 1)], ["cumin"])

    def test_undo_on_an_empty_fridge_says_so(self):
        self.assertEqual(fridge.undo_last(self.con, 1), "Nothing to undo.")

    def test_clear_wipes_both_piles(self):
        fridge.add_items(self.con, 1, ["milk", "cumin", "onions"], TODAY)
        n_items, n_pantry = fridge.clear_chat(self.con, 1)
        self.assertEqual((n_items, n_pantry), (1, 2))
        self.assertEqual(fridge.open_items(self.con, 1), [])
        self.assertEqual(fridge.pantry_items(self.con, 1), [])

    def test_one_chat_cannot_see_another(self):
        fridge.add_items(self.con, 1, ["milk", "cumin"], TODAY)
        fridge.add_items(self.con, 2, ["spinach"], TODAY)
        fridge.clear_chat(self.con, 2)
        self.assertEqual(len(fridge.open_items(self.con, 1)), 1)
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 1)


class NothingIsLostSilently(unittest.TestCase):
    def test_an_over_long_fragment_is_reported_not_swallowed(self):
        text = ("milk, I really need to remember to use up that chicken before "
                "the weekend because otherwise it will go off, spinach")
        names, too_long = fridge.parse_list(text, report=True)
        self.assertEqual(names, ["milk", "spinach"])
        self.assertEqual(len(too_long), 1)
        self.assertTrue(too_long[0].endswith("..."))

    def test_parse_list_still_works_without_report(self):
        self.assertEqual(fridge.parse_list("milk, spinach"), ["milk", "spinach"])

    def test_a_reply_to_me_is_not_a_fridge_item(self):
        for text in ("ok", "thanks", "Thank you", "yes", "nope", "hi", "cool",
                     "got it", "done", "testing", "OK!", "sure."):
            self.assertTrue(fridge.is_chatter(text), text)

    def test_food_is_not_mistaken_for_chatter(self):
        for text in ("milk", "ok choy", "yes please add milk", "thanksgiving turkey",
                     "milk, spinach"):
            self.assertFalse(fridge.is_chatter(text), text)

    def test_quantities_come_off_the_front_and_back(self):
        names = fridge.parse_list("2 bunches cilantro\n1 lb ground beef\nbacon x2")
        self.assertEqual(names, ["cilantro", "ground beef", "bacon"])


class MigratesInPlace(unittest.TestCase):
    def test_an_old_database_gains_the_batch_column(self):
        # Someone already running the bot must not have to delete their fridge
        # to get /undo.
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        old = sqlite3.connect(tmp.name)
        old.executescript("""
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                name TEXT NOT NULL, use_by TEXT NOT NULL, risk TEXT NOT NULL,
                estimated INTEGER NOT NULL, added TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'open', closed TEXT);
            INSERT INTO items (chat_id,name,use_by,risk,estimated,added,state)
            VALUES (1,'milk','2026-09-30','yellow',0,'2026-09-23','open');
        """)
        old.commit()
        old.close()
        con = fridge.connect(tmp.name)
        cols = [r[1] for r in con.execute("PRAGMA table_info(items)")]
        self.assertIn("batch", cols)
        self.assertEqual(len(fridge.open_items(con, 1)), 1)   # data survived
        fridge.add_items(con, 1, ["spinach"], TODAY)
        self.assertIn("Took back", fridge.undo_last(con, 1))
        con.close()
        os.unlink(tmp.name)




class SentencesAreNotFood(unittest.TestCase):
    """The sentence he actually typed, and its neighbours. Each of these used to
    become a dated fridge item with a clause for a name."""

    def test_the_sentence_that_broke_it(self):
        self.assertTrue(fridge.looks_like_sentence(
            "these items are all from the pantry"))

    def test_prose_is_recognised_as_prose(self):
        for text in ("these items are all from the pantry",
                     "that is my pantry not my fridge",
                     "I think I already have most of this",
                     "can you remove the ones that are not perishable",
                     "none of these go bad",
                     "why did you add my spices"):
            self.assertTrue(fridge.looks_like_sentence(text), text)

    def test_a_list_is_not_mistaken_for_prose(self):
        for text in ("milk, spinach, chicken thighs",
                     "milk\nspinach\nchicken thighs",
                     "ground beef",
                     "2 bunches cilantro, 1 lb ground beef, bacon",
                     "oat milk and yogurt",
                     "chicken thighs, bell peppers, cilantro, limes"):
            self.assertFalse(fridge.looks_like_sentence(text), text)


class Corrections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.con = fridge.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()
        os.unlink(self.tmp.name)

    def test_pantry_phrasings_are_all_understood(self):
        for text in ("these items are all from the pantry",
                     "those are pantry items",
                     "that is all in my cupboard",
                     "these are shelf stable",
                     "none of these go bad",
                     "they are all dry goods"):
            self.assertEqual(fridge.correction(text), "pantry", text)

    def test_negation_flips_the_bucket(self):
        self.assertEqual(fridge.correction("none of these go bad"), "pantry")
        self.assertEqual(fridge.correction("these dont go off"), "pantry")
        self.assertEqual(fridge.correction("nothing here is perishable"), "pantry")
        self.assertEqual(fridge.correction("these are not pantry items"), "fridge")
        self.assertEqual(fridge.correction("none of that is shelf stable"), "fridge")

    def test_a_leading_no_is_not_a_negation(self):
        # "no, those go off quickly" is agreement-then-claim, not negation.
        self.assertEqual(fridge.correction("no those go off quickly"), "fridge")

    def test_fridge_phrasings_are_all_understood(self):
        for text in ("these are in the fridge",
                     "those are perishable",
                     "no those go off quickly",
                     "please track these"):
            self.assertEqual(fridge.correction(text), "fridge", text)

    def test_a_plain_list_is_not_a_correction(self):
        for text in ("milk, spinach", "ground beef", "cumin, oregano",
                     "milk\nspinach"):
            self.assertIsNone(fridge.correction(text), text)

    def test_saying_it_is_pantry_moves_the_last_list(self):
        # The exact sequence he hit: a pantry list gets tracked, and he says so.
        fridge.add_items(self.con, 1, ["dragonfruit curd", "sumac blend"], TODAY)
        self.assertEqual(len(fridge.open_items(self.con, 1)), 2)
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(sorted(names), ["dragonfruit curd", "sumac blend"])
        self.assertEqual(fridge.open_items(self.con, 1), [])
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 2)
        self.assertIn("pantry", reply)

    def test_moved_items_never_nudge_again(self):
        fridge.add_items(self.con, 1, ["dragonfruit curd"], TODAY)
        fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        for offset in range(0, 40):
            day = TODAY + timedelta(days=offset)
            self.assertEqual(fridge.at_risk(self.con, 1, day), [], "day %d" % offset)

    def test_saying_it_is_fridge_moves_it_back(self):
        fridge.add_items(self.con, 1, ["cumin", "olive oil"], TODAY)
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 2)
        names, reply = fridge.reclassify_last(self.con, 1, "fridge", TODAY)
        self.assertEqual(sorted(names), ["cumin", "olive oil"])
        self.assertEqual(fridge.pantry_items(self.con, 1), [])
        self.assertEqual(len(fridge.open_items(self.con, 1)), 2)
        self.assertIn("Tracking 2", reply)

    def test_a_correction_only_touches_the_last_list(self):
        fridge.add_items(self.con, 1, ["milk"], TODAY)
        fridge.add_items(self.con, 1, ["dragonfruit curd"], TODAY)
        fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 1)], ["milk"])

    def test_correcting_with_nothing_captured_says_so(self):
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(names, [])
        self.assertIn("recent list", reply)

    def test_correcting_the_wrong_way_is_not_silent(self):
        # Said "those are pantry" when nothing was tracked in that batch.
        fridge.add_items(self.con, 1, ["cumin"], TODAY)
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(names, [])
        self.assertIn("nothing to move", reply.lower())
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 1)   # unharmed

    def test_raw_meat_is_not_moved_on_a_vague_instruction(self):
        # "those are pantry" must not quietly stop me watching raw chicken.
        # Everything else in the list still moves.
        fridge.add_items(self.con, 1, ["chicken thighs", "spinach", "cumin"], TODAY)
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(names, ["spinach"])
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 1)],
                         ["chicken thighs"])
        self.assertIn("kept chicken thighs tracked", reply)
        self.assertIn("/undo", reply)

    def test_an_all_raw_list_moves_nothing_and_says_why(self):
        fridge.add_items(self.con, 1, ["chicken thighs", "salmon"], TODAY)
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(names, [])
        self.assertEqual(len(fridge.open_items(self.con, 1)), 2)
        self.assertIn("chicken thighs and salmon", reply)

    def test_raw_meat_can_still_be_removed_outright(self):
        # The guard holds it back from the pantry; it must not trap it forever.
        fridge.add_items(self.con, 1, ["chicken thighs"], TODAY)
        fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertIn("Took back", fridge.undo_last(self.con, 1))
        self.assertEqual(fridge.open_items(self.con, 1), [])

    def test_a_non_red_list_still_moves_whole(self):
        fridge.add_items(self.con, 1, ["spinach", "yogurt", "milk"], TODAY)
        names, reply = fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        self.assertEqual(sorted(names), ["milk", "spinach", "yogurt"])
        self.assertNotIn("kept", reply)

    def test_a_correction_can_be_undone_by_the_other_correction(self):

        fridge.add_items(self.con, 1, ["milk"], TODAY)
        fridge.reclassify_last(self.con, 1, "pantry", TODAY)
        fridge.reclassify_last(self.con, 1, "fridge", TODAY)
        self.assertEqual([i["name"] for i in fridge.open_items(self.con, 1)], ["milk"])
        self.assertEqual(fridge.pantry_items(self.con, 1), [])




class Onboarding(unittest.TestCase):
    """The four steps, and the promises each one makes."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.con = fridge.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()
        os.unlink(self.tmp.name)

    def test_a_new_chat_has_not_started(self):
        self.assertFalse(onb.started(self.con, 1))
        self.assertFalse(onb.active(self.con, 1))

    def test_step_one_asks_for_one_thing_not_a_list(self):
        text = onb.begin(self.con, 1)
        self.assertIn("one thing", text.lower())
        self.assertNotIn("commas", text.lower())
        self.assertTrue(onb.active(self.con, 1))

    def test_step_one_admits_the_date_is_a_guess(self):
        reply, nxt = onb.handle_item(self.con, 1, "dragonfruit curd", TODAY)
        self.assertIn("guessed", reply.lower())
        self.assertEqual(onb.step(self.con, 1), "2")

    def test_step_one_does_not_call_a_known_life_a_guess(self):
        reply, nxt = onb.handle_item(self.con, 1, "milk", TODAY)
        self.assertNotIn("guessed", reply.lower())
        self.assertIn("Wed Sep 30", reply)   # 7 days from TODAY

    def test_step_one_handles_a_pantry_item_without_a_fake_date(self):
        # If the first thing they name is a spice, the demo still has to be
        # honest: no invented date, and no pretending it was tracked.
        reply, nxt = onb.handle_item(self.con, 1, "cumin", TODAY)
        self.assertIn("pantry", reply.lower())
        self.assertEqual(fridge.open_items(self.con, 1), [])
        self.assertEqual(len(fridge.pantry_items(self.con, 1)), 1)

    def test_step_one_recovers_from_an_unreadable_answer(self):
        onb.begin(self.con, 1)
        reply, nxt = onb.handle_item(self.con, 1, "   ", TODAY)
        self.assertIn("just one", reply.lower())
        self.assertEqual(onb.step(self.con, 1), "1")   # does not advance

    def test_step_two_teaches_the_sort_by_doing_it(self):
        onb.begin(self.con, 1)
        onb.handle_item(self.con, 1, "milk", TODAY)
        reply, nxt = onb.handle_list(self.con, 1, "spinach, cumin, olive oil", TODAY)
        self.assertIn("spinach", reply)
        self.assertIn("cumin", reply)
        self.assertIn("stay quiet about these", reply)
        self.assertEqual(onb.step(self.con, 1), "3")

    def test_step_two_says_so_when_nothing_went_to_the_pantry(self):
        onb.begin(self.con, 1)
        onb.handle_item(self.con, 1, "milk", TODAY)
        reply, nxt = onb.handle_list(self.con, 1, "spinach, yogurt", TODAY)
        self.assertIn("nothing went to the pantry", reply.lower())

    def test_the_time_is_a_real_number_not_once_a_day(self):
        self.assertIn("When do you want", onb.STEP3)
        hours = [b["callback_data"] for row in onb.TIME_BUTTONS for b in row]
        self.assertTrue(all(h.startswith("onb:time:") for h in hours))
        self.assertEqual(len(hours), 6)

    def test_the_chosen_hour_is_stored_per_chat(self):
        fridge.set_pref(self.con, 1, "nudge_hour", 19)
        self.assertEqual(fridge.nudge_hour(self.con, 1, 8), 19)
        self.assertEqual(fridge.nudge_hour(self.con, 2, 8), 8)    # untouched

    def test_a_nonsense_stored_hour_falls_back(self):
        fridge.set_pref(self.con, 1, "nudge_hour", "half past")
        self.assertEqual(fridge.nudge_hour(self.con, 1, 8), 8)
        fridge.set_pref(self.con, 1, "nudge_hour", 44)
        self.assertEqual(fridge.nudge_hour(self.con, 1, 8), 8)

    def test_step_four_shows_the_way_out_before_it_is_needed(self):
        for phrase in ("those are pantry", "those are fridge", "/undo"):
            self.assertIn(phrase, onb.STEP4_HEAD)

    def test_the_closing_message_defines_silence(self):
        text = onb.finished(8)
        self.assertIn("08:00", text)
        self.assertIn("hear nothing", text)

    def test_skip_leaves_no_half_finished_state(self):
        onb.begin(self.con, 1)
        msg = onb.skip(self.con, 1, 8)
        self.assertFalse(onb.active(self.con, 1))
        self.assertTrue(onb.started(self.con, 1))
        self.assertIn("08:00", msg)

    def test_clearing_the_fridge_keeps_the_chosen_hour(self):
        fridge.set_pref(self.con, 1, "nudge_hour", 19)
        fridge.add_items(self.con, 1, ["milk"], TODAY)
        fridge.clear_chat(self.con, 1)
        self.assertEqual(fridge.nudge_hour(self.con, 1, 8), 19)

    def test_onboarding_state_is_not_a_fridge_item(self):
        # meta and items are separate tables; a state write must never show up
        # as something to use tonight.
        onb.begin(self.con, 1)
        self.assertEqual(fridge.open_items(self.con, 1), [])
        self.assertEqual(fridge.at_risk(self.con, 1, TODAY), [])




class Delight(unittest.TestCase):
    """The art is the easiest thing here to get wrong, because a drawing that
    breaks a rule still looks fine in isolation. These tests hold the rules."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.con = fridge.connect(self.tmp.name)

    def tearDown(self):
        self.con.close()
        os.unlink(self.tmp.name)

    # --- the frames themselves ---

    def test_every_frame_fits_a_phone(self):
        for f in art.all_frames():
            lines, width = art.measure(f)
            self.assertLessEqual(width, art.MAX_WIDTH,
                                 "too wide (%d): %r" % (width, f))
            self.assertLessEqual(lines, art.MAX_LINES,
                                 "too tall (%d): %r" % (lines, f))

    def test_ascii_art_is_actually_ascii(self):
        # A Cyrillic o got into the cheese wedge once. It renders as a box on
        # some phones, which is worse than no drawing at all.
        for f in art.all_frames():
            for ch in f:
                self.assertLess(ord(ch), 127,
                                "non-ascii %r in %r" % (ch, f[:20]))

    def test_no_frame_is_blank_or_ragged(self):
        for f in art.all_frames():
            self.assertTrue(f.strip(), "empty frame")
            self.assertFalse(f.startswith("\n"), "leading blank line")
            self.assertFalse(f.endswith("\n"), "trailing blank line")

    def test_frames_are_distinct(self):
        frames = art.all_frames()
        self.assertEqual(len(frames), len(set(frames)))

    # --- where art may not go ---

    def test_a_nudge_never_carries_a_drawing(self):
        self.assertIsNone(art.choose("nudge"))
        self.assertIsNone(art.choose("nudge", item="milk"))

    def test_a_toss_is_never_celebrated(self):
        # Food was wasted. A picture over it reads as mockery.
        self.assertIsNone(art.choose("tossed"))
        self.assertIsNone(art.choose("tossed", item="spinach"))

    def test_a_disposal_question_carries_no_drawing(self):
        self.assertIsNone(art.choose("toss_prompt"))

    def test_every_forbidden_moment_states_a_reason(self):
        # A rule without a reason gets deleted by the next person.
        for moment, why in art.FORBIDDEN.items():
            self.assertTrue(why and len(why) > 15, moment)

    # --- where it does go ---

    def test_using_something_gets_a_drawing(self):
        self.assertIsNotNone(art.choose("used"))
        self.assertIsNotNone(art.choose("frozen"))
        self.assertIsNotNone(art.choose("allclear"))
        self.assertIsNotNone(art.choose("welcome"))

    def test_the_drawing_matches_the_food(self):
        self.assertEqual(art.choose("used", item="milk"), art.CARTON)
        self.assertEqual(art.choose("used", item="oat milk"), art.CARTON)
        self.assertEqual(art.choose("used", item="baby spinach"), art.LEAF)
        self.assertEqual(art.choose("used", item="chicken thighs"), art.HEN)
        self.assertEqual(art.choose("used", item="ground beef"), art.CHOP)
        self.assertEqual(art.choose("used", item="salmon"), art.FISH)
        self.assertEqual(art.choose("used", item="leftover guiso"), art.POT)
        self.assertEqual(art.choose("used", item="eggs"), art.EGG)
        self.assertEqual(art.choose("used", item="parmesan"), art.WEDGE)
        self.assertEqual(art.choose("used", item="sourdough bread"), art.LOAF)
        self.assertEqual(art.choose("used", item="strawberries"), art.APPLE)

    def test_an_unmatched_food_still_gets_something(self):
        frame = art.choose("used", item="dragonfruit curd")
        self.assertIsNotNone(frame)
        self.assertIn(frame, art.MOMENT_ART["used"])

    def test_food_matching_does_not_leak_into_other_moments(self):
        # A carton on the all-clear message would make no sense.
        self.assertIn(art.choose("allclear", item="milk"),
                      art.MOMENT_ART["allclear"])

    # --- never twice running ---

    def test_a_rotating_frame_never_lands_twice(self):
        # Applies to frames only: an unmatched food falls through to the
        # moment's own frames, and those are meant to surprise.
        first = art.choose("used", item="dragonfruit curd")
        second = art.choose("used", item="dragonfruit curd", avoid=first)
        self.assertNotEqual(first, second)

    def test_a_glyph_repeats_on_purpose(self):
        # This inverts the rule that applies to frames, and the inversion is the
        # point. A glyph is a label: two cartons in a row means two dairy items,
        # which is correct. If the carton dodged itself it would stop meaning
        # dairy, and the vocabulary would be worth nothing.
        again = art.choose("used", item="milk", avoid=art.CARTON)
        self.assertEqual(again, art.CARTON)

    def test_a_glyph_is_the_same_every_time(self):
        for _ in range(5):
            self.assertEqual(art.glyph("pantry"), art.CAN)
            self.assertEqual(art.for_item("chicken thighs"), art.HEN)

    def test_every_category_has_exactly_one_glyph(self):
        for key, frame in art.GLYPHS.items():
            self.assertTrue(frame.strip(), key)
        # No two categories share a drawing: a shared glyph means the
        # vocabulary cannot distinguish the things it is meant to distinguish.
        frames = list(art.GLYPHS.values())
        self.assertEqual(len(frames), len(set(frames)))

    def test_the_buckets_have_their_own_marks(self):
        self.assertEqual(art.glyph("pantry"), art.CAN)
        self.assertEqual(art.glyph("counter"), art.ONION)
        self.assertEqual(art.glyph("fridge"), art.ICEBOX)
        self.assertNotEqual(art.CAN, art.ONION)

    def test_a_single_frame_moment_repeats_rather_than_vanishing(self):
        # "welcome" has one frame. Better the same door twice than nothing:
        # onboarding only finishes once per person anyway.
        self.assertEqual(art.choose("welcome", avoid=art.ICEBOX), art.ICEBOX)

    def test_the_last_frame_is_remembered_per_chat(self):
        fridge.note_art(self.con, 1, art.CARTON)
        self.assertEqual(fridge.last_art(self.con, 1), art.CARTON)
        self.assertIsNone(fridge.last_art(self.con, 2))

    def test_noting_nothing_is_harmless(self):
        fridge.note_art(self.con, 1, None)
        self.assertIsNone(fridge.last_art(self.con, 1))

    # --- rendering ---

    def test_a_frame_renders_inside_a_pre_block(self):
        out = art.render(art.CARTON)
        self.assertTrue(out.startswith("<pre>"))
        self.assertTrue(out.endswith("</pre>"))

    def test_angle_brackets_in_a_frame_are_escaped(self):
        # Unescaped, Telegram reads them as tags and drops the drawing.
        out = art.render("<&>")
        self.assertIn("&lt;", out)
        self.assertIn("&gt;", out)
        self.assertIn("&amp;", out)
        self.assertNotIn("<&", out)

    def test_a_caption_sits_under_the_drawing(self):
        out = art.render(art.CARTON, "That one did not go to waste.")
        self.assertTrue(out.index("</pre>") < out.index("That one"))

    def test_a_food_name_cannot_break_an_html_message(self):
        # "<3 cilantro" unescaped makes Telegram read the rest as a tag and
        # silently drop it.
        out = art.render(art.CAN, "cumin & <3 cilantro")
        self.assertIn("&amp;", out)
        self.assertIn("&lt;3", out)

    def test_a_plain_message_is_not_escaped(self):
        # No pre block means no HTML, so escaping here would show the user
        # "&amp;" instead of "&".
        self.assertEqual(art.render(None, "cumin & spice"), "cumin & spice")

    def test_no_frame_means_just_the_caption(self):
        self.assertEqual(art.render(None, "Noted."), "Noted.")
        self.assertEqual(art.render(None), "")

    # --- milestones stay rare ---

    def test_milestones_are_held_back(self):
        import bot
        self.assertNotIn(1, bot.MILESTONES)
        self.assertNotIn(2, bot.MILESTONES)
        self.assertIn(10, bot.MILESTONES)
        # Sparse enough that they stay special: no two within 10 of each other
        # after the first.
        gaps = [b - a for a, b in zip(bot.MILESTONES, bot.MILESTONES[1:])]
        self.assertTrue(all(g >= 10 for g in gaps), gaps)

    def test_used_items_are_counted_for_milestones(self):
        for name in ("milk", "spinach", "yogurt"):
            fridge.add_items(self.con, 1, [name], TODAY)
        for i in fridge.open_items(self.con, 1):
            fridge.close_item(self.con, 1, i["id"], "used")
        self.assertEqual(fridge.count_closed(self.con, 1, "used"), 3)
        self.assertEqual(fridge.count_closed(self.con, 1, "tossed"), 0)

    def test_a_toss_does_not_count_toward_a_milestone(self):
        fridge.add_items(self.con, 1, ["spinach"], TODAY)
        item = fridge.open_items(self.con, 1)[0]
        fridge.close_item(self.con, 1, item["id"], "tossed")
        self.assertEqual(fridge.count_closed(self.con, 1, "used"), 0)



if __name__ == "__main__":
    unittest.main(verbosity=2)
