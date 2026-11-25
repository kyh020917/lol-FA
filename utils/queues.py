from __future__ import annotations

QUEUE_NAMES = {
    400: "일반 (드래프트)",
    430: "일반 (블라인드)",
    420: "솔로랭크",
    440: "자유랭크",
    450: "칼바람 나락",
    490: "빠른 대전",
    700: "격전",
    720: "칼바람 (격전)",
    900: "URF",
    1900: "URF",
    1020: "단일 챔피언",
    1300: "돌격! 넥서스",
    1400: "궁극기 주문서",
    1700: "아레나",
    1710: "아레나",
    830: "AI 대전 (입문)",
    840: "AI 대전 (초급)",
    850: "AI 대전 (중급)",
    2400: "칼바람 대혼란",
}

# 큐 ID -> league-v4 queueType
RANKED_QUEUES = {420: "RANKED_SOLO_5x5", 440: "RANKED_FLEX_SR"}
ARENA_QUEUES = {1700, 1710}

# 큐 필터 (계정별 설정)
FILTER_LABELS = {
    "all": "전체 게임",
    "ranked": "랭크만 (솔로+자유)",
    "solo": "솔로랭크만",
    "rift": "소환사의 협곡만 (일반+랭크)",
}
_RIFT = {400, 430, 420, 440, 490, 700}


def queue_name(queue_id: int) -> str:
    return QUEUE_NAMES.get(queue_id, f"기타 게임 ({queue_id})")


def queue_allowed(queue_id: int, queue_filter: str) -> bool:
    if queue_filter == "ranked":
        return queue_id in RANKED_QUEUES
    if queue_filter == "solo":
        return queue_id == 420
    if queue_filter == "rift":
        return queue_id in _RIFT
    return True
