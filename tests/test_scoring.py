import unittest

from didimdol_ai.config import axis_ids, load_axes
from didimdol_ai.scoring import (
    axis_profile,
    classify_quadrant,
    level_to_scale,
    prioritize_gaps,
    projected_weeks_to_target,
    step_cost_hours,
)
from tests.fixtures import energy_evidence, energy_goal


class AxesDataTest(unittest.TestCase):
    def test_six_fixed_axes_with_five_anchors(self):
        axes = load_axes()["axes"]
        self.assertEqual(len(axes), 6)
        for a in axes:
            self.assertEqual(sorted(a["anchors"]), ["1", "2", "3", "4", "5"])


class ConversionTest(unittest.TestCase):
    def test_level_to_scale(self):
        self.assertEqual(level_to_scale(0), 1.0)
        self.assertEqual(level_to_scale(3), 5.0)
        self.assertEqual(level_to_scale(1.5), 3.0)
        self.assertEqual(level_to_scale(9), 5.0)  # 범위 밖은 잘라냄

    def test_step_cost(self):
        self.assertEqual(step_cost_hours(0, 2), 28.0)
        self.assertEqual(step_cost_hours(2, 2), 0.0)


class AxisProfileTest(unittest.TestCase):
    def test_target_and_evidence(self):
        prof = axis_profile(energy_goal(), energy_evidence(), {"data": 4, "research": 4, "domain": 2})
        self.assertEqual(set(prof), set(axis_ids()))
        self.assertEqual(prof["data"].target, 3.67)
        self.assertEqual(prof["data"].evidence, 3.67)
        self.assertEqual(prof["research"].evidence, 2.33)
        # 연결된 요구 항목이 없는 축은 점수를 지어내지 않는다
        self.assertIsNone(prof["problem"].target)
        self.assertIsNone(prof["collaboration"].evidence)

    def test_quadrants_from_profile(self):
        prof = axis_profile(energy_goal(), energy_evidence(), {"data": 4, "research": 4, "domain": 2})
        self.assertEqual(prof["data"].quadrant, "maintain_expand")
        self.assertEqual(prof["research"].quadrant, "record_proof")
        self.assertEqual(prof["domain"].quadrant, "learn_experience")
        self.assertEqual(prof["research"].self_minus_evidence, 1.67)

    def test_classify_quadrant(self):
        self.assertEqual(classify_quadrant(2, 4, 3.5), "confidence_expression")
        self.assertEqual(classify_quadrant(2, 2, None), "learn_experience")


class GapPlanTest(unittest.TestCase):
    def test_priority_order_and_checklist(self):
        plan = prioritize_gaps(energy_goal(), energy_evidence())
        ids = [g.requirement.id for g in plan.items]
        self.assertNotIn("r1", ids)  # 이미 충족
        self.assertEqual(ids[0], "r2")  # 공고 우대 항목이 큐레이션 기본값보다 우선
        self.assertEqual(ids, ["r2", "r3", "r4"])
        self.assertEqual([(r.id, ok) for r, ok in plan.checklist], [("r5", False)])
        self.assertFalse(plan.needs_adjustment)
        self.assertTrue(all(g.fits_plan for g in plan.items))

    def test_needs_adjustment_when_time_short(self):
        plan = prioritize_gaps(energy_goal(weeks_left=2, weekly_hours=5), energy_evidence())
        self.assertTrue(plan.needs_adjustment)
        self.assertEqual(plan.available_hours, 10)
        self.assertFalse(plan.items[0].fits_plan or plan.items[0].feasibility == 1.0)

    def test_style_bonus_changes_ranking(self):
        goal = energy_goal()
        goal.requirements[2].style = "talk"  # r3
        base = prioritize_gaps(goal, energy_evidence())
        boosted = prioritize_gaps(goal, energy_evidence(), {"talk": 1.0})
        p_base = next(g.priority for g in base.items if g.requirement.id == "r3")
        p_boost = next(g.priority for g in boosted.items if g.requirement.id == "r3")
        self.assertAlmostEqual(p_boost, p_base * 1.2, places=3)


class ProjectionTest(unittest.TestCase):
    def test_projection(self):
        self.assertEqual(projected_weeks_to_target([2.0, 2.5, 3.0], 4.0), 2)
        self.assertEqual(projected_weeks_to_target([4.2], 4.0), 0)
        self.assertIsNone(projected_weeks_to_target([3.0, 3.0, 2.8], 4.0))
        self.assertIsNone(projected_weeks_to_target([], 4.0))


if __name__ == "__main__":
    unittest.main()
