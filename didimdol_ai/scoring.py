"""목표 ↔ 경험 카드 ↔ 자기평가를 연결하는 결정적(코드) 계산.

LLM은 '요구 항목 추출'과 '카드 근거 수준 판정'까지만 하고,
점수·갭·우선순위·방향 종류는 모두 여기서 코드로 계산한다 (재현 가능, 설명 가능).
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Literal, Optional

from .config import axis_ids, load_planning
from .models import Evidence, Goal, Requirement

MAX_LEVEL = 3
Quadrant = Literal[
    "record_proof",  # 자기평가 높음 · 근거 낮음 → 기록·증명
    "maintain_expand",  # 자기평가 높음 · 근거 높음 → 유지·확장
    "learn_experience",  # 자기평가 낮음 · 근거 낮음 → 학습·경험
    "confidence_expression",  # 자기평가 낮음 · 근거 높음 → 자신감·표현
]


# ---------------------------------------------------------------- 기본 변환


def level_to_scale(level: float) -> float:
    """근거/요구 수준(0~3)을 육각형 척도(1~5)로 환산."""
    level = max(0.0, min(float(MAX_LEVEL), level))
    return round(1 + level * 4 / MAX_LEVEL, 2)


NCS_BASIC = {"의사소통능력", "수리능력", "문제해결능력", "자기개발능력", "자원관리능력", "대인관계능력",
             "정보능력", "기술능력", "조직이해능력", "직업윤리"}


def is_basic_competency(req: Requirement) -> bool:
    """NCS 직업기초능력 10개. 공고의 모든 직무에 똑같이 붙는 일반 항목이라 직무 고유 항목보다 가볍게 다룬다."""
    return re.sub(r"\s", "", req.label) in NCS_BASIC


def requirement_weight(req: Requirement) -> float:
    """중요도 × 출처 신뢰도 × 유형 가중치. 기관·분야 목표는 공고 요구 빈도를 중요도로 쓴다.
    직업기초능력은 basic_competency_weight를 곱해 직무 고유 항목이 우선순위·목표선을 이끌게 한다."""
    p = load_planning()
    if req.frequency is not None:
        importance = req.frequency
    elif req.necessity == "required":
        importance = p["importance"]["required"]
    elif req.necessity == "preferred":
        importance = p["importance"]["preferred"]
    else:
        importance = p["importance"]["curated_default"]
    kind_factor = p.get("kind_weight", {}).get(req.kind or "", 1.0)
    if is_basic_competency(req):
        kind_factor *= p.get("basic_competency_weight", 1.0)
    return importance * p["source_weight"][req.source] * kind_factor


def best_evidence(evidences: list[Evidence]) -> dict[str, tuple[int, list[Evidence]]]:
    """요구 항목별 최고 근거 수준과 그 근거 목록."""
    out: dict[str, tuple[int, list[Evidence]]] = {}
    for ev in evidences:
        level, items = out.get(ev.requirement_id, (0, []))
        out[ev.requirement_id] = (max(level, ev.level), items + [ev])
    return out


# ---------------------------------------------------------------- 6축 점수


@dataclass
class AxisScore:
    axis: str
    target: Optional[float]  # 목표선 (1~5), 연결 요구 항목이 없으면 None
    evidence: Optional[float]  # 근거 점수 (1~5)
    self_rating: Optional[int]  # 자기평가 (1~5)
    quadrant: Optional[Quadrant]

    @property
    def self_minus_evidence(self) -> Optional[float]:
        if self.self_rating is None or self.evidence is None:
            return None
        return round(self.self_rating - self.evidence, 2)

    @property
    def gap_to_target(self) -> Optional[float]:
        if self.target is None or self.evidence is None:
            return None
        return round(max(0.0, self.target - self.evidence), 2)


def classify_quadrant(self_rating: float, evidence: float, target: Optional[float]) -> Quadrant:
    """목표선을 기준으로 자기평가·근거가 각각 충분한지로 방향 종류를 정한다."""
    threshold = target if target is not None else 3.0
    self_high = self_rating >= threshold
    ev_high = evidence >= threshold
    if self_high and not ev_high:
        return "record_proof"
    if self_high and ev_high:
        return "maintain_expand"
    if not self_high and ev_high:
        return "confidence_expression"
    return "learn_experience"


def axis_profile(
    goal: Goal, evidences: list[Evidence], self_ratings: Optional[dict[str, int]] = None
) -> dict[str, AxisScore]:
    """축별 목표선·근거 점수·자기평가·방향 종류."""
    self_ratings = self_ratings or {}
    best = best_evidence(evidences)
    result: dict[str, AxisScore] = {}
    for axis in axis_ids():
        linked = [r for r in goal.requirements if axis in r.axes]
        target = evidence = None
        if linked:
            weights = [requirement_weight(r) for r in linked]
            total = sum(weights) or 1.0
            target = level_to_scale(
                sum(w * r.required_level for w, r in zip(weights, linked)) / total
            )
            evidence = level_to_scale(
                sum(w * best.get(r.id, (0, []))[0] for w, r in zip(weights, linked)) / total
            )
        rating = self_ratings.get(axis)
        quadrant = (
            classify_quadrant(rating, evidence, target)
            if rating is not None and evidence is not None
            else None
        )
        result[axis] = AxisScore(axis, target, evidence, rating, quadrant)
    return result


# ---------------------------------------------------------------- 갭 · 우선순위


def step_cost_hours(current: int, required: int) -> float:
    """현재 수준 → 요구 수준까지 필요한 예상 시간 (planning.json 가정값)."""
    hours = load_planning()["step_hours"]
    return float(sum(hours[f"{lv}to{lv + 1}"] for lv in range(current, required)))


@dataclass
class GapItem:
    requirement: Requirement
    current_level: int
    gap: int
    cost_hours: float
    feasibility: float
    priority: float
    fits_plan: bool = False


@dataclass
class GapPlan:
    items: list[GapItem]
    available_hours: float
    total_cost_hours: float
    needs_adjustment: bool  # 남은 시간으로 모든 갭을 메울 수 없음 → 기한·목표선 조정 제안
    checklist: list[tuple[Requirement, bool]] = field(default_factory=list)  # (항목, 충족 여부)


def prioritize_gaps(
    goal: Goal,
    evidences: list[Evidence],
    style_share: Optional[dict[str, float]] = None,
) -> GapPlan:
    """우선순위 = 갭 × 중요도 × 기간 내 실현가능성 × (1 + 성향 적합 보정)."""
    p = load_planning()
    style_share = style_share or {}
    best = best_evidence(evidences)
    available = max(0.0, goal.weeks_left * goal.weekly_hours)

    items: list[GapItem] = []
    checklist: list[tuple[Requirement, bool]] = []
    for req in goal.requirements:
        current = best.get(req.id, (0, []))[0]
        if req.is_checklist_only:
            checklist.append((req, current >= req.required_level))
            continue
        gap = max(0, req.required_level - current)
        if gap == 0:
            continue
        cost = step_cost_hours(current, req.required_level)
        feasibility = 1.0 if cost <= available else (available / cost if cost else 1.0)
        bonus = p["style_bonus_max"] * style_share.get(req.style, 0.0) if req.style else 0.0
        priority = gap * requirement_weight(req) * feasibility * (1 + bonus)
        items.append(GapItem(req, current, gap, cost, round(feasibility, 3), round(priority, 4)))

    items.sort(key=lambda g: g.priority, reverse=True)
    used = 0.0
    for item in items:
        if used + item.cost_hours <= available:
            item.fits_plan = True
            used += item.cost_hours
    total = sum(i.cost_hours for i in items)
    return GapPlan(items, available, total, total > available, checklist)


# ---------------------------------------------------------------- 추세


def projected_weeks_to_target(history: list[float], target: float, window: int = 4) -> Optional[int]:
    """최근 주간 근거 점수 추세로 목표선 도달까지 남은 주 수를 추정. 상승 추세가 없으면 None."""
    if not history:
        return None
    if history[-1] >= target:
        return 0
    recent = history[-(window + 1):]
    if len(recent) < 2:
        return None
    slope = (recent[-1] - recent[0]) / (len(recent) - 1)
    if slope <= 0:
        return None
    weeks = (target - recent[-1]) / slope
    return int(weeks) + (0 if weeks == int(weeks) else 1)
