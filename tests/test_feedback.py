import unittest

from didimdol_ai.feedback import build_weekly_feedback
from didimdol_ai.models import Checkin, MilestoneResult
from didimdol_ai.scoring import axis_profile, prioritize_gaps
from tests.fixtures import energy_evidence, energy_goal

RATINGS = {"data": 2, "research": 4, "domain": 2, "communication": 1}


def run(checkin, prev_evidence=None, tone="balanced", weeks_left=8, goal=None):
    goal = goal or energy_goal(weeks_left=weeks_left)
    now = axis_profile(goal, energy_evidence(), checkin.self_ratings)
    prev = axis_profile(goal, prev_evidence, checkin.self_ratings) if prev_evidence is not None else None
    plan = prioritize_gaps(goal, energy_evidence())
    return build_weekly_feedback(now, prev, checkin, plan, weeks_left, tone)


class FeedbackTest(unittest.TestCase):
    def test_overrate_is_push_and_underrate_is_praise(self):
        fb = run(Checkin("2026-W46", RATINGS))
        reasons = {(c.kind, c.reason, c.axis) for c in fb.all_candidates}
        self.assertIn(("push", "overrated", "research"), reasons)  # 4 vs 2.33
        self.assertIn(("praise", "underrated", "data"), reasons)  # 2 vs 3.67
        self.assertFalse(fb.suggest_healing)

    def test_low_condition_suppresses_push(self):
        fb = run(Checkin("2026-W46", RATINGS, condition=1), tone="direct")
        self.assertTrue(fb.suggest_healing)
        self.assertFalse(any(c.kind == "push" for c in fb.all_candidates))
        self.assertTrue(any(c.softened for c in fb.all_candidates))
        self.assertEqual(fb.items[0].kind, "encourage")

    def test_tone_controls_order_and_cap(self):
        direct = run(Checkin("2026-W46", RATINGS), tone="direct")
        gentle = run(Checkin("2026-W46", RATINGS), tone="praise")
        self.assertEqual(direct.items[0].kind, "push")
        self.assertEqual(gentle.items[0].kind, "praise")
        self.assertLessEqual(len(direct.items), 2)

    def test_stuck_milestone_suggests_split(self):
        ms = [MilestoneResult("m1", "미니 분석 프로젝트", "on_hold", "time", consecutive_hold_weeks=2)]
        fb = run(Checkin("2026-W46", RATINGS, milestones=ms))
        stuck = [c for c in fb.all_candidates if c.reason == "stuck_milestone"]
        self.assertEqual(len(stuck), 1)
        self.assertTrue(stuck[0].suggest_split)

    def test_axis_up_and_milestone_done_praised(self):
        prev = [e for e in energy_evidence() if e.requirement_id != "r1"]  # 지난주엔 r1 근거 없음
        ms = [MilestoneResult("m1", "분석 카드 정리", "done")]
        fb = run(Checkin("2026-W46", RATINGS, milestones=ms), prev_evidence=prev)
        reasons = {c.reason for c in fb.all_candidates}
        self.assertIn("axis_up", reasons)
        self.assertIn("milestone_done", reasons)
        self.assertNotIn("stagnation", reasons)

    def test_stagnation_and_return(self):
        fb = run(Checkin("2026-W46", RATINGS, missed_previous_week=True), prev_evidence=energy_evidence())
        reasons = {c.reason for c in fb.all_candidates}
        self.assertIn("stagnation", reasons)
        self.assertIn("returned", reasons)

    def test_deadline_gap(self):
        goal = energy_goal(weeks_left=2, weekly_hours=5)
        fb = run(Checkin("2026-W46", RATINGS), weeks_left=2, goal=goal)
        self.assertIn("deadline_gap", {c.reason for c in fb.all_candidates})


if __name__ == "__main__":
    unittest.main()
