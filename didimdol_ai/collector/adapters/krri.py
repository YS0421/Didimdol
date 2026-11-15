"""한국철도기술연구원(KRRI) 채용공고 게시판. 목록 링크가 fn_goView('id') 자바스크립트라 id를 꺼내 상세 URL을 만든다."""

from __future__ import annotations

import re

from ..filters import parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, longest, text_of

ORIGIN = "https://www.krri.re.kr"
BOARD = f"{ORIGIN}/web/contents/krri030502.do"


class KrriAdapter(Adapter):
    code = "krri"

    def list_urls(self, pages: int) -> list[str]:
        return [BOARD] + [f"{BOARD}?page={i + 1}" for i in range(1, pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table//tbody/tr"):
            a = first(row, "./td[contains(@class,'board_tit')]//a")
            m = re.search(r"fn_goView\('(\d+)'\)", a.get("onclick", "")) if a is not None else None
            if not m:
                continue
            start, end = parse_range(text_of(first(row, "./td[contains(@class,'board_write_date')]")))
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a),
                url=f"{BOARD}?id={m.group(1)}&schM=view", posted_on=start, apply_start_on=start, apply_end_on=end,
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = longest(doc, "//div[contains(@class,'board_detail_wrap')]")
        return text_of(body), attachment_links(doc, "//a[contains(@href,'/afile/fileDownload/')]", ORIGIN)
