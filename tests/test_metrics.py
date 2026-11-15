import json
import unittest

from didimdol_ai.demo import NOW, PREV, REQS, RATINGS
from didimdol_ai.metrics import (
    MentoringRecord, ReportInputs, WeekState, build_report, condition_trend, execution,
    goal_progress, requirement_coverage, style_alignment, tech_stack,
)
from didimdol_ai.models import Checkin, ExperienceCard, Goal, MilestoneResult
from didimdol_ai.scoring import axis_profile

GOAL = Goal("demo", "연구 인턴", REQS, weeks_left=6, weekly_hours=6)
CARDS = [
    ExperienceCard("c1", "학부연구생", "세포 실험", "프로토콜대로 세포를 배양하고 측정했다.", tools=["MTT assay", "Excel"], period="2026.03"),
    ExperienceCard("c2", "수업 프로젝트", "분석 프로젝트", "데이터를 분석하고 통계 검정 결과를 발표했다.", tools=["Python", "Excel"], period="2025.09"),
]


def week(w, evid, cond=None, ms=(), hours=None):
    return WeekState(Checkin(w, RATINGS, list(ms), hours, cond), evid)


class MetricTest(unittest.TestCase):
    def test_goal_progress_bounded(self):
        gp = goal_progress(axis_profile(GOAL, NOW, RATINGS))
        self.assertTrue(0 < gp["achievement"] <= 1)

    def test_coverage(self):
        cov = requirement_coverage(GOAL, NOW)
        self.assertEqual(sum(cov["counts"].values()), len(REQS))
        self.assertEqual(cov["counts"].get("충족"), 2)  # d1(1/1), d3(2/2)

    def test_execution(self):
        cks = [
            Checkin("W1", {}, [MilestoneResult("m1", "a", "in_progress")], hours_spent=4),
            Checkin("W2", {}, [MilestoneResult("m1", "a", "done"), MilestoneResult("m2", "b", "on_hold", "time")], hours_spent=2),
        ]
        ex = execution(cks, 6)
        self.assertEqual((ex["milestones_done"], ex["milestones_total"]), (1, 2))
        self.assertEqual(ex["hold_reasons"], {"time": 1})
        self.assertEqual(ex["hours_ratio"], 0.5)

    def test_tech_stack_and_style(self):
        ts = tech_stack(CARDS)
        self.assertEqual(ts[0], {"tool": "Excel", "count": 2, "latest_period": "2026.03"})
        st = style_alignment({"analyze": 0.5, "make": 0.5}, CARDS)
        self.assertIsNotNone(st["alignment"])
        self.assertAlmostEqual(sum(st["activity_share"].values()), 1.0, places=1)

    def test_condition_is_private_and_needs_4_weeks(self):
        cks = [Checkin(f"W{i}", {}, [MilestoneResult("m", "a", "done" if i % 2 else "on_hold")], condition=c)
               for i, c in enumerate([2, 4, 2, 5])]
        ct = condition_trend(cks)
        self.assertTrue(ct["private"])
        self.assertIsNotNone(ct["condition_vs_execution"])
        self.assertIsNone(condition_trend(cks[:3])["condition_vs_execution"])


class ReportTest(unittest.TestCase):
    def test_weekly_and_monthly_are_json_serializable(self):
        hist = [week("W1", PREV, 4, hours=3), week("W2", NOW, 3, [MilestoneResult("m1", "카드 정리", "done")], 5)]
        inp = ReportInputs(GOAL, hist, CARDS, {"analyze": 0.5, "make": 0.5}, [MentoringRecord("W2", "질문", True, True)])
        weekly = build_report(inp, "weekly")
        monthly = build_report(inp, "monthly")
        json.dumps(weekly, ensure_ascii=False)
        json.dumps(monthly, ensure_ascii=False)
        self.assertNotIn("condition", weekly)
        self.assertEqual(monthly["mentoring"], {"asked": 1, "answered": 1, "followed_up": 1})
        self.assertEqual(monthly["series"]["weeks"], ["W1", "W2"])
        self.assertEqual(weekly["growth"]["most_grown"], "research")
        self.assertTrue(weekly["next_actions"])

    def test_stuck_milestone_turns_its_requirement_into_small_step(self):
        stuck = MilestoneResult("m2", "분석 미니 프로젝트", "on_hold", "time", consecutive_hold_weeks=2, requirement_id="d2")
        report = build_report(ReportInputs(GOAL, [week("W2", NOW, ms=[stuck])], CARDS))
        d2 = next(a for a in report["next_actions"] if a["requirement_id"] == "d2")
        self.assertTrue(d2["small_step"])

    def test_empty_history_raises(self):
        with self.assertRaises(ValueError):
            build_report(ReportInputs(GOAL, [], CARDS))


if __name__ == "__main__":
    unittest.main()
