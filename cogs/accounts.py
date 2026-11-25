from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs._common import (account_autocomplete, find_account, is_admin, parse_riot_id,
                          riot_error_message)
from services.riot_api import RiotError
from utils.channels import create_alert_channel
from utils.embeds import BLUE, riot_id
from utils.queues import FILTER_LABELS

log = logging.getLogger(__name__)

ADMIN_ONLY = "이 명령어는 서버 **관리자** 권한이 있는 사람만 사용할 수 있어요."


def settings_embed(acc: dict, title: str) -> discord.Embed:
    onoff = lambda v: "켜짐 ✅" if v else "꺼짐 ❌"  # noqa: E731
    e = discord.Embed(title=title, color=BLUE)
    e.add_field(name="게임 시작 알림", value=onoff(acc["notify_start"]), inline=True)
    e.add_field(name="게임 종료 알림", value=onoff(acc["notify_end"]), inline=True)
    e.add_field(name="일일 요약", value=onoff(acc["notify_daily"]), inline=True)
    e.add_field(name="알림 받을 게임", value=FILTER_LABELS.get(acc["queue_filter"], acc["queue_filter"]), inline=False)
    role = f"<@&{acc['mention_role_id']}>" if acc["mention_role_id"] else "없음"
    e.add_field(name="시작 알림 멘션", value=role, inline=False)
    return e


class Accounts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- /계정추가 ----------
    @app_commands.command(name="계정추가", description="추적할 롤 계정을 추가하고 알림 채널을 만듭니다 (관리자 전용)")
    @app_commands.describe(riot_id="닉네임#태그 (예: Hide on bush#KR1)")
    @app_commands.rename(riot_id="라이엇아이디")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def add_account(self, interaction: discord.Interaction, riot_id: str):
        if not is_admin(interaction):
            return await interaction.response.send_message(ADMIN_ONLY, ephemeral=True)
        parsed = parse_riot_id(riot_id)
        if not parsed:
            return await interaction.response.send_message(
                "형식이 올바르지 않아요. `닉네임#태그` 형태로 입력해 주세요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            data = await self.bot.riot.get_account(*parsed)
        except RiotError as e:
            return await interaction.followup.send(riot_error_message(e), ephemeral=True)
        if not data:
            return await interaction.followup.send(
                f"`{parsed[0]}#{parsed[1]}` 계정을 찾을 수 없어요. 닉네임과 태그를 다시 확인해 주세요.", ephemeral=True)

        db = self.bot.db
        existing = await db.get_account_by_puuid(interaction.guild_id, data["puuid"])
        if existing:
            return await interaction.followup.send(
                f"이미 등록된 계정이에요. (<#{existing['channel_id']}>)", ephemeral=True)

        try:
            channel = await create_alert_channel(interaction.guild, self.bot.cfg.category_name,
                                                 data["gameName"], data["tagLine"])
        except discord.Forbidden:
            return await interaction.followup.send(
                "채널을 만들 권한이 없어요. 봇에게 **채널 관리** 권한을 주세요.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"채널 생성에 실패했어요: {e}", ephemeral=True)

        try:
            await db.add_account(interaction.guild_id, channel.id, data["puuid"], data["gameName"],
                                 data["tagLine"], interaction.user.id)
        except Exception:  # noqa: BLE001
            log.exception("계정 저장 실패 - 만든 채널을 정리합니다")
            await channel.delete(reason="계정 저장 실패")
            return await interaction.followup.send("계정을 저장하는 중 오류가 발생했어요.", ephemeral=True)

        welcome = discord.Embed(
            title=f"✅ {data['gameName']}#{data['tagLine']} 추적을 시작합니다",
            description="이 채널에 게임 시작/종료 알림과 하루 요약이 올라와요.\n"
                        "알림 설정은 `/알림설정` 으로 바꿀 수 있어요.",
            color=BLUE)
        await channel.send(embed=welcome)
        await interaction.followup.send(f"✅ `{data['gameName']}#{data['tagLine']}` 추가 완료! {channel.mention}",
                                        ephemeral=True)

    # ---------- /계정삭제 ----------
    @app_commands.command(name="계정삭제", description="추적 중인 계정을 삭제합니다 (관리자 전용)")
    @app_commands.describe(account="삭제할 계정", delete_channel="알림 채널도 함께 삭제할까요? (기본: 예)")
    @app_commands.rename(account="계정", delete_channel="채널삭제")
    @app_commands.autocomplete(account=account_autocomplete)
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def remove_account(self, interaction: discord.Interaction, account: str, delete_channel: bool = True):
        if not is_admin(interaction):
            return await interaction.response.send_message(ADMIN_ONLY, ephemeral=True)
        acc = await find_account(interaction, account)
        if not acc:
            return await interaction.response.send_message("등록된 계정을 찾을 수 없어요.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)

        note = ""
        if delete_channel:
            ch = interaction.guild.get_channel(acc["channel_id"])
            if ch:
                try:
                    await ch.delete(reason=f"계정 삭제 ({interaction.user})")
                except discord.HTTPException:
                    note = "\n⚠️ 채널은 삭제하지 못했어요. 직접 지워주세요."
        await self.bot.db.delete_account(acc["id"])
        await interaction.followup.send(f"🗑️ `{riot_id(acc)}` 추적을 중단하고 삭제했어요.{note}", ephemeral=True)

    # ---------- /계정목록 ----------
    @app_commands.command(name="계정목록", description="이 서버에서 추적 중인 계정 목록")
    @app_commands.guild_only()
    async def list_accounts(self, interaction: discord.Interaction):
        accounts = await self.bot.db.get_guild_accounts(interaction.guild_id)
        if not accounts:
            return await interaction.response.send_message(
                "등록된 계정이 없어요. 관리자가 `/계정추가` 로 추가할 수 있어요.", ephemeral=True)
        lines = [f"• **{riot_id(a)}** → <#{a['channel_id']}>" for a in accounts]
        e = discord.Embed(title=f"추적 중인 계정 ({len(accounts)})", description="\n".join(lines), color=BLUE)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---------- /알림설정 ----------
    @app_commands.command(name="알림설정", description="계정별 알림 설정을 보거나 바꿉니다 (관리자 또는 등록한 사람)")
    @app_commands.describe(
        account="설정할 계정",
        notify_start="게임 시작 알림",
        notify_end="게임 종료(승패/LP) 알림",
        notify_daily="하루 요약 알림",
        queue_filter="알림 받을 게임 종류",
        mention_role="게임 시작 알림 때 멘션할 역할",
        clear_mention="멘션 설정 해제",
    )
    @app_commands.rename(account="계정", notify_start="시작알림", notify_end="종료알림", notify_daily="일일요약",
                         queue_filter="게임종류", mention_role="멘션역할", clear_mention="멘션해제")
    @app_commands.choices(queue_filter=[app_commands.Choice(name=v, value=k) for k, v in FILTER_LABELS.items()])
    @app_commands.autocomplete(account=account_autocomplete)
    @app_commands.guild_only()
    async def settings(self, interaction: discord.Interaction, account: str,
                       notify_start: bool | None = None, notify_end: bool | None = None,
                       notify_daily: bool | None = None,
                       queue_filter: app_commands.Choice[str] | None = None,
                       mention_role: discord.Role | None = None, clear_mention: bool = False):
        acc = await find_account(interaction, account)
        if not acc:
            return await interaction.response.send_message("등록된 계정을 찾을 수 없어요.", ephemeral=True)
        if not (is_admin(interaction) or acc["added_by"] == interaction.user.id):
            return await interaction.response.send_message(
                "관리자 또는 이 계정을 등록한 사람만 설정을 바꿀 수 있어요.", ephemeral=True)

        changes: dict = {}
        if notify_start is not None:
            changes["notify_start"] = int(notify_start)
        if notify_end is not None:
            changes["notify_end"] = int(notify_end)
        if notify_daily is not None:
            changes["notify_daily"] = int(notify_daily)
        if queue_filter is not None:
            changes["queue_filter"] = queue_filter.value
        if clear_mention:
            changes["mention_role_id"] = None
        elif mention_role is not None:
            changes["mention_role_id"] = mention_role.id

        if changes:
            await self.bot.db.update_settings(acc["id"], **changes)
            acc = await self.bot.db.get_account(acc["id"])
            title = f"⚙️ {riot_id(acc)} 설정이 변경됐어요"
        else:
            title = f"⚙️ {riot_id(acc)} 현재 설정"
        await interaction.response.send_message(embed=settings_embed(acc, title), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Accounts(bot))
