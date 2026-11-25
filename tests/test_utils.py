import unittest

from utils.embeds import deeplol_url, streak_text
from utils.lp import format_delta, format_tier, lp_delta, snapshot_entries
from utils.queues import queue_allowed, queue_name


def e(tier, rank, lp):
    return {"tier": tier, "rank": rank, "lp": lp}


class LpTests(unittest.TestCase):
    def test_same_division(self):
        self.assertEqual(lp_delta(e("GOLD", "II", 47), e("GOLD", "II", 65)), 18)
        self.assertEqual(lp_delta(e("GOLD", "II", 47), e("GOLD", "II", 28)), -19)

    def test_promotion_and_demotion(self):
        self.assertEqual(lp_delta(e("GOLD", "II", 90), e("GOLD", "I", 12)), 22)
        self.assertEqual(lp_delta(e("GOLD", "IV", 5), e("SILVER", "I", 80)), -25)
        self.assertEqual(lp_delta(e("EMERALD", "I", 95), e("DIAMOND", "IV", 10)), 15)

    def test_apex(self):
        self.assertEqual(lp_delta(e("DIAMOND", "I", 80), e("MASTER", "I", 20)), 40)
        self.assertEqual(lp_delta(e("MASTER", "I", 300), e("GRANDMASTER", "I", 290)), -10)

    def test_format(self):
        self.assertEqual(format_tier(None), "언랭크")
        self.assertEqual(format_tier(e("GOLD", "II", 47)), "골드 II 47LP")
        self.assertEqual(format_tier(e("MASTER", "I", 120)), "마스터 120LP")
        self.assertEqual(format_delta(18), "+18 LP")
        self.assertEqual(format_delta(-19), "-19 LP")
        self.assertEqual(format_delta(0), "±0 LP")

    def test_snapshot(self):
        snap = snapshot_entries([
            {"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II", "leaguePoints": 47},
            {"queueType": "RANKED_TFT", "tier": "IRON", "rank": "I", "leaguePoints": 1},
        ])
        self.assertEqual(snap, {"RANKED_SOLO_5x5": e("GOLD", "II", 47)})


class MiscTests(unittest.TestCase):
    def test_queue(self):
        self.assertEqual(queue_name(420), "솔로랭크")
        self.assertEqual(queue_name(440), "자유랭크")
        self.assertTrue(queue_allowed(420, "solo"))
        self.assertFalse(queue_allowed(440, "solo"))
        self.assertTrue(queue_allowed(440, "ranked"))
        self.assertFalse(queue_allowed(450, "rift"))
        self.assertTrue(queue_allowed(450, "all"))

    def test_streak(self):
        self.assertIsNone(streak_text([]))
        self.assertIsNone(streak_text(["win", "loss"]))
        self.assertEqual(streak_text(["win", "win", "win", "loss"]), "🔥 3연승 중")
        self.assertEqual(streak_text(["loss", "loss"]), "🥶 2연패 중")

    def test_deeplol(self):
        self.assertEqual(deeplol_url("Hide on bush", "KR1"),
                         "https://www.deeplol.gg/summoner/kr/Hide%20on%20bush-KR1")


if __name__ == "__main__":
    unittest.main()
