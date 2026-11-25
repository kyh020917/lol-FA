from __future__ import annotations

TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
         "MASTER", "GRANDMASTER", "CHALLENGER"]
TIER_KO = {
    "IRON": "아이언", "BRONZE": "브론즈", "SILVER": "실버", "GOLD": "골드", "PLATINUM": "플래티넘",
    "EMERALD": "에메랄드", "DIAMOND": "다이아몬드", "MASTER": "마스터",
    "GRANDMASTER": "그랜드마스터", "CHALLENGER": "챌린저",
}
DIVISIONS = {"IV": 0, "III": 1, "II": 2, "I": 3}
APEX = {"MASTER", "GRANDMASTER", "CHALLENGER"}
_APEX_BASE = 7 * 400  # 다이아몬드 I 100LP 다음부터 마스터 시작

TRACKED_KEYS = ("RANKED_SOLO_5x5", "RANKED_FLEX_SR")


def lp_total(entry: dict) -> int:
    """티어/디비전/LP를 하나의 점수로 환산한다. entry: {tier, rank, lp}"""
    tier = entry["tier"]
    if tier in APEX:
        return _APEX_BASE + entry["lp"]
    return TIERS.index(tier) * 400 + DIVISIONS[entry["rank"]] * 100 + entry["lp"]


def lp_delta(before: dict, after: dict) -> int:
    return lp_total(after) - lp_total(before)


def format_tier(entry: dict | None) -> str:
    if not entry:
        return "언랭크"
    tier = TIER_KO.get(entry["tier"], entry["tier"])
    if entry["tier"] in APEX:
        return f"{tier} {entry['lp']}LP"
    return f"{tier} {entry['rank']} {entry['lp']}LP"


def snapshot_entries(entries: list[dict]) -> dict:
    """league-v4 응답에서 필요한 큐만 {queueType: {tier, rank, lp}} 로 줄인다."""
    snap = {}
    for e in entries or []:
        key = e.get("queueType")
        if key in TRACKED_KEYS and e.get("tier"):
            snap[key] = {"tier": e["tier"], "rank": e.get("rank", "I"), "lp": e.get("leaguePoints", 0)}
    return snap


def format_delta(delta: int) -> str:
    return f"{delta:+d} LP" if delta else "±0 LP"
