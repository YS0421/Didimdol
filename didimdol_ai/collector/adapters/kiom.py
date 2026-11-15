"""한국한의학연구원(KIOM) 채용공고 게시판."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..filters import parse_date, parse_range
from ..models import AttachmentLink, PostingRef
from .base import Adapter, first, text_of

ORIGIN = "https://kiom.re.kr"
BOARD = f"{ORIGIN}/board.es?mid=a10503020000&bid=0038"


class KiomAdapter(Adapter):
    code = "kiom"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{BOARD}&nPage={i + 1}" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table[contains(@class,'tstyle_list')]/tbody/tr"):
            a = first(row, ".//td[contains(@class,'m_title')]//a")
            if a is None:
                continue
            m = re.search(r"list_no=(\d+)", a.get("href", ""))
            if not m:
                continue
            start, end = parse_range(text_of(first(row, "./td[@aria-label='접수기간']")))
            refs.append(PostingRef(
                institute=self.code,
                external_id=m.group(1),
                title=text_of(a),
                url=f"{BOARD}&act=view&list_no={m.group(1)}",
                posted_on=parse_date(text_of(first(row, "./td[@aria-label='등록일']"))),
                apply_start_on=start, apply_end_on=end,
                status_text=text_of(first(row, "./td[@aria-label='분류']")),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = text_of(first(doc, "//div[contains(@class,'board_view')]//div[contains(@class,'contents')]"))
        atts = []
        for a in doc.xpath("//a[starts-with(@href,'/boardDownload.es')]"):
            li = a.getparent()
            while li is not None and li.tag != "li":
                li = li.getparent()
            name = text_of(first(li, ".//em")) if li is not None else ""
            atts.append(AttachmentLink(name or a.get("href"), urljoin(ORIGIN, a.get("href"))))
        return body, atts
