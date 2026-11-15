"""페르소나 시뮬레이션 (LLM 없음): 가상 학생 5명 × 8주를 돌려 리포트·피드백·행동 제안이 원칙을 지키는지 검사.

검사 항목 (위반이 하나라도 있으면 실패):
- 모든 주의 주간·월간 리포트가 계산되고 JSON·HTML로 만들어진다
- 리포트·피드백 문장에 타인 비교 표현이 없다
- 컨디션이 낮은(≤2) 주에는 채찍질이 나가지 않고 숲 힐링이 제안된다
- 근거가 늘면 목표 달성도가 줄지 않는다 (단조성)
- 주간 피드백은 최대 2개
- 연속 보류된 마일스톤의 항목은 '작은 첫걸음'으로 제안된다
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from .feedback import build_weekly_feedback
from .metrics import ReportInputs, WeekState, build_report
from .models import Checkin, Evidence, ExperienceCard, Goal, MilestoneResult, Requirement
from .report_html import render
from .scoring import axis_profile, prioritize_gaps

from .llm.feedback_writer import COMPARISON_WORDS_RE as COMPARISON  # 피드백 검사와 같은 비교 표현 규칙

REQS = [
    Requirement("p1", "생물학 관련 지식", 1, ["domain"], "posting", "required", kind="knowledge"),
    Requirement("p2", "실험 결과 분석 능력", 2, ["research", "data"], "posting", "required", kind="skill"),
    Requirement("p3", "세포 및 동물실험 경험", 2, ["research"], "posting", "preferred", kind="skill"),
    Requirement("p4", "연구노트 작성", 1, ["communication"], "posting", "required", kind="skill"),
    Requirement("p5", "Python", 2, ["data"], "posting", "preferred", kind="tool"),
    Requirement("p6", "책임감", 1, ["collaboration"], "posting", "required", kind="attitude"),
    Requirement("p7", "연구실 안전교육 이수", 1, [], "posting", "required", kind="certificate"),
]


@dataclass
class Persona:
    name: str
    grade: str
    start_levels: dict[str, int]  # 요구 항목 → 시작 근거 수준
    growth_weeks: dict[str, int]  # 요구 항목 → 그 주에 한 단계 오름
    self_bias: int  # 자기평가 경향 (+1 과대, -1 과소, 0)
    weekly_hours: float
    low_condition_weeks: set[int]
    stuck_from: int  # 이 주부터 같은 마일스톤이 보류됨 (0이면 없음)


PERSONAS = [
    Persona("1학년·경험 거의 없음", "1학년", {}, {"p1": 2, "p4": 5}, 0, 4, {3}, 0),
    Persona("3학년·학부연구생", "3학년", {"p1": 1, "p3": 1}, {"p3": 2, "p2": 4, "p5": 6}, 1, 8, set(), 0),
    Persona("4학년·졸업예정·과대평가", "4학년", {"p1": 1, "p2": 1}, {"p4": 3}, 2, 6, set(), 5),
    Persona("4학년·과소평가·경험 많음", "4학년", {"p1": 1, "p2": 2, "p3": 2, "p5": 1}, {"p5": 3, "p4": 4}, -1, 10, {6, 7}, 0),
    Persona("2학년·시간 부족", "2학년", {"p1": 1}, {"p2": 7}, 0, 2, {2, 4, 6}, 3),
]


def _week_states(p: Persona, rng: random.Random) -> list[WeekState]:
    levels = dict(p.start_levels)
    states = []
    for w in range(1, 9):
        for rid, wk in p.growth_weeks.items():
            if wk == w:
                levels[rid] = min(3, levels.get(rid, 0) + 1)
        evid = [Evidence(rid, lv, f"card-{rid}", "기록") for rid, lv in levels.items() if lv > 0]
        prof = axis_profile(Goal("g", "t", REQS, 9 - w, p.weekly_hours), evid)
        ratings = {a: max(1, min(5, round((s.evidence or 1) + p.self_bias))) for a, s in prof.items() if s.target}
        ms = [MilestoneResult("m-done", "카드 정리", "done" if w % 2 == 0 else "in_progress", requirement_id="p4")]
        if p.stuck_from and w >= p.stuck_from:
            ms.append(MilestoneResult("m-stuck", "분석 미니 프로젝트", "on_hold", "time", w - p.stuck_from + 1,
                                      requirement_id="p2"))
        cond = 2 if w in p.low_condition_weeks else rng.choice([3, 4, 5])
        states.append(WeekState(Checkin(f"W{w}", ratings, ms, round(p.weekly_hours * rng.uniform(0.5, 1.1), 1), cond,
                                        missed_previous_week=(w == 5 and p.name.startswith("2학년"))), evid))
    return states


def run(seed: int = 7) -> dict:
    rng = random.Random(seed)
    results, violations = [], []
    for p in PERSONAS:
        states = _week_states(p, rng)
        cards = [ExperienceCard(f"card-{r}", "학부연구생", f"{r} 경험", "실험 데이터를 분석했다", tools=["Python"])
                 for r in p.start_levels]
        last_ach = -1.0
        pushes = healings = small_steps = 0
        for w in range(1, len(states) + 1):
            goal = Goal("g", f"{p.name} 목표", REQS, 9 - w, p.weekly_hours)
            hist = states[:w]
            for kind in ("weekly", "monthly"):
                rep = build_report(ReportInputs(goal, hist, cards, {"analyze": .5, "make": .5}), kind)
                json.dumps(rep, ensure_ascii=False)
                page = render(rep)
                if COMPARISON.search(page):
                    violations.append(f"{p.name} W{w} {kind}: 비교 표현")
            ach = rep["goal_progress"]["achievement"] or 0
            if ach + 1e-9 < last_ach:
                violations.append(f"{p.name} W{w}: 근거가 줄지 않았는데 달성도 감소 {last_ach}→{ach}")
            last_ach = ach
            now_s, prev_s = hist[-1], hist[-2] if w > 1 else None
            now = axis_profile(goal, now_s.evidences, now_s.checkin.self_ratings)
            prev = axis_profile(goal, prev_s.evidences, prev_s.checkin.self_ratings) if prev_s else None
            for tone in ("praise", "balanced", "direct"):
                fb = build_weekly_feedback(now, prev, now_s.checkin, prioritize_gaps(goal, now_s.evidences),
                                           goal.weeks_left, tone)
                if len(fb.items) > 2:
                    violations.append(f"{p.name} W{w}: 피드백 {len(fb.items)}개")
                low = (now_s.checkin.condition or 5) <= 2
                if low and any(i.kind == "push" for i in fb.items):
                    violations.append(f"{p.name} W{w} {tone}: 컨디션 낮은데 채찍질")
                if low and not fb.suggest_healing:
                    violations.append(f"{p.name} W{w}: 힐링 제안 누락")
                if any(COMPARISON.search(i.message) for i in fb.items):
                    violations.append(f"{p.name} W{w}: 피드백 비교 표현")
                pushes += sum(i.kind == "push" for i in fb.items)
                healings += fb.suggest_healing
            stuck_ids = {m.requirement_id for m in now_s.checkin.milestones if m.consecutive_hold_weeks >= 2}
            p2_action = next((a for a in rep["next_actions"] if a["requirement_id"] == "p2"), None)
            if "p2" in stuck_ids and p2_action and not p2_action["small_step"]:
                violations.append(f"{p.name} W{w}: 보류 항목이 작은 첫걸음으로 안 바뀜")
            small_steps += sum(a["small_step"] for a in rep["next_actions"])
        results.append({"persona": p.name, "final_achievement": last_ach, "push_feedback": pushes,
                        "healing_weeks": healings // 3, "small_steps": small_steps})
    return {"personas": results, "violations": violations}


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out = run()
    for r in out["personas"]:
        print(f"- {r['persona']}: 최종 달성도 {r['final_achievement']:.0%}, 채찍질 {r['push_feedback']}회, "
              f"힐링 제안 {r['healing_weeks']}주, 작은 첫걸음 {r['small_steps']}회")
    print("위반 없음 ✓" if not out["violations"] else "위반:\n  " + "\n  ".join(out["violations"]))
    raise SystemExit(1 if out["violations"] else 0)
