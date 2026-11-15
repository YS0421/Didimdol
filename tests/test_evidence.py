"""경험 카드 근거 판정 테스트 (가짜 클라이언트, 실제 API 호출 없음)."""

import json
import unittest
from types import SimpleNamespace

from didimdol_ai.llm.evidence import _schema, judge_card, mask_pii
from didimdol_ai.llm.requirements import ExtractionError
from didimdol_ai.models import ExperienceCard, Goal, Requirement
from didimdol_ai.scoring import axis_profile, prioritize_gaps

REQS = [
    Requirement("p#0-0", "세포 및 동물실험 경험", 2, ["research"], "posting", "preferred", quote="세포 및 동물실험 유경험자"),
    Requirement("p#0-1", "생물학 관련 지식", 1, ["domain"], "posting", "required", quote="생물학 관련 지식"),
    Requirement("p#0-2", "실험 결과 분석 능력", 2, ["research", "data"], "posting", "required", quote="실험 결과 분석 능력"),
]

CARD = ExperienceCard(
    id="c1", kind="학부연구생", title="세포 독성 실험 보조",
    actions="대학원생 선배가 정해 준 프로토콜대로 세포를 배양하고 MTT assay로 세포 생존율을 측정했다. "
            "문의는 student01@example.com 또는 010-1234-5678.",
    tools=["세포 배양", "Excel"],
)


class FakeClient:
    def __init__(self, output, stop_reason="end_turn"):
        self.calls, self.output, self.stop_reason = [], output, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps(self.output, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=900, output_tokens=200), model=kw["model"],
        )


OUTPUT = {
    "evidence": [
        {"requirement_id": "p#0-0", "level": 2, "quote": "프로토콜대로 세포를 배양하고",
         "reason": "정해진 절차대로 세포 실험을 직접 수행했다."},
        {"requirement_id": "p#0-0", "level": 1, "quote": "세포를 배양하고", "reason": "중복 항목"},
        {"requirement_id": "p#0-2", "level": 3, "quote": "통계 모델을 직접 설계했다",  # 카드에 없는 인용 → 버림
         "reason": "지어낸 근거"},
    ],
    "followup_questions": ["측정 결과는 어떻게 해석했나요?", "두 번째", "세 번째는 잘림"],
}


class JudgeTest(unittest.TestCase):
    def test_verified_evidence_only(self):
        j = judge_card(FakeClient(OUTPUT), CARD, REQS)
        self.assertEqual([(e.requirement_id, e.level, e.card_id) for e in j.evidences], [("p#0-0", 2, "c1")])
        self.assertEqual(len(j.dropped), 1)
        self.assertEqual(j.dropped[0]["requirement_id"], "p#0-2")
        self.assertEqual(len(j.followup_questions), 2)

    def test_request_shape_and_pii_masking(self):
        client = FakeClient(OUTPUT)
        judge_card(client, CARD, REQS)
        call = client.calls[0]
        content = call["messages"][0]["content"]
        self.assertNotIn("student01@example.com", content)
        self.assertNotIn("010-1234-5678", content)
        self.assertIn("[이메일]", content)
        self.assertIn("id=p#0-0", content)
        self.assertEqual(call["fallbacks"], "default")
        ids = call["output_config"]["format"]["schema"]["properties"]["evidence"]["items"]["properties"]["requirement_id"]["enum"]
        self.assertEqual(ids, ["p#0-0", "p#0-1", "p#0-2"])

    def test_feeds_scoring_end_to_end(self):
        j = judge_card(FakeClient(OUTPUT), CARD, REQS)
        goal = Goal("g", "항노화 유효성 평가 지원", REQS, weeks_left=8, weekly_hours=8)
        prof = axis_profile(goal, j.evidences, {"research": 4})
        self.assertEqual(prof["research"].quadrant, "record_proof")  # 자기평가 4 > 근거
        plan = prioritize_gaps(goal, j.evidences)
        self.assertNotIn("p#0-0", [g.requirement.id for g in plan.items])  # 충족된 항목은 갭에서 빠짐

    def test_errors(self):
        with self.assertRaises(ExtractionError):
            judge_card(FakeClient(OUTPUT, stop_reason="refusal"), CARD, REQS)
        with self.assertRaises(ExtractionError):
            judge_card(FakeClient(OUTPUT), CARD, [])

    def test_schema_levels_exclude_zero(self):
        level = _schema(["a"])["properties"]["evidence"]["items"]["properties"]["level"]
        self.assertEqual(level["enum"], [1, 2, 3])

    def test_mask_pii(self):
        self.assertEqual(mask_pii("연락 02-958-6131, a.b@c.kr"), "연락 [전화번호], [이메일]")


if __name__ == "__main__":
    unittest.main()
