from __future__ import annotations

import discord
from discord import app_commands

from services.riot_api import RiotError


def is_admin(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator


def parse_riot_id(text: str) -> tuple[str, str] | None:
    """'닉네임#태그' -> (닉네임, 태그). 형식이 틀리면 None."""
    name, sep, tag = text.strip().rpartition("#")
    name, tag = name.strip(), tag.strip()
    if not sep or not name or not tag or len(name) > 32 or len(tag) > 10:
        return None
    return name, tag


async def account_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []
    accounts = await interaction.client.db.get_guild_accounts(interaction.guild_id)
    cur = current.lower()
    return [
        app_commands.Choice(name=f"{a['game_name']}#{a['tag_line']}"[:100], value=str(a["id"]))
        for a in accounts
        if cur in f"{a['game_name']}#{a['tag_line']}".lower()
    ][:25]


async def find_account(interaction: discord.Interaction, text: str) -> dict | None:
    """자동완성 값(계정 id) 또는 '닉네임#태그' 직접 입력으로 이 서버의 등록 계정을 찾는다."""
    db = interaction.client.db
    text = text.strip()
    if text.isdigit():
        acc = await db.get_account(int(text))
        return acc if acc and acc["guild_id"] == interaction.guild_id else None
    parsed = parse_riot_id(text)
    if not parsed:
        return None
    name, tag = parsed[0].lower(), parsed[1].lower()
    for a in await db.get_guild_accounts(interaction.guild_id):
        if a["game_name"].lower() == name and a["tag_line"].lower() == tag:
            return a
    return None


def riot_error_message(e: RiotError) -> str:
    from services.riot_api import RiotAuthError
    if isinstance(e, RiotAuthError):
        return "Riot API 키가 만료되었거나 올바르지 않아요. 봇 관리자가 키를 갱신해야 합니다."
    return f"Riot 서버 조회에 실패했어요. 잠시 후 다시 시도해 주세요. ({e.status})"
