import unittest

from utils.performance import analyze, luck_label

POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def player(pid, team, pos, win, k, d, a, dmg=15000, gold=10000, cs=150, vision=20, played=1800):
    return {"puuid": pid, "teamId": team, "teamPosition": pos, "win": win, "kills": k, "deaths": d,
            "assists": a, "totalDamageDealtToChampions": dmg, "goldEarned": gold,
            "totalMinionsKilled": cs, "neutralMinionsKilled": 0, "visionScore": vision, "timePlayed": played}


def make(me_stats, ally_stats, enemy_stats, win=True, ally_played=1800):
    parts = [player("me", 100, "MIDDLE", win, *me_stats)]
    for i, s in enumerate(ally_stats):
        parts.append(player(f"a{i}", 100, POS[(i + (i >= 2)) % 5] if i < 4 else "TOP", win, *s,
                            played=ally_played if i == 0 else 1800))
    for i, s in enumerate(enemy_stats):
        parts.append(player(f"e{i}", 200, POS[i], not win, *s))
    return {"info": {"participants": parts}}


class PerformanceTests(unittest.TestCase):
    def test_carry_gets_high_score_and_first_rank(self):
        m = make((15, 2, 8), [(3, 5, 8)] * 4, [(5, 5, 6)] * 5)
        r = analyze(m, "me", 1800)
        self.assertEqual(r["rank"], 1)
        self.assertEqual(r["badge"], "MVP")
        self.assertTrue(0 <= r["score"] <= 100)
        self.assertGreater(r["score"], 60)

    def test_feeder_is_last_and_gets_no_badge(self):
        m = make((0, 12, 1), [(6, 3, 8)] * 4, [(5, 5, 6)] * 5)
        r = analyze(m, "me", 1800)
        self.assertEqual(r["rank"], 10)
        self.assertIsNone(r["badge"])
        self.assertLess(r["score"], 40)

    def test_losing_team_best_is_ace(self):
        m = make((15, 2, 8), [(2, 8, 3)] * 4, [(8, 4, 8)] * 5, win=False)
        self.assertEqual(analyze(m, "me", 1800)["badge"], "ACE")

    def test_luck_levels(self):
        self.assertEqual([luck_label(x) for x in (-30, -10, 0, 10, 30)],
                         ["극악", "나쁨", "보통", "좋음", "버스"])

    def test_bad_allies_in_a_loss_are_worse_luck_than_good_allies(self):
        bad = analyze(make((8, 6, 6), [(0, 10, 1)] * 4, [(9, 3, 9)] * 5, win=False), "me", 1800)
        good = analyze(make((8, 6, 6), [(8, 5, 9)] * 4, [(7, 5, 7)] * 5, win=False), "me", 1800)
        self.assertLess(bad["luck_diff"], good["luck_diff"])
        self.assertIn(bad["luck"], ("극악", "나쁨"))

    def test_leaver_ally_hurts_luck(self):
        stats = ([(8, 4, 8)] * 4, [(8, 4, 8)] * 5)
        normal = analyze(make((8, 4, 8), *stats), "me", 1800)
        leaver = analyze(make((8, 4, 8), *stats, ally_played=300), "me", 1800)
        self.assertEqual(leaver["leavers"]["ally"], 1)
        self.assertLess(leaver["luck_diff"], normal["luck_diff"])

    def test_non_5v5_returns_none(self):
        self.assertIsNone(analyze({"info": {"participants": [player("me", 100, "TOP", True, 1, 1, 1)]}},
                                  "me", 1800))

    def test_aram_without_positions_works(self):
        m = make((10, 3, 10), [(5, 5, 5)] * 4, [(5, 5, 5)] * 5)
        for p in m["info"]["participants"]:
            p["teamPosition"] = ""
        r = analyze(m, "me", 1200)
        self.assertEqual(r["rank"], 1)


if __name__ == "__main__":
    unittest.main()
