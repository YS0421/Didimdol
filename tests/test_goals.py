"""분야 공통 요구: 추천과 같은 공고만, 안정적인 id, 가까운 NCS 세분류."""

import unittest

from didimdol_ai.goals import field_requirements
from didimdol_ai.models import Requirement
from didimdol_ai.ncs import load
from didimdol_ai.recommend import RoleCandidate


def _role(reqs, fields=("chem",)):
    return RoleCandidate("u", 0, "공고", "kiom", "한의학연", None, "직무", "research", list(fields), [],
                         True, False, None, "http://example.org", None, reqs)


def _req(label, level=2, axes=("research",), kind="skill"):
    return Requirement(label, label, level, list(axes), "posting", kind=kind)


def _chem_experiment_code() -> str:
    for code, detail in load()["details"].items():
        if "chem" in detail["fields"] and any("실험" in u["name"] for u in detail["units"]):
            return code
    raise AssertionError("화학 분야 실험 세분류가 없어요.")


class FieldRequirementsTest(unittest.TestCase):
    def test_empty_title_does_not_invent_generic_management(self):
        self.assertEqual(field_requirements(["chem"], []), [])
        self.assertEqual(field_requirements(["no-such-field"], [], title="실험"), [])

    def test_title_uses_a_nearby_detail(self):
        reqs = field_requirements(["chem"], [], title="파일럿 실험 검증")
        self.assertTrue(reqs)
        self.assertLessEqual(len(reqs), 8)
        self.assertTrue(all(r.source == "ncs_curated" and r.id.startswith("ncs#") for r in reqs))
        labels = {r.label for r in reqs}
        self.assertNotIn("안전관리", labels)
        self.assertTrue(any("실험" in label or "반응" in label for label in labels))
        self.assertEqual(field_requirements(["chem"], [], title="파일럿 실험 검증"), reqs)
        stuck = field_requirements(["chem"], [], title="세포 실험을 직접 설계하기")
        self.assertTrue(stuck)
        self.assertNotIn("안전관리", {r.label for r in stuck})

    def test_posting_frequency_id_stays_when_fields_change(self):
        roles = [
            _role([_req("세포 배양"), _req("의사소통능력", axes=("communication",))]),
            _role([_req("세포 배양", level=3), _req("데이터 정리", axes=("data",))]),
        ]
        roles[0].ncs_codes = [_chem_experiment_code()]
        chem = field_requirements(["chem"], roles)
        both = field_requirements(["chem", "energy"], roles)
        by_label = {r.label: r for r in chem}
        self.assertNotIn("의사소통능력", by_label)
        self.assertEqual(by_label["세포 배양"].frequency, 1.0)
        self.assertEqual(by_label["세포 배양"].id, "req#세포배양")
        self.assertEqual(by_label["데이터 정리"].frequency, 0.5)
        self.assertEqual(next(r.id for r in both if r.label == "세포 배양"), "req#세포배양")
        self.assertTrue(any(r.source == "ncs_curated" and "안전관리" not in r.label for r in chem))

    def test_frequency_ignores_closed_admin_and_graduate_roles(self):
        closed, grad, admin = _role([_req("마감만")]), _role([_req("대학원만")]), _role([_req("행정만")])
        closed.is_closed, grad.undergrad_eligible, admin.category = True, False, "admin"
        labels = {r.label for r in field_requirements(["chem"], [closed, grad, admin, _role([_req("세포 배양")])])}
        self.assertIn("세포 배양", labels)
        self.assertTrue(labels.isdisjoint({"마감만", "대학원만", "행정만"}))

    def test_skips_ncs_when_postings_already_cover_the_field(self):
        reqs = [_req(f"고유항목{i}") for i in range(4)]
        role = _role(reqs, fields=("energy",))
        role.ncs_codes = [_chem_experiment_code()]
        out = field_requirements(["energy"], [role], title="파일럿 실험 검증")
        self.assertEqual([r.label for r in out], [r.label for r in reqs])
        self.assertTrue(all(r.source == "posting" for r in out))


if __name__ == "__main__":
    unittest.main()
