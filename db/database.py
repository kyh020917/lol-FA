from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id         INTEGER NOT NULL,
    channel_id       INTEGER NOT NULL,
    puuid            TEXT    NOT NULL,
    game_name        TEXT    NOT NULL,
    tag_line         TEXT    NOT NULL,
    added_by         INTEGER NOT NULL,
    notify_start     INTEGER NOT NULL DEFAULT 1,
    notify_end       INTEGER NOT NULL DEFAULT 1,
    notify_daily     INTEGER NOT NULL DEFAULT 1,
    queue_filter     TEXT    NOT NULL DEFAULT 'all',
    mention_role_id  INTEGER,
    created_at       INTEGER NOT NULL,
    UNIQUE (guild_id, puuid)
);

CREATE TABLE IF NOT EXISTS active_games (
    account_id    INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    game_id       INTEGER NOT NULL,
    queue_id      INTEGER NOT NULL,
    champion_id   INTEGER NOT NULL,
    start_ts      INTEGER NOT NULL,
    start_entries TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    lp_retries    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    game_id     INTEGER NOT NULL,
    queue_id    INTEGER NOT NULL,
    champion_id INTEGER NOT NULL,
    result      TEXT    NOT NULL,           -- win / loss / remake
    kills       INTEGER NOT NULL,
    deaths      INTEGER NOT NULL,
    assists     INTEGER NOT NULL,
    cs          INTEGER NOT NULL,
    damage      INTEGER NOT NULL,
    duration    INTEGER NOT NULL,
    placement   INTEGER,
    lp_delta    INTEGER,
    ended_ts    INTEGER NOT NULL,
    UNIQUE (account_id, game_id)
);
CREATE INDEX IF NOT EXISTS idx_results_acc_time ON game_results(account_id, ended_ts);

-- 계정별로 같은 팀이었던 사람들 (듀오/N인큐 추정용). 게임당 팀원 4명씩 저장한다.
CREATE TABLE IF NOT EXISTS teammates (
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    game_id        INTEGER NOT NULL,
    teammate_puuid TEXT    NOT NULL,
    game_name      TEXT,
    tag_line       TEXT,
    ended_ts       INTEGER NOT NULL,
    PRIMARY KEY (account_id, game_id, teammate_puuid)
);
CREATE INDEX IF NOT EXISTS idx_teammates_acc_time ON teammates(account_id, ended_ts);

CREATE TABLE IF NOT EXISTS daily_reports (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    PRIMARY KEY (account_id, date)
);
"""

SETTING_FIELDS = {"notify_start", "notify_end", "notify_daily", "queue_filter", "mention_role_id"}


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ---- 내부 헬퍼 ----
    async def _one(self, sql: str, params: tuple = ()) -> dict | None:
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _exec(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    # ---- 계정 ----
    async def add_account(self, guild_id: int, channel_id: int, puuid: str, game_name: str,
                          tag_line: str, added_by: int) -> int:
        cur = await self._exec(
            "INSERT INTO accounts (guild_id, channel_id, puuid, game_name, tag_line, added_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, puuid, game_name, tag_line, added_by, int(time.time())),
        )
        return cur.lastrowid

    async def get_account(self, account_id: int) -> dict | None:
        return await self._one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    async def get_account_by_puuid(self, guild_id: int, puuid: str) -> dict | None:
        return await self._one("SELECT * FROM accounts WHERE guild_id = ? AND puuid = ?", (guild_id, puuid))

    async def get_guild_accounts(self, guild_id: int) -> list[dict]:
        return await self._all("SELECT * FROM accounts WHERE guild_id = ? ORDER BY id", (guild_id,))

    async def get_all_accounts(self) -> list[dict]:
        return await self._all("SELECT * FROM accounts ORDER BY id")

    async def delete_account(self, account_id: int) -> None:
        await self._exec("DELETE FROM accounts WHERE id = ?", (account_id,))

    async def delete_guild_accounts(self, guild_id: int) -> None:
        await self._exec("DELETE FROM accounts WHERE guild_id = ?", (guild_id,))

    async def update_settings(self, account_id: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in SETTING_FIELDS}
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self._exec(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))

    async def update_channel(self, account_id: int, channel_id: int) -> None:
        await self._exec("UPDATE accounts SET channel_id = ? WHERE id = ?", (channel_id, account_id))

    async def update_puuid(self, account_id: int, puuid: str) -> None:
        await self._exec("UPDATE accounts SET puuid = ? WHERE id = ?", (puuid, account_id))

    async def update_riot_id(self, puuid: str, game_name: str, tag_line: str) -> None:
        await self._exec("UPDATE accounts SET game_name = ?, tag_line = ? WHERE puuid = ?",
                         (game_name, tag_line, puuid))

    # ---- 진행 중인 게임 ----
    async def get_active(self, account_id: int) -> dict | None:
        return await self._one("SELECT * FROM active_games WHERE account_id = ?", (account_id,))

    async def set_active(self, account_id: int, game_id: int, queue_id: int, champion_id: int,
                         start_ts: int, start_entries_json: str | None) -> None:
        await self._exec(
            "INSERT OR REPLACE INTO active_games "
            "(account_id, game_id, queue_id, champion_id, start_ts, start_entries, attempts, lp_retries) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
            (account_id, game_id, queue_id, champion_id, start_ts, start_entries_json),
        )

    async def bump_attempts(self, account_id: int) -> None:
        await self._exec("UPDATE active_games SET attempts = attempts + 1 WHERE account_id = ?", (account_id,))

    async def bump_lp_retries(self, account_id: int) -> None:
        await self._exec("UPDATE active_games SET lp_retries = lp_retries + 1 WHERE account_id = ?", (account_id,))

    async def delete_active(self, account_id: int) -> None:
        await self._exec("DELETE FROM active_games WHERE account_id = ?", (account_id,))

    # ---- 게임 결과 ----
    async def add_result(self, account_id: int, r: dict) -> bool:
        """이미 저장된 게임이면 False."""
        cur = await self._exec(
            "INSERT OR IGNORE INTO game_results "
            "(account_id, game_id, queue_id, champion_id, result, kills, deaths, assists, cs, damage, "
            " duration, placement, lp_delta, ended_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, r["game_id"], r["queue_id"], r["champion_id"], r["result"], r["kills"], r["deaths"],
             r["assists"], r["cs"], r["damage"], r["duration"], r.get("placement"), r.get("lp_delta"),
             r["ended_ts"]),
        )
        return cur.rowcount > 0

    async def recent_results(self, account_id: int, queue_id: int, limit: int = 30) -> list[str]:
        rows = await self._all(
            "SELECT result FROM game_results WHERE account_id = ? AND queue_id = ? AND result != 'remake' "
            "ORDER BY ended_ts DESC, id DESC LIMIT ?",
            (account_id, queue_id, limit),
        )
        return [r["result"] for r in rows]

    async def results_between(self, account_id: int, start_ts: int, end_ts: int) -> list[dict]:
        return await self._all(
            "SELECT * FROM game_results WHERE account_id = ? AND ended_ts >= ? AND ended_ts < ? "
            "ORDER BY ended_ts",
            (account_id, start_ts, end_ts),
        )

    # ---- 팀원 기록 (듀오 추정) ----
    async def add_teammates(self, account_id: int, game_id: int, ended_ts: int,
                            rows: list[tuple[str, str | None, str | None]]) -> None:
        """rows: (teammate_puuid, game_name, tag_line). 이미 저장된 게임/팀원은 무시."""
        await self.conn.executemany(
            "INSERT OR IGNORE INTO teammates (account_id, game_id, teammate_puuid, game_name, tag_line, ended_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(account_id, game_id, pu, name, tag, ended_ts) for pu, name, tag in rows],
        )
        await self.conn.commit()

    async def teammate_counts(self, account_id: int, games: int = 20) -> dict[str, dict]:
        """최근 `games`판 동안 같은 팀이었던 횟수. {puuid: {cnt, game_name, tag_line}}"""
        rows = await self._all(
            "SELECT teammate_puuid, COUNT(*) AS cnt, MAX(game_name) AS game_name, MAX(tag_line) AS tag_line "
            "FROM teammates WHERE account_id = ? AND game_id IN ("
            "  SELECT game_id FROM teammates WHERE account_id = ? "
            "  GROUP BY game_id ORDER BY MAX(ended_ts) DESC LIMIT ?) "
            "GROUP BY teammate_puuid",
            (account_id, account_id, games),
        )
        return {r["teammate_puuid"]: r for r in rows}

    # ---- 일일 요약 ----
    async def mark_daily_sent(self, account_id: int, date: str) -> bool:
        cur = await self._exec("INSERT OR IGNORE INTO daily_reports (account_id, date) VALUES (?, ?)",
                               (account_id, date))
        return cur.rowcount > 0
