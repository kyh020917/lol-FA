from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

PLATFORM_HOST = "https://kr.api.riotgames.com"      # 게임 중 / 랭크 정보
REGION_HOST = "https://asia.api.riotgames.com"      # 계정 / 매치 정보


class RiotError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"Riot API {status}: {message}")
        self.status = status


class RiotAuthError(RiotError):
    """API 키 만료/오류 (401, 403)."""


class RateLimiter:
    """슬라이딩 윈도우 방식. 개발용 키: 1초 20회, 2분 100회 (여유를 두고 설정)."""

    def __init__(self, limits: list[tuple[int, float]]):
        self.limits = limits
        self.stamps = [deque() for _ in limits]
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                wait = 0.0
                for (max_calls, per), dq in zip(self.limits, self.stamps):
                    while dq and now - dq[0] >= per:
                        dq.popleft()
                    if len(dq) >= max_calls:
                        wait = max(wait, per - (now - dq[0]))
                if wait <= 0:
                    break
                await asyncio.sleep(wait)
            now = time.monotonic()
            for dq in self.stamps:
                dq.append(now)


class RiotClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str,
                 per_sec: int = 18, per_2min: int = 95):
        self.session = session
        self.api_key = api_key
        self.limiter = RateLimiter([(per_sec, 1.0), (per_2min, 120.0)])
        self._cache: dict[tuple, tuple[float, object]] = {}

    # ---- 저수준 ----
    async def _request(self, url: str, params: dict | None):
        for attempt in range(4):
            await self.limiter.acquire()
            try:
                async with self.session.get(url, params=params,
                                            headers={"X-Riot-Token": self.api_key}) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return None
                    if resp.status in (401, 403):
                        raise RiotAuthError(resp.status, f"API 키 거부됨 - {(await resp.text())[:120]}")
                    if resp.status == 429:
                        wait = float(resp.headers.get("Retry-After", 5))
                        log.warning("Riot 요청 제한(429) - %.1f초 대기", wait)
                        await asyncio.sleep(wait + 0.5)
                        continue
                    if resp.status >= 500:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    raise RiotError(resp.status, (await resp.text())[:200])
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == 3:
                    raise RiotError(0, f"네트워크 오류: {e}") from e
                await asyncio.sleep(2)
        raise RiotError(0, "재시도 횟수를 초과했습니다.")

    async def _get(self, host: str, path: str, *, params: dict | None = None,
                   cache_ttl: float = 0, cache_none: bool = False):
        url = f"{host}{path}"
        key = (url, tuple(sorted((params or {}).items())))
        if cache_ttl:
            hit = self._cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        data = await self._request(url, params)
        if cache_ttl and (data is not None or cache_none):
            if len(self._cache) >= 200:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + cache_ttl, data)
        return data

    async def check_key(self) -> None:
        """키가 유효하지 않으면 RiotAuthError. 시작할 때 한 번 호출."""
        await self._request(f"{PLATFORM_HOST}/lol/status/v4/platform-data", None)

    # ---- 엔드포인트 ----
    async def get_account(self, game_name: str, tag_line: str) -> dict | None:
        path = f"/riot/account/v1/accounts/by-riot-id/{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
        return await self._get(REGION_HOST, path)

    async def get_account_by_puuid(self, puuid: str) -> dict | None:
        return await self._get(REGION_HOST, f"/riot/account/v1/accounts/by-puuid/{puuid}")

    async def get_active_game(self, puuid: str) -> dict | None:
        """게임 중이 아니면 None."""
        return await self._get(PLATFORM_HOST, f"/lol/spectator/v5/active-games/by-summoner/{puuid}",
                               cache_ttl=15, cache_none=True)

    async def get_league_entries(self, puuid: str) -> list[dict]:
        data = await self._get(PLATFORM_HOST, f"/lol/league/v4/entries/by-puuid/{puuid}",
                               cache_ttl=15, cache_none=True)
        return data or []

    async def get_match(self, match_id: str) -> dict | None:
        return await self._get(REGION_HOST, f"/lol/match/v5/matches/{match_id}", cache_ttl=600)

    async def get_match_ids(self, puuid: str, count: int = 10) -> list[str]:
        data = await self._get(REGION_HOST, f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                               params={"start": 0, "count": count}, cache_ttl=15)
        return data or []
