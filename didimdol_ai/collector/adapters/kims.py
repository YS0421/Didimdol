"""한국재료연구원(KIMS) 채용공고 게시판 (그누보드 bx_table=03_05)."""

from __future__ import annotations

import re

from ..filters import parse_date
from ..models import AttachmentLink, PostingRef
from .base import Adapter, attachment_links, first, text_of

ORIGIN = "https://www.kims.re.kr"
BOARD = f"{ORIGIN}/v17/bbx/board.php?bx_table=03_05"


class KimsAdapter(Adapter):
    code = "kims"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{BOARD}&page={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table//tbody/tr"):
            a = first(row, "./td[contains(@class,'td_subject')]//a")
            m = re.search(r"wr_id=(\d+)", a.get("href", "")) if a is not None else None
            if not m:
                continue
            refs.append(PostingRef(
                institute=self.code, external_id=m.group(1), title=text_of(a), url=f"{BOARD}&wr_id={m.group(1)}",
                posted_on=parse_date(text_of(first(row, "./td[contains(@class,'td_datetime')]"))),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = first(doc, "//*[@id='bo_v_con']")
        return text_of(body), attachment_links(doc, "//a[contains(@href,'/bbx/download.php')]", ORIGIN)
