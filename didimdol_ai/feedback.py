"""주간 피드백 규칙 엔진.

규칙이 피드백 '종류'(칭찬·격려·채찍질)와 근거를 정하고,
문장은 템플릿 기본값을 두되 운영에서는 LLM이 코치 톤에 맞춰 다시 쓴다.
컨디션이 낮으면 채찍질은 자동으로 격려로 바뀌고 숲 힐링을 제안한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from .config import axis_names, load_planning
from .text import fix_josa
from .models import Checkin
from .scoring import AxisScore, GapPlan

Kind = Literal["praise", "encourage", "push"]
CoachTone = Literal["praise", "balanced", "direct"]

TEMPLATES: dict[str, str] = {
    "axis_up": "{axis} 근거 점수가 {prev} → {now}로 올랐어요. 기록한 경험이 쌓이고 있어요.",
    "milestone_done": "'{title}'을(를) 끝냈어요. 목표에 한 칸 더 가까워졌어요.",
    "underrated": "{axis}은(는) 스스로 {self}점으로 봤지만, 기록된 근거는 {evidence}점이에요. 생각보다 잘하고 있어요.",
    "returned": "다시 돌아와 줘서 반가워요. 쉬어 간 주가 있어도 길은 이어져 있어요.",
    "stagnation": "이번 주는 숫자가 움직이지 않았어요. 다음 한 칸을 더 작게 나눠 볼까요?",
    "external_hold": "'{title}'은(는) 상황 때문에 잠시 멈췄네요. 여건이 될 때 이어서 하면 돼요.",
    "low_condition": "이번 주는 컨디션이 낮았네요. 오늘은 쉬어 가는 것도 준비의 일부예요.",
    "overrated": "{axis}은(는) 스스로 {self}점으로 봤지만, 기록된 근거는 {evidence}점이에요. 이미 한 경험이라면 카드로 남기고, 아니라면 증명할 결과물을 하나 만들어 봐요.",
    "stuck_milestone": "'{title}'이(가) {weeks}주째 멈춰 있어요. 이번 주에 끝낼 수 있는 크기로 쪼개 볼게요.",
    "deadline_gap": "목표 기한까지 {weeks}주 남았는데, 남은 시간으로는 모든 갭을 메우기 어려워요. 우선순위 상위 항목에 집중하거나 목표를 조정해 봐요.",
}

TONE_ORDER: dict[CoachTone, list[Kind]] = {
    "direct": ["push", "praise", "encourage"],
    "balanced": ["praise", "push", "encourage"],
    "praise": ["praise", "encourage", "push"],
}


@dataclass
class FeedbackItem:
    kind: Kind
    reason: str
    message: str
    axis: Optional[str] = None
    evidence: dict = field(default_factory=dict)  # 리포트에 함께 표시할 근거 데이터
    softened: bool = False  # 컨디션 때문에 채찍질 → 격려로 바뀐 경우
    suggest_split: bool = False  # 마일스톤을 더 작게 쪼개 제안


@dataclass
class WeeklyFeedback:
    items: list[FeedbackItem]
    suggest_healing: bool
    all_candidates: list[FeedbackItem]  # 상한 적용 전 전체 (월간 리포트·디버깅용)


def _item(kind: Kind, reason: str, axis: Optional[str] = None, **ctx) -> FeedbackItem:
    names = axis_names()
    fmt = {"axis": names.get(axis, axis or ""), **ctx}
    return FeedbackItem(kind, reason, fix_josa(TEMPLATES[reason].format(**fmt)), axis, dict(ctx))


def build_weekly_feedback(
    now: dict[str, AxisScore],
    prev: Optional[dict[str, AxisScore]],
    checkin: Checkin,
    gap_plan: GapPlan,
    weeks_left: int,
    coach_tone: CoachTone = "balanced",
) -> WeeklyFeedback:
    cfg = load_planning()["feedback"]
    cands: list[FeedbackItem] = []

    # --- 칭찬
    for axis, s in now.items():
        p = prev.get(axis) if prev else None
        if p and s.evidence is not None and p.evidence is not None and s.evidence - p.evidence >= 0.1:
            cands.append(_item("praise", "axis_up", axis, prev=p.evidence, now=s.evidence))
    for m in checkin.milestones:
        if m.status == "done":
            cands.append(_item("praise", "milestone_done", title=m.title))
    for axis, s in now.items():
        diff = s.self_minus_evidence
        if diff is not None and -diff >= cfg["underrate_threshold"]:
            cands.append(_item("praise", "underrated", axis, self=s.self_rating, evidence=s.evidence))

    # --- 격려
    if checkin.missed_previous_week:
        cands.append(_item("encourage", "returned"))
    low_condition = checkin.condition is not None and checkin.condition <= cfg["low_condition_max"]
    if low_condition:
        cands.append(_item("encourage", "low_condition", condition=checkin.condition))
    for m in checkin.milestones:
        if m.status == "on_hold" and m.hold_reason == "external":
            cands.append(_item("encourage", "external_hold", title=m.title))
    if prev and not any(c.reason in ("axis_up", "milestone_done") for c in cands):
        cands.append(_item("encourage", "stagnation"))

    # --- 채찍질
    for axis, s in now.items():
        diff = s.self_minus_evidence
        if diff is not None and diff >= cfg["overrate_threshold"]:
            cands.append(_item("push", "overrated", axis, self=s.self_rating, evidence=s.evidence))
    for m in checkin.milestones:
        if m.status == "on_hold" and m.consecutive_hold_weeks >= cfg["stuck_weeks"]:
            item = _item("push", "stuck_milestone", title=m.title, weeks=m.consecutive_hold_weeks)
            item.suggest_split = True
            cands.append(item)
    if weeks_left <= cfg["deadline_alert_weeks"] and gap_plan.needs_adjustment:
        cands.append(_item("push", "deadline_gap", weeks=weeks_left))

    # --- 컨디션이 낮으면 채찍질 억제 → 격려로 전환
    if low_condition:
        for c in cands:
            if c.kind == "push":
                c.kind = "encourage"
                c.softened = True

    # --- 코치 톤에 따른 정렬 (컨디션 낮으면 격려 우선)
    order = ["encourage", "praise", "push"] if low_condition else TONE_ORDER[coach_tone]
    ranked = sorted(cands, key=lambda c: order.index(c.kind))

    # 같은 종류만 몰리지 않게: 종류별 1개씩 먼저 뽑고 남은 자리를 채운다
    picked: list[FeedbackItem] = []
    for kind in order:
        first = next((c for c in ranked if c.kind == kind), None)
        if first and len(picked) < cfg["max_items_weekly"]:
            picked.append(first)
    for c in ranked:
        if len(picked) >= cfg["max_items_weekly"]:
            break
        if c not in picked:
            picked.append(c)
    picked.sort(key=lambda c: order.index(c.kind))

    return WeeklyFeedback(picked, suggest_healing=low_condition, all_candidates=ranked)
