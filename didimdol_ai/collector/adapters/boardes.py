"""전자정부 표준 게시판(board.es)을 쓰는 기관: KRISS(표준연), KFE(핵융합연), KIGAM(지질자원연).

목록은 table.tstyle_list(td에 aria-label) 또는 div.tstyle_list(ul 행) 두 가지 모양이 있다.
상세의 첨부는 /boardDownload.es 링크다.
"""

from __future__ import annotations

import re

from ..filters import parse_date, parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, longest, text_of


class BoardEsAdapter(Adapter):
    origin: str
    mid: str
    bid: str

    @property
    def board(self) -> str:
        return f"{self.origin}/board.es?mid={self.mid}&bid={self.bid}"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{self.board}&nPage={i + 1}" for i in range(pages)]

    def _ref(self, list_no: str, title: str, posted, start=None, end=None, status: str = "") -> PostingRef:
        return PostingRef(institute=self.code, external_id=list_no, title=title,
                          url=f"{self.board}&act=view&list_no={list_no}",
                          posted_on=posted, apply_start_on=start, apply_end_on=end, status_text=status)

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table[contains(@class,'tstyle_list')]/tbody/tr"):
            a = first(row, "./td[@aria-label='제목']//a")
            m = re.search(r"list_no=(\d+)", a.get("href", "")) if a is not None else None
            if not m:
                continue
            posted = None
            for label in ("작성일자", "등록일", "작성일"):
                posted = posted or parse_date(text_of(first(row, f"./td[@aria-label='{label}']")))
            start, end = parse_range(text_of(first(row, "./td[@aria-label='공고기간']")))
            status = text_of(first(row, ".//span[contains(@class,'progress')]"))
            refs.append(self._ref(m.group(1), text_of(a).removeprefix(status).strip(), posted, start, end, status))
        for row in doc.xpath("//div[contains(@class,'tstyle_list')]//div[contains(@class,'dbody')]/ul"):
            a = first(row, "./li[contains(@class,'title')]//a")
            m = re.search(r"list_no=(\d+)", a.get("href", "")) if a is not None else None
            if not m:
                continue
            dates = [parse_date(text_of(li)) for li in row.xpath("./li")]
            refs.append(self._ref(m.group(1), text_of(a), next((d for d in dates if d), None)))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = longest(doc, "//div[contains(@class,'board_view') or contains(@class,'tstyle_view')]")
        return text_of(body), attachment_links(doc, "//a[contains(@href,'boardDownload.es')]", self.origin)


class KrissAdapter(BoardEsAdapter):
    """한국표준과학연구원."""

    code, origin, mid, bid = "kriss", "https://www.kriss.re.kr", "a10502020000", "0006"


class KfeAdapter(BoardEsAdapter):
    """한국핵융합에너지연구원 (목록에 공고기간이 있음)."""

    code, origin, mid, bid = "kfe", "https://www.kfe.re.kr", "a10304010000", "0013"


class KigamAdapter(BoardEsAdapter):
    """한국지질자원연구원 (목록이 div/ul 모양)."""

    code, origin, mid, bid = "kigam", "https://www.kigam.re.kr", "a10705030000", "0029"
