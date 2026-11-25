from __future__ import annotations

import asyncio
import logging

import aiohttp
import discord
from discord.ext import commands

from config import Config, load_config
from db.database import Database
from services.ddragon import DDragon
from services.reporter import Reporter
from services.riot_api import RiotClient
from services.tracker import Tracker

log = logging.getLogger("lol-alert-bot")


class LolAlertBot(commands.Bot):
    def __init__(self, cfg: Config):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.cfg = cfg
        self._bg_tasks: list[asyncio.Task] = []

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.db = Database(self.cfg.db_path)
        await self.db.connect()
        self.riot = RiotClient(self.session, self.cfg.riot_api_key)
        self.ddragon = DDragon(self.session)
        try:
            await self.ddragon.load()
        except Exception as e:  # noqa: BLE001
            log.warning("Data Dragon 로드 실패 (챔피언 이름이 숫자로 표시될 수 있음): %s", e)

        await self.load_extension("cogs.accounts")
        await self.load_extension("cogs.stats")

        if self.cfg.dev_guild_id:
            guild = discord.Object(id=self.cfg.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("슬래시 명령어를 개발 서버(%s)에 등록했습니다.", self.cfg.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("슬래시 명령어를 전역 등록했습니다. (반영까지 최대 1시간)")

        self.tracker = Tracker(self)
        self.reporter = Reporter(self)
        self._bg_tasks = [asyncio.create_task(self.tracker.run()), asyncio.create_task(self.reporter.run())]

    async def on_ready(self) -> None:
        log.info("로그인: %s (서버 %d개)", self.user, len(self.guilds))

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        await self.db.delete_guild_accounts(guild.id)
        log.info("서버 %s 에서 제거되어 등록된 계정을 정리했습니다.", guild.id)

    async def close(self) -> None:
        for t in self._bg_tasks:
            t.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        if hasattr(self, "session"):
            await self.session.close()
        if hasattr(self, "db"):
            await self.db.close()
        await super().close()


def main() -> None:
    cfg = load_config()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = LolAlertBot(cfg)
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
