import unittest

from db.database import Database
from services.duo import backfill, detect_party, record_teammates
from utils.embeds import party_text

ME = "me"


def make_match(game_id, mates, ended=1000, queue=420):
    """me + 같은 팀 4명(mates) + 적 5명"""
    parts = [{"puuid": ME, "teamId": 100}]
    for m in mates:
        parts.append({"puuid": m, "teamId": 100, "riotIdGameName": f"N-{m}", "riotIdTagline": "KR1"})
    parts += [{"puuid": f"e{i}", "teamId": 200} for i in range(5)]
    return {"info": {"gameId": game_id, "queueId": queue, "gameEndTimestamp": ended * 1000,
                     "participants": parts}}


def make_game(mates):
    parts = [{"puuid": ME, "teamId": 100}] + [{"puuid": m, "teamId": 100, "riotId": f"X-{m}#T"} for m in mates]
    parts += [{"puuid": f"e{i}", "teamId": 200} for i in range(5)]
    return {"participants": parts}


class DuoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.connect()
        self.acc = await self.db.add_account(1, 1, ME, "Me", "KR1", 1)

    async def asyncTearDown(self):
        await self.db.close()

    async def rec(self, game_id, mates, ended=None):
        await record_teammates(self.db, self.acc, ME, make_match(game_id, mates, ended or game_id))

    async def test_third_game_is_detected_but_second_is_not(self):
        mates = ["a", "b", "c", "d"]
        await self.rec(1, mates)
        counts = await self.db.teammate_counts(self.acc)
        self.assertIsNone(detect_party(make_game(["a", "x", "y", "z"]), ME, counts, 440))   # 이번이 2판째
        await self.rec(2, mates)
        counts = await self.db.teammate_counts(self.acc)
        party = detect_party(make_game(["a", "x", "y", "z"]), ME, counts, 440)             # 이번이 3판째
        self.assertEqual([(p["name"], p["count"]) for p in party], [("N-a", 2)])

    async def test_n_stack_and_solo_queue_limit(self):
        for g in (1, 2):
            await self.rec(g, ["a", "b", "c", "d"])
        counts = await self.db.teammate_counts(self.acc)
        flex = detect_party(make_game(["a", "b", "x", "y"]), ME, counts, 440)
        self.assertEqual(len(flex), 2)
        self.assertIn("3인큐", party_text(flex))
        solo = detect_party(make_game(["a", "b", "x", "y"]), ME, counts, 420)
        self.assertEqual(len(solo), 1)
        self.assertIn("듀오", party_text(solo))

    async def test_enemy_or_stranger_is_not_party(self):
        for g in (1, 2):
            await self.rec(g, ["a", "b", "c", "d"])
        counts = await self.db.teammate_counts(self.acc)
        game = make_game(["x", "y", "z", "w"])
        game["participants"][-1]["puuid"] = "a"        # 자주 만난 사람이 이번엔 적팀
        self.assertIsNone(detect_party(game, ME, counts, 440))

    async def test_only_recent_20_games_count(self):
        for g in range(1, 4):
            await self.rec(g, ["a", "b", "c", "d"], ended=g)          # 옛날 3판
        for g in range(10, 30):
            await self.rec(g, [f"s{g}{i}" for i in range(4)], ended=g)  # 최근 20판은 매번 다른 사람
        counts = await self.db.teammate_counts(self.acc)
        self.assertNotIn("a", counts)

    async def test_duplicate_record_is_ignored(self):
        await self.rec(1, ["a", "b", "c", "d"])
        await self.rec(1, ["a", "b", "c", "d"])
        self.assertEqual((await self.db.teammate_counts(self.acc))["a"]["cnt"], 1)

    async def test_arena_is_skipped(self):
        match = {"info": {"gameId": 9, "participants": [{"puuid": ME, "teamId": 100}] * 16}}
        self.assertEqual(await record_teammates(self.db, self.acc, ME, match), 0)

    async def test_backfill(self):
        matches = {f"KR_{i}": make_match(i, ["a", "b", "c", "d"], ended=i) for i in (1, 2, 3)}

        class Riot:
            async def get_match_ids(self, puuid, count=10):
                return list(matches)

            async def get_match(self, mid):
                return matches[mid]

        self.assertEqual(await backfill(self.db, Riot(), self.acc, ME), 3)
        self.assertEqual((await self.db.teammate_counts(self.acc))["a"]["cnt"], 3)


if __name__ == "__main__":
    unittest.main()
