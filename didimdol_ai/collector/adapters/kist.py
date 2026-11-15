"""한국과학기술연구원(KIST) 채용공지 게시판."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..filters import parse_date
from ..models import AttachmentLink, PostingRef
from .base import Adapter, first, text_of

LIST = "https://kist.re.kr/ko/notice/employment-announcement.do"


class KistAdapter(Adapter):
    code = "kist"

    def list_urls(self, pages: int) -> list[str]:
        return [f"{LIST}?article.offset={i * 10}&articleLimit=10" for i in range(pages)]

    def parse_list(self, html: str, url: str) -> list[PostingRef]:
        doc = self.doc(html)
        refs = []
        for row in doc.xpath("//table[contains(@class,'board-table')]/tbody/tr"):
            a = first(row, ".//div[contains(@class,'b-title-box')]/a[contains(@href,'mode=view')]")
            if a is None:
                continue
            m = re.search(r"articleNo=(\d+)", a.get("href", ""))
            if not m:
                continue
            title = (a.get("title") or text_of(a)).replace("자세히 보기", "").strip()
            cells = row.xpath("./td")
            posted = parse_date(text_of(first(row, ".//span[contains(@class,'b-date')]")))
            deadline = parse_date(text_of(cells[3])) if len(cells) > 3 else None
            refs.append(PostingRef(
                institute=self.code,
                external_id=m.group(1),
                title=title,
                url=f"{LIST}?mode=view&articleNo={m.group(1)}",
                posted_on=posted, apply_start_on=posted, apply_end_on=deadline,
                status_text=text_of(first(row, ".//span[contains(@class,'b-progress')]")),
            ))
        return refs

    def parse_detail(self, html: str, ref: PostingRef) -> tuple[str, list[AttachmentLink]]:
        doc = self.doc(html)
        body = text_of(first(doc, "//div[contains(@class,'b-content-box')]"))
        atts = [
            AttachmentLink(text_of(a), urljoin(LIST, a.get("href")))
            for a in doc.xpath("//a[contains(@class,'file-down-btn')]")
        ]
        return body, atts
