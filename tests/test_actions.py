import unittest

from didimdol_ai.actions import load_templates, next_actions
from didimdol_ai.config import axis_ids
from didimdol_ai.models import Evidence, Goal, Requirement
from didimdol_ai.scoring import prioritize_gaps

REQS = [
    Requirement("a", "실험 결과 분석", 2, ["data", "research"], "posting", "required", kind="skill"),
    Requirement("b", "세포 실험", 2, ["research"], "posting", "preferred", kind="skill"),
    Requirement("c", "Origin", 2, ["data"], "posting", "preferred", kind="tool"),
    Requirement("d", "책임감", 1, ["collaboration"], "posting", "required", kind="attitude"),
    Requirement("e", "연구실 안전교육 이수", 1, [], "posting", "required", kind="certificate"),
]


class TemplateDataTest(unittest.TestCase):
    def test_every_axis_and_step_has_template(self):
        t = load_templates()
        for axis in axis_ids():
            for step in ("0to1", "1to2", "2to3"):
                tpl = t["by_axis"][axis][step]
                self.assertIn("{label}", tpl["title"])
                self.assertTrue(tpl["how"])


class NextActionsTest(unittest.TestCase):
    def setUp(self):
        goal = Goal("g", "목표", REQS, weeks_left=10, weekly_hours=10)
        self.plan = prioritize_gaps(goal, [Evidence("a", 1, "c1", "q")])

    def test_one_step_at_a_time_and_skips_attitude(self):
        acts = next_actions(self.plan.items, max_actions=5)
        by_id = {a.requirement_id: a for a in acts}
        self.assertNotIn("d", by_id)  # 태도는 행동 과제로 만들지 않음
        self.assertEqual((by_id["a"].from_level, by_id["a"].to_level, by_id["a"].hours), (1, 2, 20.0))
        self.assertIn("미니 분석", by_id["a"].title)  # data 축 1→2 템플릿
        self.assertEqual(by_id["b"].to_level, 1)  # 0→1부터
        self.assertIn("Origin", by_id["c"].title)  # 도구 템플릿

    def test_stuck_requirement_becomes_small_step(self):
        acts = next_actions(self.plan.items, stuck_requirement_ids={"a"})
        a = next(x for x in acts if x.requirement_id == "a")
        self.assertTrue(a.small_step)
        self.assertEqual(a.hours, 0.5)

    def test_max_actions(self):
        self.assertEqual(len(next_actions(self.plan.items, max_actions=2)), 2)


if __name__ == "__main__":
    unittest.main()
