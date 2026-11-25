from __future__ import annotations

import asyncio
import json
import logging
import time

from services.notifier import Notifier
from services.riot_api import RiotAuthError, RiotError
from utils.embeds import build_end_embed, build_start_embed, deeplol_view, streak_text
from utils.lp import format_delta, format_tier, lp_delta, snapshot_entries
from utils.queues import RANKED_QUEUES, queue_allowed

log = logging.getLogger(__name__)

MAX_MATCH_RETRIES = 40   # 매치 데이터가 안 올라올 때 (약 30분) 포기
MAX_LP_RETRIES = 3       # LP 반영이 늦을 때 추가로 기다리는 횟수
REMAKE_SECONDS = 300


def tier_for_queue(snapshot: dict | None, queue_id: int) -> str:
    snapshot = snapshot or {}
    key = RANKED_QUEUES.get(queue_id, "RANKED_SOLO_5x5")
    return format_tier(snapshot.get(key))


class Tracker(Notifier):
    def __init__(self, bot):
        super().__init__(bot)
        self._auth_warned = False

    # ---- 루프 ----
    async def run(self) -> None:
        await self.bot.wait_until_ready()
        log.info("게임 감시를 시작합니다 (간격 %d초)", self.bot.cfg.poll_interval)
        while True:
            try:
                await self.poll_all()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("감시 루프 오류")
            await asyncio.sleep(self.bot.cfg.poll_interval)

    async def poll_all(self) -> None:
        for acc in await self.bot.db.get_all_accounts():
            try:
                await self.poll_account(acc)
                self._auth_warned = False
            except RiotAuthError:
                if not self._auth_warned:
                    log.error("Riot API 키가 만료되었거나 올바르지 않습니다. .env 의 RIOT_API_KEY 를 갱신하고 재시작하세요.")
                    self._auth_warned = True
                return
            except RiotError as e:
                log.warning("계정 %s 조회 실패: %s", acc["id"], e)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("계정 %s 처리 중 오류", acc["id"])

    # ---- 계정 하나 ----
    async def poll_account(self, acc: dict) -> None:
        db, riot = self.bot.db, self.bot.riot
        active = await db.get_active(acc["id"])
        game = await riot.get_active_game(acc["puuid"])

        if game:
            if active and active["game_id"] != game["gameId"]:
                # 이전 게임 결과를 못 받은 채 새 게임이 시작된 경우
                await self.finalize(acc, active)
                active = await db.get_active(acc["id"])
                if active:
                    log.warning("계정 %s: 이전 게임 결과를 받지 못하고 새 게임으로 넘어갑니다.", acc["id"])
                    await db.delete_active(acc["id"])
                    active = None
            if not active:
                await self.on_start(acc, game)
        elif active:
            await self.finalize(acc, active)

    # ---- 게임 시작 ----
    async def on_start(self, acc: dict, game: dict) -> None:
        db, riot, dd = self.bot.db, self.bot.riot, self.bot.ddragon
        me = next((p for p in game.get("participants", []) if p.get("puuid") == acc["puuid"]), None)
        if me is None:
            return
        queue_id = game.get("gameQueueConfigId", 0) or 0
        champion_id = me["championId"]
        start_ts = int(game.get("gameStartTime", 0) / 1000) or int(time.time())
        await dd.ensure(champion_id)

        try:
            snapshot = snapshot_entries(await riot.get_league_entries(acc["puuid"]))
        except RiotAuthError:
            raise
        except RiotError:
            snapshot = None

        # 알림 전에 먼저 저장해서 전송이 실패해도 중복 알림이 가지 않게 한다
        await db.set_active(acc["id"], game["gameId"], queue_id, champion_id, start_ts,
                            json.dumps(snapshot) if snapshot is not None else None)

        if acc["notify_start"] and queue_allowed(queue_id, acc["queue_filter"]):
            embed = build_start_embed(acc, queue_id, champion_id, start_ts,
                                      tier_for_queue(snapshot, queue_id), dd)
            await self._send(acc, embed=embed, view=deeplol_view(acc["game_name"], acc["tag_line"]),
                             mention=True)

    # ---- 게임 종료 ----
    async def finalize(self, acc: dict, active: dict) -> None:
        db, riot, dd = self.bot.db, self.bot.riot, self.bot.ddragon

        match = await riot.get_match(f"KR_{active['game_id']}")
        if match is None:
            if active["attempts"] + 1 >= MAX_MATCH_RETRIES:
                log.warning("계정 %s: 게임 %s 결과를 가져오지 못해 포기합니다.", acc["id"], active["game_id"])
                await db.delete_active(acc["id"])
            else:
                await db.bump_attempts(acc["id"])
            return

        info = match["info"]
        p = next((x for x in info["participants"] if x["puuid"] == acc["puuid"]), None)
        if p is None:
            await db.delete_active(acc["id"])
            return

        queue_id = info.get("queueId") or active["queue_id"]
        duration = int(info.get("gameDuration", 0))
        if duration > 100000:  # 아주 오래된 매치는 밀리초 단위
            duration //= 1000
        remake = bool(p.get("gameEndedInEarlySurrender")) or duration < REMAKE_SECONDS
        result = "remake" if remake else ("win" if p.get("win") else "loss")

        # 현재 티어 / LP 변동
        before_snap = json.loads(active["start_entries"]) if active["start_entries"] else None
        after_snap = None
        fetch_failed = False
        try:
            after_snap = snapshot_entries(await riot.get_league_entries(acc["puuid"]))
        except RiotAuthError:
            raise
        except RiotError:
            fetch_failed = True

        ranked_key = RANKED_QUEUES.get(queue_id)
        delta = None
        lp_detail = None
        if ranked_key and not remake:
            before = (before_snap or {}).get(ranked_key)
            after = (after_snap or {}).get(ranked_key)
            if before and after:
                delta = lp_delta(before, after)
            stale = fetch_failed or (before is not None and before == after)
            if stale and active["lp_retries"] < MAX_LP_RETRIES:
                await db.bump_lp_retries(acc["id"])   # LP 반영이 늦는 중 - 다음 감시 때 다시 시도
                return
            if delta is not None:
                lp_detail = f"**{format_delta(delta)}**  ({format_tier(before)} → {format_tier(after)})"
            else:
                lp_detail = "변동 정보를 가져오지 못했어요 (배치게임이거나 조회 실패)"

        await dd.ensure(p["championId"])
        row = {
            "game_id": active["game_id"],
            "queue_id": queue_id,
            "champion_id": p["championId"],
            "result": result,
            "kills": p.get("kills", 0),
            "deaths": p.get("deaths", 0),
            "assists": p.get("assists", 0),
            "cs": p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0),
            "damage": p.get("totalDamageDealtToChampions", 0),
            "duration": duration,
            "placement": p.get("placement") if p.get("placement") else None,
            "lp_delta": delta,
            "ended_ts": int(info["gameEndTimestamp"] / 1000) if info.get("gameEndTimestamp") else int(time.time()),
        }
        added = await db.add_result(acc["id"], row)
        await db.delete_active(acc["id"])
        if not added:
            return

        await self._refresh_riot_id(acc)

        if acc["notify_end"] and queue_allowed(queue_id, acc["queue_filter"]):
            streak = streak_text(await db.recent_results(acc["id"], queue_id))
            tier_text = tier_for_queue(after_snap, queue_id) if after_snap is not None \
                else tier_for_queue(before_snap, queue_id)
            embed = build_end_embed(acc, row, dd, tier_text, lp_detail, streak)
            await self._send(acc, embed=embed, view=deeplol_view(acc["game_name"], acc["tag_line"]))

    async def _refresh_riot_id(self, acc: dict) -> None:
        """닉네임/태그가 바뀌었으면 DB에 반영 (실패해도 무시)."""
        try:
            data = await self.bot.riot.get_account_by_puuid(acc["puuid"])
        except RiotError:
            return
        if data and (data.get("gameName"), data.get("tagLine")) != (acc["game_name"], acc["tag_line"]):
            await self.bot.db.update_riot_id(acc["puuid"], data["gameName"], data["tagLine"])
            acc["game_name"], acc["tag_line"] = data["gameName"], data["tagLine"]
