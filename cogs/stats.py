from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import account_autocomplete, find_account, parse_riot_id, riot_error_message
from services.riot_api import RiotError
from utils.embeds import BLUE, deeplol_view, fmt_duration
from utils.lp import format_tier, snapshot_entries
from utils.queues import queue_name


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="전적", description="최근 게임 전적을 조회합니다")
    @app_commands.describe(account="등록된 계정 선택 또는 닉네임#태그 직접 입력", count="조회할 판수 (1~10, 기본 5)")
    @app_commands.rename(account="계정", count="판수")
    @app_commands.autocomplete(account=account_autocomplete)
    @app_commands.guild_only()
    async def record(self, interaction: discord.Interaction, account: str,
                     count: app_commands.Range[int, 1, 10] = 5):
        await interaction.response.defer(thinking=True)
        riot, dd = self.bot.riot, self.bot.ddragon

        try:
            acc = await find_account(interaction, account)
            if acc:
                puuid, name, tag = acc["puuid"], acc["game_name"], acc["tag_line"]
            else:
                parsed = parse_riot_id(account)
                if not parsed:
                    return await interaction.followup.send("계정을 선택하거나 `닉네임#태그` 로 입력해 주세요.")
                data = await riot.get_account(*parsed)
                if not data:
                    return await interaction.followup.send("계정을 찾을 수 없어요.")
                puuid, name, tag = data["puuid"], data["gameName"], data["tagLine"]

            ids = await riot.get_match_ids(puuid, count)
            matches = await asyncio.gather(*(riot.get_match(m) for m in ids))
            entries = snapshot_entries(await riot.get_league_entries(puuid))
        except RiotError as e:
            return await interaction.followup.send(riot_error_message(e))

        lines, wins, losses = [], 0, 0
        for m in matches:
            if not m:
                continue
            info = m["info"]
            p = next((x for x in info["participants"] if x["puuid"] == puuid), None)
            if not p:
                continue
            duration = int(info.get("gameDuration", 0))
            if p.get("gameEndedInEarlySurrender") or duration < 300:
                emoji = "🔄"
            elif p.get("win"):
                emoji, wins = "🟦", wins + 1
            else:
                emoji, losses = "🟥", losses + 1
            await dd.ensure(p["championId"])
            cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
            ts = int(info.get("gameEndTimestamp", 0) / 1000) or int(info.get("gameCreation", 0) / 1000)
            lines.append(
                f"{emoji} **{queue_name(info.get('queueId', 0))}** · {dd.name(p['championId'])} · "
                f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)} · CS {cs} · "
                f"{fmt_duration(duration)} · <t:{ts}:R>"
            )

        e = discord.Embed(title=f"📜 {name}#{tag} 최근 전적", color=BLUE)
        e.description = "\n".join(lines) if lines else "최근 게임 기록이 없어요."
        tiers = []
        if "RANKED_SOLO_5x5" in entries:
            tiers.append(f"솔로랭크: {format_tier(entries['RANKED_SOLO_5x5'])}")
        if "RANKED_FLEX_SR" in entries:
            tiers.append(f"자유랭크: {format_tier(entries['RANKED_FLEX_SR'])}")
        e.add_field(name="현재 티어", value="\n".join(tiers) or "언랭크", inline=True)
        if wins + losses:
            e.add_field(name="요약", value=f"{wins}승 {losses}패 (승률 {round(wins / (wins + losses) * 100)}%)",
                        inline=True)
        await interaction.followup.send(embed=e, view=deeplol_view(name, tag))


async def setup(bot):
    await bot.add_cog(Stats(bot))
