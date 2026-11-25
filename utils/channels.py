from __future__ import annotations

import discord


async def create_alert_channel(guild: discord.Guild, category_name: str, game_name: str,
                               tag_line: str) -> discord.TextChannel:
    """'롤 알림' 카테고리 아래에 계정 전용 채널을 만든다. 카테고리가 가득 차면 카테고리 없이 만든다."""
    category = discord.utils.get(guild.categories, name=category_name)
    if category is None:
        category = await guild.create_category(category_name, reason="롤 알림 봇")
    if len(category.channels) >= 50:
        category = None
    return await guild.create_text_channel(
        f"{game_name}-{tag_line}"[:100],
        category=category,
        topic=f"{game_name}#{tag_line} 의 롤 게임 알림",
        reason="롤 알림 봇: 계정 추가",
    )
