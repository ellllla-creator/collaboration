import os
import random
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("LUNCH_OFFLINE", "1")
os.environ["LUNCH_DB_PATH"] = ":memory:"

from lunch_roulette import app as bot  # noqa: E402
from lunch_roulette.db import Store  # noqa: E402
from lunch_roulette.pairing import make_groups  # noqa: E402

MONDAY = date(2026, 10, 19)
WEDNESDAY = date(2026, 10, 21)


class PairingTest(unittest.TestCase):
    def test_even_count_makes_pairs(self):
        groups = make_groups(list("abcdef"), rng=random.Random(1))
        self.assertEqual(sorted(len(g) for g in groups), [2, 2, 2])
        self.assertEqual(sorted(u for g in groups for u in g), list("abcdef"))

    def test_odd_count_makes_one_trio(self):
        groups = make_groups(list("abcde"), rng=random.Random(1))
        self.assertEqual(sorted(len(g) for g in groups), [2, 3])

    def test_too_few_people(self):
        self.assertEqual(make_groups([]), [])
        self.assertEqual(make_groups(["a"]), [])

    def test_avoids_recent_partners(self):
        recent = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}
        for seed in range(20):
            groups = make_groups(list("abcd"), recent, random.Random(seed))
            self.assertNotIn(["a", "b"], [sorted(g) for g in groups])
            self.assertNotIn(["c", "d"], [sorted(g) for g in groups])


class StoreTest(unittest.TestCase):
    def test_optins_and_history(self):
        s = Store(":memory:")
        s.set_days("U1", {"mon", "thu"})
        s.set_days("U2", {"mon"})
        self.assertEqual(s.participants_for("mon"), ["U1", "U2"])
        self.assertEqual(s.participants_for("thu"), ["U1"])
        s.set_days("U1", set())
        self.assertEqual(s.participants_for("mon"), ["U2"])

        self.assertTrue(s.record_run(MONDAY, [["U1", "U2"]]))
        self.assertFalse(s.record_run(MONDAY, [["U1", "U2"]]))  # no double send
        self.assertEqual(s.recent_partners(MONDAY), {"U1": {"U2"}, "U2": {"U1"}})


class RunPairingTest(unittest.TestCase):
    def setUp(self):
        bot.store = Store(":memory:")
        self.client = mock.patch.object(bot.app, "_client").start()
        self.addCleanup(mock.patch.stopall)

    def sent(self):
        return {
            c.kwargs["channel"]: c.kwargs["text"]
            for c in self.client.chat_postMessage.call_args_list
        }

    def test_sends_each_person_their_partner(self):
        for u in ["U1", "U2", "U3"]:
            bot.store.set_days(u, {"mon"})
        bot.store.set_days("U4", {"tue"})  # not in on Monday

        groups = bot.run_pairing(MONDAY)

        self.assertEqual(len(groups), 1)  # trio
        msgs = self.sent()
        self.assertEqual(set(msgs), {"U1", "U2", "U3"})
        self.assertIn("you are paired up with <@", msgs["U1"])
        self.assertIn("for lunch today", msgs["U1"])
        for partner in ("<@U2>", "<@U3>"):
            self.assertIn(partner, msgs["U1"])
        self.assertNotIn("<@U1>", msgs["U1"])

        self.client.chat_postMessage.reset_mock()
        bot.run_pairing(MONDAY)  # second run same day sends nothing
        self.client.chat_postMessage.assert_not_called()

    def test_skips_non_roulette_days(self):
        bot.store.set_days("U1", {"mon", "tue", "thu"})
        bot.store.set_days("U2", {"mon", "tue", "thu"})
        self.assertEqual(bot.run_pairing(WEDNESDAY), [])
        self.client.chat_postMessage.assert_not_called()

    def test_lone_participant_is_told(self):
        bot.store.set_days("U1", {"mon"})
        bot.run_pairing(MONDAY)
        self.assertIn("not enough people", self.sent()["U1"])


class CommandTest(unittest.TestCase):
    def setUp(self):
        bot.store = Store(":memory:")

    def run_cmd(self, text):
        respond = mock.Mock()
        bot.on_command(mock.Mock(), {"user_id": "U1", "text": text}, mock.Mock(), respond)
        return respond.call_args.args[0]

    def test_join_leave_status(self):
        self.assertIn("Monday, Tuesday, Thursday", self.run_cmd("join"))
        self.assertIn("Monday, Thursday", self.run_cmd("leave tue"))
        self.assertIn("mon, tue, thu", self.run_cmd("join fri"))
        self.assertIn("not signed up", self.run_cmd("leave"))
        self.assertIn("/lunch-roulette join", self.run_cmd(""))


if __name__ == "__main__":
    unittest.main()
