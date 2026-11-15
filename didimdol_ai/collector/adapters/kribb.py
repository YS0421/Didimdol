"""한국생명공학연구원(KRIBB) 채용공고 게시판. robots.txt 요청이 400으로 막혀 표준대로 허용 처리됨."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..filters import parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, first, text_of

ORIGIN = "https://www.kribb.re.kr"
LIST = f"{ORIGIN}/kor/sub03/sub03_01_01.jsp"
VIEW = f"{ORIGIN}/kor/sub03/sub03_01_01_view.jsp"


class KribbAdapter(Adapter):
    code = "kribb"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{LIST}?page={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table//tbody/tr"):
            cells = row.xpath("./td")
            a = first(row, ".//a[contains(@href,'sub03_01_01_view.jsp')]")
            if a is None or len(cells) < 4:
                continue
            m = re.search(r"b_idx=(\d+)", a.get("href", ""))
            if not m:
                continue
            start, end = parse_range(text_of(cells[3]))
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a),
                url=f"{VIEW}?b_idx={m.group(1)}", posted_on=start, apply_start_on=start, apply_end_on=end,
                status_text=text_of(cells[1]),  # 구분 (연수직/계약직 등)
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body_el = first(doc, "//div[contains(@class,'board_content') or contains(@class,'bbs_content')]")
        atts = [AttachmentLink(text_of(a), urljoin(ORIGIN, a.get("href")))
                for a in doc.xpath("//div[contains(@class,'board_file_list')]//a[contains(@href,'file_down.jsp')]")]
        return text_of(body_el), atts
