"""한 경기 10명의 기록을 서로 비교해 개인 점수(100점 만점), 순위, 팀운을 계산한다.

표본 데이터 없이 그 경기 안에서만 상대 평가를 하므로 API 호출이 늘지 않는다.
"""
from __future__ import annotations

# 가중치 (합 1.0). 서포터는 CS/골드/딜량 대신 시야·관여율 비중을 키운다.
WEIGHTS_NORMAL = {"kda": 0.25, "damage": 0.25, "kp": 0.15, "cs": 0.15, "gold": 0.10, "vision": 0.10}
WEIGHTS_SUPPORT = {"kda": 0.30, "kp": 0.35, "vision": 0.35}
WEIGHTS_NO_ROLE = {"kda": 0.35, "damage": 0.30, "kp": 0.25, "gold": 0.10}   # 칼바람 등 포지션 없는 모드

# 팀운: (아군 4명 평균 점수 - 적 5명 평균 점수) 를 승패 기준선으로 보정한 값의 경계값.
# 이긴 팀은 점수가 원래 높게 나오므로 (실측: 승리 평균 약 +18, 패배 평균 약 -14, 편차 약 8)
# 승패 때문에 생기는 차이를 빼고 "그 승패치고 아군이 어땠는지"로 판정한다.
LUCK_LEVELS = [(-14, "극악"), (-5, "나쁨"), (5, "보통"), (14, "좋음")]
RESULT_BASELINE = 16
LUCK_BEST = "버스"
LUCK_EMOJI = {"극악": "💀", "나쁨": "😢", "보통": "😐", "좋음": "😊", "버스": "🚌"}
LEAVER_RATIO = 0.7   # 게임 시간의 70%도 못 채우고 나간 사람은 탈주로 본다
LEAVER_SHIFT = 10    # 탈주자 1명당 팀운 점수차 보정


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _metrics(p: dict, team_kills: int, minutes: float) -> dict:
    k, d, a = p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)
    return {
        "kda": (k + a) / max(d, 1),
        "damage": p.get("totalDamageDealtToChampions", 0),
        "kp": (k + a) / team_kills if team_kills else 0.0,
        "cs": (p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)) / minutes,
        "gold": p.get("goldEarned", 0),
        "vision": p.get("visionScore", 0) / minutes,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def luck_label(diff: float) -> str:
    for bound, label in LUCK_LEVELS:
        if diff < bound:
            return label
    return LUCK_BEST


def analyze(match: dict, puuid: str, duration: int) -> dict | None:
    """5v5 경기에서만 결과를 돌려준다. 그 외(아레나 등)나 데이터 부족이면 None.

    반환: {score, rank, total, badge, luck, luck_diff, ally_avg, enemy_avg, leavers}
    """
    parts = match.get("info", {}).get("participants", [])
    if len(parts) != 10 or duration <= 0:
        return None
    teams = {p.get("teamId") for p in parts}
    if len(teams) != 2 or any(sum(1 for p in parts if p.get("teamId") == t) != 5 for t in teams):
        return None
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if me is None:
        return None

    minutes = max(duration / 60, 1.0)
    team_kills = {t: sum(p.get("kills", 0) for p in parts if p.get("teamId") == t) for t in teams}
    has_roles = all(p.get("teamPosition") for p in parts)

    rows = []
    for p in parts:
        rows.append((p, _metrics(p, team_kills[p["teamId"]], minutes)))

    def is_support(p: dict) -> bool:
        return has_roles and p.get("teamPosition") == "UTILITY"

    # 지표별 평균: 시야만 서포터/비서포터를 따로 비교한다
    means = {key: _mean([m[key] for _, m in rows]) for key in WEIGHTS_NORMAL}
    sup_vis = [m["vision"] for p, m in rows if is_support(p)]
    non_vis = [m["vision"] for p, m in rows if not is_support(p)]

    scores: list[tuple[dict, float]] = []
    for p, m in rows:
        if not has_roles:
            weights = WEIGHTS_NO_ROLE
        elif is_support(p):
            weights = WEIGHTS_SUPPORT
        else:
            weights = WEIGHTS_NORMAL
        total = 0.0
        for key, w in weights.items():
            base = means[key]
            if key == "vision":
                base = _mean(sup_vis if is_support(p) else non_vis)
            ratio = m[key] / base if base > 0 else 1.0
            total += w * _clamp(ratio, 0.0, 2.0) / 2.0
        scores.append((p, total * 100))

    by_id = {id(p): s for p, s in scores}
    my_score = by_id[id(me)]
    rank = 1 + sum(1 for _, s in scores if s > my_score)

    # MVP: 이긴 팀 1등 / ACE: 진 팀 1등
    team_best = max(s for p, s in scores if p["teamId"] == me["teamId"])
    badge = None
    if my_score >= team_best:
        badge = "MVP" if me.get("win") else "ACE"

    allies = [s for p, s in scores if p["teamId"] == me["teamId"] and p is not me]
    enemies = [s for p, s in scores if p["teamId"] != me["teamId"]]
    ally_avg, enemy_avg = _mean(allies), _mean(enemies)
    diff = ally_avg - enemy_avg - (RESULT_BASELINE if me.get("win") else -RESULT_BASELINE)

    leavers = {"ally": 0, "enemy": 0}
    for p in parts:
        played = p.get("timePlayed")
        if played and played < duration * LEAVER_RATIO and p is not me:
            leavers["ally" if p["teamId"] == me["teamId"] else "enemy"] += 1
    diff += (leavers["enemy"] - leavers["ally"]) * LEAVER_SHIFT

    return {
        "score": int(round(_clamp(my_score, 0, 100))),
        "rank": rank,
        "total": 10,
        "badge": badge,
        "luck": luck_label(diff),
        "luck_diff": diff,
        "ally_avg": ally_avg,
        "enemy_avg": enemy_avg,
        "leavers": leavers,
    }
