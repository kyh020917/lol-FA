from __future__ import annotations

import logging
import time

import aiohttp

log = logging.getLogger(__name__)

BASE = "https://ddragon.leagueoflegends.com"


class DDragon:
    """챔피언 한글 이름/아이콘 (Data Dragon)."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.version: str | None = None
        self.champs: dict[int, dict] = {}
        self._loaded_at = 0.0

    async def load(self) -> None:
        async with self.session.get(f"{BASE}/api/versions.json") as r:
            r.raise_for_status()
            version = (await r.json())[0]
        async with self.session.get(f"{BASE}/cdn/{version}/data/ko_KR/champion.json") as r:
            r.raise_for_status()
            data = await r.json()
        self.champs = {int(c["key"]): {"name": c["name"], "id": c["id"]} for c in data["data"].values()}
        self.version = version
        self._loaded_at = time.time()
        log.info("Data Dragon 로드 완료 (버전 %s, 챔피언 %d명)", version, len(self.champs))

    async def ensure(self, champion_id: int) -> None:
        """모르는 챔피언(신규 패치)이면 1시간에 한 번까지 다시 불러온다."""
        if champion_id in self.champs or time.time() - self._loaded_at < 3600:
            return
        try:
            await self.load()
        except Exception as e:  # noqa: BLE001
            self._loaded_at = time.time()
            log.warning("Data Dragon 갱신 실패: %s", e)

    def name(self, champion_id: int) -> str:
        c = self.champs.get(champion_id)
        return c["name"] if c else f"챔피언 {champion_id}"

    def icon(self, champion_id: int) -> str | None:
        c = self.champs.get(champion_id)
        if not c or not self.version:
            return None
        return f"{BASE}/cdn/{self.version}/img/champion/{c['id']}.png"
