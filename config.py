from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import dotenv_values, load_dotenv

load_dotenv()


def clean_secret(value: str) -> str:
    """앞뒤 공백/줄바꿈/따옴표를 제거한다 (호스트 환경변수 칸에 따옴표째 넣는 실수 방지)."""
    return value.strip().strip("\"'").strip()


def mask_key(key: str) -> str:
    return f"{key[:6]}****{key[-4:]} ({len(key)}자)" if len(key) > 12 else f"({len(key)}자)"


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
    riot_key_conflict: bool = False   # 환경변수의 키와 .env 파일의 키가 서로 다름


def load_config() -> Config:
    token = clean_secret(os.getenv("DISCORD_TOKEN", ""))
    key = clean_secret(os.getenv("RIOT_API_KEY", ""))
    file_key = clean_secret(dotenv_values().get("RIOT_API_KEY") or "")
    key_conflict = bool(file_key) and file_key != key
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
        riot_key_conflict=key_conflict,
    )
