from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from services.notifier import Notifier
from utils.embeds import build_daily_embed, deeplol_view
from utils.queues import queue_allowed

log = logging.getLogger(__name__)


class Reporter(Notifier):
    """매일 23:59:59 (설정한 시간대)에 하루 요약을 보낸다."""

    def __init__(self, bot):
        super().__init__(bot)
        self.tz = ZoneInfo(bot.cfg.timezone)

    async def run(self) -> None:
        await self.bot.wait_until_ready()
        log.info("일일 요약 스케줄러 시작 (%s 23:59:59)", self.bot.cfg.timezone)
        while True:
            now = datetime.now(self.tz)
            target = now.replace(hour=23, minute=59, second=59, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                await self.send_reports(target.date())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("일일 요약 전송 오류")
            await asyncio.sleep(2)

    async def send_reports(self, day: date) -> None:
        start = int(datetime(day.year, day.month, day.day, tzinfo=self.tz).timestamp())
        end = start + 86400
        db, dd = self.bot.db, self.bot.ddragon

        for acc in await db.get_all_accounts():
            if not acc["notify_daily"]:
                continue
            rows = [r for r in await db.results_between(acc["id"], start, end)
                    if r["result"] != "remake" and queue_allowed(r["queue_id"], acc["queue_filter"])]
            if not rows:
                continue
            if not await db.mark_daily_sent(acc["id"], day.isoformat()):
                continue  # 이미 보냈음

            wins = sum(r["result"] == "win" for r in rows)
            losses = len(rows) - wins
            lps = [r["lp_delta"] for r in rows if r["lp_delta"] is not None]
            embed = build_daily_embed(acc, day.isoformat(), wins, losses,
                                      sum(lps) if lps else None,
                                      Counter(r["champion_id"] for r in rows), dd)
            await self._send(acc, embed=embed, view=deeplol_view(acc["game_name"], acc["tag_line"]))
