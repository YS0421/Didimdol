"""데모 시나리오: 가상 학부생의 한 주 (실존 인물·실제 공고 아님).

목표: 한의학 분야 연구 인턴 (실험 결과 분석·세포실험 중심)
- 지난주보다 세포실험 근거가 늘었고, 마일스톤 하나를 끝냄 → 칭찬 재료
- 데이터 분석을 스스로 높게 보지만 근거가 부족 → 채찍질 재료
- 같은 마일스톤이 2주째 보류, 기한 3주 남았는데 시간 부족 → 채찍질 재료
"""

from __future__ import annotations

from typing import Optional

from .feedback import CoachTone, WeeklyFeedback, build_weekly_feedback
from .models import Checkin, Evidence, Goal, MilestoneResult, Requirement
from .scoring import GapPlan, axis_profile, prioritize_gaps

REQS = [
    Requirement("d1", "생물학 관련 지식", 1, ["domain"], "posting", "required", quote="생물학 관련 지식"),
    Requirement("d2", "실험 결과 분석 능력", 2, ["research", "data"], "posting", "required", quote="실험 결과 분석 능력"),
    Requirement("d3", "세포 및 동물실험 경험", 2, ["research"], "posting", "preferred", quote="세포 및 동물실험 유경험자"),
    Requirement("d4", "연구노트 작성", 1, ["communication"], "posting", "required", quote="연구노트 작성에 대한 기본 지식"),
]
PREV = [Evidence("d1", 1, "c3", "수강"), Evidence("d3", 1, "c3", "수강")]
NOW = [Evidence("d1", 1, "c3", "수강"), Evidence("d3", 2, "c1", "배양"), Evidence("d2", 1, "c2", "분석")]
RATINGS = {"research": 4, "data": 4, "domain": 2, "communication": 2}


def history_inputs():
    """월간 리포트 데모: 같은 목표로 4주간 기록이 쌓인 이력."""
    from .metrics import MentoringRecord, ReportInputs, WeekState
    from .models import ExperienceCard

    goal = Goal("demo", "한의학 분야 연구 인턴", REQS, weeks_left=3, weekly_hours=4)
    weeks = [
        ("2026-W43", [Evidence("d1", 1, "c3", "생물학 과목을 수강했다")], {"research": 3, "data": 3, "domain": 2, "communication": 2}, 4, []),
        ("2026-W44", PREV, {"research": 3, "data": 4, "domain": 2, "communication": 2}, 3,
         [MilestoneResult("m1", "세포실험 경험 카드 정리", "in_progress", requirement_id="d3")]),
        ("2026-W45", PREV, RATINGS, 2,
         [MilestoneResult("m1", "세포실험 경험 카드 정리", "in_progress", requirement_id="d3"),
          MilestoneResult("m2", "Python 데이터 분석 미니 프로젝트", "on_hold", "time", 1, requirement_id="d2")]),
        ("2026-W46", NOW, RATINGS, 3,
         [MilestoneResult("m1", "세포실험 경험 카드 정리", "done", requirement_id="d3"),
          MilestoneResult("m2", "Python 데이터 분석 미니 프로젝트", "on_hold", "time", 2, requirement_id="d2")]),
    ]
    history = [WeekState(Checkin(w, r, ms, hours_spent=h, condition=c), ev)
               for (w, ev, r, c, ms), h in zip(weeks, [3, 4, 2, 3])]
    cards = [
        ExperienceCard("c1", "학부연구생", "세포 독성 실험 보조", "프로토콜대로 세포를 배양하고 MTT assay로 측정했다. 결과를 엑셀로 정리해 공유했다.",
                       tools=["세포 배양", "MTT assay", "Excel"], period="2026.03"),
        ExperienceCard("c2", "수업 프로젝트", "생화학 실험 기말 프로젝트", "실험을 직접 설계하고 Python으로 통계 검정해 보고서를 썼다.",
                       role="팀장", tools=["DPPH assay", "Python", "pandas"], period="2025.09"),
        ExperienceCard("c3", "수업", "일반생물학·분자생물학 수강", "생물학 과목을 수강했다.", period="2025"),
    ]
    mentoring = [MentoringRecord("2026-W44", "학부연구생 경험을 어떻게 정리하면 좋을까요?", True, True),
                 MentoringRecord("2026-W46", "데이터 분석은 어디서부터 시작하면 좋을까요?", False)]
    return ReportInputs(goal, history, cards, {"analyze": 0.45, "make": 0.35, "talk": 0.1, "plan": 0.1}, mentoring)


def scenario(condition: Optional[int] = None, tone: CoachTone = "balanced") -> tuple[Goal, WeeklyFeedback, GapPlan]:
    goal = Goal("demo", "한의학 분야 연구 인턴", REQS, weeks_left=3, weekly_hours=4)
    checkin = Checkin(
        "2026-W46", RATINGS,
        milestones=[
            MilestoneResult("m1", "세포실험 경험 카드 정리", "done"),
            MilestoneResult("m2", "Python 데이터 분석 미니 프로젝트", "on_hold", "time", consecutive_hold_weeks=2),
        ],
        hours_spent=3, condition=condition,
    )
    plan = prioritize_gaps(goal, NOW)
    weekly = build_weekly_feedback(
        axis_profile(goal, NOW, RATINGS), axis_profile(goal, PREV, RATINGS),
        checkin, plan, goal.weeks_left, tone,
    )
    return goal, weekly, plan
