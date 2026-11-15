"""2026-11 추가 기관 어댑터 테스트: 실제 게시판 구조를 줄인 HTML 조각으로 목록·상세 파싱을 확인한다."""

import unittest
from datetime import date

from didimdol_ai.collector.adapters import ADAPTERS
from didimdol_ai.collector.filters import infer_deadline, is_closed
from didimdol_ai.collector.models import Posting, PostingRef
from didimdol_ai.models import Requirement
from didimdol_ai.scoring import is_basic_competency, requirement_weight

REF = PostingRef("x", "1", "t", "u")

BOARD_ES_TABLE = """<table class="tstyle_list"><tbody><tr>
<td aria-label="번호">236</td>
<td aria-label="제목" class="txt_left"><span class="progress ing">진행중</span>
  <a href="/board.es?mid=a10304010000&amp;bid=0013&amp;act=view&amp;list_no=19900&amp;nPage=1">2026년 하반기 청년인턴 채용</a></td>
<td aria-label="등록일">2026-11-02</td><td aria-label="공고기간">2026-11-02 ~ 2026-11-16</td></tr></tbody></table>"""
BOARD_ES_DIV = """<div class="tstyle_list"><div class="dbody"><ul>
<li class="W8">255</li><li class="title"><a href="/board.es?mid=a10705030000&amp;bid=0029&amp;act=view&amp;list_no=65100">
2026년 제2차 인턴[체험형] 공개채용</a></li><li class="W13">홍길동</li><li class="W13">2026/05/20</li></ul></div></div>"""
BOARD_ES_DETAIL = """<div class="board_view"><p>짧은 머리말</p></div>
<div class="board_view"><p>공고 본문입니다. 접수기간 : 2026. 11. 2.(월) ~ 11. 16.(월)</p>
<ul><li><img alt="pdf"> 붙임1. 직무기술서.pdf <span class="txt">(100KB)</span>
<span class="link"><a href="/boardDownload.es?bid=0013&amp;list_no=19900&amp;seq=1">다운로드</a></span></li></ul></div>"""

KAERI_LIST = """<ul class="newsfeed_lst"><li class="item"><div class="content"><strong class="subject">
<a href="/board/view?pageNum=1&amp;linkId=13001&amp;menuId=MENU00428">2026년 하반기 인턴연구원 공개채용</a></strong>
<dl class="info"><dt>작성일</dt><dd>2026.07.31</dd><dt class="receiptTit">접수여부</dt><dd class="receipt">마감</dd></dl>
</div></li></ul>"""
KAERI_DETAIL = """<div class="board_body">본문
<a href="/fileDownload?titleId=1&amp;fileId=1&amp;fileDownType=C">붙임1. 직무기술서.pdf 84.9KB 다운로드</a>
<a href="/fileDownload?titleId=1&amp;fileId=1&amp;fileDownType=C">다운로드</a></div>"""

KIMM_LIST = """<table><tbody><tr><td aria-label="번호">75</td>
<td aria-label="제목"><strong><a href="/sub050301/view/id/21499">2026년도 체험형 인턴 채용</a></strong></td>
<td aria-label="상태">진행중</td><td aria-label="접수마감일">2026-11-18</td></tr></tbody></table>"""
KIMS_LIST = """<table><tbody><tr><td class="td_num">656</td><td class="td_subject">
<a href="https://www.kims.re.kr/v17/bbx/board.php?bx_table=03_05&amp;wr_id=657">2026년 4차 청년인턴 모집 공고</a></td>
<td class="td_datetime">2026-10-02</td></tr></tbody></table>"""
KIMS_DETAIL = """<div id="bo_v_con">본문</div><a class="view_file_download"
href="https://www.kims.re.kr/v17/bbx/download.php?bx_table=03_05&amp;wr_id=657&amp;no=0"><strong>붙임1. 공고문.pdf</strong> (177.6K)</a>"""
KRRI_LIST = """<table><tbody><tr class="tr"><td class="board_tit"><a href="#none" onclick="fn_goView('25519')">2026년 청년인턴 채용</a></td>
<td class="board_write_date"><span>2026-08-05 ~ 2026-08-20</span></td></tr></tbody></table>"""
KFRI_LIST = """<table><tbody>
<tr onclick="location.href='/web/board/13/35422'"><td>729</td><td class="tit_td">2027년 상반기 학생연구원 모집 공고</td><td>담당</td><td>2026-09-30</td></tr>
<tr onclick="location.href='/web/board/13/35500'"><td>728</td><td class="tit_td">└ RE: 서류전형 결과 안내</td><td>담당</td><td>2026-10-26</td></tr>
</tbody></table>"""


class NewAdapterTest(unittest.TestCase):
    def test_board_es_table_and_detail(self):
        ad = ADAPTERS["kfe"]()
        [r] = ad.parse_list(BOARD_ES_TABLE, "")
        self.assertEqual((r.external_id, r.title, r.apply_end_on, r.status_text),
                         ("19900", "2026년 하반기 청년인턴 채용", date(2026, 11, 16), "진행중"))
        body, atts = ad.parse_detail(BOARD_ES_DETAIL, r)
        self.assertIn("공고 본문", body)  # 같은 class 중 글이 가장 긴 요소
        self.assertEqual([a.name for a in atts], ["붙임1. 직무기술서.pdf"])
        self.assertTrue(atts[0].url.startswith("https://www.kfe.re.kr/boardDownload.es"))

    def test_board_es_div_list(self):
        [r] = ADAPTERS["kigam"]().parse_list(BOARD_ES_DIV, "")
        self.assertEqual((r.external_id, r.posted_on), ("65100", date(2026, 5, 20)))
        self.assertIn("list_no=65100", r.url)

    def test_kaeri_dedupes_attachment_links(self):
        ad = ADAPTERS["kaeri"]()
        [r] = ad.parse_list(KAERI_LIST, "")
        self.assertEqual((r.external_id, r.posted_on, r.status_text), ("13001", date(2026, 7, 31), "마감"))
        _, atts = ad.parse_detail(KAERI_DETAIL, r)
        self.assertEqual([a.name for a in atts], ["붙임1. 직무기술서.pdf"])

    def test_kimm_kims_krri_kfri(self):
        [m] = ADAPTERS["kimm"]().parse_list(KIMM_LIST, "")
        self.assertEqual((m.external_id, m.apply_end_on), ("21499", date(2026, 11, 18)))
        [k] = ADAPTERS["kims"]().parse_list(KIMS_LIST, "")
        self.assertEqual((k.external_id, k.posted_on), ("657", date(2026, 10, 2)))
        _, atts = ADAPTERS["kims"]().parse_detail(KIMS_DETAIL, k)
        self.assertEqual(atts[0].name, "붙임1. 공고문.pdf")
        [r] = ADAPTERS["krri"]().parse_list(KRRI_LIST, "")
        self.assertEqual((r.external_id, r.apply_end_on), ("25519", date(2026, 8, 20)))
        self.assertTrue(r.url.endswith("id=25519&schM=view"))
        refs = ADAPTERS["kfri"]().parse_list(KFRI_LIST, "")
        self.assertEqual([x.external_id for x in refs], ["35422"])  # 답글(└ RE:)은 공고가 아님

    def test_list_urls_paging(self):
        self.assertTrue(ADAPTERS["kriss"]().list_urls(2)[1].endswith("&nPage=2"))
        self.assertEqual(ADAPTERS["kimm"]().list_urls(2)[1], "https://www.kimm.re.kr/sub050301/index/page/2")


class DeadlineTest(unittest.TestCase):
    def test_infer_deadline(self):
        self.assertEqual(infer_deadline("□ 원서접수 : 2026. 10. 2.(금) ~ 10. 16.(금) 18:00")[1], date(2026, 10, 16))
        self.assertEqual(infer_deadline("공고 안내만 있음"), (None, None))
        # 첫 '원서접수'에는 날짜가 없고, 뒤의 '접수기간'에 한글 날짜가 있는 경우 (KIMS 공고문)
        text = ("원서접수 ○ 채용사이트 온라인 접수 1차 서류전형 ... 7. 서류접수 ○ 접수기간 : 2026년 7월 16일(목) 16:00 ~ "
                "2026년 7월 27일(월) 18:00")
        self.assertEqual(infer_deadline(text), (date(2026, 7, 16), date(2026, 7, 27)))

    def test_stale_posting_without_deadline_is_closed(self):
        old = Posting(PostingRef("x", "1", "t", "u", posted_on=date(2026, 5, 1)))
        new = Posting(PostingRef("x", "2", "t", "u", posted_on=date(2026, 11, 1)))
        self.assertTrue(is_closed(old, date(2026, 11, 15)))
        self.assertFalse(is_closed(new, date(2026, 11, 15)))


class PostgradFilterTest(unittest.TestCase):
    def test_postdoc_trainee_is_not_undergrad_intern(self):
        from didimdol_ai.collector.filters import classify

        p = Posting(PostingRef("kaeri", "1", "2026년 하반기 석박사후연수생 공개채용", "u"))
        classify(p)
        self.assertFalse(p.include)
        q = Posting(PostingRef("kist", "2", "연수직(박사후연구원, 석사후연구원, 연구인턴) 추천선발", "u"))
        classify(q)
        self.assertTrue(q.include)  # 같은 공고에 '연구인턴'이 함께 있으면 포함


class VolatileTextTest(unittest.TestCase):
    def test_view_counts_removed_before_hashing(self):
        from didimdol_ai.collector.runner import strip_volatile

        a = strip_volatile("공고 작성일 2026.07.31 조회수 5,447 본문")
        b = strip_volatile("공고 작성일 2026.07.31 조회수 5,512 본문")
        self.assertEqual(a, b)  # 조회수만 바뀐 공고를 '정정공고'로 보지 않음
        self.assertEqual(strip_volatile("등록일 2026-11-09 조회 303 본문"), "등록일 2026-11-09 본문")


class BasicCompetencyTest(unittest.TestCase):
    def test_weight_lower_than_job_specific(self):
        basic = Requirement("b", "수리 능력", 1, ["data"], "posting", "required", kind="skill")
        job = Requirement("j", "세포배양 실험기술", 1, ["research"], "posting", "required", kind="skill")
        self.assertTrue(is_basic_competency(basic))
        self.assertLess(requirement_weight(basic), requirement_weight(job))


if __name__ == "__main__":
    unittest.main()
