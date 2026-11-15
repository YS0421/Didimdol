"""피드백 문장 생성 테스트 (가짜 클라이언트, 실제 API 호출 없음)."""

import json
import unittest
from types import SimpleNamespace

from didimdol_ai.demo import scenario
from didimdol_ai.llm.feedback_writer import check_text, write_feedback


class FakeClient:
    def __init__(self, texts_by_index, healing="", stop_reason="end_turn"):
        self.calls = []
        self.texts, self.healing, self.stop_reason = texts_by_index, healing, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        out = {"messages": [{"index": i, "text": t} for i, t in self.texts.items()], "healing_text": self.healing}
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(out, ensure_ascii=False))],
                               model=kw["model"])


class DemoScenarioTest(unittest.TestCase):
    def test_scenario_produces_all_kinds(self):
        _, weekly, plan = scenario()
        reasons = {c.reason for c in weekly.all_candidates}
        self.assertTrue({"axis_up", "milestone_done", "overrated", "stuck_milestone", "deadline_gap"} <= reasons)
        self.assertTrue(plan.needs_adjustment)

    def test_low_condition_has_no_push(self):
        _, weekly, _ = scenario(condition=1, tone="direct")
        self.assertFalse(any(c.kind == "push" for c in weekly.items))
        self.assertTrue(weekly.suggest_healing)


class CheckTextTest(unittest.TestCase):
    def test_rules(self):
        allowed = {"2.33", "4", "3"}
        self.assertIsNone(check_text("데이터 분석 근거는 2.33점이에요. 이번 주 작은 분석 하나를 해 봐요.", allowed))
        self.assertIsNone(check_text("근거는 2.3점이에요.", allowed))  # 반올림 표기 허용
        self.assertEqual(check_text("근거가 1.5점 올랐어요.", allowed), "근거에 없는 숫자 1.5")
        self.assertEqual(check_text("다른 학생들보다 빨라요.", allowed), "타인 비교 표현")
        self.assertEqual(check_text("상위 10% 수준이에요.", {"10"}), "타인 비교 표현")
        self.assertEqual(check_text("이건 핑계예요.", allowed), "비난 표현")
        self.assertEqual(check_text("", allowed), "빈 문장")
        self.assertEqual(check_text("이번 주 컨디션은 1이었어요.", {"1"}), "컨디션 수치 언급")
        self.assertIsNone(check_text("우선순위가 높은 것부터 해 봐요.", allowed))  # '우선순위'는 비교 아님
        self.assertEqual(check_text("순위가 올랐어요.", allowed), "타인 비교 표현")

    def test_invisible_chars_removed(self):
        from didimdol_ai.llm.feedback_writer import clean
        self.assertEqual(clean("이 흐름 이어가요. ‍"), "이 흐름 이어가요.")

    def test_condition_not_sent_as_fact(self):
        from didimdol_ai.llm.feedback_writer import _facts
        _, weekly, _ = scenario(condition=1)
        low = next(c for c in weekly.all_candidates if c.reason == "low_condition")
        self.assertNotIn("condition", _facts(low))


class WriteFeedbackTest(unittest.TestCase):
    def test_good_text_used_bad_text_falls_back(self):
        goal, weekly, _ = scenario(tone="balanced")
        n = len(weekly.items)
        texts = {0: "지난주보다 연구·실험 근거가 쌓였어요. 이 흐름을 이어 가요."}
        if n > 1:
            texts[1] = "다른 지원자들보다 늦었으니 서둘러야 해요."  # 비교 표현 → 템플릿으로 대체
        written, healing = write_feedback(FakeClient(texts), weekly, "balanced", goal.title, goal.weeks_left)
        self.assertEqual(written[0].source, "llm")
        if n > 1:
            self.assertEqual(written[1].source, "template")
            self.assertEqual(written[1].text, weekly.items[1].message)
            self.assertEqual(written[1].rejected_reason, "타인 비교 표현")
        self.assertEqual(healing, "")

    def test_payload_and_request(self):
        goal, weekly, _ = scenario(condition=1, tone="direct")
        client = FakeClient({0: "괜찮아요."}, healing="숲길을 잠깐 걸어 봐요.")
        _, healing = write_feedback(client, weekly, "direct", goal.title, goal.weeks_left, ["실험 결과 분석 능력"])
        call = client.calls[0]
        payload = json.loads(call["messages"][0]["content"])
        self.assertTrue(payload["healing"])
        self.assertTrue(any(it["softened"] for it in payload["items"]) or all(it["kind"] != "채찍질" for it in payload["items"]))
        self.assertIn("직설형", payload["tone"])
        self.assertEqual(call["fallbacks"], "default")
        self.assertEqual(healing, "숲길을 잠깐 걸어 봐요.")

    def test_refusal_falls_back_to_templates(self):
        goal, weekly, _ = scenario()
        written, _ = write_feedback(FakeClient({}, stop_reason="refusal"), weekly, "balanced", goal.title, 3)
        self.assertTrue(all(w.source == "template" for w in written))


if __name__ == "__main__":
    unittest.main()
