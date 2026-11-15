"""갭 → 다음 한 칸 행동 (템플릿 라이브러리, 결정적).

- 항목의 종류(kind)가 자격증·도구면 그 템플릿, 아니면 첫 번째 축의 템플릿을 쓴다.
- 목표 수준까지 한 번에가 아니라 '다음 한 단계'만 제안한다 (현재 수준 → +1).
- 같은 항목이 연속 보류됐으면 30분짜리 작은 첫걸음으로 쪼갠다.
- 태도 항목은 행동 과제로 만들지 않는다 (경험 카드에서 자연스럽게 드러나는 부분).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Optional

from .config import DATA_DIR, load_planning
from .scoring import GapItem


@lru_cache(maxsize=None)
def load_templates() -> dict:
    with open(DATA_DIR / "action_templates.json", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Action:
    requirement_id: str
    requirement_label: str
    title: str
    how: str
    hours: float
    from_level: int
    to_level: int
    card_kind: Optional[str]  # 끝나면 남길 경험 카드 유형
    source_quote: str  # 이 행동이 필요한 근거 (공고 원문)
    small_step: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _template_for(gap: GapItem) -> Optional[dict]:
    t = load_templates()
    req, step = gap.requirement, f"{gap.current_level}to{gap.current_level + 1}"
    if req.kind == "certificate":
        return t["by_kind"]["certificate"]
    if req.kind == "tool":
        return t["by_kind"]["tool"].get(step)
    if not req.axes:
        return None
    return t["by_axis"].get(req.axes[0], {}).get(step)


def next_actions(
    gaps: list[GapItem], max_actions: int = 3, stuck_requirement_ids: Optional[set[str]] = None,
) -> list[Action]:
    """우선순위 순 갭 목록(prioritize_gaps 결과) → 다음 행동 최대 N개."""
    stuck = stuck_requirement_ids or set()
    hours_cfg = load_planning()["step_hours"]
    small = load_templates()["small_step"]
    actions = []
    for g in gaps:
        req = g.requirement
        if req.kind == "attitude" or g.gap <= 0:
            continue
        tpl = _template_for(g)
        if tpl is None:
            continue
        frm, to = g.current_level, g.current_level + 1
        if req.id in stuck:
            actions.append(Action(req.id, req.label, small["title"].format(label=req.label),
                                  small["how"], small["hours"], frm, frm, None, req.quote, small_step=True))
        else:
            actions.append(Action(req.id, req.label, tpl["title"].format(label=req.label),
                                  tpl["how"].format(label=req.label), float(hours_cfg[f"{frm}to{to}"]),
                                  frm, to, tpl.get("card"), req.quote))
        if len(actions) >= max_actions:
            break
    return actions
