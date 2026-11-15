"""NCS 큐레이션 테스트: 원본과 같은 형식(cp949, 앞자리 0 빠짐)의 작은 CSV로 빌드."""

import json
import tempfile
import unittest
from pathlib import Path

from didimdol_ai import ncs

CSV = """국가직무능력표준(NCS)분류,국가직무능력표준(NCS)명칭
2,경영ㆍ회계ㆍ사무
201,기획사무
20102,홍보ㆍ광고
2010202,PR/광고
17,화학
1701,화학물질ㆍ화학공정관리
170101,화학물질관리
17010101,화학물질분석
1701010101_17v2,화학분석 시료 채취
1701010102_17v2,기기분석 데이터 해석
1701010102_17v2.1,세부 요소(제외 대상)
20,정보통신
2001,정보기술
200101,정보기술전략ㆍ계획
20010105,빅데이터기획ㆍ분석
6,보건ㆍ의료
602,의료
60203,기초의학
6020301,예방의학
6020302,병리학
24,농림어업
2401,농업
240101,작물재배
24010101,식량작물재배
"""


class NcsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        raw, out = Path(cls.tmp.name) / "raw.csv", Path(cls.tmp.name) / "cur.json"
        raw.write_bytes(CSV.encode("cp949"))
        cls.data = ncs.build(raw, out)
        cls._orig = ncs.CURATED
        ncs.CURATED = out
        ncs.load.cache_clear()
        ncs._name_index.cache_clear()

    @classmethod
    def tearDownClass(cls):
        ncs.CURATED = cls._orig
        ncs.load.cache_clear()
        ncs._name_index.cache_clear()
        cls.tmp.cleanup()

    def test_code_normalization_and_levels(self):
        self.assertEqual(ncs.normalize_code("2010202"), "02010202")
        self.assertEqual(ncs.normalize_code("1701010101_17v2"), "1701010101_17v2")
        self.assertEqual(ncs.level_of("17010101"), "detail")
        self.assertEqual(ncs.level_of("1701010101_17v2"), "unit")
        self.assertEqual(ncs.level_of("1701010102_17v2.1"), "element")

    def test_build_scope_fields_and_units(self):
        d = self.data["details"]
        self.assertNotIn("24010101", d)  # 농림어업은 큐레이션 범위 밖
        self.assertEqual(d["17010101"]["fields"], ["chem"])
        self.assertEqual(d["20010105"]["fields"], ["it", "ai"])  # 이름에 빅데이터 → AI데이터
        self.assertEqual(d["02010202"]["fields"], [])  # 행정 계열
        units = d["17010101"]["units"]
        self.assertEqual([u["name"] for u in units], ["화학분석 시료 채취", "기기분석 데이터 해석"])  # 요소 제외
        self.assertEqual(units[1]["axis"], "data")
        self.assertIn("data.go.kr", self.data["source"])

    def test_find_detail_codes(self):
        f = ncs.find_detail_codes
        self.assertEqual(f({"major": "화학⋅바이오", "middle": "화학물질⋅화학공정", "minor": "x", "detail": "화학물질 분석"}),
                         ["17010101"])
        self.assertEqual(f({"major": "02. 경영·회계·사무", "middle": "01. 기획사무", "minor": "02. 홍보·광고",
                            "detail": "03. PR"}), ["02010202"])  # 부분 일치
        self.assertEqual(f({"major": "보건의료", "middle": "의료", "minor": "기초의학", "detail": "-"}),
                         ["06020301", "06020302"])  # 소분류로 대체
        self.assertEqual(f(None), [])

    def test_curated_requirements(self):
        reqs = ncs.curated_requirements("17010101", "kiom:1#0")
        self.assertEqual(len(reqs), 2)
        self.assertEqual((reqs[0].source, reqs[0].required_level, reqs[0].necessity), ("ncs_curated", 1, "curated"))
        self.assertEqual(reqs[0].ncs_unit_code, "1701010101_17v2")
        self.assertEqual(ncs.curated_requirements("99999999", "x"), [])

    def test_search(self):
        hits = ncs.search("기기분석")
        self.assertEqual(hits[0]["code"], "17010101")
        self.assertEqual(hits[0]["matched_units"], ["기기분석 데이터 해석"])
        json.dumps(hits, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
