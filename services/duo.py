"""최근 20판 팀원 기록으로 이번 게임의 듀오/N인큐를 추정한다.

Riot API는 파티 정보를 주지 않는다. 그래서 "이 계정의 최근 20판에서 같은 팀이었던 사람"을 저장해 두고,
게임이 시작되면 같은 팀원 중 이전에 2판 이상 같이 한 사람이 있는지로 추정한다 (이번이 3판째부터 표시).
"""
from __future__ import annotations

import logging

from services.riot_api import RiotAuthError, RiotError

log = logging.getLogger(__name__)

RECENT_GAMES = 20       # 비교할 최근 판 수
MIN_PRIOR_GAMES = 2     # 이전에 이만큼 같이 했으면 이번 게임에서 파티로 추정
SOLO_DUO_QUEUE = 420    # 솔로/듀오 랭크는 파티가 최대 2명


async def record_teammates(db, account_id: int, puuid: str, match: dict) -> int:
    """끝난 경기에서 같은 팀 4명을 저장한다. 저장한 팀원 수를 반환 (5v5가 아니면 0)."""
    info = match.get("info", {})
    parts = info.get("participants", [])
    if len(parts) != 10:    # 아레나 등은 제외
        return 0
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None or info.get("gameId") is None:
        return 0
    rows = [(p["puuid"], p.get("riotIdGameName") or p.get("summonerName"), p.get("riotIdTagline"))
            for p in parts if p.get("teamId") == me.get("teamId") and p.get("puuid") != puuid]
    ended = int(info["gameEndTimestamp"] / 1000) if info.get("gameEndTimestamp") else 0
    if rows:
        await db.add_teammates(account_id, int(info["gameId"]), ended, rows)
    return len(rows)


async def backfill(db, riot, account_id: int, puuid: str, count: int = RECENT_GAMES) -> int:
    """계정을 추가할 때 최근 `count`판의 팀원을 한 번 채워 둔다. 처리한 경기 수를 반환."""
    done = 0
    try:
        ids = await riot.get_match_ids(puuid, count=count)
        for mid in ids:
            match = await riot.get_match(mid)
            if match and await record_teammates(db, account_id, puuid, match):
                done += 1
    except RiotAuthError as e:
        log.warning("계정 %s 최근 경기 가져오기 중단 (접근 거부): %s", account_id, e)
    except RiotError as e:
        log.warning("계정 %s 최근 경기 가져오기 실패: %s", account_id, e)
    return done


def detect_party(game: dict, puuid: str, counts: dict[str, dict], queue_id: int) -> list[dict] | None:
    """진행 중인 게임의 같은 팀원 중 자주 같이 한 사람 목록 (많이 한 순). 없으면 None."""
    parts = game.get("participants", [])
    if len(parts) != 10:
        return None
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None or me.get("teamId") is None:
        return None
    found = []
    for p in parts:
        if p.get("teamId") != me["teamId"] or p.get("puuid") == puuid:
            continue
        c = counts.get(p.get("puuid"))
        if not c or c["cnt"] < MIN_PRIOR_GAMES:
            continue
        name, tag = c.get("game_name"), c.get("tag_line")
        if not name:
            name, _, tag = (p.get("riotId") or "").partition("#")
        found.append({"name": name or "알 수 없음", "tag": tag or "", "count": c["cnt"]})
    if not found:
        return None
    found.sort(key=lambda x: -x["count"])
    if queue_id == SOLO_DUO_QUEUE:
        found = found[:1]
    return found
