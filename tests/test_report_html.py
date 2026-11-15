import re
import unittest

from didimdol_ai.demo import history_inputs
from didimdol_ai.metrics import build_report
from didimdol_ai.report_html import render


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.monthly = build_report(history_inputs(), "monthly")
        self.weekly = build_report(history_inputs(), "weekly")

    def test_monthly_sections(self):
        page = render(self.monthly)
        for text in ("육각형 능력치", "다음 한 칸", "축별 근거 점수 추이", "목표 직무 요구 항목",
                     "자소서·면접에 쓸 대표 경험", "나만 볼 수 있고"):
            self.assertIn(text, page)
        self.assertIn('prefers-color-scheme:dark', page)  # 다크 모드 지정
        self.assertIn("<table>", page)  # 육각형 표 보기 (접근성)

    def test_weekly_has_no_monthly_only_sections(self):
        page = render(self.weekly)
        self.assertNotIn("축별 근거 점수 추이", page)
        self.assertNotIn("나의 컨디션 흐름", page)

    def test_self_contained_and_no_comparison_words(self):
        page = render(self.monthly, feedback=[{"kind": "praise", "text": "잘했어요"}], healing="숲에서 쉬어요")
        self.assertIsNone(re.search(r'<script[^>]+src=|<link[^>]+href=', page))  # 외부 리소스 없음
        self.assertIsNone(re.search(r"평균|상위\s*\d|다른 학생", page))
        self.assertIn("이번 주 코치의 말", page)

    def test_escaping(self):
        self.monthly["goal"]["title"] = "<script>alert(1)</script>"
        page = render(self.monthly)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()
