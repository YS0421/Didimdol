import re
import unittest

from didimdol_ai.demo import history_inputs
from didimdol_ai.metrics import build_report
from didimdol_ai.report_html import CSS, render, render_fragment
from didimdol_ai.text import fix_josa


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.monthly = build_report(history_inputs(), "monthly")
        self.weekly = build_report(history_inputs(), "weekly")

    def test_monthly_sections_in_reading_order(self):
        page = render(self.monthly, feedback=[{"kind": "praise", "text": "잘했어요"}])
        order = ["dd-hero", "이번 주 코치의 말", "다음 한 칸", "나의 육각형 능력치", "한 달 돌아보기"]
        body = page[page.index('<section class="dd-report"'):]  # CSS 주석 제외
        positions = [body.index(t) for t in order]
        self.assertEqual(positions, sorted(positions))  # 요약 → 코치 → 다음 한 칸 → 육각형 → 상세
        for text in ("주차별 변화", "목표 직무 요구 항목", "자소서·면접에 쓸 경험", "나만 볼 수 있고"):
            self.assertIn(text, page)
        self.assertIn("<table>", page)  # 숫자로 보기 (접근성)
        self.assertGreaterEqual(page.count('class="dd-more"'), 4)  # 월간 상세는 접힌 묶음

    def test_weekly_has_no_monthly_only_sections(self):
        page = render(self.weekly)
        self.assertNotIn("주차별 변화", page)
        self.assertNotIn("나의 컨디션 흐름", page)

    def test_fragment_is_scoped_for_embedding(self):
        frag = render_fragment(self.monthly)
        self.assertTrue(frag.startswith("<style>"))
        self.assertNotIn("<html", frag)
        self.assertNotIn("<body", frag)
        # 모든 규칙이 .dd-report 아래에 있어 사이트 스타일과 충돌하지 않음
        css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
        for rule in re.findall(r"(?:^|})\s*([^{}@]+)\{", css):
            for sel in re.split(r",(?![^(]*\))", rule):  # :where(a,b) 안의 쉼표는 나누지 않음
                self.assertIn(".dd-report", sel, sel)
        self.assertIn(':where(.dark,[data-theme="dark"]) .dd-report', CSS)  # 사이트 다크 모드 방식을 따름
        self.assertIn("#007e5c", CSS)  # 사이트 대표색 (didim-green)

    def test_standalone_page_follows_system_theme_and_has_no_external_resources(self):
        page = render(self.monthly, feedback=[{"kind": "praise", "text": "잘했어요"}], healing="숲에서 쉬어요")
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIsNone(re.search(r'<script[^>]+src=|<link[^>]+href=', page))
        self.assertIsNone(re.search(r"평균|상위\s*\d|다른 학생", page))
        self.assertIn("숲에서 잠깐 쉬어 가요", page)

    def test_escaping(self):
        self.monthly["goal"]["title"] = "<script>alert(1)</script>"
        page = render(self.monthly)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


class JosaTest(unittest.TestCase):
    def test_fix_josa(self):
        self.assertEqual(fix_josa("'세라믹 합성'이(가) 멈췄어요"), "'세라믹 합성'이 멈췄어요")
        self.assertEqual(fix_josa("'공정 익히기'을(를) 끝냈어요"), "'공정 익히기'를 끝냈어요")
        self.assertEqual(fix_josa("전공 지식은(는)"), "전공 지식은")
        self.assertEqual(fix_josa("Python을(를)"), "Python을(를)")  # 한글이 아니면 그대로


if __name__ == "__main__":
    unittest.main()
