import io
import os
import tempfile
import unittest
import zipfile
from datetime import date

from didimdol_ai.collector.adapters import KictAdapter, KiomAdapter, KistAdapter
from didimdol_ai.collector.extract import extract_text, hwpx_text, zip_text
from didimdol_ai.collector.filters import classify, is_closed, parse_date, parse_range
from didimdol_ai.collector.models import Attachment, Posting, PostingRef
from didimdol_ai.collector.store import Store, dedup_key

KICT_LIST = """<html><body><div class="dbody" id="listView">
<ul class="notice"><li class="W8">7</li>
<li class="title"><a href="/x" onclick="egov_recruit_detail(this.href, '3351', '7'); return false;">2027년(1회) 연수직(학생연구원, 인턴) 채용 공고</a></li>
<li class="W20" aria-title="공고기간">2026/11/06 ~ 2026/11/16</li>
<li class="W15" aria-title="진행상태"><span class="state ing">진행중</span></li></ul>
</div></body></html>"""

KICT_VIEW = """<html><body><div class="tstyle_view">
<a href="#" onclick="egov_download_atchfile('announcement_recruit', '', '채용공고문.pdf', 'abc.pdf'); return false;">채용공고문.pdf</a>
<a href="#" onclick="egov_download_atchfile('announcement_recruit', '', '채용공고문.pdf', 'abc.pdf'); return false;">다운로드</a>
<div class="tb_contents">세부 내용은 첨부 참조</div></div></body></html>"""

KIST_LIST = """<html><body><table class="board-table recruit"><tbody><tr>
<td class="b-num-box">905</td>
<td class="b-td-left"><div class="b-title-box"><span class="b-progress">진행중</span>
<a href="?mode=view&amp;articleNo=18542&amp;article.offset=0" title="KIST 2026-6차 행정인턴 공개채용 자세히 보기">KIST 2026-6차 행정인턴 공개채용</a>
<div class="b-m-con"><span class="b-date">26.11.02</span></div></div></td>
<td>인사경영팀</td><td>26.11.16</td><td>1080</td></tr></tbody></table></body></html>"""

KIST_VIEW = """<html><body><div class="b-content-box">온라인 지원서 작성 바로가기</div>
<a class="file-down-btn pdf" href="?mode=download&amp;articleNo=18542&amp;attachNo=16774">직무기술서.pdf</a></body></html>"""

KIOM_LIST = """<html><body><table class="tstyle_list"><tbody><tr>
<td class="m_noti">공지</td><td aria-label="분류"><span class="icon type1">서류접수중</span></td>
<td class="txt_left m_title" aria-label="공고명"><strong><a href="/board.es?mid=a10503020000&amp;bid=0038&amp;act=view&amp;list_no=20233&amp;nPage=1">2026년 하반기 인턴 채용 공고</a></strong></td>
<td aria-label="등록일">2026-11-02</td><td aria-label="접수기간">2026-11-02 ~ 2026-11-17</td></tr></tbody></table></body></html>"""

KIOM_VIEW = """<html><body><div class="board_view"><div class="contents">채용사이트 바로가기</div>
<ul><li><em>붙임1_인턴_선발_공고.pdf</em><span class="link"><a href="/boardDownload.es?bid=0038&amp;list_no=20233&amp;seq=1">다운로드</a></span></li></ul>
</div></body></html>"""


class AdapterTest(unittest.TestCase):
    def test_kict(self):
        a = KictAdapter()
        [ref] = a.parse_list(KICT_LIST, "")
        self.assertEqual(ref.external_id, "3351")
        self.assertTrue(ref.url.endswith("id=3351"))
        self.assertEqual((ref.apply_start_on, ref.apply_end_on), (date(2026, 11, 6), date(2026, 11, 16)))
        body, atts = a.parse_detail(KICT_VIEW, ref)
        self.assertEqual(body, "세부 내용은 첨부 참조")
        self.assertEqual([(x.name, x.url) for x in atts], [("채용공고문.pdf", None)])  # 중복 제거, URL 없음

    def test_kist(self):
        a = KistAdapter()
        [ref] = a.parse_list(KIST_LIST, "")
        self.assertEqual(ref.title, "KIST 2026-6차 행정인턴 공개채용")
        self.assertEqual(ref.posted_on, date(2026, 11, 2))
        self.assertEqual(ref.apply_end_on, date(2026, 11, 16))
        _, atts = a.parse_detail(KIST_VIEW, ref)
        self.assertEqual(atts[0].url, "https://kist.re.kr/ko/notice/employment-announcement.do"
                                      "?mode=download&articleNo=18542&attachNo=16774")

    def test_kiom(self):
        a = KiomAdapter()
        [ref] = a.parse_list(KIOM_LIST, "")
        self.assertEqual(ref.external_id, "20233")
        self.assertEqual(ref.status_text, "서류접수중")
        _, atts = a.parse_detail(KIOM_VIEW, ref)
        self.assertEqual(atts[0].name, "붙임1_인턴_선발_공고.pdf")
        self.assertTrue(atts[0].url.startswith("https://kiom.re.kr/boardDownload.es"))


def posting(title, text="", status="", end=None):
    p = Posting(PostingRef("kict", "1", title, "u", apply_end_on=end, status_text=status))
    if text:
        p.attachments = [Attachment("a.pdf", "u", text=text)]
    return p


class FilterTest(unittest.TestCase):
    def test_include_exclude(self):
        cases = {
            "2027년(1회) 연수직(학생연구원, 인턴) 채용 공고": (True, "research"),
            "KIST 2026-6차 행정인턴 공개채용": (True, "admin"),
            "2026년 하반기 체험형 인턴 채용": (True, "experience"),
            "연수직(박사후연구원, 석사후연구원, 연구인턴) 추천선발 안내": (True, "research"),
        }
        for title, (inc, cat) in cases.items():
            p = posting(title)
            classify(p)
            self.assertEqual((p.include, p.category), (inc, cat), title)

        for title in ["2027년(1회) 연수직(박사후연구원) 채용 공고",
                      "★★ 비위면직자등의 취업제한제도 안내 ★★",
                      "2026년 하반기 인턴 서류전형 합격자 발표"]:
            p = posting(title)
            classify(p)
            self.assertFalse(p.include, title)
            self.assertTrue(p.exclude_reason)

    def test_targets_from_attachment_text(self):
        p = posting("인턴 채용", "지원자격: 4년제 대학 재학생(휴학생 포함) 또는 졸업예정자, 학사학위 소지자")
        classify(p)
        self.assertEqual(p.targets, ["enrolled", "expected", "graduated"])

    def test_targets_real_phrasings(self):
        # KIST 행정인턴 공고문 표현
        p = posting("행정인턴", "마. 임용예정일 기준 최종학위 (학사 또는 석사학위)를 취득한 자 또는 3개월 이내 학위취득 예정자")
        classify(p)
        self.assertEqual(p.targets, ["expected", "graduated"])
        # KIOM 인턴 공고문 표현: 재학·휴학생은 지원 불가
        p = posting("인턴", "▪임용예정일 기준 학사 학위 취득 후 5년 이내인 자로서 재학 또는 휴학 중이 아닌 자")
        classify(p)
        self.assertNotIn("enrolled", p.targets)
        self.assertIn("graduated", p.targets)

    def test_closed(self):
        self.assertTrue(is_closed(posting("인턴", status="전형완료"), date(2026, 1, 1)))
        self.assertTrue(is_closed(posting("인턴", end=date(2026, 11, 1)), date(2026, 11, 14)))
        self.assertFalse(is_closed(posting("인턴", end=date(2026, 11, 16)), date(2026, 11, 14)))

    def test_dates(self):
        self.assertEqual(parse_date("26.11.02"), date(2026, 11, 2))
        self.assertEqual(parse_range(" ~ "), (None, None))
        self.assertEqual(parse_range("2026/11/06 ~ 2026/11/16")[1], date(2026, 11, 16))


class _Cp949ZipInfo(zipfile.ZipInfo):
    """한국어 Windows 압축 프로그램처럼 이름을 UTF-8 플래그 없이 cp949 바이트로 기록."""

    def _encodeFilenameFlags(self):
        return self.filename.encode("cp949"), self.flag_bits & ~0x800


def _zip(entries: dict, utf8_names=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name) if utf8_names else _Cp949ZipInfo(name)
            zf.writestr(info, data)
    return buf.getvalue()


HWPX_SECTION = (
    '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
    "<hp:p><hp:run><hp:t>지원자격</hp:t></hp:run></hp:p>"
    "<hp:p><hp:run><hp:t>Python </hp:t></hp:run><hp:run><hp:t>가능자 우대</hp:t></hp:run></hp:p></hs:sec>"
)


class ExtractTest(unittest.TestCase):
    def test_hwpx(self):
        data = _zip({"Contents/section0.xml": HWPX_SECTION})
        self.assertEqual(hwpx_text(data), "지원자격\nPython 가능자 우대")

    def test_zip_with_cp949_names_and_nested_formats(self):
        inner = _zip({"Contents/section0.xml": HWPX_SECTION})
        data = _zip({"직무기술서.hwpx": inner, "메모.txt": "전기화학 실험".encode(), "실행.exe": b"MZ"},
                    utf8_names=False)
        text = zip_text(data)
        self.assertIn("[직무기술서.hwpx]", text)
        self.assertIn("가능자 우대", text)
        self.assertIn("전기화학 실험", text)
        self.assertNotIn("실행.exe", text)

    def test_unsupported(self):
        with self.assertRaises(ValueError):
            extract_text("a.pptx", b"")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.sqlite3"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_upsert_revision_and_export(self):
        p = posting("인턴 채용", "학사학위 소지자", end=date(2026, 11, 16))
        classify(p)
        self.assertEqual(self.store.upsert(p), "new")
        self.assertEqual(self.store.upsert(p), "same")
        p.attachments[0].text += " (정정)"
        self.assertEqual(self.store.upsert(p), "changed")
        [item] = self.store.export({"kict": {"name": "한국건설기술연구원", "region": "고양", "fields": ["infra"]}},
                                   with_text=True)
        self.assertEqual(item["revision"], 2)
        self.assertEqual(item["targets"], ["graduated"])
        self.assertIn("(정정)", item["attachments"][0]["text"])

    def test_closed_postings_are_kept(self):
        p = posting("인턴 채용", end=date(2026, 11, 1))
        classify(p)
        self.store.upsert(p)
        self.assertEqual(self.store.mark_closed_by_date(date(2026, 11, 14)), 1)
        [item] = self.store.export({})
        self.assertTrue(item["is_closed"])

    def test_dedup_key_ignores_spacing_and_brackets(self):
        a = dedup_key("kist", "KIST 2026-6차 [행정인턴] 공개채용", date(2026, 11, 16))
        b = dedup_key("kist", "KIST 2026 6차 행정인턴 공개채용", date(2026, 11, 16))
        self.assertEqual(a, b)

    def test_zero_run_alert(self):
        self.store.log_run("2026-11-13T00:00:00", "kict", 0, 0, 0, 0, [])
        self.store.log_run("2026-11-14T00:00:00", "kict", 0, 0, 0, 0, [])
        self.assertTrue(self.store.recent_zero_runs("kict"))


if __name__ == "__main__":
    unittest.main()
