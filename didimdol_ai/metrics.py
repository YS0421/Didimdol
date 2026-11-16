"""리포트 지표 (모두 '내 목표'와 '과거의 나' 기준, 타인 비교 없음).

입력: 목표, 주간 이력(체크인 + 그 주 시점의 근거 목록), 경험 카드, 성향 분포, 멘토링 기록
출력: JSON으로 바로 내보낼 수 있는 dict (API·HTML 리포트 공용)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from .config import axis_ids, axis_names
from .models import Checkin, Evidence, ExperienceCard, Goal
from .scoring import AxisScore, axis_profile, best_evidence, prioritize_gaps, projected_weeks_to_target

STYLE_KEYWORDS = {
    "analyze": r"분석|데이터|통계|원인|해석|검정|비교",
    "make": r"실험|제작|만들|구현|배양|측정|설계|코딩|개발",
    "talk": r"발표|토론|소통|설명|공유|인터뷰",
    "plan": r"계획|일정|기획|관리|팀장|조율|정리",
}


@dataclass
class WeekState:
    checkin: Checkin
    evidences: list[Evidence]  # 그 주 시점까지 쌓인 근거


@dataclass
class MentoringRecord:
    week: str
    question: str
    answered: bool
    followed_up: bool = False  # 받은 조언을 행동(마일스톤·카드)으로 옮겼는지


@dataclass
class ReportInputs:
    goal: Goal
    history: list[WeekState]  # 오래된 주 → 최근 주
    cards: list[ExperienceCard]
    style_share: dict[str, float] = field(default_factory=dict)
    mentoring: list[MentoringRecord] = field(default_factory=list)


def _axis_dict(s: AxisScore) -> dict:
    return {"target": s.target, "evidence": s.evidence, "self": s.self_rating, "quadrant": s.quadrant,
            "gap_to_target": s.gap_to_target, "self_minus_evidence": s.self_minus_evidence}


# ---------------------------------------------------------------- 개별 지표


def goal_progress(now: dict[str, AxisScore]) -> dict:
    axes = [s for s in now.values() if s.target]
    if not axes:
        return {"achievement": None, "by_axis": {}}
    achieved = sum(min(s.evidence or 1, s.target) for s in axes)
    return {"achievement": round(achieved / sum(s.target for s in axes), 3),
            "by_axis": {s.axis: s.gap_to_target for s in axes}}


def growth(prev: Optional[dict[str, AxisScore]], now: dict[str, AxisScore]) -> dict:
    if not prev:
        return {"deltas": {}, "most_grown": None, "stalled": []}
    deltas = {a: round((now[a].evidence or 0) - (prev[a].evidence or 0), 2)
              for a in now if now[a].evidence is not None and prev.get(a) and prev[a].evidence is not None}
    grown = max(deltas, key=deltas.get) if deltas and max(deltas.values()) > 0 else None
    stalled = [a for a, d in deltas.items() if d == 0 and (now[a].gap_to_target or 0) > 0]
    return {"deltas": deltas, "most_grown": grown, "stalled": stalled}


def self_awareness(history_profiles: list[dict[str, AxisScore]]) -> dict:
    diffs: dict[str, list[float]] = {}
    for prof in history_profiles:
        for a, s in prof.items():
            if s.self_minus_evidence is not None:
                diffs.setdefault(a, []).append(s.self_minus_evidence)
    tendency = {}
    for a, ds in diffs.items():
        m = mean(ds)
        tendency[a] = "과대평가 경향" if m >= 1 else "과소평가 경향" if m <= -1 else "비슷하게 보고 있음"
    return {"latest": {a: ds[-1] for a, ds in diffs.items()},
            "mean": {a: round(mean(ds), 2) for a, ds in diffs.items()}, "tendency": tendency}


def requirement_coverage(goal: Goal, evidences: list[Evidence]) -> dict:
    best = best_evidence(evidences)
    rows, counts = [], Counter()
    for r in goal.requirements:
        level = best.get(r.id, (0, []))[0]
        status = "충족" if level >= r.required_level else "부분" if level > 0 else "없음"
        counts[status] += 1
        rows.append({"id": r.id, "label": r.label, "required": r.required_level, "current": level,
                     "status": status, "necessity": r.necessity, "checklist": r.is_checklist_only})
    total = len(goal.requirements) or 1
    return {"counts": dict(counts), "covered_ratio": round(counts["충족"] / total, 3), "items": rows}


def execution(checkins: list[Checkin], planned_weekly_hours: float) -> dict:
    last_status: dict[str, str] = {}
    hold_reasons = Counter()
    for c in checkins:
        for m in c.milestones:
            last_status[m.milestone_id] = m.status
            if m.status == "on_hold" and m.hold_reason:
                hold_reasons[m.hold_reason] += 1
    done = sum(1 for s in last_status.values() if s == "done")
    hours = [c.hours_spent for c in checkins if c.hours_spent is not None]
    return {
        "milestone_completion": round(done / len(last_status), 3) if last_status else None,
        "milestones_done": done, "milestones_total": len(last_status),
        "hold_reasons": dict(hold_reasons),
        "avg_hours": round(mean(hours), 1) if hours else None,
        "planned_hours": planned_weekly_hours,
        "hours_ratio": round(mean(hours) / planned_weekly_hours, 2) if hours and planned_weekly_hours else None,
    }


def activity_pattern(cards: list[ExperienceCard], checkins: list[Checkin], total_weeks: int) -> dict:
    return {"card_kinds": dict(Counter(c.kind for c in cards)),
            "checkin_weeks": [c.week for c in checkins],
            "consistency": round(len(checkins) / total_weeks, 2) if total_weeks else None}


def tech_stack(cards: list[ExperienceCard]) -> list[dict]:
    seen: dict[str, dict] = {}
    for c in cards:
        for t in c.tools:
            item = seen.setdefault(t, {"tool": t, "count": 0, "latest_period": ""})
            item["count"] += 1
            if c.period and c.period > item["latest_period"]:
                item["latest_period"] = c.period
    return sorted(seen.values(), key=lambda x: (-x["count"], x["tool"]))


def style_alignment(style_share: dict[str, float], cards: list[ExperienceCard]) -> dict:
    counts = Counter()
    for c in cards:
        text = c.actions + " " + c.role
        for style, pat in STYLE_KEYWORDS.items():
            counts[style] += len(re.findall(pat, text))
    total = sum(counts.values())
    activity = {s: round(counts[s] / total, 2) for s in STYLE_KEYWORDS} if total else {}
    if not activity or not style_share:
        return {"activity_share": activity, "self_share": style_share, "alignment": None}
    l1 = sum(abs(activity.get(s, 0) - style_share.get(s, 0)) for s in STYLE_KEYWORDS)
    return {"activity_share": activity, "self_share": style_share, "alignment": round(1 - l1 / 2, 2)}


def strength_narrative(goal: Goal, cards: list[ExperienceCard], evidences: list[Evidence]) -> list[dict]:
    labels = {r.id: r.label for r in goal.requirements}
    per_card: dict[str, list[Evidence]] = {}
    for e in evidences:
        per_card.setdefault(e.card_id, []).append(e)
    titles = {c.id: c.title for c in cards}
    ranked = sorted(per_card.items(), key=lambda kv: (-sum(e.level for e in kv[1]), kv[0]))
    return [{"card_id": cid, "title": titles.get(cid, cid), "score": sum(e.level for e in evs),
             "keywords": [labels.get(e.requirement_id, e.requirement_id) for e in evs],
             "quotes": [e.quote for e in evs]} for cid, evs in ranked[:3]]


def mentoring_summary(records: list[MentoringRecord]) -> dict:
    answered = [r for r in records if r.answered]
    return {"asked": len(records), "answered": len(answered),
            "followed_up": sum(1 for r in answered if r.followed_up)}


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 4:
        return None
    mx, my = mean(xs), mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def condition_trend(checkins: list[Checkin]) -> dict:
    """본인에게만 보여주는 지표. 진로 점수와 섞지 않는다."""
    pts = [(c.week, c.condition) for c in checkins if c.condition is not None]
    pairs = [(c.condition, sum(m.status == "done" for m in c.milestones) / len(c.milestones))
             for c in checkins if c.condition is not None and c.milestones]
    corr = _pearson([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
    return {"private": True, "series": pts, "condition_vs_execution": corr}


# ---------------------------------------------------------------- 리포트 묶음


def build_report(inp: ReportInputs, kind: str = "weekly") -> dict:
    goal, history = inp.goal, inp.history
    if not history:
        raise ValueError("체크인 이력이 없어요.")
    profiles = [axis_profile(goal, w.evidences, w.checkin.self_ratings) for w in history]
    now, prev = profiles[-1], profiles[-2] if len(profiles) > 1 else None
    evidences = history[-1].evidences
    names = axis_names()
    series = {a: [p[a].evidence for p in profiles] for a in axis_ids()}
    targets = {a: now[a].target for a in axis_ids()}
    projected = {a: projected_weeks_to_target([v for v in series[a] if v is not None], targets[a])
                 for a in axis_ids() if targets[a] is not None}
    plan = prioritize_gaps(goal, evidences, inp.style_share)

    from .actions import next_actions  # 순환 import 방지

    stuck = {m.requirement_id for m in history[-1].checkin.milestones
             if m.consecutive_hold_weeks >= 2 and m.requirement_id}
    report = {
        "kind": kind,
        "goal": {"title": goal.title, "weeks_left": goal.weeks_left, **({"means": goal.means} if goal.means else {})},
        "week": history[-1].checkin.week,
        "axis_names": names,
        "axes": {a: _axis_dict(s) for a, s in now.items()},
        "previous_axes": {a: _axis_dict(s) for a, s in prev.items()} if prev else None,
        "goal_progress": goal_progress(now),
        "growth": growth(prev, now),
        "projected_weeks": projected,
        "next_actions": [a.to_dict() for a in next_actions(plan.items, stuck_requirement_ids=stuck)],
        "needs_adjustment": plan.needs_adjustment,
        "checklist": [{"label": r.label, "done": ok} for r, ok in plan.checklist],
    }
    if kind == "monthly":
        checkins = [w.checkin for w in history]
        report.update({
            "series": {"weeks": [c.week for c in checkins], "evidence": series,
                       "self": {a: [p[a].self_rating for p in profiles] for a in axis_ids()}, "targets": targets},
            "self_awareness": self_awareness(profiles),
            "requirement_coverage": requirement_coverage(goal, evidences),
            "execution": execution(checkins, goal.weekly_hours),
            "activity": activity_pattern(inp.cards, checkins, len(history)),
            "tech_stack": tech_stack(inp.cards),
            "style": style_alignment(inp.style_share, inp.cards),
            "strengths": strength_narrative(goal, inp.cards, evidences),
            "mentoring": mentoring_summary(inp.mentoring),
            "condition": condition_trend(checkins),
        })
    return report
