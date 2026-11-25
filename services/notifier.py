from __future__ import annotations

import logging

import discord

from utils.channels import create_alert_channel

log = logging.getLogger(__name__)


class Notifier:
    """계정의 알림 채널로 임베드를 보내는 공통 기능."""

    def __init__(self, bot):
        self.bot = bot

    async def _get_channel(self, acc: dict):
        ch = self.bot.get_channel(acc["channel_id"])
        if ch:
            return ch
        try:
            return await self.bot.fetch_channel(acc["channel_id"])
        except discord.NotFound:
            # 채널이 수동으로 삭제된 경우 다시 만든다
            guild = self.bot.get_guild(acc["guild_id"])
            if not guild:
                return None
            try:
                ch = await create_alert_channel(guild, self.bot.cfg.category_name,
                                                acc["game_name"], acc["tag_line"])
            except discord.HTTPException:
                log.warning("알림 채널 재생성 실패 (계정 %s)", acc["id"])
                return None
            await self.bot.db.update_channel(acc["id"], ch.id)
            acc["channel_id"] = ch.id
            log.info("삭제된 알림 채널을 다시 만들었습니다 (계정 %s)", acc["id"])
            return ch
        except discord.HTTPException:
            return None

    async def _send(self, acc: dict, *, embed: discord.Embed, view: discord.ui.View | None = None,
                    mention: bool = False) -> None:
        ch = await self._get_channel(acc)
        if ch is None:
            log.warning("알림 채널을 찾을 수 없어 전송하지 못했습니다 (계정 %s)", acc["id"])
            return
        content = None
        allowed = discord.AllowedMentions.none()
        role_id = acc.get("mention_role_id")
        if mention and role_id:
            content = f"<@&{role_id}>"
            allowed = discord.AllowedMentions(roles=[discord.Object(id=role_id)])
        try:
            await ch.send(content=content, embed=embed, view=view, allowed_mentions=allowed)
        except discord.HTTPException as e:
            log.warning("알림 전송 실패 (계정 %s): %s", acc["id"], e)
