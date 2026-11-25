"""네트워크/디스코드 없이 감시 → 종료 → 일일 요약 흐름을 가짜 객체로 검증한다."""
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from db.database import Database
from services.reporter import Reporter
from services.riot_api import RiotError
from services.tracker import Tracker

PUUID = "puuid-1"


class FakeDD:
    async def ensure(self, cid):
        pass

    def name(self, cid):
        return {103: "아리"}.get(cid, f"챔피언 {cid}")

    def icon(self, cid):
        return "https://example.com/icon.png"


class FakeRiot:
    def __init__(self):
        self.game = None
        self.entries = []
        self.match = None

    async def get_active_game(self, puuid):
        if puuid == "old-puuid":   # 예전 키로 저장된 PUUID
            raise RiotError(400, "Bad Request - Exception decrypting abc")
        return self.game

    async def get_account(self, name, tag):
        return {"puuid": PUUID, "gameName": name, "tagLine": tag}

    async def check_key(self):
        return None

    async def get_league_entries(self, puuid):
        return self.entries

    async def get_match(self, match_id):
        return self.match

    async def get_account_by_puuid(self, puuid):
        return {"gameName": "Tester", "tagLine": "KR1"}


def solo(tier, rank, lp):
    return [{"queueType": "RANKED_SOLO_5x5", "tier": tier, "rank": rank, "leaguePoints": lp}]


def make_game(game_id, queue_id=420):
    return {"gameId": game_id, "gameQueueConfigId": queue_id, "gameStartTime": int(time.time() * 1000),
            "participants": [{"puuid": PUUID, "championId": 103}, {"puuid": "x", "championId": 1}]}


def make_match(win, queue_id=420, duration=1800):
    return {"info": {"queueId": queue_id, "gameDuration": duration,
                     "gameEndTimestamp": int(time.time() * 1000),
                     "participants": [{"puuid": PUUID, "championId": 103, "win": win, "kills": 8, "deaths": 2,
                                       "assists": 10, "totalMinionsKilled": 200, "neutralMinionsKilled": 10,
                                       "totalDamageDealtToChampions": 25000}]}}


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.connect()
        self.riot = FakeRiot()
        cfg = SimpleNamespace(poll_interval=45, timezone="Asia/Seoul", category_name="롤 알림")
        bot = SimpleNamespace(db=self.db, riot=self.riot, ddragon=FakeDD(), cfg=cfg)
        self.sent = []

        async def fake_send(self_, acc, *, embed, view=None, mention=False):
            self.sent.append((embed, view, mention))

        Tracker._send = fake_send
        Reporter._send = fake_send
        self.tracker, self.reporter = Tracker(bot), Reporter(bot)
        acc_id = await self.db.add_account(1, 10, PUUID, "Tester", "KR1", 99)
        self.acc_id = acc_id

    async def asyncTearDown(self):
        await self.db.close()

    async def play(self, game_id, win, before, after, queue_id=420):
        self.riot.game = make_game(game_id, queue_id)
        self.riot.entries = before
        await self.tracker.poll_all()
        self.riot.game = None
        self.riot.match = make_match(win, queue_id)
        self.riot.entries = after
        await self.tracker.poll_all()

    async def test_full_flow(self):
        await self.db.update_settings(self.acc_id, mention_role_id=555)

        # 시작
        self.riot.game = make_game(1)
        self.riot.entries = solo("GOLD", "II", 47)
        await self.tracker.poll_all()
        self.assertEqual(len(self.sent), 1)
        start = self.sent[0][0]
        self.assertIn("게임을 시작", start.title)
        self.assertEqual([f.value for f in start.fields][:3], ["솔로랭크", "아리", "골드 II 47LP"])
        self.assertTrue(self.sent[0][2])                       # 멘션 대상
        self.assertEqual(self.sent[0][1].children[0].label, "딥롤에서 보기")

        await self.tracker.poll_all()                           # 같은 게임 - 중복 알림 없음
        self.assertEqual(len(self.sent), 1)

        # 종료 직후 매치가 아직 없음 -> 대기
        self.riot.game = None
        await self.tracker.poll_all()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((await self.db.get_active(self.acc_id))["attempts"], 1)

        # 매치는 왔지만 LP가 아직 안 바뀜 -> 대기
        self.riot.match = make_match(True)
        await self.tracker.poll_all()
        self.assertEqual(len(self.sent), 1)

        # LP 반영 -> 종료 알림
        self.riot.entries = solo("GOLD", "II", 65)
        await self.tracker.poll_all()
        self.assertEqual(len(self.sent), 2)
        end = self.sent[1][0]
        self.assertIn("승리", end.title)
        fields = {f.name: f.value for f in end.fields}
        self.assertIn("+18 LP", fields["LP 변동"])
        self.assertEqual(fields["KDA"], "8 / 2 / 10  (9.00:1)")
        self.assertEqual(fields["게임 시간"], "30분 00초")
        self.assertEqual(fields["현재 티어"], "골드 II 65LP")
        self.assertNotIn("연속 기록", fields)
        self.assertFalse(self.sent[1][2])
        self.assertIsNone(await self.db.get_active(self.acc_id))

        # 두 번째 게임 승리 -> 2연승
        await self.play(2, True, solo("GOLD", "II", 65), solo("GOLD", "II", 84))
        fields = {f.name: f.value for f in self.sent[-1][0].fields}
        self.assertEqual(fields["연속 기록"], "🔥 2연승 중")

        # 세 번째 게임 패배 -> 연패 표시 없음, 마이너스 LP
        await self.play(3, False, solo("GOLD", "II", 84), solo("GOLD", "II", 66))
        end = self.sent[-1][0]
        self.assertIn("패배", end.title)
        self.assertIn("-18 LP", {f.name: f.value for f in end.fields}["LP 변동"])

        # 일일 요약
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        before = len(self.sent)
        await self.reporter.send_reports(today)
        self.assertEqual(len(self.sent), before + 1)
        daily = self.sent[-1][0]
        f = {x.name: x.value for x in daily.fields}
        self.assertIn("2승 1패", f["전적"])
        self.assertEqual(f["총 LP 변동"], "+19 LP")
        self.assertIn("아리 ×3", f["플레이한 챔피언"])

        await self.reporter.send_reports(today)                 # 중복 전송 방지
        self.assertEqual(len(self.sent), before + 1)

    async def test_stale_puuid_is_repaired(self):
        """키를 바꿔 PUUID가 안 맞으면 닉네임#태그로 다시 조회해서 고치고 계속 동작한다."""
        old_id = await self.db.add_account(2, 20, "old-puuid", "Old", "KR1", 1)
        self.riot.game = make_game(5)
        self.riot.entries = solo("GOLD", "II", 10)
        await self.tracker.poll_all()
        self.assertEqual((await self.db.get_account(old_id))["puuid"], PUUID)
        self.assertGreaterEqual(len(self.sent), 2)             # 두 계정 모두 시작 알림

    async def test_remake_and_filter(self):
        await self.db.update_settings(self.acc_id, queue_filter="solo")
        await self.play(10, False, [], [], queue_id=450)         # 칼바람: 필터로 알림 안 감
        self.assertEqual(self.sent, [])
        # 그래도 기록은 저장됨
        rows = await self.db.results_between(self.acc_id, 0, 2 ** 40)
        self.assertEqual(len(rows), 1)

        await self.db.update_settings(self.acc_id, queue_filter="all")
        self.riot.game = make_game(11)
        self.riot.entries = solo("GOLD", "II", 50)
        await self.tracker.poll_all()
        self.riot.game = None
        self.riot.match = make_match(False, duration=200)       # 3분 컷 = 다시하기
        await self.tracker.poll_all()
        end = self.sent[-1][0]
        self.assertIn("다시하기", end.title)
        self.assertNotIn("LP 변동", [f.name for f in end.fields])


if __name__ == "__main__":
    unittest.main()
