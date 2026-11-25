"""cogs 가 로드되고 슬래시 명령어가 디스코드 규칙에 맞게 등록되는지 확인."""
import unittest
from types import SimpleNamespace

import discord
from discord.ext import commands


class LoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_register(self):
        bot = commands.Bot(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        bot.cfg = SimpleNamespace()
        await bot.load_extension("cogs.accounts")
        await bot.load_extension("cogs.stats")
        names = {c.name for c in bot.tree.get_commands()}
        self.assertEqual(names, {"계정추가", "계정삭제", "계정목록", "알림설정", "전적"})
        # 관리자 전용 명령어는 기본 권한이 administrator
        by = {c.name: c for c in bot.tree.get_commands()}
        self.assertTrue(by["계정추가"].default_permissions.administrator)
        self.assertTrue(by["계정삭제"].default_permissions.administrator)
        payload = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
        self.assertEqual(len(payload), 5)
        await bot.close()


if __name__ == "__main__":
    unittest.main()
