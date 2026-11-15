import unittest
from datetime import date

from didimdol_ai.models import ExperienceCard, Requirement
from didimdol_ai.recommend import (
    BUCKET_LATER, BUCKET_NOW, BUCKET_PREPARE, Match, RoleCandidate, UserProfile,
    estimate_card_level, estimate_evidence, recommend,
)

CARDS = [
    ExperienceCard("c1", "학부연구생", "세포 독성 실험 보조", "프로토콜대로 세포를 배양하고 MTT assay로 측정했다."),
    ExperienceCard("c2", "수업 프로젝트", "기말 프로젝트", "실험을 직접 설계하고 Python으로 실험 결과를 분석했다.", role="팀장"),
]


def role(uid, idx, *, fields=("chem",), category="research", targets=(), ug=True, closed=False,
         end="2026-12-01", inst="kiom", reqs=None):
    return RoleCandidate(uid, idx, f"{uid} 공고", inst, inst.upper(), "대전", f"직무{idx}", category,
                         list(fields), list(targets), ug, closed, end, "u", None, reqs or [])


REQ_CELL = Requirement("r1", "세포 및 동물실험 경험", 2, ["research"], "posting", "preferred", quote="세포 및 동물실험 유경험자")
REQ_ANAL = Requirement("r2", "실험 결과 분석", 2, ["research", "data"], "posting", "required", quote="실험 결과 분석 능력")
REQ_PCR = Requirement("r3", "PCR 실험 수행", 2, ["research"], "posting", "required", quote="PCR 실험 수행 가능자")
PROFILE = UserProfile("expected", ["chem"], style_share={"analyze": 0.5, "make": 0.3, "talk": 0.1, "plan": 0.1})
TODAY = date(2026, 11, 15)


class EstimateTest(unittest.TestCase):
    def test_card_level(self):
        self.assertEqual(estimate_card_level(CARDS[0]), 2)
        self.assertEqual(estimate_card_level(CARDS[1]), 3)  # 직접 설계 + 팀장
        self.assertEqual(estimate_card_level(ExperienceCard("c", "수업", "강의", "직접 설계 원리를 배웠다")), 1)

    def test_lexical_match(self):
        m = estimate_evidence(REQ_CELL, CARDS, 0.34)
        self.assertEqual((m.card_id, m.level, m.source), ("c1", 2, "추정"))
        self.assertEqual(estimate_evidence(REQ_ANAL, CARDS, 0.34).card_id, "c2")
        self.assertIsNone(estimate_evidence(REQ_PCR, CARDS, 0.34))

    def test_no_cross_word_or_attitude_match(self):
        bio = [ExperienceCard("b", "수업", "생물 수강", "생화학 과목을 수강했다. 전기영동 원리를 배웠다.")]
        echem = Requirement("e", "전기화학 지식", 1, ["domain"], "posting", "required")
        self.assertIsNone(estimate_evidence(echem, bio, 0.34))  # '전기'+'화학'이 다른 낱말에서 온 우연한 겹침
        self.assertIsNotNone(estimate_evidence(Requirement("g", "생화학 지식", 1, ["domain"], "posting", "required"),
                                               bio, 0.34))
        grad = Requirement("a", "대학원 진학 관심", 1, [], "posting", "preferred", kind="attitude")
        self.assertIsNone(estimate_evidence(grad, [ExperienceCard("x", "수업", "대학원 진학 준비", "대학원 진학 관심")],
                                            0.34))

    def test_unknown_readiness_ranks_below_partial_evidence(self):
        empty = role("kims:1", 0, inst="kims")  # 공고에 구체 요건 없음 → 준비도 계산 불가
        half = role("kiom:2", 0, reqs=[REQ_ANAL, REQ_PCR])  # 필수 2개 중 1개 근거 → 준비도 0.5
        recs = recommend([empty, half], PROFILE, CARDS, today=TODAY)
        self.assertEqual([r.uid for r in recs], ["kiom:2", "kims:1"])

    def test_basic_competency_excluded(self):
        basic = Requirement("k", "의사소통능력", 1, ["communication"], "posting", "required", kind="skill")
        rec = recommend([role("kiom:1", 0, reqs=[REQ_CELL, basic])], PROFILE, CARDS, today=TODAY)[0]
        self.assertFalse(any("의사소통능력" in g for g in rec.gaps))


class RecommendTest(unittest.TestCase):
    def test_filters_and_buckets(self):
        roles = [
            role("a", 0, reqs=[REQ_CELL, REQ_ANAL]),                    # 준비 완료 → 지금 도전
            role("b", 0, reqs=[REQ_PCR]),                               # 근거 없음 → 준비하며 목표
            role("c", 0, reqs=[REQ_CELL], targets=["graduated"]),       # 지원 시기 아님 → 자격 후 목표
            role("d", 0, ug=False),                                     # 대학원 대상 → 제외
            role("e", 0, closed=True),                                  # 마감 → 제외
            role("f", 0, category="admin"),                             # 행정 → 기본 제외
            role("g", 0, end="2026-11-01"),                             # 날짜상 마감 → 제외
        ]
        recs = recommend(roles, PROFILE, CARDS, top=10, today=TODAY)
        got = {r.uid: r.bucket for r in recs}
        self.assertEqual(got, {"a": BUCKET_NOW, "b": BUCKET_PREPARE, "c": BUCKET_LATER})
        self.assertEqual([r.uid for r in recs], ["a", "b", "c"])  # 버킷 순서
        self.assertIn("PCR 실험 수행", recs[1].gaps[0])

    def test_field_mismatch_lowers_score(self):
        recs = recommend([role("a", 0, reqs=[REQ_CELL]), role("b", 0, reqs=[REQ_CELL], fields=["mech"])],
                         PROFILE, CARDS, today=TODAY)
        self.assertGreater(recs[0].score, recs[1].score)
        self.assertEqual(recs[0].uid, "a")

    def test_diversity_limits(self):
        roles = [role("a", i, reqs=[REQ_CELL]) for i in range(4)] + \
                [role(f"x{i}", 0, reqs=[REQ_CELL], inst="kist") for i in range(5)]
        recs = recommend(roles, PROFILE, CARDS, top=10, today=TODAY)
        self.assertEqual(sum(r.uid == "a" for r in recs), 2)        # 같은 공고 최대 2
        self.assertEqual(sum(r.institute == "KIST" for r in recs), 3)  # 같은 기관 최대 3

    def test_judged_evidence_overrides_estimate(self):
        roles = [role("a", 0, reqs=[REQ_PCR])]
        judged = {("a", 0): {"r3": Match("PCR 실험 수행", "c2", "기말 프로젝트", 2, "판정")}}
        [rec] = recommend(roles, PROFILE, CARDS, today=TODAY, judged_by_role=judged)
        self.assertEqual(rec.readiness, 1.0)
        self.assertEqual(rec.matches[0].source, "판정")


if __name__ == "__main__":
    unittest.main()
