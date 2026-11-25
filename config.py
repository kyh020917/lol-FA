from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    discord_token: str
    riot_api_key: str
    poll_interval: int
    timezone: str
    dev_guild_id: int | None
    db_path: str
    category_name: str
    log_level: str


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    key = os.getenv("RIOT_API_KEY", "").strip()
    missing = [n for n, v in (("DISCORD_TOKEN", token), ("RIOT_API_KEY", key)) if not v]
    if missing:
        raise SystemExit(f".env 에 {', '.join(missing)} 값을 채워주세요. (.env.example 참고)")

    dev_guild = os.getenv("DEV_GUILD_ID", "").strip()
    return Config(
        discord_token=token,
        riot_api_key=key,
        poll_interval=max(15, int(os.getenv("POLL_INTERVAL", "45") or 45)),
        timezone=os.getenv("TIMEZONE", "Asia/Seoul").strip() or "Asia/Seoul",
        dev_guild_id=int(dev_guild) if dev_guild else None,
        db_path=os.getenv("DB_PATH", "data/lol_alert.db").strip() or "data/lol_alert.db",
        category_name=os.getenv("ALERT_CATEGORY_NAME", "롤 알림").strip() or "롤 알림",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
