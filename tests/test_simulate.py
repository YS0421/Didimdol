import unittest

from didimdol_ai.simulate import run


class PersonaSimulationTest(unittest.TestCase):
    def test_five_personas_eight_weeks_no_violations(self):
        out = run()
        self.assertEqual(len(out["personas"]), 5)
        self.assertEqual(out["violations"], [])
        by = {p["persona"]: p for p in out["personas"]}
        # 과대평가 성향은 채찍질을 받고, 과소평가 성향은 받지 않는다
        self.assertGreater(by["4학년·졸업예정·과대평가"]["push_feedback"], 0)
        self.assertEqual(by["4학년·과소평가·경험 많음"]["push_feedback"], 0)
        # 시간이 부족해 보류가 이어지면 작은 첫걸음이 제안된다
        self.assertGreater(by["2학년·시간 부족"]["small_steps"], 0)


if __name__ == "__main__":
    unittest.main()
