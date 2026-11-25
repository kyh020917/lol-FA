from __future__ import annotations

from collections import Counter
from urllib.parse import quote

import discord

from utils.queues import ARENA_QUEUES, queue_name

BLUE = 0x3498DB
GREEN = 0x2ECC71
RED = 0xE74C3C
GREY = 0x95A5A6
PURPLE = 0x9B59B6


def riot_id(acc: dict) -> str:
    return f"{acc['game_name']}#{acc['tag_line']}"


def deeplol_url(game_name: str, tag_line: str) -> str:
    return f"https://www.deeplol.gg/summoner/kr/{quote(game_name, safe='')}-{quote(tag_line, safe='')}"


def deeplol_view(game_name: str, tag_line: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="딥롤에서 보기", style=discord.ButtonStyle.link,
                                    url=deeplol_url(game_name, tag_line)))
    return view


def streak_text(results: list[str]) -> str | None:
    """results: 최신순 결과 목록 (remake 제외). 2연속 이상일 때만 표시."""
    if not results:
        return None
    n = 0
    for r in results:
        if r != results[0]:
            break
        n += 1
    if n < 2:
        return None
    return f"🔥 {n}연승 중" if results[0] == "win" else f"🥶 {n}연패 중"


def fmt_duration(seconds: int) -> str:
    return f"{seconds // 60}분 {seconds % 60:02d}초"


def fmt_kda(k: int, d: int, a: int) -> str:
    ratio = "Perfect" if d == 0 else f"{(k + a) / d:.2f}:1"
    return f"{k} / {d} / {a}  ({ratio})"


def _thumb(embed: discord.Embed, ddragon, champion_id: int) -> None:
    icon = ddragon.icon(champion_id)
    if icon:
        embed.set_thumbnail(url=icon)


def build_start_embed(acc: dict, queue_id: int, champion_id: int, start_ts: int,
                      tier_text: str, ddragon) -> discord.Embed:
    e = discord.Embed(title=f"🎮 {riot_id(acc)} 님이 게임을 시작했어요!", color=BLUE)
    e.add_field(name="게임 모드", value=queue_name(queue_id), inline=True)
    e.add_field(name="챔피언", value=ddragon.name(champion_id), inline=True)
    e.add_field(name="현재 티어", value=tier_text, inline=True)
    e.add_field(name="시작 시각", value=f"<t:{start_ts}:T> (<t:{start_ts}:R>)", inline=False)
    _thumb(e, ddragon, champion_id)
    return e


def build_end_embed(acc: dict, r: dict, ddragon, tier_text: str, lp_detail: str | None,
                    streak: str | None) -> discord.Embed:
    if r["result"] == "win":
        title, color = f"🏆 승리! — {riot_id(acc)}", GREEN
    elif r["result"] == "loss":
        title, color = f"💀 패배 — {riot_id(acc)}", RED
    else:
        title, color = f"🔄 다시하기 (게임 무효) — {riot_id(acc)}", GREY
    e = discord.Embed(title=title, color=color)
    e.add_field(name="게임 모드", value=queue_name(r["queue_id"]), inline=True)
    e.add_field(name="챔피언", value=ddragon.name(r["champion_id"]), inline=True)
    e.add_field(name="게임 시간", value=fmt_duration(r["duration"]), inline=True)
    e.add_field(name="KDA", value=fmt_kda(r["kills"], r["deaths"], r["assists"]), inline=False)
    cs_min = r["cs"] / (r["duration"] / 60) if r["duration"] else 0
    e.add_field(name="CS", value=f"{r['cs']} ({cs_min:.1f}/분)", inline=True)
    e.add_field(name="챔피언 딜량", value=f"{r['damage']:,}", inline=True)
    if r.get("placement") and r["queue_id"] in ARENA_QUEUES:
        e.add_field(name="순위", value=f"{r['placement']}등", inline=True)
    if lp_detail:
        e.add_field(name="LP 변동", value=lp_detail, inline=False)
    e.add_field(name="현재 티어", value=tier_text, inline=True)
    if streak and r["result"] != "remake":
        e.add_field(name="연속 기록", value=streak, inline=True)
    _thumb(e, ddragon, r["champion_id"])
    return e


def build_daily_embed(acc: dict, date_str: str, wins: int, losses: int, lp_total: int | None,
                      champs: Counter, ddragon) -> discord.Embed:
    total = wins + losses
    rate = round(wins / total * 100) if total else 0
    e = discord.Embed(title=f"📊 {riot_id(acc)} 님의 오늘 요약", color=PURPLE)
    e.add_field(name="전적", value=f"**{wins}승 {losses}패** (승률 {rate}%)", inline=True)
    if lp_total is not None:
        e.add_field(name="총 LP 변동", value=f"{lp_total:+d} LP" if lp_total else "±0 LP", inline=True)
    if champs:
        top = ", ".join(f"{ddragon.name(cid)} ×{n}" for cid, n in champs.most_common(5))
        e.add_field(name="플레이한 챔피언", value=top, inline=False)
    e.set_footer(text=date_str)
    return e
