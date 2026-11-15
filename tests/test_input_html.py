"""자기상태표 입력 화면 조각 테스트 (브라우저 동작은 README의 수동 확인 절차로 검증)."""

import json
import re
import unittest

from didimdol_ai.input_html import CSS, build_config, demo_config, render_input, render_input_fragment


class InputHtmlTest(unittest.TestCase):
    def setUp(self):
        self.cfg = build_config("W3", profile={"status": "expected", "interest_fields": ["chem"]},
                                last_ratings={"domain": 2},
                                milestones=[{"milestone_id": "m1", "title": "실험 절차 익히기", "requirement_id": "r1"}],
                                cards=[{"id": "c1", "kind": "수업", "title": "생화학 수강", "actions": "생화학을 수강했다."}],
                                endpoints={"checkin": "/api/modules/sirsoft-jobfit/me/jobfit/checkins"})

    def test_config_has_fixed_six_axes_with_anchors(self):
        self.assertEqual([a["id"] for a in self.cfg["axes"]],
                         ["domain", "research", "data", "problem", "communication", "collaboration"])
        for a in self.cfg["axes"]:
            self.assertEqual(sorted(a["anchors"]), ["1", "2", "3", "4", "5"])

    def test_fragment_is_scoped_and_embeds_config(self):
        frag = render_input_fragment(self.cfg)
        self.assertTrue(frag.startswith("<style>"))
        self.assertNotIn("<html", frag)
        css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
        for rule in re.findall(r"(?:^|})\s*([^{}@]+)\{", css):
            for sel in re.split(r",(?![^(]*\))", rule):
                self.assertIn(".dd-input", sel, sel)
        self.assertIn(':where(.dark,[data-theme="dark"]) .dd-input', CSS)
        data = re.search(r'<script type="application/json">(.*?)</script>', frag, re.S).group(1)
        self.assertEqual(json.loads(data)["week"], "W3")
        self.assertIn("didimdol:save", frag)  # G7이 받는 저장 이벤트

    def test_config_cannot_break_out_of_script(self):
        cfg = build_config("W1", cards=[{"id": "x", "kind": "수업", "title": "</script><script>alert(1)</script>",
                                         "actions": "a & b"}])
        frag = render_input_fragment(cfg)
        self.assertNotIn("</script><script>alert(1)", frag)
        data = re.search(r'<script type="application/json">(.*?)</script>', frag, re.S).group(1)
        self.assertEqual(json.loads(data)["cards"][0]["title"], "</script><script>alert(1)</script>")

    def test_no_comparison_words_and_condition_is_private(self):
        page = render_input(demo_config())
        self.assertIsNone(re.search(r"평균|상위\s*\d|다른 학생|순위", page))
        self.assertIn("진로 점수에는 쓰이지 않아요", page)
        self.assertIsNone(re.search(r'<script[^>]+src=|<link[^>]+href=', page))  # 외부 리소스 없음


if __name__ == "__main__":
    unittest.main()
